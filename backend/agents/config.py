import os

from google.adk.models.lite_llm import LiteLlm

from backend.llm_config import get_llm_provider_settings


def get_model(max_tokens: int = 1200) -> LiteLlm:
    """Return the ADK model selected by the shared GROQ/OLLAMA setting."""
    settings = get_llm_provider_settings("adk")

    if settings.provider == "ollama":
        model_name = settings.model
        os.environ["OLLAMA_API_BASE"] = settings.api_base or ""
        if not model_name.startswith("ollama_chat/"):
            model_name = f"ollama_chat/{model_name}"
    else:
        model_name = f"groq/{settings.model}"

    timeout_seconds = int(os.getenv("ADK_MODEL_TIMEOUT_SECONDS", "180"))
    num_retries = int(os.getenv("ADK_MODEL_NUM_RETRIES", "0"))

    return LiteLlm(
        model=model_name,
        api_base=settings.api_base,
        api_key=settings.api_key,
        max_tokens=max_tokens,
        timeout=timeout_seconds,
        num_retries=num_retries,
        retry_strategy="exponential_backoff_retry",
    )