import json

import httpx
import pytest
from openai import OpenAI

from backend.agents.config import get_model
from backend.crewai_research.config import (
    CREWAI_MODEL_MAX_RETRIES,
    CREWAI_MODEL_TIMEOUT_SECONDS,
    get_crewai_llm,
)
from backend.llm_config import GROQ_API_BASE, get_llm_provider_settings


def test_adk_and_crewai_share_groq_provider_and_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setenv("CREWAI_LLM_PROVIDER", "ollama")

    adk_settings = get_llm_provider_settings("adk")
    crew_settings = get_llm_provider_settings("crewai")
    adk_model = get_model(max_tokens=321)
    crew_model = get_crewai_llm()

    assert adk_settings.provider == crew_settings.provider == "groq"
    assert adk_settings.model == crew_settings.model == "openai/gpt-oss-120b"
    assert adk_model.model == "groq/openai/gpt-oss-120b"
    assert adk_model._additional_args["api_base"] == GROQ_API_BASE
    assert adk_model._additional_args["api_key"] == "test-groq-key"
    assert adk_model._additional_args["timeout"] == 180
    assert adk_model._additional_args["num_retries"] == 0
    assert crew_model.delegate.model == "groq/openai/gpt-oss-120b"
    assert crew_model.delegate.base_url == GROQ_API_BASE
    assert crew_model.delegate.api_key == "test-groq-key"
    assert crew_model.delegate.timeout == CREWAI_MODEL_TIMEOUT_SECONDS == 45
    assert CREWAI_MODEL_MAX_RETRIES == 1


def test_groq_model_can_be_selected_without_code_changes(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")

    assert get_llm_provider_settings("adk").model == "openai/gpt-oss-20b"
    assert get_llm_provider_settings("crewai").model == "openai/gpt-oss-20b"


def test_groq_requires_key_and_does_not_fall_back_to_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is missing"):
        get_llm_provider_settings("adk")


def test_only_groq_or_ollama_can_be_selected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")

    with pytest.raises(ValueError, match="Use 'groq' or 'ollama'"):
        get_llm_provider_settings("crewai")


def test_groq_compatible_chat_supports_mocked_json_schema_and_tools(
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    settings = get_llm_provider_settings("adk")
    observed = {}

    def respond(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("Authorization")
        observed["path"] = request.url.path
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1,
                "model": settings.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"result":"validated"}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAI(
            api_key="test-groq-key",
            base_url=GROQ_API_BASE,
            http_client=http_client,
        )
        response = client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": "Return a small result."}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "research_result",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                        "additionalProperties": False,
                    },
                },
            },
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_evidence",
                        "description": "Look up retrieved evidence.",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                }
            ],
        )

    assert response.choices[0].message.content == '{"result":"validated"}'
    assert observed["authorization"] == "Bearer test-groq-key"
    assert observed["path"] == "/openai/v1/chat/completions"
    assert observed["body"]["model"] == settings.model
    assert observed["body"]["response_format"]["type"] == "json_schema"
    assert observed["body"]["tools"][0]["function"]["name"] == "lookup_evidence"
