"""
This module contains utility functions for the Resume and Cover Letter Builder service.
"""

# app/libs/resume_and_cover_builder/utils.py
import json
import re
import time
from datetime import datetime
from typing import Dict, List
from langchain_core.messages.ai import AIMessage
from langchain_core.prompt_values import StringPromptValue
from .config import global_config
from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None


# Per-model token pricing (input_price, output_price per token)
_MODEL_PRICING = {
    "gpt-3.5-turbo": (0.0000005, 0.0000015),
    "gpt-4": (0.00003, 0.00006),
    "gpt-4o": (0.0000025, 0.00001),
    "gpt-4o-mini": (0.00000015, 0.0000006),
    "claude-sonnet-4-6": (0.000003, 0.000015),
    "claude-opus-4-6": (0.000015, 0.000075),
    "claude-haiku-4-5-20251001": (0.0000008, 0.000004),
}
_DEFAULT_PRICING = (0.000001, 0.000002)


class LLMLogger:

    def __init__(self, llm):
        self.llm = llm

    @staticmethod
    def log_request(prompts, parsed_reply: Dict[str, Dict]):
        calls_log = global_config.LOG_OUTPUT_FILE_PATH / "open_ai_calls.json"
        if isinstance(prompts, StringPromptValue):
            prompts = prompts.text
        elif hasattr(prompts, "messages"):
            prompts = {
                f"prompt_{i+1}": prompt.content
                for i, prompt in enumerate(prompts.messages)
            }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Extract token usage details from the response
        token_usage = parsed_reply["usage_metadata"]
        output_tokens = token_usage["output_tokens"]
        input_tokens = token_usage["input_tokens"]
        total_tokens = token_usage["total_tokens"]

        # Extract model details from the response
        model_name = parsed_reply["response_metadata"]["model_name"]
        prompt_price, completion_price = _MODEL_PRICING.get(model_name, _DEFAULT_PRICING)

        # Calculate the total cost of the API call
        total_cost = (input_tokens * prompt_price) + (
            output_tokens * completion_price
        )

        # Create a log entry with all relevant information
        log_entry = {
            "model": model_name,
            "time": current_time,
            "prompts": prompts,
            "replies": parsed_reply["content"],
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_cost": total_cost,
        }

        # Write the log entry to the log file in JSON format
        with open(calls_log, "a", encoding="utf-8") as f:
            json_string = json.dumps(log_entry, ensure_ascii=False, indent=4)
            f.write(json_string + "\n")


class LoggerChatModel:

    def __init__(self, llm):
        self.llm = llm

    def __call__(self, messages: List[Dict[str, str]]) -> str:
        max_retries = 15
        retry_delay = 10

        for attempt in range(max_retries):
            try:
                reply = self.llm.invoke(messages)
                parsed_reply = self.parse_llmresult(reply)
                LLMLogger.log_request(prompts=messages, parsed_reply=parsed_reply)
                return reply
            except Exception as err:
                status_code = None
                # Extract HTTP status code from various exception types
                if hasattr(err, "response") and hasattr(err.response, "status_code"):
                    status_code = err.response.status_code
                elif hasattr(err, "status_code"):
                    status_code = err.status_code

                if status_code == 429:
                    wait_time = self._parse_retry_after(err)
                    logger.warning(
                        f"Rate limit (429). Waiting {wait_time}s before retry "
                        f"{attempt + 1}/{max_retries}..."
                    )
                    time.sleep(wait_time)
                    retry_delay = min(retry_delay * 2, 300)
                else:
                    logger.error(
                        f"LLM error: {err}, retrying in {retry_delay}s "
                        f"(attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 300)

        logger.critical("Failed to get a response from the model after multiple attempts.")
        raise RuntimeError("Failed to get a response from the model after multiple attempts.")

    @staticmethod
    def _parse_retry_after(err) -> int:
        """Extract retry-after delay from error message or headers."""
        # Try to get from response headers
        if hasattr(err, "response") and hasattr(err.response, "headers"):
            headers = err.response.headers
            if "retry-after" in headers:
                try:
                    return int(headers["retry-after"])
                except (ValueError, TypeError):
                    pass
            if "retry-after-ms" in headers:
                try:
                    return max(1, int(headers["retry-after-ms"]) // 1000)
                except (ValueError, TypeError):
                    pass
        # Try to extract from error message
        err_str = str(err)
        match = re.search(r"retry after (\d+)", err_str, re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"(\d+)\s*seconds?", err_str, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 30  # default

    def parse_llmresult(self, llmresult: AIMessage) -> Dict[str, Dict]:
        # Parse the LLM result into a structured format.
        content = llmresult.content
        response_metadata = llmresult.response_metadata
        id_ = llmresult.id
        usage_metadata = llmresult.usage_metadata

        parsed_result = {
            "content": content,
            "response_metadata": {
                "model_name": response_metadata.get("model_name", ""),
                "system_fingerprint": response_metadata.get("system_fingerprint", ""),
                "finish_reason": response_metadata.get("finish_reason", ""),
                "logprobs": response_metadata.get("logprobs", None),
            },
            "id": id_,
            "usage_metadata": {
                "input_tokens": usage_metadata.get("input_tokens", 0),
                "output_tokens": usage_metadata.get("output_tokens", 0),
                "total_tokens": usage_metadata.get("total_tokens", 0),
            },
        }
        return parsed_result
