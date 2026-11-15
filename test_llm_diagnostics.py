import json

import httpx

from backend.llm_diagnostics import diagnose_llm_providers


def test_ollama_diagnostic_checks_models_without_repeating_endpoint_request(
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_API_BASE", "")
    monkeypatch.setenv("OLLAMA_OPENAI_BASE_URL", "")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("CREWAI_OLLAMA_MODEL", "llama3.1:latest")
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={"models": [{"name": "llama3.1:latest"}]},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        report = diagnose_llm_providers(client)

    assert len(requests) == 1
    assert str(requests[0].url) == "http://ollama.local:11434/api/tags"
    assert report["checks"]["adk"] == {
        "status": "ready",
        "model": "llama3.1",
        "model_available": True,
    }
    assert report["checks"]["crewai"]["model_available"] is True
    assert report["credentials_exposed"] is False


def test_groq_diagnostic_redacts_credentials_and_provider_error_body(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "never-print-this-key")
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer never-print-this-key"
        return httpx.Response(
            401,
            request=request,
            text="provider error with never-print-this-key",
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        report = diagnose_llm_providers(client)

    rendered = json.dumps(report)
    assert len(requests) == 1
    assert report["checks"]["adk"]["status"] == (
        "authentication_failed:http_401"
    )
    assert "never-print-this-key" not in rendered
    assert "provider error" not in rendered


def test_groq_diagnostic_reports_missing_key_without_secret_details(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    report = diagnose_llm_providers()

    assert report["checks"]["adk"] == {
        "status": "configuration_error",
        "error_type": "RuntimeError",
    }
    assert report["checks"]["crewai"] == report["checks"]["adk"]
