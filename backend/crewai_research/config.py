import os
from pathlib import Path

from dotenv import load_dotenv
from crewai import LLM


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def get_crewai_llm() -> LLM:
    """
    Create the CrewAI LLM.

    Defaults to local Ollama to avoid paid API calls.
    OpenRouter is used only when explicitly selected.
    """

    provider = os.getenv(
        "CREWAI_LLM_PROVIDER",
        "ollama",
    ).strip().lower()

    if provider == "ollama":
        model_name = os.getenv(
            "CREWAI_OLLAMA_MODEL",
            "llama3.1:latest",
        )

        base_url = os.getenv(
            "OLLAMA_OPENAI_BASE_URL",
            "http://127.0.0.1:11434/v1",
        )

        return LLM(
            model=model_name,
            custom_openai=True,
            base_url=base_url,
            api_key="ollama",
            max_tokens=700,
            temperature=0.2,
        )

    if provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")

        if not api_key:
            raise RuntimeError(
                "CREWAI_LLM_PROVIDER is set to openrouter, "
                "but OPENROUTER_API_KEY is missing."
            )

        model_name = os.getenv(
            "LLM_MODEL",
            "openrouter/google/gemini-2.5-flash",
        )

        return LLM(
            model=model_name,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            max_tokens=700,
            temperature=0.2,
        )

    raise ValueError(
        f"Unsupported CREWAI_LLM_PROVIDER: {provider!r}. "
        "Use 'ollama' or 'openrouter'."
    )