"""Tests for llm_manager module."""
import pytest
from unittest.mock import MagicMock, patch

from src.libs.llm_manager import AIAdapter, LoggerChatModel


class TestAIAdapter:
    @patch("src.libs.llm_manager.cfg")
    def test_unsupported_model_raises(self, mock_cfg):
        mock_cfg.LLM_MODEL_TYPE = "unsupported_model"
        mock_cfg.LLM_MODEL = "fake"
        mock_cfg.LLM_API_URL = ""
        with pytest.raises(ValueError, match="Unsupported model type"):
            AIAdapter(config={}, api_key="test-key")


class TestLoggerChatModel:
    def test_max_retries_exhausted(self):
        """Verify that the retry loop does not run forever."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Always fails")

        lcm = LoggerChatModel(mock_llm)
        with pytest.raises(RuntimeError, match="LLM call failed after"):
            lcm(messages=[{"role": "user", "content": "test"}], max_retries=2)

        assert mock_llm.invoke.call_count == 2

    def test_successful_call(self):
        """Verify successful LLM call returns the reply."""
        mock_reply = MagicMock()
        mock_reply.content = "Hello"
        mock_reply.response_metadata = {"model_name": "test", "system_fingerprint": "", "finish_reason": "stop", "logprobs": None}
        mock_reply.id = "msg_123"
        mock_reply.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_reply

        lcm = LoggerChatModel(mock_llm)
        # Patch log_request to avoid file I/O
        with patch("src.libs.llm_manager.LLMLogger.log_request"):
            result = lcm(messages=[{"role": "user", "content": "test"}])

        assert result == mock_reply
