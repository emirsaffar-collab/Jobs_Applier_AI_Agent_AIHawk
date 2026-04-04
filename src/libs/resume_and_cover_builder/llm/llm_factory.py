"""Factory functions that create the correct LangChain chat model and embeddings
based on the globally configured LLM provider (config.LLM_MODEL_TYPE).

This replaces the previous hard-coded OpenAI usage in the resume builder so that
Claude, Gemini, Ollama, and other providers work out of the box.
"""

import config as cfg


def create_chat_model(api_key: str, model_type: str = "", model_name: str = ""):
    """Return a LangChain chat model matching the configured provider.

    When model_type/model_name are empty strings the global config values are
    used as a fallback, preserving backward-compatibility with the CLI path.
    The web server passes explicit values so it never mutates global state.
    """
    model_type = model_type or cfg.LLM_MODEL_TYPE
    model_name = model_name or cfg.LLM_MODEL

    if model_type == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, api_key=api_key, temperature=0.4)
    elif model_type == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model_name=model_name, openai_api_key=api_key, temperature=0.4)
    elif model_type == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    elif model_type == "ollama":
        from langchain_ollama import ChatOllama
        if cfg.LLM_API_URL:
            return ChatOllama(model=model_name, base_url=cfg.LLM_API_URL)
        return ChatOllama(model=model_name)
    else:
        # Fallback to OpenAI-compatible
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model_name=model_name, openai_api_key=api_key, temperature=0.4)


def create_embeddings(api_key: str, model_type: str = ""):
    """Return an embeddings model for the configured provider.

    Non-OpenAI providers fall back to a free HuggingFace model so that
    FAISS vectorstore operations work without an OpenAI key.
    """
    model_type = model_type or cfg.LLM_MODEL_TYPE

    if model_type == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(openai_api_key=api_key)
    else:
        # Free local embeddings — no API key required
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings()
