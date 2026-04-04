"""LLM provider metadata used by CLI error messages, web onboarding, and the
``/api/llm-providers`` endpoint.

Keeping everything in one place makes it easy to add new providers or update
dashboard URLs without touching multiple files.
"""

LLM_PROVIDER_INFO: dict[str, dict] = {
    "claude": {
        "name": "Anthropic (Claude)",
        "dashboard_url": "https://console.anthropic.com/settings/keys",
        "signup_url": "https://console.anthropic.com/",
        "key_prefix": "sk-ant-",
        "instructions": [
            "Go to console.anthropic.com and create an account",
            "Navigate to Settings \u2192 API Keys",
            "Click 'Create Key' and copy the key",
            "Free tier available with limited usage",
        ],
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "dashboard_url": "https://platform.openai.com/api-keys",
        "signup_url": "https://platform.openai.com/signup",
        "key_prefix": "sk-",
        "instructions": [
            "Go to platform.openai.com and create an account",
            "Navigate to API Keys in the left sidebar",
            "Click 'Create new secret key' and copy it",
            "Requires adding a payment method",
        ],
    },
    "gemini": {
        "name": "Google (Gemini)",
        "dashboard_url": "https://aistudio.google.com/apikey",
        "signup_url": "https://aistudio.google.com/",
        "key_prefix": "AI",
        "instructions": [
            "Go to aistudio.google.com and sign in with Google",
            "Click 'Get API key' in the left sidebar",
            "Create a key in a new or existing Google Cloud project",
            "Free tier available with generous limits",
        ],
    },
    "huggingface": {
        "name": "Hugging Face",
        "dashboard_url": "https://huggingface.co/settings/tokens",
        "signup_url": "https://huggingface.co/join",
        "key_prefix": "hf_",
        "instructions": [
            "Go to huggingface.co and create an account",
            "Navigate to Settings \u2192 Access Tokens",
            "Click 'New token' and select 'Read' scope",
            "Free tier available for most models",
        ],
    },
    "perplexity": {
        "name": "Perplexity",
        "dashboard_url": "https://www.perplexity.ai/settings/api",
        "signup_url": "https://www.perplexity.ai/",
        "key_prefix": "pplx-",
        "instructions": [
            "Go to perplexity.ai and create an account",
            "Navigate to Settings \u2192 API",
            "Generate a new API key",
            "Requires a Perplexity Pro subscription or API credits",
        ],
    },
    "ollama": {
        "name": "Ollama (Local)",
        "dashboard_url": "",
        "signup_url": "https://ollama.ai/download",
        "key_prefix": "",
        "instructions": [
            "Download and install Ollama from ollama.ai",
            "Run 'ollama pull llama3' to download a model",
            "No API key needed \u2014 runs locally on your machine",
            "Set LLM_API_URL if not using default http://localhost:11434",
        ],
    },
}


def get_provider_info(provider_key: str) -> dict:
    """Return info for *provider_key*, falling back to the default (claude)."""
    return LLM_PROVIDER_INFO.get(provider_key, LLM_PROVIDER_INFO["claude"])
