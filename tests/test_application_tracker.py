"""Tests for ApplicationTracker SQLite operations."""
import pytest
from pathlib import Path
from src.automation.application_tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "test_apps.db"
    return ApplicationTracker(db_path=db)


class TestApplicationTracker:
    def test_record_and_url_seen(self, tracker):
        row_id = tracker.record_discovered(
            platform="linkedin",
            company="Acme",
            title="Engineer",
            url="https://example.com/job1",
            session_id="s1",
        )
        assert row_id is not None
        assert tracker.url_seen("https://example.com/job1") is True
        assert tracker.url_seen("https://example.com/job2") is False

    def test_duplicate_url_returns_none(self, tracker):
        tracker.record_discovered("linkedin", "Acme", "Engineer", "https://example.com/j1")
        result = tracker.record_discovered("linkedin", "Acme", "Engineer", "https://example.com/j1")
        assert result is None

    def test_mark_applied(self, tracker):
        tracker.record_discovered("indeed", "Corp", "Dev", "https://example.com/j2")
        tracker.mark_applied("https://example.com/j2", "/path/resume.pdf", "")
        assert tracker.already_applied("Corp", "Dev") is True

    def test_already_applied_different_title(self, tracker):
        tracker.record_discovered("indeed", "Corp", "Dev", "https://example.com/j3")
        tracker.mark_applied("https://example.com/j3")
        assert tracker.already_applied("Corp", "Manager") is False

    def test_mark_skipped(self, tracker):
        tracker.record_discovered("dice", "X", "Y", "https://example.com/j4")
        tracker.mark_skipped("https://example.com/j4", "low score")
        apps = tracker.get_applications(status="skipped")
        assert len(apps) == 1
        assert apps[0]["notes"] == "low score"

    def test_mark_failed(self, tracker):
        tracker.record_discovered("dice", "X", "Z", "https://example.com/j5")
        tracker.mark_failed("https://example.com/j5", "timeout")
        apps = tracker.get_applications(status="failed")
        assert len(apps) == 1

    def test_update_score(self, tracker):
        tracker.record_discovered("linkedin", "A", "B", "https://example.com/j6")
        tracker.update_score("https://example.com/j6", 8, "good match")
        apps = tracker.get_applications()
        assert apps[0]["score"] == 8
        assert apps[0]["status"] == "scored"

    def test_get_stats(self, tracker):
        tracker.record_discovered("linkedin", "A", "B", "https://example.com/j7")
        tracker.mark_applied("https://example.com/j7")
        tracker.record_discovered("indeed", "C", "D", "https://example.com/j8")
        tracker.mark_skipped("https://example.com/j8")
        stats = tracker.get_stats()
        assert stats["total"] == 2
        assert stats["applied"] == 1
        assert stats["skipped"] == 1

    def test_export_csv(self, tracker):
        tracker.record_discovered("linkedin", "A", "B", "https://example.com/j9")
        csv = tracker.export_csv()
        assert "linkedin" in csv
        assert "https://example.com/j9" in csv

    def test_get_application_by_id(self, tracker):
        row_id = tracker.record_discovered("linkedin", "A", "B", "https://example.com/j10")
        app = tracker.get_application(row_id)
        assert app is not None
        assert app["company"] == "A"
        assert tracker.get_application(99999) is None
