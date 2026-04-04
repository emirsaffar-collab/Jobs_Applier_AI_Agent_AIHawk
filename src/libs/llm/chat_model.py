"""LoggerChatModel — LLM invocation with retry logic, parsing, and logging."""
import time
from typing import Dict, List, Union

import httpx
from langchain_core.messages.ai import AIMessage

from src.libs.llm.models import (
    OpenAIModel,
    OllamaModel,
    ClaudeModel,
    GeminiModel,
    HuggingFaceModel,
    PerplexityModel,
)
from src.libs.llm.llm_logger import LLMLogger
from src.logging import logger
from src.utils.constants import (
    CONTENT,
    FINISH_REASON,
    ID,
    INPUT_TOKENS,
    LOGPROBS,
    MODEL,
    MODEL_NAME,
    OUTPUT_TOKENS,
    RESPONSE_METADATA,
    SYSTEM_FINGERPRINT,
    TOKEN_USAGE,
    TOTAL_TOKENS,
    USAGE_METADATA,
)


class LoggerChatModel:
    def __init__(self, llm: Union[OpenAIModel, OllamaModel, ClaudeModel, GeminiModel, HuggingFaceModel, PerplexityModel]):
        self.llm = llm
        logger.debug(f"LoggerChatModel successfully initialized with LLM: {llm}")

    def __call__(self, messages: List[Dict[str, str]], max_retries: int = 5) -> str:
        logger.debug(f"Entering __call__ method with messages")
        retries = 0
        while retries < max_retries:
            try:
                reply = self.llm.invoke(messages)

                parsed_reply = self.parse_llmresult(reply)
                LLMLogger.log_request(prompts=messages, parsed_reply=parsed_reply)

                return reply

            except httpx.HTTPStatusError as e:
                retries += 1
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("retry-after")
                    retry_after_ms = e.response.headers.get("retry-after-ms")

                    if retry_after:
                        wait_time = int(retry_after)
                    elif retry_after_ms:
                        wait_time = int(retry_after_ms) / 1000.0
                    else:
                        wait_time = min(30 * (2 ** (retries - 1)), 120)

                    logger.warning(
                        f"Rate limit exceeded. Waiting {wait_time}s before retry {retries}/{max_retries}..."
                    )
                    time.sleep(wait_time)
                else:
                    wait_time = min(5 * (2 ** (retries - 1)), 60)
                    logger.error(
                        f"HTTP error {e.response.status_code}, retry {retries}/{max_retries}, waiting {wait_time}s..."
                    )
                    time.sleep(wait_time)

            except (TimeoutError, OSError) as e:
                retries += 1
                wait_time = min(5 * (2 ** (retries - 1)), 60)
                logger.error(
                    f"Network error: {e}, retry {retries}/{max_retries}, waiting {wait_time}s..."
                )
                time.sleep(wait_time)

            except Exception as e:
                retries += 1
                wait_time = min(10 * (2 ** (retries - 1)), 60)
                logger.error(
                    f"LLM error: {e}, retry {retries}/{max_retries}, waiting {wait_time}s..."
                )
                time.sleep(wait_time)

        raise RuntimeError(f"LLM call failed after {max_retries} retries")

    def parse_llmresult(self, llmresult: AIMessage) -> Dict[str, Dict]:
        logger.debug(f"Parsing LLM result: {llmresult}")

        try:
            if hasattr(llmresult, USAGE_METADATA):
                content = llmresult.content
                response_metadata = llmresult.response_metadata
                id_ = llmresult.id
                usage_metadata = llmresult.usage_metadata

                parsed_result = {
                    CONTENT: content,
                    RESPONSE_METADATA: {
                        MODEL_NAME: response_metadata.get(
                            MODEL_NAME, ""
                        ),
                        SYSTEM_FINGERPRINT: response_metadata.get(
                            SYSTEM_FINGERPRINT, ""
                        ),
                        FINISH_REASON: response_metadata.get(
                            FINISH_REASON, ""
                        ),
                        LOGPROBS: response_metadata.get(
                            LOGPROBS, None
                        ),
                    },
                    ID: id_,
                    USAGE_METADATA: {
                        INPUT_TOKENS: usage_metadata.get(
                            INPUT_TOKENS, 0
                        ),
                        OUTPUT_TOKENS: usage_metadata.get(
                            OUTPUT_TOKENS, 0
                        ),
                        TOTAL_TOKENS: usage_metadata.get(
                            TOTAL_TOKENS, 0
                        ),
                    },
                }
            else:
                content = llmresult.content
                response_metadata = llmresult.response_metadata
                id_ = llmresult.id
                token_usage = response_metadata[TOKEN_USAGE]

                parsed_result = {
                    CONTENT: content,
                    RESPONSE_METADATA: {
                        MODEL_NAME: response_metadata.get(
                            MODEL, ""
                        ),
                        FINISH_REASON: response_metadata.get(
                            FINISH_REASON, ""
                        ),
                    },
                    ID: id_,
                    USAGE_METADATA: {
                        INPUT_TOKENS: token_usage.prompt_tokens,
                        OUTPUT_TOKENS: token_usage.completion_tokens,
                        TOTAL_TOKENS: token_usage.total_tokens,
                    },
                }
            logger.debug(f"Parsed LLM result successfully: {parsed_result}")
            return parsed_result

        except KeyError as e:
            logger.error(f"KeyError while parsing LLM result: missing key {str(e)}")
            raise

        except Exception as e:
            logger.error(f"Unexpected error while parsing LLM result: {str(e)}")
            raise
