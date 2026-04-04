"""Tests for Autopilot channel protocol modules (models, inbox, outbox)."""

import json
import time

import pytest

from soothe.cognition.channel.inbox import ChannelInbox
from soothe.cognition.channel.models import (
    CHANNEL_SOOTHE_TO_USER,
    CHANNEL_USER_TO_SOOTHE,
    CRITICAL_MESSAGE_TYPES,
    ChannelMessage,
)
from soothe.cognition.channel.outbox import MAX_RETRIES, ChannelOutbox


class TestChannelMessageDefaults:
    """Unit tests for ChannelMessage default construction."""

    def test_default_fields(self) -> None:
        msg = ChannelMessage(type="task_submit")
        assert msg.type == "task_submit"
        assert msg.payload == {}
        assert msg.sender == "soothe"
        assert msg.requires_ack is False
        assert msg.ack_id is None
        assert msg.timestamp is not None

    def test_custom_payload(self) -> None:
        msg = ChannelMessage(type="feedback", payload={"rating": 5, "text": "Great"})
        assert msg.payload == {"rating": 5, "text": "Great"}

    def test_custom_timestamp_preserved(self) -> None:
        from datetime import UTC, datetime, timedelta

        fixed_time = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        msg = ChannelMessage(type="status_update", timestamp=fixed_time)
        assert msg.timestamp == fixed_time

    def test_sender_user(self) -> None:
        msg = ChannelMessage(type="task_submit", sender="user")
        assert msg.sender == "user"

    def test_sender_soothe(self) -> None:
        msg = ChannelMessage(type="status_update", sender="soothe")
        assert msg.sender == "soothe"

    def test_sender_system(self) -> None:
        msg = ChannelMessage(type="signal_interrupt", sender="system")
        assert msg.sender == "system"


class TestChannelMessageCriticalTypes:
    """Tests for __post_init__ auto-setting requires_ack on critical types."""

    def test_blocker_alert_auto_requires_ack(self) -> None:
        msg = ChannelMessage(type="blocker_alert")
        assert msg.requires_ack is True

    def test_dreaming_entered_auto_requires_ack(self) -> None:
        msg = ChannelMessage(type="dreaming_entered")
        assert msg.requires_ack is True

    def test_must_goal_confirmation_auto_requires_ack(self) -> None:
        msg = ChannelMessage(type="must_goal_confirmation")
        assert msg.requires_ack is True

    def test_non_critical_stays_false(self) -> None:
        msg = ChannelMessage(type="status_update")
        assert msg.requires_ack is False

    def test_explicit_requires_ack_false_not_overridden(self) -> None:
        msg = ChannelMessage(type="blocker_alert", requires_ack=False)
        assert msg.requires_ack is True

    def test_explicit_requires_ack_true_stays_true(self) -> None:
        msg = ChannelMessage(type="status_update", requires_ack=True)
        assert msg.requires_ack is True

    def test_all_critical_types_covered(self) -> None:
        for ctype in CRITICAL_MESSAGE_TYPES:
            msg = ChannelMessage(type=ctype)
            assert msg.requires_ack is True, f"{ctype} should auto-set requires_ack"

    def test_user_to_soothe_types_not_critical(self) -> None:
        non_critical_user = CHANNEL_USER_TO_SOOTHE - CRITICAL_MESSAGE_TYPES
        for utype in non_critical_user:
            msg = ChannelMessage(type=utype)
            assert msg.requires_ack is False

    def test_soothe_to_user_types_not_critical(self) -> None:
        non_critical_soothe = CHANNEL_SOOTHE_TO_USER - CRITICAL_MESSAGE_TYPES
        for stype in non_critical_soothe:
            msg = ChannelMessage(type=stype)
            assert msg.requires_ack is False


