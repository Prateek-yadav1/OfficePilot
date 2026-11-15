"""Check configured ADK and CrewAI model-provider connectivity safely."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.llm_config import LLMConsumer, LLMProviderSettings, get_llm_provider_settings


def _ollama_api_root(api_base: str | None) -> str:
    if not api_base:
        return "http://127.0.0.1:11434"
    parts = urlsplit(api_base)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3].rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def _matches_model(available: set[str], configured: str) -> bool:
    if configured in available:
        return True
    return ":" not in configured and f"{configured}:latest" in available


def _provider_models(
    settings: LLMProviderSettings,
    client: httpx.Client,
) -> tuple[set[str], str]:
    if settings.provider == "groq":
        if not settings.api_key:
            return set(), "missing_credentials"
        url = f"{settings.api_base}/models"
        headers = {"Authorization": f"Bearer {settings.api_key}"}
    else:
        url = f"{_ollama_api_root(settings.api_base)}/api/tags"
        headers = {}

    if settings.provider == "groq":
        headers["Authorization"] = "Bearer " + (settings.api_key or "")

    try:
        response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return set(), f"unreachable:{type(exc).__name__}"

    if response.status_code in {401, 403}:
        return set(), f"authentication_failed:http_{response.status_code}"
    if not response.is_success:
        return set(), f"provider_error:http_{response.status_code}"

    try:
        payload: Any = response.json()
    except ValueError:
        return set(), "invalid_provider_response"

    rows = payload.get("data" if settings.provider == "groq" else "models")
    if not isinstance(rows, list):
        return set(), "invalid_provider_response"
    model_field = "id" if settings.provider == "groq" else "name"
    model_names = {
        row[model_field]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get(model_field), str)
    }
    return model_names, "reachable"


def diagnose_llm_providers(
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Report provider readiness without returning credentials or response bodies."""
    owns_client = client is None
    http_client = client or httpx.Client(timeout=5.0)
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    report: dict[str, Any] = {
        "provider": provider,
        "checks": {},
        "credentials_exposed": False,
    }
    available_by_endpoint: dict[tuple[str, str], tuple[set[str], str]] = {}

    try:
        for consumer in ("adk", "crewai"):
            consumer_name: LLMConsumer = consumer  # narrowed by the fixed tuple
            try:
                settings = get_llm_provider_settings(consumer_name)
            except (RuntimeError, ValueError) as exc:
                report["checks"][consumer] = {
                    "status": "configuration_error",
                    "error_type": type(exc).__name__,
                }
                continue

            api_base = settings.api_base or ""
            if settings.provider == "ollama":
                api_base = _ollama_api_root(api_base)
            endpoint_key = (settings.provider, api_base)
            if endpoint_key not in available_by_endpoint:
                available_by_endpoint[endpoint_key] = _provider_models(
                    settings,
                    http_client,
                )
            available, endpoint_status = available_by_endpoint[endpoint_key]
            model_available = _matches_model(available, settings.model)
            status = (
                endpoint_status
                if endpoint_status != "reachable"
                else "ready" if model_available else "model_not_available"
            )
            report["checks"][consumer] = {
                "status": status,
                "model": settings.model,
                "model_available": model_available,
            }
    finally:
        if owns_client:
            http_client.close()

    return report


def main() -> None:
    print(json.dumps(diagnose_llm_providers(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
