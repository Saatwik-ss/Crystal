"""
Provider router for dynamically dispatching LLM calls between Groq and Gemini
based on the provided API key or model.
"""
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models_url": "https://api.groq.com/openai/v1/models",
        "default_model": "llama-3.3-70b-versatile",
    },
    "gemini": {
        "name": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models_url": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "default_model": "gemini-2.5-flash",
    },
}

GEMINI_CHAT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]


def is_gemini_key(key: Optional[str]) -> bool:
    """Check if the provided key matches the Google/Gemini key format (starts with AIza)."""
    if not key:
        return False
    return key.strip().startswith("AIza")


def detect_provider(api_key: Optional[str] = None, model: Optional[str] = None) -> str:
    """Detect whether this request is for Gemini or Groq."""
    key = (api_key or "").strip()
    if is_gemini_key(key):
        return "gemini"
    if model and "gemini" in model.lower():
        return "gemini"
    return "groq"


def get_provider_info(provider: str) -> Dict[str, Any]:
    """Retrieve metadata for the given provider (base_url, models_url, default_model)."""
    return PROVIDERS.get(provider, PROVIDERS["groq"])


def resolve_provider_model(provider: str, user_model: Optional[str] = None) -> str:
    """Resolve model name appropriate for the given provider."""
    model = (user_model or "").strip()
    if provider == "gemini":
        if model and "gemini" in model.lower():
            return model
        return PROVIDERS["gemini"]["default_model"]
    else:
        # groq
        if model and "gemini" not in model.lower():
            return model
        return PROVIDERS["groq"]["default_model"]


def create_provider_client(
    provider: str,
    api_key: str,
    model: Optional[str] = None,
) -> Tuple[Any, str, bool]:
    """
    Create an SDK client for the detected provider.
    Returns (client, resolved_model_name, initialized).
    """
    resolved_model = resolve_provider_model(provider, model)
    if not api_key:
        return None, resolved_model, False

    try:
        if provider == "gemini":
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url=PROVIDERS["gemini"]["base_url"],
            )
            return client, resolved_model, True
        else:
            from groq import Groq
            return Groq(api_key=api_key), resolved_model, True
    except Exception as e:
        logger.error(f"Failed to create {provider} client: {e}")
        return None, resolved_model, False
