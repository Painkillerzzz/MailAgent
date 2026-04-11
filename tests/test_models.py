"""数据模型测试"""

from datetime import datetime, timezone

from mail_agent.models import (
    CalendarEvent,
    EmailAnalysis,
    EmailCategory,
    EmailIntent,
    EmailMessage,
    PriorityScore,
    ProcessingResult,
    ReplyDraft,
    ScheduleConflict,
    UrgencyLevel,
)


class TestEmailMessage:
    def test_create_minimal(self):
        msg = EmailMessage()
        assert msg.sender == ""
        assert msg.subject == ""
        assert msg.body == ""
        assert msg.recipients == []
        assert msg.is_read is False

    def test_create_full(self):
        msg = EmailMessage(
            message_id="<123@mail.com>",
            sender="test@test.com",
            sender_name="Test User",
            recipients=["a@b.com", "c@d.com"],
            subject="Hello",
            body="World",
            date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            thread_id="thread-1",
            is_read=True,
            has_attachments=True,
            attachments=["file.pdf"],
        )
        assert msg.message_id == "<123@mail.com>"
        assert msg.sender == "test@test.com"
        assert len(msg.recipients) == 2
        assert msg.has_attachments is True
        assert "file.pdf" in msg.attachments


class TestEmailIntent:
    def test_enum_values(self):
        assert EmailIntent.MEETING_REQUEST.value == "meeting_request"
        assert EmailIntent.TASK_ASSIGNMENT.value == "task_assignment"
        assert EmailIntent.DEADLINE_REMINDER.value == "deadline_reminder"

    def test_from_string(self):
        intent = EmailIntent("meeting_request")
        assert intent == EmailIntent.MEETING_REQUEST


class TestUrgencyLevel:
    def test_enum_values(self):
        assert UrgencyLevel.CRITICAL.value == "critical"
        assert UrgencyLevel.HIGH.value == "high"
        assert UrgencyLevel.MEDIUM.value == "medium"
        assert UrgencyLevel.LOW.value == "low"


class TestEmailAnalysis:
    def test_default_values(self):
        analysis = EmailAnalysis()
        assert analysis.intent == EmailIntent.OTHER
        assert analysis.urgency == UrgencyLevel.LOW
        assert analysis.requires_reply is False
        assert analysis.contains_schedule is False
        assert analysis.key_points == []

    def test_full_analysis(self):
        analysis = EmailAnalysis(
            intent=EmailIntent.MEETING_REQUEST,
            urgency=UrgencyLevel.HIGH,
            category=EmailCategory.MEETING,
            requires_reply=True,
            contains_schedule=True,
            schedule_description="Thursday at 3pm",
            summary="Meeting request",
            key_points=["point1", "point2"],
        )
        assert analysis.intent == EmailIntent.MEETING_REQUEST
        assert analysis.urgency == UrgencyLevel.HIGH
        assert len(analysis.key_points) == 2


class TestCalendarEvent:
    def test_create_event(self):
        now = datetime.now()
        event = CalendarEvent(
            event_id="evt-1",
            title="Test Meeting",
            start_time=now,
            end_time=now,
        )
        assert event.event_id == "evt-1"
        assert event.title == "Test Meeting"
        assert event.attendees == []


class TestScheduleConflict:
    def test_no_conflict(self):
        conflict = ScheduleConflict()
        assert conflict.has_conflict is False
        assert conflict.conflicting_events == []

    def test_with_conflict(self):
        now = datetime.now()
        evt = CalendarEvent(
            title="Existing", start_time=now, end_time=now
        )
        conflict = ScheduleConflict(has_conflict=True, conflicting_events=[evt])
        assert conflict.has_conflict is True
        assert len(conflict.conflicting_events) == 1


class TestPriorityScore:
    def test_default_score(self):
        score = PriorityScore()
        assert score.total_score == 0.0
        assert score.level == UrgencyLevel.LOW

    def test_score_values(self):
        score = PriorityScore(
            sender_weight=2.0,
            deadline_weight=3.0,
            intent_weight=2.5,
            urgency_weight=1.5,
            total_score=9.0,
            level=UrgencyLevel.HIGH,
            reasoning="test reasoning",
        )
        assert score.total_score == 9.0
        assert score.level == UrgencyLevel.HIGH


class TestReplyDraft:
    def test_create_draft(self):
        draft = ReplyDraft(
            subject="Re: Hello",
            body="Thanks for your email.",
            to=["sender@test.com"],
        )
        assert draft.subject == "Re: Hello"
        assert "sender@test.com" in draft.to


class TestProcessingResult:
    def test_minimal_result(self):
        result = ProcessingResult(
            email=EmailMessage(),
            analysis=EmailAnalysis(),
            priority=PriorityScore(),
        )
        assert result.calendar_event is None
        assert result.reply_draft is None
        assert result.processing_steps == []
