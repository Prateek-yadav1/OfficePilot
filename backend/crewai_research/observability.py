"""Latency instrumentation for CrewAI's synchronous model client."""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any

from crewai.llms.base_llm import BaseLLM

from backend.agents.observability import emit_execution_event

_agent_iterations: ContextVar[dict[str, int]] = ContextVar(
    "officepilot_crewai_agent_iterations",
    default={},
)


def begin_crewai_iteration_tracking() -> Token[dict[str, int]]:
    return _agent_iterations.set({})


def end_crewai_iteration_tracking(token: Token[dict[str, int]]) -> None:
    _agent_iterations.reset(token)


class InstrumentedCrewLLM(BaseLLM):
    """Delegate unchanged model requests while recording safe timing metrics."""

    delegate: Any
    timeout_seconds: float = 45
    max_retries: int = 1
    retry_backoff_seconds: float = 0.5

    def call(
        self,
        messages: Any,
        tools: list[Any] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> Any:
        agent = str(
            getattr(from_agent, "role", None)
            or getattr(from_agent, "role_name", None)
            or "unknown"
        )
        task = str(getattr(from_task, "name", None) or "")
        iterations = dict(_agent_iterations.get())
        iteration = iterations.get(agent, 0) + 1
        iterations[agent] = iteration
        _agent_iterations.set(iterations)

        for attempt in range(self.max_retries + 1):
            started_at = perf_counter()
            emit_execution_event(
                "crewai_model_started",
                {
                    "agent": agent,
                    "task": task,
                    "agent_iteration": iteration,
                    "attempt": attempt + 1,
                    "timeout_seconds": self.timeout_seconds,
                },
            )
            try:
                response = self.delegate.call(
                    messages=messages,
                    tools=tools,
                    callbacks=callbacks,
                    available_functions=available_functions,
                    from_task=from_task,
                    from_agent=from_agent,
                    response_model=response_model,
                )
            except Exception as exc:
                error_type = type(exc).__name__
                duration_ms = round(
                    (perf_counter() - started_at) * 1000,
                    2,
                )
                timed_out = "timeout" in error_type.casefold()
                emit_execution_event(
                    "crewai_model_timed_out" if timed_out else "crewai_model_failed",
                    {
                        "agent": agent,
                        "task": task,
                        "agent_iteration": iteration,
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        "error_type": error_type,
                    },
                )
                if (
                    attempt >= self.max_retries
                    or not _is_retryable_model_error(error_type)
                ):
                    raise
                time.sleep(
                    self.retry_backoff_seconds * (2**attempt)
                )
                emit_execution_event(
                    "crewai_model_retrying",
                    {
                        "agent": agent,
                        "task": task,
                        "agent_iteration": iteration,
                        "next_attempt": attempt + 2,
                    },
                )
                continue

            emit_execution_event(
                "crewai_model_completed",
                {
                    "agent": agent,
                    "task": task,
                    "agent_iteration": iteration,
                    "attempt": attempt + 1,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            return response

        raise RuntimeError("CrewAI model retry loop exited unexpectedly.")

    def supports_function_calling(self) -> bool:
        return bool(self.delegate.supports_function_calling())

    def supports_stop_words(self) -> bool:
        return bool(self.delegate.supports_stop_words())

    def get_context_window_size(self) -> int:
        return int(self.delegate.get_context_window_size())

    def supports_multimodal(self) -> bool:
        return bool(self.delegate.supports_multimodal())

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"officepilot-instrumented-crewai"]


def _is_retryable_model_error(error_type: str) -> bool:
    retryable = {
        "apiconnectionerror",
        "apitimeouterror",
        "connecterror",
        "connecttimeout",
        "ratelimiterror",
        "readtimeout",
        "timeout",
        "timeouterror",
        "timeoutexception",
    }
    return error_type.casefold() in retryable
