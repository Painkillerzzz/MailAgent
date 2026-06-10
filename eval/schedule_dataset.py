# -*- coding: utf-8 -*-
"""排程评测共享数据集 / Ground-Truth oracle / 校验器（纯逻辑，无 LLM）。

被 eval/schedule_eval.py(真实 LLM 端到端) 与 tests/test_schedule_eval.py(确定性) 复用。
"""

from __future__ import annotations

from datetime import datetime, timedelta

WORK_START, WORK_END = 9, 18
GRAN = 15          # 空闲槽粒度（分钟）
SEARCH_DAYS = 3    # 顺延搜索天数

MON = datetime(2026, 6, 15)   # 周一
TUE = datetime(2026, 6, 16)
WED = datetime(2026, 6, 17)


def _dt(day: datetime, h: int, m: int = 0) -> datetime:
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def mk(eid, day, h, m, dur, sender=None, subject=None, body=None):
    start = _dt(day, h, m)
    if body is None:
        body = (
            f"Let's meet on {start:%A, %B %d} at {start:%I:%M %p} "
            f"for {dur} minutes."
        )
    return dict(
        id=eid, start=start, dur=dur,
        sender=sender or f"{eid}@example.com",
        subject=subject or eid.replace("_", " ").title(),
        body=body,
    )


# ── 场景 1：单日、自然语言、5 对冲突（手写自然正文）──
SINGLE_DAY = [
    mk("standup", MON, 9, 0, 15, "team-lead@corp.com", "Quick standup",
       "Hi, let's do our quick team standup on Monday, June 15 at 9:00 AM — just 15 minutes."),
    mk("lee", MON, 10, 0, 60, "prof.lee@tsinghua.edu.cn", "Paper discussion",
       "Hi Xiangyu, can we meet on Monday, June 15 at 10am for an hour to go over the paper results?"),
    mk("office", MON, 9, 0, 60, "prof.chen@tsinghua.edu.cn", "Office hours",
       "I'll be holding office hours on Monday, June 15 from 9 to 10 in the morning. Feel free to drop by."),
    mk("wang", MON, 11, 0, 45, "dr.wang@stanford.edu", "Collaboration call",
       "Could we have a collaboration call on Monday, June 15 at 11:00? About 45 minutes should be enough."),
    mk("john", MON, 10, 30, 30, "john@company.com", "Quick sync",
       "Let's do a quick sync on Monday, June 15 at 10:30. Should take about 30 minutes."),
    mk("vendor", MON, 11, 30, 45, "sales@vendor.io", "Product demo",
       "We'd love to give you a product demo on Monday, June 15 at 11:30. Plan for about 45 minutes."),
    mk("recruiter", MON, 13, 0, 45, "recruiter@bigtech.com", "Phone screen",
       "Your phone screen is scheduled for Monday, June 15 at 1:00 PM. Please allow 45 minutes."),
    mk("advisor", MON, 14, 30, 60, "advisor@tsinghua.edu.cn", "Thesis meeting",
       "Let's have your thesis progress meeting on Monday, June 15 at 2:30 PM for one hour."),
    mk("alice", MON, 13, 15, 30, "alice@gmail.com", "Coffee chat",
       "Want to grab a coffee chat on Monday, June 15 at 1:15pm? Half an hour is plenty."),
    mk("client", MON, 15, 0, 45, "client@acme.com", "Project review",
       "Can we do the project review on Monday, June 15 at 3:00 PM? Plan for about 45 minutes."),
    mk("lunch", MON, 12, 0, 30, "friend@gmail.com", "Lunch",
       "Lunch on Monday, June 15 around 12:00 noon? Let's say half an hour."),
    mk("dentist", MON, 16, 30, 30, "clinic@dental.com", "Appointment reminder",
       "Reminder: your dental appointment is on Monday, June 15 at 4:30 PM (30 minutes)."),
    mk("gym", MON, 17, 0, 30, "bookings@gym.com", "Workout session",
       "Your workout session is booked for Monday, June 15 at 5:00 PM, 30 minutes."),
]