class TestChannelMessageSerialization:
    """Tests for to_dict / from_dict / to_json / from_json round-trips."""

    def test_to_dict_all_fields(self) -> None:
        from datetime import UTC, datetime

        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        msg = ChannelMessage(
            type="goal_progress",
            payload={"goal_id": "abc123", "progress": 0.5},
            timestamp=ts,
            sender="soothe",
            requires_ack=True,
            ack_id="deadbeef00",
        )
        d = msg.to_dict()
        assert d["type"] == "goal_progress"
        assert d["payload"] == {"goal_id": "abc123", "progress": 0.5}
        assert d["timestamp"] == "2025-06-01T12:00:00+00:00"
        assert d["sender"] == "soothe"
        assert d["requires_ack"] is True
        assert d["ack_id"] == "deadbeef00"

    def test_from_dict_round_trip(self) -> None:
        from datetime import UTC, datetime

        ts = datetime(2025, 3, 10, 8, 15, 0, tzinfo=UTC)
        original = ChannelMessage(
            type="session_summary",
            payload={"items_done": 5},
            timestamp=ts,
            sender="soothe",
            requires_ack=False,
        )
        d = original.to_dict()
        restored = ChannelMessage.from_dict(d)
        assert restored.type == original.type
        assert restored.payload == original.payload
        assert restored.timestamp == original.timestamp
        assert restored.sender == original.sender
        assert restored.requires_ack == original.requires_ack

    def test_from_dict_defaults(self) -> None:
        d = {"type": "task_submit"}
        msg = ChannelMessage.from_dict(d)
        assert msg.type == "task_submit"
        assert msg.payload == {}
        assert msg.sender == "soothe"
        assert msg.requires_ack is False
        assert msg.ack_id is None

    def test_from_dict_with_ack_id(self) -> None:
        d = {
            "type": "blocker_alert",
            "payload": {"detail": "OOM"},
            "sender": "system",
            "requires_ack": True,
            "ack_id": "aabbcc1122",
        }
        msg = ChannelMessage.from_dict(d)
        assert msg.ack_id == "aabbcc1122"
        assert msg.requires_ack is True

    def test_to_json_is_valid_json(self) -> None:
        msg = ChannelMessage(
            type="finding_report",
            payload={"url": "https://example.com"},
            sender="soothe",
        )
        text = msg.to_json()
        parsed = json.loads(text)
        assert parsed["type"] == "finding_report"

    def test_from_json_round_trip(self) -> None:
        from datetime import UTC, datetime

        ts = datetime(2025, 9, 20, 14, 0, 0, tzinfo=UTC)
        original = ChannelMessage(
            type="dreaming_entered",
            payload={"mode": "research"},
            timestamp=ts,
            sender="soothe",
            ack_id="xyz789",
        )
        json_text = original.to_json()
        restored = ChannelMessage.from_json(json_text)
        assert restored.type == original.type
        assert restored.payload == original.payload
        assert restored.timestamp == original.timestamp
        assert restored.ack_id == original.ack_id

    def test_to_json_from_json_symmetry(self) -> None:
        msg = ChannelMessage(
            type="signal_resume",
            payload={"reason": "user requested"},
            sender="user",
        )
        restored = ChannelMessage.from_json(msg.to_json())
        assert restored.type == msg.type
        assert restored.payload == msg.payload
        assert restored.sender == msg.sender


