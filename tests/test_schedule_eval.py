"""排程评测（确定性，pytest 版）

用桩解析（绕过 LLM）驱动真实的 CalendarScheduler，验证多场景下：
  - 排程可行（无重叠 / 不丢会 / 在工作时间 / 时长保留）
  - 与 Ground-Truth(贪心 oracle) 落位一致
覆盖：单日冲突、多日、严重超额顺延、相邻边界。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

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
from mail_agent.config import CalendarConfig
from mail_agent.models import EmailAnalysis, EmailMessage


def _run(items, tmp_path):
    """用桩解析驱动调度器，返回最终事件列表（不调用 LLM）。"""
    cfg = CalendarConfig(
        storage_path=tmp_path / "cal.json",
        work_start_hour=WORK_START, work_end_hour=WORK_END,
        slot_granularity_min=GRAN, suggest_count=5, search_days=SEARCH_DAYS,
    )
    store = CalendarStore(cfg)
    store.clear()
    sch = CalendarScheduler(store, llm_client=None, config=cfg,
                            auto_resolve_conflicts=True)
    for it in items:
        email = EmailMessage(message_id=it["id"], sender=it["sender"],
                             subject=it["subject"], body=it["body"], date=it["start"])
        analysis = EmailAnalysis(contains_schedule=True, schedule_description=it["subject"])
        # 桩：直接返回该邮件的预期解析结果，绕过 LLM
        sch.parse_schedule = (  # noqa: E731
            lambda *a, _it=it, **k: {
                "start_time": _it["start"],
                "end_time": _it["start"] + timedelta(minutes=_it["dur"]),
                "title": _it["id"],
            }
        )
        sch.schedule_from_email(email, analysis, write=True)
    return store.list_events()


@pytest.mark.parametrize("name", list(SCENARIOS.keys()))
def test_schedule_is_feasible(name, tmp_path):
    items = SCENARIOS[name]
    events = _run(items, tmp_path)
    fails = validate_schedule(events, items)
    assert not fails, f"[{name}] 不可行: {fails}"


@pytest.mark.parametrize("name", list(SCENARIOS.keys()))
def test_matches_ground_truth(name, tmp_path):
    items = SCENARIOS[name]
    events = _run(items, tmp_path)
    gt = greedy_place(items)
    got = {e.source_email_id: (e.start_time, e.end_time) for e in events}
    mismatches = [
        (it["id"], got.get(it["id"]), gt[it["id"]])
        for it in items if got.get(it["id"]) != gt[it["id"]]
    ]
    assert not mismatches, f"[{name}] 与 GT 落位不一致: {mismatches}"


def test_multi_day_no_cross_day_conflict(tmp_path):
    """跨日同一时刻不应被判为冲突：mon_a 与 tue_a 都应保持各自原始时间。"""
    items = SCENARIOS["multi_day"]
    events = _run(items, tmp_path)
    by_id = {e.source_email_id: e for e in events}
    assert by_id["mon_a"].start_time.hour == 10  # 保持原时间
    assert by_id["tue_a"].start_time.hour == 10  # 同点不同天，未被挪动
    assert by_id["mon_a"].start_time.day != by_id["tue_a"].start_time.day


def test_adjacency_not_conflict(tmp_path):
    """背靠背(10-11,11-12,12-13)不算冲突，应保持原时间；仅真冲突被避让。"""
    items = SCENARIOS["adjacency"]
    events = _run(items, tmp_path)
    by_id = {e.source_email_id: e for e in events}
    for eid, hour in [("adj1", 10), ("adj2", 11), ("adj3", 12)]:
        assert by_id[eid].start_time.hour == hour, f"{eid} 不应被挪动"
    # clash(10:30) 与 adj1 冲突 → 必须被移走，不再是 10:30
    assert not (by_id["clash"].start_time.hour == 10 and by_id["clash"].start_time.minute == 30)


def test_dense_spills_to_next_day(tmp_path):
    """单日严重超额 → 部分顺延到次日，且整体仍无冲突。"""
    items = SCENARIOS["dense"]
    events = _run(items, tmp_path)
    assert not validate_schedule(events, items)
    days = {e.start_time.day for e in events}
    assert len(days) >= 2, "超额场景应顺延到次日"
