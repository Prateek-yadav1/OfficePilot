"""Shared model-provider configuration for ADK and CrewAI."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

LLMConsumer = Literal["adk", "crewai"]
GROQ_API_BASE = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class LLMProviderSettings:
    provider: Literal["groq", "ollama"]
    model: str
    api_key: str | None = None
    api_base: str | None = None


def get_llm_provider_settings(consumer: LLMConsumer) -> LLMProviderSettings:
    """Resolve the single provider switch and the consumer's model settings."""
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "LLM_PROVIDER is set to groq, but GROQ_API_KEY is missing."
            )
        model = os.getenv(
            "GROQ_MODEL",
            "openai/gpt-oss-120b",
        ).strip()
        if not model:
            raise ValueError("GROQ_MODEL must be non-empty.")
        return LLMProviderSettings(
            provider="groq",
            model=model,
            api_key=api_key,
            api_base=GROQ_API_BASE,
        )

    if provider == "ollama":
        if consumer == "adk":
            model = os.getenv("OLLAMA_MODEL", "llama3.1").strip()
            api_base = os.getenv(
                "OLLAMA_API_BASE",
                "http://127.0.0.1:11434",
            ).rstrip("/")
        else:
            model = os.getenv(
                "CREWAI_OLLAMA_MODEL",
                "llama3.1:latest",
            ).strip()
            api_base = os.getenv(
                "OLLAMA_OPENAI_BASE_URL",
                "http://127.0.0.1:11434/v1",
            ).rstrip("/")
        if not model:
            raise ValueError("The configured Ollama model must be non-empty.")
        return LLMProviderSettings(
            provider="ollama",
            model=model,
            api_base=api_base,
        )

    raise ValueError(
        f"Unsupported LLM_PROVIDER: {provider!r}. Use 'groq' or 'ollama'."
    )
