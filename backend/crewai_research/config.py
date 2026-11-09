from .observability import InstrumentedCrewLLM
from crewai import LLM
from crewai.llms.base_llm import BaseLLM

from backend.llm_config import get_llm_provider_settings

CREWAI_MODEL_TIMEOUT_SECONDS = 45
CREWAI_MODEL_MAX_RETRIES = 1
CREWAI_RETRY_BACKOFF_SECONDS = 0.5


def _instrument(llm: LLM) -> BaseLLM:
    return InstrumentedCrewLLM(
        model=llm.model,
        delegate=llm,
        timeout_seconds=CREWAI_MODEL_TIMEOUT_SECONDS,
        max_retries=CREWAI_MODEL_MAX_RETRIES,
        retry_backoff_seconds=CREWAI_RETRY_BACKOFF_SECONDS,
    )


def get_crewai_llm() -> BaseLLM:
    """Create CrewAI's model using the shared provider selection."""
    settings = get_llm_provider_settings("crewai")

    if settings.provider == "ollama":
        return _instrument(
            LLM(
                model=settings.model,
                custom_openai=True,
                base_url=settings.api_base,
                api_key="ollama",
                max_tokens=700,
                temperature=0.2,
                timeout=CREWAI_MODEL_TIMEOUT_SECONDS,
            )
        )

    return _instrument(
        LLM(
            model=f"groq/{settings.model}",
            base_url=settings.api_base,
            api_key=settings.api_key,
            max_tokens=700,
            temperature=0.2,
            timeout=CREWAI_MODEL_TIMEOUT_SECONDS,
        )
    )