"""邮件管理 Agent 编排器

主流程：邮件获取 → 语义分析 → 优先级评分 → 日历调度 → 回复生成 → 结果输出
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from mail_agent.calendar.scheduler import CalendarScheduler
from mail_agent.calendar.store import CalendarStore
from mail_agent.config import AppConfig, load_config
from mail_agent.llm.client import LLMClient
from mail_agent.models import EmailMessage, ProcessingResult
from mail_agent.reply.generator import ReplyGenerator
from mail_agent.understanding.analyzer import EmailAnalyzer
from mail_agent.understanding.priority import PriorityScorer

logger = logging.getLogger(__name__)


class MailAgent:
    """邮件管理 Agent"""

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        gmail_client=None,
        calendar_backend=None,
        send_replies: bool = False,
        create_drafts: bool = False,
        mark_read: bool = False,
        write_calendar: bool = False,
        redirect_to: str | None = None,
        allow_real: bool = False,
    ):
        """
        Args:
            config: 应用配置
            gmail_client: 可选的 GmailClient，用于真实投递回复/标记已读。
                为 None 且 config.google.enabled 时会按需创建。
            calendar_backend: 日历后端（含 add_event/check_conflict/list_events）。
                为 None 时按配置选择 Google Calendar 或本地 JSON。
            send_replies: 为 True 时直接发送回复（需要 gmail_client）。
            create_drafts: 为 True 时创建 Gmail 草稿（默认 False，仅生成文本不推送）。
            mark_read: 处理完成后是否将邮件标记为已读（需要 gmail_client）。
            write_calendar: 为 True 时才真正写入日历后端（默认 False，仅计算用于展示）。
            redirect_to: 外发回复重定向邮箱。默认（allow_real=False 且未显式传值）
                重定向到 config.testing.redirect_to（安全）。
            allow_real: 显式允许发给真实收件人（危险）。为 False 时若没有重定向目标，
                投递会被安全拦截而不会误发真实收件人。
        """
        self._config = config or load_config()
        self._llm = LLMClient(self._config.llm)
        self._analyzer = EmailAnalyzer(self._llm)
        self._scorer = PriorityScorer()
        self._send_replies = send_replies
        self._create_drafts = create_drafts
        self._mark_read = mark_read
        self._write_calendar = write_calendar
        self._allow_real = allow_real
        # 安全默认：未显式允许真实收件人时，缺省重定向到测试邮箱
        if allow_real:
            self._redirect_to = redirect_to
        else:
            self._redirect_to = redirect_to or self._config.testing.redirect_to

        # 共享一次 Google 授权凭据，避免重复授权
        self._gmail = gmail_client
        google = self._config.google
        creds = None
        google_ready = google.enabled
        if google.enabled and (self._gmail is None or calendar_backend is None):
            from mail_agent.gapi.auth import GoogleAuthError, get_credentials

            try:
                creds = get_credentials(google, allow_interactive=False)
            except GoogleAuthError as e:
                # 尚未授权：降级为本地日历 + 不投递回复，而非让整个应用崩溃
                logger.warning("Google 未授权，降级到本地模式: %s", e)
                google_ready = False

        if self._gmail is None and google_ready:
            from mail_agent.gapi.gmail import GmailClient

            self._gmail = GmailClient(google, credentials=creds)

        # 选择日历后端
        if calendar_backend is not None:
            self._calendar_store = calendar_backend
            self._calendar_backend_name = getattr(
                calendar_backend, "backend_name", "custom"
            )
        elif google_ready:
            from mail_agent.gapi.gcalendar import GoogleCalendarClient

            self._calendar_store = GoogleCalendarClient(google, credentials=creds)
            self._calendar_backend_name = "google"
        else:
            self._calendar_store = CalendarStore(self._config.calendar)
            self._calendar_backend_name = "local"

        self._scheduler = CalendarScheduler(
            self._calendar_store, self._llm, self._config.calendar
        )
        self._reply_gen = ReplyGenerator(self._llm, self._config.user)
        # 并行处理多封邮件时，串行化日历写入，避免并发冲突检查竞态导致重复占用
        self._write_lock = threading.Lock()

    @property
    def calendar_store(self):
        return self._calendar_store

    @property
    def gmail(self):
        return self._gmail

    def process_email(self, email_msg: EmailMessage) -> ProcessingResult:
        """处理单封邮件的完整流程

        Args:
            email_msg: 邮件消息

        Returns:
            ProcessingResult 完整处理结果
        """
        steps: list[str] = []

        # Step 1: 邮件语义分析
        steps.append("Step 1: 邮件语义分析")
        logger.info("分析邮件: %s", email_msg.subject)
        analysis = self._analyzer.analyze(email_msg)
        steps.append(
            f"  → 意图={analysis.intent.value}, "
            f"紧急度={analysis.urgency.value}, "
            f"需要回复={analysis.requires_reply}, "
            f"包含日程={analysis.contains_schedule}"
        )

        # Step 2: 优先级评分
        steps.append("Step 2: 优先级评分")
        priority = self._scorer.score(email_msg, analysis)
        steps.append(
            f"  → 总分={priority.total_score:.1f}, "
            f"等级={priority.level.value}"
        )

        result = ProcessingResult(
            email=email_msg,
            analysis=analysis,
            priority=priority,
            calendar_backend=self._calendar_backend_name,
            processing_steps=steps,
        )

        # Step 3: 日历调度（如有日程信息）
        if analysis.contains_schedule:
            steps.append("Step 3: 日历调度")
            try:
                if self._write_calendar:
                    # 写入模式：串行化「冲突检查 + 落库」整段，避免并发双订
                    with self._write_lock:
                        event, conflict = self._scheduler.schedule_from_email(
                            email_msg, analysis, write=True
                        )
                else:
                    # 展示模式：只读，安全并行
                    event, conflict = self._scheduler.schedule_from_email(
                        email_msg, analysis, write=False
                    )
                result.calendar_event = event
                result.schedule_conflict = conflict
                if event:
                    steps.append(
                        f"  → 创建事件: {event.title} "
                        f"({event.start_time.strftime('%Y-%m-%d %H:%M')} - "
                        f"{event.end_time.strftime('%H:%M')})"
                    )
                if conflict and conflict.has_conflict:
                    steps.append(
                        f"  → 警告: 与 {len(conflict.conflicting_events)} 个事件冲突"
                    )
            except Exception as e:
                logger.error("日历调度失败: %s", e)
                steps.append(f"  → 日历调度失败: {e}")

        # Step 4: 生成回复（如需要回复）
        if analysis.requires_reply:
            steps.append(
                f"Step {'4' if analysis.contains_schedule else '3'}: 生成回复"
            )
            try:
                reply = self._reply_gen.generate(
                    email_msg,
                    analysis,
                    calendar_event=result.calendar_event,
                    conflict=result.schedule_conflict,
                )
                result.reply_draft = reply
                steps.append(f"  → 回复草稿已生成 (To: {', '.join(reply.to)})")
                # 投递回复（发送 / 创建草稿）
                self._deliver_reply(result, email_msg, steps)
            except Exception as e:
                logger.error("回复生成失败: %s", e)
                steps.append(f"  → 回复生成失败: {e}")

        # 标记已读
        if self._mark_read and self._gmail and email_msg.gmail_id:
            try:
                self._gmail.mark_read(email_msg.gmail_id)
                steps.append("  → 已标记为已读")
            except Exception as e:
                logger.error("标记已读失败: %s", e)
                steps.append(f"  → 标记已读失败: {e}")

        steps.append("处理完成")
        return result

    def _deliver_reply(
        self,
        result: ProcessingResult,
        email_msg: EmailMessage,
        steps: list[str],
    ) -> None:
        """根据配置发送回复或创建草稿"""
        reply = result.reply_draft
        if reply is None or self._gmail is None:
            return
        # 展示模式（既不发送也不建草稿）：不投递、不改写回复，保持原样供查看
        if not (self._send_replies or self._create_drafts):
            return
        # 收件人校验：拒绝空/无效收件人，避免投递垃圾草稿/邮件
        if not any((a or "").strip() for a in (reply.to or [])):
            result.reply_delivery = "failed:empty-recipient"
            steps.append("  → 投递跳过：收件人为空/无效")
            return
        # 测试重定向：改写收件人并标注真实目标
        if self._redirect_to:
            self._apply_test_redirect(reply, steps)
        elif not self._allow_real:
            # 安全网：未配置重定向且未显式允许真实发送 → 拦截，绝不误发真实收件人
            result.reply_delivery = "blocked:no-redirect"
            steps.append("  → 安全拦截：未设重定向且未允许真实发送，跳过投递")
            return
        try:
            if self._send_replies:
                msg_id = self._gmail.send_reply(reply, email_msg)
                result.reply_delivery = "sent"
                result.reply_message_id = msg_id
                steps.append(f"  → 回复已发送 (id={msg_id})")
            elif self._create_drafts:
                draft_id = self._gmail.create_draft(reply, email_msg)
                result.reply_delivery = "draft"
                result.reply_message_id = draft_id
                steps.append(f"  → 已创建 Gmail 草稿 (id={draft_id})")
        except Exception as e:
            logger.error("回复投递失败: %s", e)
            result.reply_delivery = f"failed:{e}"
            steps.append(f"  → 回复投递失败: {e}")

    def _apply_test_redirect(self, reply, steps: list[str]) -> None:
        """测试模式：把回复重定向到测试邮箱，并在正文/主题标注真实目标收件人"""
        original_to = list(reply.to)
        original_str = ", ".join(original_to) if original_to else "(无)"

        banner = (
            "⚠️ 测试模式 / TEST MODE ⚠️\n"
            f"真实目标收件人 (REAL recipient): {original_str}\n"
            f"本邮件被重定向至测试邮箱: {self._redirect_to}\n"
            "—— 正式发送时请关闭 --test ——\n"
            f"{'=' * 50}\n\n"
        )
        reply.body = banner + reply.body
        reply.to = [self._redirect_to]
        if not reply.subject.startswith("[TEST"):
            reply.subject = f"[TEST→{original_str}] {reply.subject}"
        steps.append(
            f"  → 测试重定向: 真实目标 {original_str} → 改投 {self._redirect_to}"
        )

    def process_emails(
        self, emails: list[EmailMessage], max_workers: int = 8
    ) -> list[ProcessingResult]:
        """批量处理邮件（多封并发，每封内部仍按依赖顺序调用 LLM）

        每封邮件相互独立，处理过程主要是若干次 LLM 调用（分析/解析时间/生成回复），
        故跨邮件并行可显著缩短总耗时。日历写入由 _write_lock 串行化保证安全。

        Args:
            emails: 邮件列表
            max_workers: 最大并发数（默认 8，避免过多并发触发 LLM 限流）

        Returns:
            处理结果列表，按优先级降序排列
        """
        results: list[ProcessingResult] = []
        workers = max(1, min(max_workers, len(emails)))

        if workers == 1:
            for email_msg in emails:
                try:
                    results.append(self.process_email(email_msg))
                except Exception as e:  # noqa: BLE001
                    logger.error("处理邮件 '%s' 失败: %s", email_msg.subject, e)
        else:
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="mailagent"
            ) as pool:
                futures = [
                    (pool.submit(self.process_email, em), em) for em in emails
                ]
                for fut, email_msg in futures:
                    try:
                        results.append(fut.result())
                    except Exception as e:  # noqa: BLE001
                        logger.error("处理邮件 '%s' 失败: %s", email_msg.subject, e)

        # 按优先级降序排列
        results.sort(key=lambda r: r.priority.total_score, reverse=True)
        return results
