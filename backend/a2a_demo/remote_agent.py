"""Isolated OfficePilot agent exposed over the A2A protocol."""

import os
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.events import Event
from google.genai import types


class RemoteResearchReviewer(BaseAgent):
    """A deterministic A2A endpoint that never claims source verification."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        user_content = getattr(ctx, "user_content", None)
        received_text = (
            "\n".join(
                part.text
                for part in user_content.parts
                if getattr(part, "text", None)
            )
            if isinstance(user_content, types.Content)
            else ""
        )

        if received_text.strip():
            response = (
                "A2A reviewer received the submitted research context. "
                "This endpoint does not access source systems and has not "
                "independently verified any factual claims. Check each claim "
                "against its original email, calendar event, or document."
            )
        else:
            response = (
                "A2A reviewer received no reviewable text. No factual claims "
                "were independently verified."
            )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part(text=response)],
            ),
        )


remote_agent = RemoteResearchReviewer(
    name="officepilot_remote_research_agent",
    description=(
        "Acknowledges submitted research context over A2A and explicitly "
        "states that no independent source verification occurred."
    ),
)

a2a_app = to_a2a(
    remote_agent,
    host=os.getenv("OFFICEPILOT_A2A_PUBLIC_HOST", "127.0.0.1"),
    port=int(os.getenv("PORT", "8000")),
    rpc_path="a2a",
)
