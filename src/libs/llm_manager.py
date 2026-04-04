"""LLM manager — backward-compatible re-export from the ``src.libs.llm`` package.

The implementation has been split into focused modules:
  - ``src.libs.llm.models``      — AIModel ABC, provider classes, AIAdapter
  - ``src.libs.llm.llm_logger``  — LLMLogger (request logging & cost tracking)
  - ``src.libs.llm.chat_model``  — LoggerChatModel (retry logic & parsing)
  - ``src.libs.llm.answerer``    — GPTAnswerer (question answering)

All public names are re-exported here so existing ``from src.libs.llm_manager import X``
imports continue to work.
"""

from src.libs.llm.models import (  # noqa: F401
    AIModel,
    OpenAIModel,
    ClaudeModel,
    OllamaModel,
    PerplexityModel,
    GeminiModel,
    HuggingFaceModel,
    AIAdapter,
)
from src.libs.llm.llm_logger import LLMLogger  # noqa: F401
from src.libs.llm.chat_model import LoggerChatModel  # noqa: F401
from src.libs.llm.answerer import GPTAnswerer  # noqa: F401
