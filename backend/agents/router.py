from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk import Event, Context
from google.adk.agents.invocation_context import InvocationContext
from google.genai import types

from .quality_guardrails import validate_briefing_state



class ConditionalRouterAgent(BaseAgent):
    """Route deterministically from the Information Checker result."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        information_status = str(
            ctx.session.state.get("information_status", "")
        ).strip().upper()
        decision = "ANALYSIS" if information_status == "ENOUGH" else "RESEARCH"
        ctx.session.state["next_step"] = decision
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part(text=decision)],
            ),
        )


router_agent = ConditionalRouterAgent(
    name="conditional_router",
    description=(
        "Deterministically routes missing information to research and "
        "sufficient information to analysis."
    ),
)


def route_decision(ctx: Context) -> Event:
    """
    Initialize research context and select the next workflow branch.
    """

    state = ctx.state

    decision = str(
        state.get("next_step", "")
    ).strip().upper()

    if decision.startswith("RESEARCH"):
        state["research_context"] = (
            "Additional research was requested. "
            "The research agent will provide its findings."
        )

        return Event(
            route="RESEARCH",
            output="Router decision: additional research is required."
        )

    state["research_context"] = (
        "No additional research was requested or run "
        "for this workflow invocation."
    )

    return Event(
        route="ANALYSIS",
        output="Router decision: sufficient information is available."
    )


class QualityRouterAgent(BaseAgent):
    """Map the checker result to a closed, fail-safe routing value."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        quality_status = str(
            ctx.session.state.get("quality_status", "")
        ).strip().upper()
        decision = "PASS" if quality_status.startswith("PASS") else "REVISE"
        ctx.session.state["quality_route"] = decision
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part(text=decision)],
            ),
        )


quality_router_agent = QualityRouterAgent(
    name="quality_router",
    description=(
        "Deterministically routes a passing quality check to final response "
        "and all other results to revision."
    ),
)



MAX_QUALITY_REVIEW_CYCLES = 3


def quality_route_decision(ctx: Context) -> Event:
    """Require deterministic validation before action proposal."""

    state = ctx.state
    review_cycles = int(state.get("quality_review_cycles", 0) or 0) + 1
    state["quality_review_cycles"] = review_cycles

    decision = str(state.get("quality_route", "")).strip().upper()
    quality_status = str(state.get("quality_status", "")).strip()

    validation_errors = validate_briefing_state(state)

    if validation_errors:
        state["deterministic_quality_errors"] = validation_errors
        state["quality_status"] = (
            "REVISE: Deterministic validation failed: "
            + " | ".join(validation_errors)
        )

        if review_cycles < MAX_QUALITY_REVIEW_CYCLES:
            return Event(
                route="REVISE",
                output=(
                    "Deterministic validation failed. "
                    "The briefing must be revised before it can proceed."
                ),
            )

        return Event(
            route="BLOCK",
            output=(
                "Briefing blocked after the permitted review cycles. "
                "Action proposal and execution will not run."
            ),
        )

    state["deterministic_quality_errors"] = []

    if decision == "PASS":
        state["execution_status"] = (
            "completed_with_warnings"
            if state.get("execution_warnings")
            else "completed"
        )
        if state.get("allow_action_proposal", True) is False:
            return Event(
                route="NO_ACTION",
                output=(
                    "Briefing passed quality checks. "
                    "Action proposals were explicitly disabled."
                ),
            )

        return Event(
            route="PASS",
            output=(
                "Quality decision: both the LLM review and "
                "deterministic validation passed."
            ),
        )

    if review_cycles < MAX_QUALITY_REVIEW_CYCLES:
        return Event(
            route="REVISE",
            output="Quality decision: briefing requires refinement.",
        )

    state["deterministic_quality_errors"] = [
        "The LLM quality checker did not return PASS within "
        f"{MAX_QUALITY_REVIEW_CYCLES} review cycles. "
        f"Last result: {quality_status[:300]}"
    ]
    state["execution_status"] = "failed"

    return Event(
        route="BLOCK",
        output=(
            "Briefing blocked because it did not receive a passing "
            "quality decision within the permitted review cycles."
        ),
    )