class TestChannelInbox:
    """Unit tests for ChannelInbox file-based message reading."""

    def test_read_pending_no_directory(self) -> None:
        inbox = ChannelInbox()
        result = inbox.read_pending()
        assert result == []

    def test_read_pending_nonexistent_directory(self, tmp_path: str) -> None:
        nonexistent = str(tmp_path / "does_not_exist")
        inbox = ChannelInbox(nonexistent)
        result = inbox.read_pending()
        assert result == []

    def test_read_pending_empty_directory(self, tmp_path: str) -> None:
        inbox = ChannelInbox(str(tmp_path))
        result = inbox.read_pending()
        assert result == []

    def test_read_pending_parses_yaml_frontmatter(self, tmp_path: str) -> None:
        f = tmp_path / "task1.md"
        f.write_text("---\ntype: task_submit\npriority: 80\n---\n\nReview the deployment logs.\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert len(msgs) == 1
        msg = msgs[0]
        assert msg.type == "task_submit"
        assert msg.payload["description"] == "Review the deployment logs."
        assert msg.payload["priority"] == 80
        assert msg.sender == "user"

    def test_read_pending_parses_plain_markdown_no_frontmatter(self, tmp_path: str) -> None:
        f = tmp_path / "simple.md"
        f.write_text("Just fix the bug in the auth module.\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert len(msgs) == 1
        msg = msgs[0]
        assert msg.type == "task_submit"
        # Without frontmatter, the full file text is the description.
        assert msg.payload["description"] == "Just fix the bug in the auth module.\n"
        assert msg.sender == "user"

    def test_read_pending_does_not_return_already_processed(self, tmp_path: str) -> None:
        f = tmp_path / "once.md"
        f.write_text("Run diagnostics.\n")
        inbox = ChannelInbox(str(tmp_path))
        first = inbox.read_pending()
        assert len(first) == 1
        second = inbox.read_pending()
        assert len(second) == 0

    def test_read_pending_multiple_files(self, tmp_path: str) -> None:
        (tmp_path / "a.md").write_text("---\ntype: signal_interrupt\n---\nStop now.\n")
        (tmp_path / "b.md").write_text("---\ntype: task_cancel\n---\nCancel task 42.\n")
        (tmp_path / "c.md").write_text("---\ntype: feedback\n---\nGood job.\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert len(msgs) == 3
        types = {m.type for m in msgs}
        assert types == {"signal_interrupt", "task_cancel", "feedback"}

    def test_read_pending_sorted_by_filename(self, tmp_path: str) -> None:
        (tmp_path / "z.md").write_text("Z message\n")
        (tmp_path / "a.md").write_text("A message\n")
        (tmp_path / "m.md").write_text("M message\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert len(msgs) == 3
        assert msgs[0].payload["description"] == "A message\n"
        assert msgs[1].payload["description"] == "M message\n"
        assert msgs[2].payload["description"] == "Z message\n"

    def test_read_pending_ignores_non_md_files(self, tmp_path: str) -> None:
        (tmp_path / "note.txt").write_text("ignored\n")
        (tmp_path / "valid.md").write_text("valid\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert len(msgs) == 1
        assert msgs[0].payload["description"] == "valid\n"

    def test_read_pending_skips_processed_during_read(self, tmp_path: str) -> None:
        """Files are marked processed during read_pending, so second call skips them."""
        (tmp_path / "x.md").write_text("First\n")
        inbox = ChannelInbox(str(tmp_path))
        inbox.read_pending()
        (tmp_path / "y.md").write_text("Second\n")
        msgs = inbox.read_pending()
        assert len(msgs) == 1
        assert msgs[0].payload["description"] == "Second\n"

    def test_archive_processed_moves_files(self, tmp_path: str) -> None:
        (tmp_path / "old.md").write_text("Old task\n")
        inbox = ChannelInbox(str(tmp_path))
        inbox.read_pending()
        count = inbox.archive_processed()
        assert count == 1
        assert not (tmp_path / "old.md").exists()
        assert (tmp_path / "processed" / "old.md").exists()

    def test_archive_processed_returns_count(self, tmp_path: str) -> None:
        (tmp_path / "a.md").write_text("A\n")
        (tmp_path / "b.md").write_text("B\n")
        (tmp_path / "c.md").write_text("C\n")
        inbox = ChannelInbox(str(tmp_path))
        inbox.read_pending()
        count = inbox.archive_processed()
        assert count == 3

    def test_archive_processed_on_no_pending(self, tmp_path: str) -> None:
        inbox = ChannelInbox(str(tmp_path))
        count = inbox.archive_processed()
        assert count == 0

    def test_archive_processed_no_directory(self) -> None:
        inbox = ChannelInbox()
        count = inbox.archive_processed()
        assert count == 0

    def test_set_directory_creates_path(self, tmp_path: str) -> None:
        new_dir = str(tmp_path / "new_inbox")
        inbox = ChannelInbox()
        inbox.set_directory(new_dir)
        import os

        assert os.path.isdir(new_dir)

    def test_frontmatter_priority_copied_to_payload(self, tmp_path: str) -> None:
        f = tmp_path / "prio.md"
        f.write_text("---\ntype: task_submit\npriority: 95\n---\nUrgent task.\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert msgs[0].payload["priority"] == 95

    def test_frontmatter_context_copied_to_payload(self, tmp_path: str) -> None:
        f = tmp_path / "ctx.md"
        f.write_text("---\ntype: task_submit\ncontext: production_env\n---\nCheck logs.\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        assert msgs[0].payload["context"] == "production_env"

    def test_frontmatter_with_context_and_priority(self, tmp_path: str) -> None:
        f = tmp_path / "both.md"
        f.write_text("---\ntype: signal_resume\npriority: 70\ncontext: staging\n---\nResume.\n")
        inbox = ChannelInbox(str(tmp_path))
        msgs = inbox.read_pending()
        msg = msgs[0]
        assert msg.type == "signal_resume"
        assert msg.payload["priority"] == 70
        assert msg.payload["context"] == "staging"
        assert msg.payload["description"] == "Resume."

    def test_read_pending_after_archive_returns_empty(self, tmp_path: str) -> None:
        (tmp_path / "task.md").write_text("---\ntype: task_submit\n---\nDo it.\n")
        inbox = ChannelInbox(str(tmp_path))
        inbox.read_pending()
        inbox.archive_processed()
        msgs = inbox.read_pending()
        assert msgs == []


class TestChannelOutbox:
    """Unit tests for ChannelOutbox file-based message writing."""

    def test_send_writes_json_file(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="status_update", payload={"status": "ok"})
        filename = outbox.send(msg)
        assert filename.endswith("_status_update.json")
        assert (tmp_path / filename).exists()
        content = json.loads((tmp_path / filename).read_text())
        assert content["type"] == "status_update"

    def test_send_generates_ack_id_for_critical(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert", payload={"detail": "crash"})
        filename = outbox.send(msg)
        parts = filename.split("_", 1)
        ack_id = parts[0]
        assert len(ack_id) == 12
        assert msg.ack_id == ack_id

    def test_send_no_ack_id_for_non_critical(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="status_update", payload={})
        filename = outbox.send(msg)
        # Still generates a UUID-based filename but ack_id stays None
        assert msg.ack_id is None
        assert filename.endswith("_status_update.json")

    def test_send_drops_message_no_directory(self) -> None:
        outbox = ChannelOutbox()
        msg = ChannelMessage(type="task_submit")
        result = outbox.send(msg)
        assert result == ""

    def test_send_creates_directory_if_missing(self, tmp_path: str) -> None:
        outbox_dir = str(tmp_path / "new_outbox")
        outbox = ChannelOutbox(outbox_dir)
        msg = ChannelMessage(type="finding_report")
        outbox.send(msg)
        import os

        assert os.path.isdir(outbox_dir)

    def test_acknowledge_removes_from_pending(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="dreaming_entered")
        outbox.send(msg)
        ack_id = msg.ack_id
        assert ack_id is not None
        unacked = outbox.get_unacked()
        assert len(unacked) == 1
        result = outbox.acknowledge(ack_id)
        assert result is True
        unacked = outbox.get_unacked()
        assert len(unacked) == 0

    def test_acknowledge_moves_file_to_acknowledged(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        ack_id = msg.ack_id
        assert ack_id is not None
        pending_files = list(tmp_path.glob(f"{ack_id}_*"))
        assert len(pending_files) == 1
        outbox.acknowledge(ack_id)
        assert not pending_files[0].exists()
        assert (tmp_path / "acknowledged" / pending_files[0].name).exists()

    def test_acknowledge_unknown_returns_false(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        result = outbox.acknowledge("unknown_ack_id")
        assert result is False

    def test_acknowledge_non_critical_no_pending(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="status_update")
        outbox.send(msg)
        unacked = outbox.get_unacked()
        assert len(unacked) == 0

    def test_get_unacked_returns_list_of_tuples(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        outbox.send(ChannelMessage(type="blocker_alert"))
        outbox.send(ChannelMessage(type="dreaming_entered"))
        unacked = outbox.get_unacked()
        assert len(unacked) == 2
        for ack_id, count in unacked:
            assert isinstance(ack_id, str)
            assert isinstance(count, int)
            assert count == 0

    def test_should_retry_initial(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        assert outbox.should_retry(msg.ack_id) is True

    def test_should_retry_after_max(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        ack_id = msg.ack_id
        for _ in range(MAX_RETRIES):
            outbox.increment_retry(ack_id)
        assert outbox.should_retry(ack_id) is False

    def test_should_retry_one_below_max(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        ack_id = msg.ack_id
        for _ in range(MAX_RETRIES - 1):
            outbox.increment_retry(ack_id)
        assert outbox.should_retry(ack_id) is True

    def test_should_retry_unknown_ack_id(self, tmp_path: str) -> None:
        """Unknown ack_ids return True because default retry count 0 < MAX_RETRIES."""
        outbox = ChannelOutbox(str(tmp_path))
        assert outbox.should_retry("nonexistent") is True

    def test_increment_retry_increments(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        ack_id = msg.ack_id
        assert outbox.increment_retry(ack_id) == 1
        assert outbox.increment_retry(ack_id) == 2
        assert outbox.increment_retry(ack_id) == 3

    def test_retry_count_initial(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        assert outbox.retry_count(msg.ack_id) == 0

    def test_retry_count_after_increments(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        outbox.increment_retry(msg.ack_id)
        outbox.increment_retry(msg.ack_id)
        assert outbox.retry_count(msg.ack_id) == 2

    def test_retry_count_unknown(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        assert outbox.retry_count("unknown") == 0

    def test_clear_ack_removes_from_tracking(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="blocker_alert")
        outbox.send(msg)
        ack_id = msg.ack_id
        assert len(outbox.get_unacked()) == 1
        outbox.clear_ack(ack_id)
        assert len(outbox.get_unacked()) == 0

    def test_clear_ack_unknown_is_noop(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        outbox.clear_ack("nonexistent")
        assert len(outbox.get_unacked()) == 0

    def test_max_retries_constant(self) -> None:
        assert MAX_RETRIES == 3

    def test_set_directory_creates_path(self, tmp_path: str) -> None:
        new_dir = str(tmp_path / "new_outbox")
        outbox = ChannelOutbox()
        outbox.set_directory(new_dir)
        import os

        assert os.path.isdir(new_dir)

    def test_send_with_existing_ack_id_not_regenerated(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(
            type="blocker_alert",
            requires_ack=True,
            ack_id="custom_ack_001",
        )
        filename = outbox.send(msg)
        assert msg.ack_id == "custom_ack_001"
        assert filename.startswith("custom_ack_001_")

    def test_acknowledged_file_readable_after_move(self, tmp_path: str) -> None:
        outbox = ChannelOutbox(str(tmp_path))
        msg = ChannelMessage(type="dreaming_entered", payload={"mode": "deep"})
        outbox.send(msg)
        ack_id = msg.ack_id
        outbox.acknowledge(ack_id)
        ack_file = tmp_path / "acknowledged" / f"{ack_id}_dreaming_entered.json"
        assert ack_file.exists()
        content = json.loads(ack_file.read_text())
        assert content["type"] == "dreaming_entered"
