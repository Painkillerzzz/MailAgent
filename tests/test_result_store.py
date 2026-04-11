"""ResultStore 测试"""

from datetime import datetime, timezone

import pytest

from mail_agent.models import (
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    PriorityScore,
    ProcessingResult,
    UrgencyLevel,
)
from mail_agent.web.result_store import ResultStore


def _make_result(
    message_id: str = "",
    subject: str = "Test",
    sender: str = "a@b.com",
    intent: EmailIntent = EmailIntent.OTHER,
    urgency: UrgencyLevel = UrgencyLevel.LOW,
    category: EmailCategory = EmailCategory.OTHER,
    score: float = 1.0,
    contains_schedule: bool = False,
    schedule_desc: str = "",
) -> ProcessingResult:
    return ProcessingResult(
        email=EmailMessage(
            message_id=message_id,
            sender=sender,
            subject=subject,
            date=datetime.now(timezone.utc),
        ),
        analysis=EmailAnalysis(
            intent=intent,
            urgency=urgency,
            category=category,
            contains_schedule=contains_schedule,
            schedule_description=schedule_desc,
            summary=f"Summary of {subject}",
        ),
        priority=PriorityScore(
            total_score=score,
            level=urgency,
        ),
    )


class TestResultStore:
    @pytest.fixture
    def store(self, tmp_path):
        return ResultStore(path=tmp_path / "results.json")

    def test_add_and_count(self, store):
        store.add(_make_result(message_id="m1"))
        assert store.count == 1
        store.add(_make_result(message_id="m2"))
        assert store.count == 2

    def test_add_deduplicates_by_message_id(self, store):
        store.add(_make_result(message_id="m1", subject="First"))
        store.add(_make_result(message_id="m1", subject="Updated"))
        assert store.count == 1
        results = store.list_results()
        assert results[0].email.subject == "Updated"

    def test_add_empty_message_id_no_dedup(self, store):
        store.add(_make_result(message_id="", subject="A"))
        store.add(_make_result(message_id="", subject="B"))
        assert store.count == 2

    def test_add_many(self, store):
        results = [_make_result(message_id=f"m{i}") for i in range(5)]
        store.add_many(results)
        assert store.count == 5

    def test_list_results_default_sort(self, store):
        store.add(_make_result(message_id="low", score=1.0))
        store.add(_make_result(message_id="high", score=10.0))
        results = store.list_results()
        assert results[0].priority.total_score >= results[1].priority.total_score

    def test_list_results_sort_asc(self, store):
        store.add(_make_result(message_id="low", score=1.0))
        store.add(_make_result(message_id="high", score=10.0))
        results = store.list_results(sort_by="priority", order="asc")
        assert results[0].priority.total_score <= results[1].priority.total_score

    def test_filter_by_urgency(self, store):
        store.add(_make_result(message_id="c", urgency=UrgencyLevel.CRITICAL, score=10))
        store.add(_make_result(message_id="l", urgency=UrgencyLevel.LOW, score=1))
        results = store.list_results(urgency="critical")
        assert len(results) == 1
        assert results[0].priority.level == UrgencyLevel.CRITICAL

    def test_filter_by_category(self, store):
        store.add(_make_result(message_id="m", category=EmailCategory.MEETING))
        store.add(_make_result(message_id="t", category=EmailCategory.TASK))
        results = store.list_results(category="meeting")
        assert len(results) == 1

    def test_filter_by_intent(self, store):
        store.add(_make_result(message_id="mr", intent=EmailIntent.MEETING_REQUEST))
        store.add(_make_result(message_id="n", intent=EmailIntent.NOTIFICATION))
        results = store.list_results(intent="meeting_request")
        assert len(results) == 1

    def test_search(self, store):
        store.add(_make_result(message_id="a", subject="Meeting with Prof"))
        store.add(_make_result(message_id="b", subject="Newsletter update"))
        results = store.list_results(search="prof")
        assert len(results) == 1
        assert "Prof" in results[0].email.subject

    def test_get_urgent(self, store):
        store.add(_make_result(message_id="c", urgency=UrgencyLevel.CRITICAL, score=10))
        store.add(_make_result(message_id="h", urgency=UrgencyLevel.HIGH, score=7))
        store.add(_make_result(message_id="l", urgency=UrgencyLevel.LOW, score=1))
        urgent = store.get_urgent()
        assert len(urgent) == 2

    def test_get_deadlines(self, store):
        store.add(_make_result(
            message_id="d",
            intent=EmailIntent.DEADLINE_REMINDER,
            contains_schedule=True,
            schedule_desc="Friday EOD",
        ))
        store.add(_make_result(message_id="n", intent=EmailIntent.NOTIFICATION))
        deadlines = store.get_deadlines()
        assert len(deadlines) == 1

    def test_clear(self, store):
        store.add(_make_result(message_id="m1"))
        store.clear()
        assert store.count == 0

    def test_persistence(self, tmp_path):
        path = tmp_path / "results.json"
        store1 = ResultStore(path=path)
        store1.add(_make_result(message_id="persist", subject="Persistent"))
        store2 = ResultStore(path=path)
        assert store2.count == 1
        assert store2.list_results()[0].email.subject == "Persistent"
