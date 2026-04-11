"""邮件管理 Agent 编排器

主流程：邮件获取 → 语义分析 → 优先级评分 → 日历调度 → 回复生成 → 结果输出
"""

from __future__ import annotations

import logging
from datetime import datetime

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

    def __init__(self, config: AppConfig | None = None):
        self._config = config or load_config()
        self._llm = LLMClient(self._config.llm)
        self._analyzer = EmailAnalyzer(self._llm)
        self._scorer = PriorityScorer()
        self._calendar_store = CalendarStore(self._config.calendar)
        self._scheduler = CalendarScheduler(self._calendar_store, self._llm)
        self._reply_gen = ReplyGenerator(self._llm, self._config.user)

    @property
    def calendar_store(self) -> CalendarStore:
        return self._calendar_store

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
            processing_steps=steps,
        )

        # Step 3: 日历调度（如有日程信息）
        if analysis.contains_schedule:
            steps.append("Step 3: 日历调度")
            try:
                event, conflict = self._scheduler.schedule_from_email(
                    email_msg, analysis
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
            except Exception as e:
                logger.error("回复生成失败: %s", e)
                steps.append(f"  → 回复生成失败: {e}")

        steps.append("处理完成")
        return result

    def process_emails(
        self, emails: list[EmailMessage]
    ) -> list[ProcessingResult]:
        """批量处理邮件

        Args:
            emails: 邮件列表

        Returns:
            处理结果列表，按优先级降序排列
        """
        results = []
        for email_msg in emails:
            try:
                result = self.process_email(email_msg)
                results.append(result)
            except Exception as e:
                logger.error("处理邮件 '%s' 失败: %s", email_msg.subject, e)
        # 按优先级降序排列
        results.sort(key=lambda r: r.priority.total_score, reverse=True)
        return results
