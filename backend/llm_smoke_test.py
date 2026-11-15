"""Exercise a selected model's ADK tool-call and Pydantic output paths."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import logging
import sys
from typing import Any

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, ConfigDict

from backend.agents.config import get_model
from backend.llm_config import get_llm_provider_settings


class ProviderSmokeResult(BaseModel):
    """Small schema used only by the explicit provider smoke test."""

    model_config = ConfigDict(extra="forbid")

    result: str
    status: str


class ProviderSmokeFailure(RuntimeError):
    """A safe, stage-specific failure without provider response contents."""

    def __init__(self, stage: str, error_code: str | None = None) -> None:
        super().__init__(stage)
        self.stage = stage
        self.error_code = error_code


async def _run_agent(agent: Agent, prompt: str, stage: str) -> str:
    app = App(name=f"officepilot_{stage}", root_agent=agent)
    runner = InMemoryRunner(app=app)
    user_id = "officepilot-provider-smoke"
    session = await runner.session_service.create_session(
        app_name=app.name,
        user_id=user_id,
    )
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        ),
    ):
        error_code = getattr(event, "error_code", None)
        if error_code:
            raise ProviderSmokeFailure(stage, str(error_code))
        content = getattr(event, "content", None)
        if getattr(event, "author", None) == agent.name and content is not None:
            text = "".join(
                part.text
                for part in content.parts
                if getattr(part, "text", None)
            )
            if text:
                final_text = text
    if not final_text:
        raise ProviderSmokeFailure(stage, "empty_response")
    return final_text


async def run_provider_smoke_test() -> dict[str, Any]:
    """Verify live text generation, tool calling, and Pydantic output."""
    model = get_model(max_tokens=160)
    ordinary_agent = Agent(
        name="officepilot_generation_probe",
        model=model,
        instruction="Reply exactly with OLLAMA_GENERATION_OK.",
    )
    ordinary_text = await _run_agent(
        ordinary_agent,
        "Return the required generation marker.",
        "ordinary_generation",
    )
    if "OLLAMA_GENERATION_OK" not in ordinary_text:
        raise ProviderSmokeFailure("ordinary_generation", "marker_missing")

    calls: list[str] = []

    def provider_capability_probe() -> dict[str, str]:
        calls.append("provider_capability_probe")
        return {"result": "OFFICEPILOT_TOOL_OK"}

    tool_agent = Agent(
        name="officepilot_tool_probe",
        model=model,
        instruction=(
            "Call provider_capability_probe exactly once and then repeat its "
            "result exactly. Do not invent or omit the marker."
        ),
        tools=[provider_capability_probe],
    )
    tool_text = await _run_agent(
        tool_agent,
        "Run the provider capability check.",
        "tool_call",
    )
    if len(calls) != 1:
        raise ProviderSmokeFailure("tool_call", "unexpected_tool_call_count")

    structured_agent = Agent(
        name="officepilot_provider_smoke_test",
        model=model,
        instruction=(
            "Return result='OFFICEPILOT_STRUCTURED_OK' and status='ok' using "
            "the configured output schema."
        ),
        output_schema=ProviderSmokeResult,
    )
    structured_text = await _run_agent(
        structured_agent,
        "Return the structured output now.",
        "structured_output",
    )
    try:
        result = ProviderSmokeResult.model_validate_json(structured_text)
    except Exception as exc:
        raise ProviderSmokeFailure(
            "structured_output",
            f"pydantic_{type(exc).__name__}",
        ) from None
    if result.result != "OFFICEPILOT_STRUCTURED_OK" or result.status != "ok":
        raise ProviderSmokeFailure("structured_output", "schema_values_invalid")

    return {
        "status": "passed",
        "provider": get_llm_provider_settings("adk").provider,
        "ordinary_generation": True,
        "tool_call": True,
        "tool_calls_executed": len(calls),
        "tool_result_echoed": "OFFICEPILOT_TOOL_OK" in tool_text,
        "pydantic_output_valid": True,
        "adk_timeout_seconds": model._additional_args["timeout"],
        "adk_retries": model._additional_args["num_retries"],
        "token_usage": "not reported by this probe",
        "cost": "not estimated",
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            report = asyncio.run(run_provider_smoke_test())
    except ProviderSmokeFailure as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": exc.stage,
                    "provider_error_code": exc.error_code,
                    "details": (
                        "Check provider configuration and endpoint availability. "
                        "Sensitive provider messages are intentionally omitted."
                    ),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": "smoke_test",
                    "error_type": type(exc).__name__,
                    "details": (
                        "Unexpected failure; sensitive provider messages are "
                        "intentionally omitted."
                    ),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
