"""Tests for resume_and_cover_builder/utils.py LoggerChatModel."""
import pytest
from unittest.mock import MagicMock, patch

from src.libs.resume_and_cover_builder.utils import LoggerChatModel


class TestLoggerChatModelRetry:
    @patch("src.libs.resume_and_cover_builder.utils.time.sleep")
    def test_max_retries_exhausted(self, mock_sleep):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Permanent failure")

        lcm = LoggerChatModel(mock_llm)
        with pytest.raises(RuntimeError, match="Failed to get a response"):
            lcm(messages=[{"role": "user", "content": "test"}])

    def test_successful_call_returns_reply(self):
        mock_reply = MagicMock()
        mock_reply.content = "Hello"
        mock_reply.response_metadata = {"model_name": "test-model", "system_fingerprint": "", "finish_reason": "stop", "logprobs": None}
        mock_reply.id = "msg_123"
        mock_reply.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_reply

        lcm = LoggerChatModel(mock_llm)
        with patch("src.libs.resume_and_cover_builder.utils.LLMLogger.log_request"):
            result = lcm(messages=[{"role": "user", "content": "test"}])
        assert result == mock_reply

    def test_parse_retry_after_from_header(self):
        """Test that _parse_retry_after extracts from response headers."""
        mock_err = MagicMock()
        mock_err.response.headers = {"retry-after": "42"}
        assert LoggerChatModel._parse_retry_after(mock_err) == 42

    def test_parse_retry_after_from_message(self):
        """Test extraction from error message string."""
        mock_err = Exception("Please retry after 60 seconds")
        assert LoggerChatModel._parse_retry_after(mock_err) == 60

    def test_parse_retry_after_default(self):
        """Test default when no retry info available."""
        mock_err = Exception("Unknown error")
        assert LoggerChatModel._parse_retry_after(mock_err) == 30
