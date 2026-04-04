"""Tests for BotManager and BotConfig."""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from src.automation.bot_manager import BotConfig, BotManager, RESUME_PATH


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset BotManager singleton between tests."""
    BotManager._instance = None
    yield
    BotManager._instance = None


# ------------------------------------------------------------------
# BotConfig dataclass
# ------------------------------------------------------------------


class TestBotConfig:
    def test_required_fields(self):
        cfg = BotConfig(
            platforms=["linkedin"],
            credentials={"linkedin": {"email": "a@b.com"}},
            preferences={"remote": True},
            llm_api_key="sk-test",
        )
        assert cfg.platforms == ["linkedin"]
        assert cfg.llm_api_key == "sk-test"

    def test_default_values(self):
        cfg = BotConfig(
            platforms=[],
            credentials={},
            preferences={},
            llm_api_key="key",
        )
        assert cfg.llm_model_type == "claude"
        assert cfg.llm_model == "claude-sonnet-4-6"
        assert cfg.llm_api_url == ""
        assert cfg.min_score == 7
        assert cfg.max_applications == 50
        assert cfg.headless is True
        assert cfg.generate_tailored_resume is False
        assert cfg.capsolver_api_key == ""
        assert cfg.proxies == []
        assert cfg.recruiter_outreach_enabled is False
        assert cfg.recruiter_outreach_daily_limit == 20
        assert cfg.recruiter_outreach_style == "professional"
        assert cfg.rate_limits == {}
        assert cfg.rate_limit_default == 80
        assert cfg.rate_limit_cooldown_minutes == 5.0

    def test_custom_overrides(self):
        cfg = BotConfig(
            platforms=["indeed"],
            credentials={},
            preferences={},
            llm_api_key="key",
            min_score=5,
            max_applications=100,
            headless=False,
            proxies=["http://proxy1:8080"],
        )
        assert cfg.min_score == 5
        assert cfg.max_applications == 100
        assert cfg.headless is False
        assert cfg.proxies == ["http://proxy1:8080"]

    def test_proxies_not_shared_between_instances(self):
        """Ensure default_factory creates independent lists."""
        cfg1 = BotConfig(platforms=[], credentials={}, preferences={}, llm_api_key="k")
        cfg2 = BotConfig(platforms=[], credentials={}, preferences={}, llm_api_key="k")
        cfg1.proxies.append("http://proxy")
        assert cfg2.proxies == []


# ------------------------------------------------------------------
# BotManager singleton
# ------------------------------------------------------------------


class TestBotManagerSingleton:
    def test_returns_same_instance(self):
        bm1 = BotManager()
        bm2 = BotManager()
        assert bm1 is bm2

    def test_reset_creates_new_instance(self):
        bm1 = BotManager()
        BotManager._instance = None
        bm2 = BotManager()
        assert bm1 is not bm2


# ------------------------------------------------------------------
# _init and get_status
# ------------------------------------------------------------------


class TestBotManagerInit:
    def test_initial_status_idle(self):
        bm = BotManager()
        assert bm.status == "idle"

    def test_initial_session_id_empty(self):
        bm = BotManager()
        assert bm.session_id == ""

    def test_initial_stats_structure(self):
        bm = BotManager()
        assert bm.stats["applied"] == 0
        assert bm.stats["skipped"] == 0
        assert bm.stats["failed"] == 0
        assert bm.stats["current_platform"] == ""
        assert bm.stats["current_job"] == ""
        assert bm.stats["log"] == []

    def test_initial_progress_callbacks_empty(self):
        bm = BotManager()
        assert bm._progress_callbacks == []

    def test_pause_event_set_by_default(self):
        bm = BotManager()
        assert bm._pause_event.is_set()


class TestGetStatus:
    def test_returns_correct_structure(self):
        bm = BotManager()
        status = bm.get_status()
        assert "status" in status
        assert "session_id" in status
        assert "stats" in status
        assert status["status"] == "idle"
        assert status["session_id"] == ""

    def test_stats_is_a_copy(self):
        bm = BotManager()
        status = bm.get_status()
        status["stats"]["applied"] = 999
        assert bm.stats["applied"] == 0


# ------------------------------------------------------------------
# _log
# ------------------------------------------------------------------


class TestLog:
    @patch("src.automation.bot_manager.logger")
    def test_appends_to_stats_log(self, mock_logger):
        bm = BotManager()
        bm._log("test message")
        assert len(bm.stats["log"]) == 1
        assert bm.stats["log"][0]["msg"] == "test message"

    @patch("src.automation.bot_manager.logger")
    def test_trims_log_to_500_entries(self, mock_logger):
        bm = BotManager()
        # Pre-fill with 500 entries
        bm.stats["log"] = [{"msg": f"old-{i}"} for i in range(500)]
        assert len(bm.stats["log"]) == 500

        # Adding one more should trigger trim
        bm._log("new entry")
        assert len(bm.stats["log"]) == 500
        # The oldest entry should have been dropped
        assert bm.stats["log"][-1]["msg"] == "new entry"
        assert bm.stats["log"][0]["msg"] != "old-0"

    @patch("src.automation.bot_manager.logger")
    def test_log_calls_logger(self, mock_logger):
        bm = BotManager()
        bm._log("hello")
        mock_logger.info.assert_called_once_with("[BotManager] {}", "hello")

    @patch("src.automation.bot_manager.logger")
    def test_log_fires_progress_callbacks(self, mock_logger):
        bm = BotManager()
        called_with = []

        async def fake_cb(entry):
            called_with.append(entry)

        bm.register_progress_callback(fake_cb)

        # _log calls asyncio.create_task which needs a running loop
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_log_in_loop(bm, "cb test"))
            # Let pending tasks complete
            loop.run_until_complete(asyncio.sleep(0.01))
        finally:
            loop.close()

        assert len(called_with) == 1
        assert called_with[0]["msg"] == "cb test"

    @patch("src.automation.bot_manager.logger")
    def test_log_handles_no_event_loop(self, mock_logger):
        """_log should not raise even if there is no running event loop."""
        bm = BotManager()

        async def fake_cb(entry):
            pass

        bm.register_progress_callback(fake_cb)
        # No event loop running -- should silently catch RuntimeError
        bm._log("no loop")
        assert bm.stats["log"][-1]["msg"] == "no loop"


async def _run_log_in_loop(bm, message):
    """Helper to call _log inside a running event loop so create_task works."""
    bm._log(message)
    await asyncio.sleep(0)  # yield to let the callback task run


# ------------------------------------------------------------------
# start
# ------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_raises_if_already_running(self):
        bm = BotManager()
        bm.status = "running"
        cfg = BotConfig(
            platforms=[], credentials={}, preferences={}, llm_api_key="k"
        )
        with pytest.raises(RuntimeError, match="already running"):
            await bm.start(cfg)

    @pytest.mark.asyncio
    async def test_start_sets_running_status(self):
        bm = BotManager()
        cfg = BotConfig(
            platforms=[], credentials={}, preferences={}, llm_api_key="k"
        )

        async def noop_run_loop(config):
            pass

        with patch.object(bm, "_run_loop", side_effect=noop_run_loop):
            session_id = await bm.start(cfg)

        assert bm.status == "running"
        assert session_id != ""
        assert len(session_id) == 8

    @pytest.mark.asyncio
    async def test_start_resets_stats(self):
        bm = BotManager()
        bm.stats["applied"] = 10
        cfg = BotConfig(
            platforms=[], credentials={}, preferences={}, llm_api_key="k"
        )

        async def noop_run_loop(config):
            pass

        with patch.object(bm, "_run_loop", side_effect=noop_run_loop):
            await bm.start(cfg)

        assert bm.stats["applied"] == 0


# ------------------------------------------------------------------
# pause / resume
# ------------------------------------------------------------------


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_from_running(self):
        bm = BotManager()
        bm.status = "running"
        await bm.pause()
        assert bm.status == "paused"
        assert not bm._pause_event.is_set()

    @pytest.mark.asyncio
    async def test_pause_from_idle_does_nothing(self):
        bm = BotManager()
        bm.status = "idle"
        await bm.pause()
        assert bm.status == "idle"

    @pytest.mark.asyncio
    async def test_resume_from_paused(self):
        bm = BotManager()
        bm.status = "paused"
        bm._pause_event.clear()
        await bm.resume()
        assert bm.status == "running"
        assert bm._pause_event.is_set()

    @pytest.mark.asyncio
    async def test_resume_from_idle_does_nothing(self):
        bm = BotManager()
        bm.status = "idle"
        await bm.resume()
        assert bm.status == "idle"

    @pytest.mark.asyncio
    async def test_pause_resume_roundtrip(self):
        bm = BotManager()
        bm.status = "running"
        await bm.pause()
        assert bm.status == "paused"
        await bm.resume()
        assert bm.status == "running"
        assert bm._pause_event.is_set()

    @pytest.mark.asyncio
    @patch("src.automation.bot_manager.logger")
    async def test_pause_logs_message(self, mock_logger):
        bm = BotManager()
        bm.status = "running"
        await bm.pause()
        assert any("paused" in e["msg"].lower() for e in bm.stats["log"])

    @pytest.mark.asyncio
    @patch("src.automation.bot_manager.logger")
    async def test_resume_logs_message(self, mock_logger):
        bm = BotManager()
        bm.status = "paused"
        await bm.resume()
        assert any("resumed" in e["msg"].lower() for e in bm.stats["log"])


# ------------------------------------------------------------------
# _load_resume
# ------------------------------------------------------------------


class TestLoadResume:
    def test_returns_content_when_file_exists(self, tmp_path):
        fake_resume = tmp_path / "resume.yaml"
        fake_resume.write_text("name: Test User", encoding="utf-8")
        with patch("src.automation.bot_manager.RESUME_PATH", fake_resume):
            result = BotManager._load_resume()
        assert result == "name: Test User"

    def test_returns_empty_string_when_missing(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        with patch("src.automation.bot_manager.RESUME_PATH", missing):
            result = BotManager._load_resume()
        assert result == ""


# ------------------------------------------------------------------
# Progress callbacks
# ------------------------------------------------------------------


class TestProgressCallbacks:
    def test_register_callback(self):
        bm = BotManager()

        async def cb(entry):
            pass

        bm.register_progress_callback(cb)
        assert cb in bm._progress_callbacks

    def test_register_multiple_callbacks(self):
        bm = BotManager()

        async def cb1(entry):
            pass

        async def cb2(entry):
            pass

        bm.register_progress_callback(cb1)
        bm.register_progress_callback(cb2)
        assert len(bm._progress_callbacks) == 2

    def test_unregister_callback(self):
        bm = BotManager()

        async def cb(entry):
            pass

        bm.register_progress_callback(cb)
        bm.unregister_progress_callback(cb)
        assert cb not in bm._progress_callbacks

    def test_unregister_nonexistent_callback_does_not_raise(self):
        bm = BotManager()

        async def cb(entry):
            pass

        # Should not raise
        bm.unregister_progress_callback(cb)
        assert bm._progress_callbacks == []

    def test_unregister_only_removes_target(self):
        bm = BotManager()

        async def cb1(entry):
            pass

        async def cb2(entry):
            pass

        bm.register_progress_callback(cb1)
        bm.register_progress_callback(cb2)
        bm.unregister_progress_callback(cb1)
        assert bm._progress_callbacks == [cb2]


# ------------------------------------------------------------------
# stop
# ------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    @patch("src.automation.bot_manager.logger")
    async def test_stop_sets_idle(self, mock_logger):
        bm = BotManager()
        bm.status = "running"
        bm._task = None
        await bm.stop()
        assert bm.status == "idle"

    @pytest.mark.asyncio
    @patch("src.automation.bot_manager.logger")
    async def test_stop_sets_stop_event(self, mock_logger):
        bm = BotManager()
        bm.status = "running"
        bm._task = None
        await bm.stop()
        assert bm._stop_event.is_set()

    @pytest.mark.asyncio
    @patch("src.automation.bot_manager.logger")
    async def test_stop_unblocks_pause(self, mock_logger):
        bm = BotManager()
        bm.status = "paused"
        bm._pause_event.clear()
        bm._task = None
        await bm.stop()
        assert bm._pause_event.is_set()

    @pytest.mark.asyncio
    @patch("src.automation.bot_manager.logger")
    async def test_stop_logs_message(self, mock_logger):
        bm = BotManager()
        bm._task = None
        await bm.stop()
        assert any("stopped" in e["msg"].lower() for e in bm.stats["log"])


# ------------------------------------------------------------------
# _reset_stats
# ------------------------------------------------------------------


class TestResetStats:
    def test_clears_all_counters(self):
        bm = BotManager()
        bm.stats["applied"] = 5
        bm.stats["skipped"] = 3
        bm.stats["failed"] = 2
        bm.stats["current_platform"] = "linkedin"
        bm.stats["current_job"] = "SWE @ Google"
        bm.stats["log"] = [{"msg": "something"}]

        bm._reset_stats()

        assert bm.stats["applied"] == 0
        assert bm.stats["skipped"] == 0
        assert bm.stats["failed"] == 0
        assert bm.stats["current_platform"] == ""
        assert bm.stats["current_job"] == ""
        assert bm.stats["log"] == []