# ── 场景 2：多日，跨日同点不冲突、各日内部有冲突 ──
MULTI_DAY = [
    mk("mon_a", MON, 10, 0, 60),
    mk("mon_b", MON, 10, 30, 30),          # 与 mon_a 冲突
    mk("mon_c", MON, 14, 0, 60),
    mk("mon_d", MON, 14, 30, 30),          # 与 mon_c 冲突
    mk("tue_a", TUE, 10, 0, 60),           # 与 mon_a 同点但不同天 → 不冲突
    mk("tue_b", TUE, 10, 0, 30),           # 与 tue_a 冲突
    mk("tue_c", TUE, 15, 0, 45),
    mk("wed_a", WED, 9, 0, 90),
    mk("wed_b", WED, 9, 30, 30),           # 与 wed_a 冲突
]

# ── 场景 3：单日严重超额（12×60 > 9h）→ 必然顺延次日 ──
DENSE = [mk(f"d{i:02d}", MON, 9 + (i % 9), 0, 60) for i in range(12)]

# ── 场景 4：相邻边界（背靠背不算冲突）+ 一个真冲突 ──
ADJACENCY = [
    mk("adj1", MON, 10, 0, 60),            # 10-11
    mk("adj2", MON, 11, 0, 60),            # 11-12 背靠背，不冲突
    mk("adj3", MON, 12, 0, 60),            # 12-13 背靠背，不冲突
    mk("clash", MON, 10, 30, 30),          # 与 adj1 真冲突 → 需避让
]

SCENARIOS = {
    "single_day": SINGLE_DAY,
    "multi_day": MULTI_DAY,
    "dense": DENSE,
    "adjacency": ADJACENCY,
}


# ── oracle ──
def _overlap(a_s, a_e, b_s, b_e):
    return a_s < b_e and b_s < a_e


def _nearest_free(want_s, dur, placed, gran=GRAN, search_days=SEARCH_DAYS):
    cands = []
    for off in range(search_days + 1):
        day = (want_s + timedelta(days=off)).replace(
            hour=WORK_START, minute=0, second=0, microsecond=0)
        we = day.replace(hour=WORK_END, minute=0)
        t = day
        while t + dur <= we:
            if not any(_overlap(t, t + dur, s, e) for s, e in placed):
                cands.append(t)
            t += timedelta(minutes=gran)
    cands.sort(key=lambda c: (abs((c - want_s).total_seconds()), c))
    return cands[0] if cands else None


def greedy_place(items):
    """Ground-Truth：按收件顺序贪心；不冲突保持原时间，冲突落最近空闲槽。"""
    placed = []          # (start, end)
    result = {}          # id -> (start, end)
    for it in items:
        dur = timedelta(minutes=it["dur"])
        ws, we = it["start"], it["start"] + dur
        if not any(_overlap(ws, we, s, e) for s, e in placed):
            slot = ws
        else:
            slot = _nearest_free(ws, dur, placed)
        result[it["id"]] = (slot, slot + dur)
        placed.append((slot, slot + dur))
    return result


# ── 校验 ──
def validate_schedule(events, items):
    """返回失败原因列表（空 = 完全可行）。events 需带 source_email_id=item id。"""
    fails = []
    if len(events) != len(items):
        fails.append(f"会议数 {len(events)} != {len(items)}")
    ev = sorted(events, key=lambda e: e.start_time)
    for i in range(len(ev)):
        for j in range(i + 1, len(ev)):
            if _overlap(ev[i].start_time, ev[i].end_time,
                        ev[j].start_time, ev[j].end_time):
                fails.append(f"重叠: {ev[i].title} & {ev[j].title}")
    for e in ev:
        end_ok = (e.end_time.hour < WORK_END
                  or (e.end_time.hour == WORK_END and e.end_time.minute == 0))
        if e.start_time.hour < WORK_START or not end_ok:
            fails.append(f"超出工作时间: {e.title} {e.start_time:%m-%d %H:%M}-{e.end_time:%H:%M}")
    by_id = {it["id"]: it for it in items}
    for e in ev:
        it = by_id.get(e.source_email_id)
        if it:
            got = int((e.end_time - e.start_time).total_seconds() // 60)
            if got != it["dur"]:
                fails.append(f"时长不符: {it['id']} 期望 {it['dur']} 得 {got}")
    return fails
