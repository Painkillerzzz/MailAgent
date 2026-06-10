# -*- coding: utf-8 -*-
"""排程评测（真实 LLM 端到端）：自然语言预约邮件 → 系统能否排出合理日程。

运行：
    uv run python eval/schedule_eval.py [scenario]
    scenario ∈ {single_day, multi_day, dense, adjacency}（默认 single_day）

数据集 / Ground-Truth / 校验器见 eval/schedule_dataset.py（与 pytest 共用）。
确定性回归见 tests/test_schedule_eval.py。
"""

from __future__ import annotations

import os
import sys
import tempfile

# 允许以 `python eval/schedule_eval.py` 直接运行（把项目根加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.schedule_dataset import (
    GRAN,
    SCENARIOS,
    SEARCH_DAYS,
    WORK_END,
    WORK_START,
    greedy_place,
    validate_schedule,
)
from mail_agent.calendar.scheduler import CalendarScheduler
from mail_agent.calendar.store import CalendarStore
from mail_agent.config import CalendarConfig, load_config
from mail_agent.llm.client import LLMClient
from mail_agent.models import EmailAnalysis, EmailMessage
from mail_agent.understanding.analyzer import EmailAnalyzer


def fmt(dt):
    return dt.strftime("%m-%d %H:%M")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "single_day"
    items = SCENARIOS[name]

    cfg = load_config()
    llm = LLMClient(cfg.llm)
    analyzer = EmailAnalyzer(llm)
    cal_cfg = CalendarConfig(
        storage_path=tempfile.mktemp(suffix=".json"),
        work_start_hour=WORK_START, work_end_hour=WORK_END,
        slot_granularity_min=GRAN, suggest_count=5, search_days=SEARCH_DAYS,
    )
    store = CalendarStore(cal_cfg)
    store.clear()
    scheduler = CalendarScheduler(store, llm, cal_cfg, auto_resolve_conflicts=True)

    print("=" * 78)
    print(f"排程评测 · 场景={name} · 工作时间 {WORK_START}:00-{WORK_END}:00 · 共 {len(items)} 封")
    print("=" * 78)

    gt = greedy_place(items)
    print("\n[Ground-Truth 可行安排(贪心 oracle)]")
    for eid, (s, e) in sorted(gt.items(), key=lambda kv: kv[1][0]):
        print(f"  {fmt(s)}-{e:%H:%M}  {eid}")

    for it in items:
        email = EmailMessage(message_id=it["id"], sender=it["sender"],
                             subject=it["subject"], body=it["body"],
                             date=it["start"].replace(hour=8))
        analysis = analyzer.analyze(email)
        if not analysis.contains_schedule:
            analysis = EmailAnalysis(contains_schedule=True, schedule_description=it["body"])
        scheduler.schedule_from_email(email, analysis, write=True)

    events = store.list_events()
    print("\n[系统排出的日程]")
    for e in sorted(events, key=lambda x: x.start_time):
        note = " (避让)" if "auto-rescheduled" in (e.description or "") else ""
        print(f"  {fmt(e.start_time)}-{e.end_time:%H:%M}  {e.source_email_id}{note}")

    fails = validate_schedule(events, items)
    got = {e.source_email_id: (e.start_time, e.end_time) for e in events}
    same = sum(1 for it in items if got.get(it["id"]) == gt[it["id"]])

    print("\n[校验]")
    print(f"  可行性: {'✓ 全部满足(无重叠/不丢会/在工时/时长正确)' if not fails else '✗ ' + '; '.join(fails)}")
    print(f"  与 Ground-Truth 落位一致: {same}/{len(items)}")
    print("\n" + "=" * 78)
    print(f"结论: {'系统排出了可行的合理日程 ✓' if not fails else '日程不完全可行 ✗'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
