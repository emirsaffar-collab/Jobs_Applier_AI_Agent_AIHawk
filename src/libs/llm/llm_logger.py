"""LLM request/response logging with cost tracking."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Union

from langchain_core.prompt_values import StringPromptValue

from src.libs.llm.models import (
    AIModel,
    OpenAIModel,
    OllamaModel,
    ClaudeModel,
    GeminiModel,
    HuggingFaceModel,
    PerplexityModel,
)
from src.logging import logger
from src.utils.constants import (
    CONTENT,
    INPUT_TOKENS,
    MODEL,
    MODEL_NAME,
    OUTPUT_TOKENS,
    PROMPTS,
    REPLIES,
    RESPONSE_METADATA,
    TIME,
    TOKEN_USAGE,
    TOTAL_COST,
    TOTAL_TOKENS,
    USAGE_METADATA,
)


# Per-model pricing (per token). Defaults are conservative estimates.
# Pricing last updated: 2026-04 — verify against provider dashboards for accuracy.
MODEL_PRICING = {
    # OpenAI
    "gpt-3.5-turbo": (0.0000005, 0.0000015),
    "gpt-4": (0.00003, 0.00006),
    "gpt-4-turbo": (0.00001, 0.00003),
    "gpt-4-1106-preview": (0.00001, 0.00003),
    "gpt-4o": (0.0000025, 0.00001),
    "gpt-4o-mini": (0.00000015, 0.0000006),
    "gpt-4.1": (0.000002, 0.000008),
    "gpt-4.1-mini": (0.0000004, 0.0000016),
    "gpt-4.1-nano": (0.0000001, 0.0000004),
    "o3": (0.00001, 0.00004),
    "o4-mini": (0.0000011, 0.0000044),
    # Anthropic Claude
    "claude-sonnet-4-6": (0.000003, 0.000015),
    "claude-opus-4-6": (0.000015, 0.000075),
    "claude-haiku-4-5": (0.0000008, 0.000004),
    "claude-haiku-4-5-20251001": (0.0000008, 0.000004),
    "claude-3-5-sonnet": (0.000003, 0.000015),
    "claude-3-5-sonnet-20241022": (0.000003, 0.000015),
    "claude-3-haiku": (0.00000025, 0.00000125),
    "claude-3-haiku-20240307": (0.00000025, 0.00000125),
    "claude-3-opus": (0.000015, 0.000075),
    # Google Gemini
    "gemini-2.5-pro": (0.0000025, 0.000015),
    "gemini-2.5-flash": (0.00000015, 0.0000006),
    "gemini-2.0-flash": (0.0000001, 0.0000004),
    "gemini-1.5-pro": (0.0000025, 0.000015),
    "gemini-1.5-flash": (0.000000075, 0.0000003),
    # Perplexity
    "sonar-pro": (0.000003, 0.000015),
    "sonar": (0.000001, 0.000001),
    "sonar-deep-research": (0.000003, 0.000015),
}
DEFAULT_PRICING = (0.000001, 0.000002)


class LLMLogger:
    # Session-level accumulators (class-level so they persist across invocations)
    _session_total_cost: float = 0.0
    _session_total_tokens: int = 0
    _session_call_count: int = 0

    def __init__(self, llm: Union[OpenAIModel, OllamaModel, ClaudeModel, GeminiModel, HuggingFaceModel, PerplexityModel]):
        self.llm = llm
        logger.debug(f"LLMLogger successfully initialized with LLM: {llm}")

    @classmethod
    def get_session_stats(cls) -> dict:
        """Return aggregated LLM usage statistics for the current session."""
        return {
            "total_cost_usd": cls._session_total_cost,
            "total_tokens": cls._session_total_tokens,
            "call_count": cls._session_call_count,
        }

    @classmethod
    def reset_session_stats(cls) -> None:
        """Reset session-level accumulators (e.g. at bot start)."""
        cls._session_total_cost = 0.0
        cls._session_total_tokens = 0
        cls._session_call_count = 0

    @staticmethod
    def log_request(prompts, parsed_reply: Dict[str, Dict]):
        try:
            calls_log = os.path.join(Path("data_folder/output"), "open_ai_calls.json")
        except Exception as e:
            logger.error(f"Error determining the log path: {str(e)}")
            raise

        if isinstance(prompts, StringPromptValue):
            prompts = prompts.text
        elif hasattr(prompts, "messages"):
            try:
                prompts = {
                    f"prompt_{i + 1}": prompt.content
                    for i, prompt in enumerate(prompts.messages)
                }
            except Exception as e:
                logger.error(f"Error converting prompts: {str(e)}")
                raise

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            token_usage = parsed_reply[USAGE_METADATA]
            output_tokens = token_usage[OUTPUT_TOKENS]
            input_tokens = token_usage[INPUT_TOKENS]
            total_tokens = token_usage[TOTAL_TOKENS]
        except KeyError as e:
            logger.error(f"KeyError in parsed_reply structure: {str(e)}")
            raise

        try:
            model_name = parsed_reply[RESPONSE_METADATA][MODEL_NAME]
        except KeyError as e:
            logger.error(f"KeyError in response_metadata: {str(e)}")
            raise

        try:
            prompt_price, completion_price = MODEL_PRICING.get(model_name, DEFAULT_PRICING)
            if model_name not in MODEL_PRICING:
                logger.warning(
                    "No pricing data for model '{}', cost estimate may be inaccurate. "
                    "Add it to MODEL_PRICING in llm_logger.py.",
                    model_name,
                )
            total_cost = (input_tokens * prompt_price) + (output_tokens * completion_price)
        except Exception as e:
            logger.error(f"Error calculating total cost: {str(e)}")
            raise

        # Update session-level accumulators
        LLMLogger._session_total_cost += total_cost
        LLMLogger._session_total_tokens += total_tokens
        LLMLogger._session_call_count += 1

        try:
            log_entry = {
                MODEL: model_name,
                TIME: current_time,
                PROMPTS: prompts,
                REPLIES: parsed_reply[CONTENT],
                TOTAL_TOKENS: total_tokens,
                INPUT_TOKENS: input_tokens,
                OUTPUT_TOKENS: output_tokens,
                TOTAL_COST: total_cost,
            }
        except KeyError as e:
            logger.error(f"Error creating log entry: missing key {str(e)}")
            raise

        try:
            with open(calls_log, "a", encoding="utf-8") as f:
                json_string = json.dumps(log_entry, ensure_ascii=False, indent=4)
                f.write(json_string + "\n")
        except Exception as e:
            logger.error(f"Error writing log entry to file: {str(e)}")
            raise
