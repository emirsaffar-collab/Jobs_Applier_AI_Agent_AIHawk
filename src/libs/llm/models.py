"""LLM model abstractions and provider implementations."""
from abc import ABC, abstractmethod

from langchain_core.messages import BaseMessage

import config as cfg
from src.logging import logger
from src.utils.constants import (
    CLAUDE,
    GEMINI,
    HUGGINGFACE,
    OLLAMA,
    OPENAI,
    PERPLEXITY,
)


class AIModel(ABC):
    @abstractmethod
    def invoke(self, prompt: str) -> str:
        pass


class OpenAIModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_openai import ChatOpenAI

        self.model = ChatOpenAI(
            model_name=llm_model, openai_api_key=api_key, temperature=0.4
        )

    def invoke(self, prompt: str) -> BaseMessage:
        logger.debug("Invoking OpenAI API")
        response = self.model.invoke(prompt)
        return response


class ClaudeModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_anthropic import ChatAnthropic

        self.model = ChatAnthropic(model=llm_model, api_key=api_key, temperature=0.4)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        logger.debug("Invoking Claude API")
        return response


class OllamaModel(AIModel):
    def __init__(self, llm_model: str, llm_api_url: str):
        from langchain_ollama import ChatOllama

        if len(llm_api_url) > 0:
            logger.debug(f"Using Ollama with API URL: {llm_api_url}")
            self.model = ChatOllama(model=llm_model, base_url=llm_api_url)
        else:
            self.model = ChatOllama(model=llm_model)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        return response


class PerplexityModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_community.chat_models import ChatPerplexity

        self.model = ChatPerplexity(model=llm_model, api_key=api_key, temperature=0.4)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        return response


class GeminiModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_google_genai import (
            ChatGoogleGenerativeAI,
            HarmBlockThreshold,
            HarmCategory,
        )

        self.model = ChatGoogleGenerativeAI(
            model=llm_model,
            google_api_key=api_key,
            safety_settings={
                HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DEROGATORY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_TOXICITY: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_VIOLENCE: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_MEDICAL: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
        )

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        return response


class HuggingFaceModel(AIModel):
    def __init__(self, api_key: str, llm_model: str):
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

        self.model = HuggingFaceEndpoint(
            repo_id=llm_model, huggingfacehub_api_token=api_key, temperature=0.4
        )
        self.chatmodel = ChatHuggingFace(llm=self.model)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.chatmodel.invoke(prompt)
        logger.debug(
            f"Invoking Model from Hugging Face API. Response: {response}, Type: {type(response)}"
        )
        return response


class AIAdapter:
    def __init__(self, config: dict, api_key: str):
        self.model = self._create_model(config, api_key)

    def _create_model(self, config: dict, api_key: str) -> AIModel:
        llm_model_type = cfg.LLM_MODEL_TYPE
        llm_model = cfg.LLM_MODEL
        llm_api_url = cfg.LLM_API_URL

        logger.debug(f"Using {llm_model_type} with {llm_model}")

        if llm_model_type == OPENAI:
            return OpenAIModel(api_key, llm_model)
        elif llm_model_type == CLAUDE:
            return ClaudeModel(api_key, llm_model)
        elif llm_model_type == OLLAMA:
            return OllamaModel(llm_model, llm_api_url)
        elif llm_model_type == GEMINI:
            return GeminiModel(api_key, llm_model)
        elif llm_model_type == HUGGINGFACE:
            return HuggingFaceModel(api_key, llm_model)
        elif llm_model_type == PERPLEXITY:
            return PerplexityModel(api_key, llm_model)
        else:
            raise ValueError(f"Unsupported model type: {llm_model_type}")

    def invoke(self, prompt: str) -> str:
        return self.model.invoke(prompt)
