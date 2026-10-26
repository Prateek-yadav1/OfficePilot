import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def get_model() -> LiteLlm:
    """
    Return the configured LLM.

    Default: local Ollama with Llama 3.1.
    Optional: OpenRouter by setting LLM_PROVIDER=openrouter.
    """

    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

    if provider in {"ollama", "local"}:
        model_name = os.getenv("OLLAMA_MODEL", "llama3.1").strip()
        api_base = os.getenv(
            "OLLAMA_API_BASE",
            "http://127.0.0.1:11434",
        ).rstrip("/")

        # LiteLLM uses this environment variable for Ollama API calls.
        os.environ["OLLAMA_API_BASE"] = api_base

        # Accept either "llama3.1" or the full LiteLLM model identifier.
        if not model_name.startswith("ollama_chat/"):
            model_name = f"ollama_chat/{model_name}"

        return LiteLlm(
            model=model_name,
            api_base=api_base,
            max_tokens=1200,
        )

    if provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")

        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER is set to openrouter, but "
                "OPENROUTER_API_KEY is missing from the environment."
            )

        model_name = os.getenv(
            "LLM_MODEL",
            "openrouter/google/gemini-2.5-flash",
        )

        return LiteLlm(
            model=model_name,
            api_key=api_key,
            max_tokens=1200,
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER: {provider!r}. "
        "Use 'ollama' or 'openrouter'."
    )