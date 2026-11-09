import asyncio
from collections import Counter
import json
import socket
from time import perf_counter
from typing import Any

import uvicorn
from crewai.llms.base_llm import BaseLLM
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.models import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
from pydantic import Field

from backend.a2a_demo.remote_agent import remote_agent
from backend.agents.observability import (
    begin_execution_observation,
    end_execution_observation,
)
from backend.agents.workflow import root_agent
from backend.agents import parallel_agents as parallel_agents_module
from backend.crewai_research import analyst as crew_analyst_module
from backend.crewai_research import crew as crew_module
from backend.crewai_research import researcher as crew_researcher_module
from backend.crewai_research import reviewer as crew_reviewer_module
from backend.crewai_research import tasks as crew_tasks_module
from backend.crewai_research.observability import InstrumentedCrewLLM
from main import run_officepilot


CLIENT = "Acme Robotics"


class ScriptedAdkModel(BaseLlm):
    model: str = "officepilot-e2e-scripted"
    label: str
    steps: list[Any] = Field(default_factory=list)
    step_index: int = 0
    calls: int = 0
    requests: list[str] = Field(default_factory=list)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities()

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"officepilot-e2e-scripted"]

    async def generate_content_async(self, llm_request, stream: bool = False):
        self.calls += 1
        request_text = []
        system_instruction = getattr(
            getattr(llm_request, "config", None),
            "system_instruction",
            None,
        )
        if isinstance(system_instruction, str):
            request_text.append(system_instruction)
        for content in getattr(llm_request, "contents", []) or []:
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    request_text.append(text)
        self.requests.append("\n".join(request_text))
        if not self.steps:
            part = types.Part(text=f"{self.label}: no response configured.")
        else:
            index = min(self.step_index, len(self.steps) - 1)
            step = self.steps[index]
            self.step_index += 1
            if isinstance(step, dict) and "tool" in step:
                part = types.Part(
                    function_call=types.FunctionCall(
                        id=f"{self.label}-{self.step_index}",
                        name=step["tool"],
                        args=step.get("args", {}),
                    )
                )
            else:
                part = types.Part(text=str(step))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class ScriptedCrewModel(BaseLLM):
    model: str = "officepilot-crewai-fixture"
    roles: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    researcher_calls: int = 0

    def call(
        self,
        messages: Any,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ) -> str:
        role = str(getattr(from_agent, "role", "unknown"))
        self.roles.append(role)
        self.prompts.append(str(messages))
        if role == "Client Research Specialist":
            self.researcher_calls += 1
            return (
                "Thought: Use only retrieved tenant-scoped evidence.\n"
                "Final Answer: The Gmail summary requests more testing for "
                "damaged barcode labels. The indexed document reports a "
                "five-minute synchronization delay and pending approval. "
                "No confirmed agenda was retrieved."
            )
        if role == "Research Analyst":
            return (
                "Thought: Separate findings from implications.\n"
                "Final Answer: Fixture analysis: prepare an agenda and keep "
                "unconfirmed details explicitly uncertain."
            )
        if role == "Research Quality Reviewer":
            return (
                "Thought: Check for unsupported facts.\n"
                "Final Answer: Reviewed fixture report. No facts beyond the "
                "research result are presented as verified."
            )
        raise AssertionError(f"Unexpected CrewAI role: {role}")

    def supports_function_calling(self) -> bool:
        return False

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"officepilot-crewai-fixture"]


def _briefing() -> str:
    return f"""# Meeting Briefing

## Client
{CLIENT}

## Meeting Details
- Acme Robotics warehouse pilot review
- Date: 5 November 2026
- Time: Not found in available sources
- Participant: Maya Shah

## Key Client Priorities
- Improve barcode scanning for damaged or low-quality labels.

## Client Concerns
- Barcode scanning fails on damaged or low-quality labels.
- Inventory synchronization is delayed by approximately five minutes.

## Important Facts
- Deployment approval is pending.
- Barcode-scanning improvements and synchronization investigation are
  high-priority actions.

## Additional Research
- Fixture research was reviewed through CrewAI and the A2A reviewer.

## Potential Risks
- INFERENCE: an unconfirmed agenda may leave meeting priorities unclear.

## Questions to Ask
- Which agenda items are most important?
- Are any dates or owners confirmed?

## Recommended Discussion Topics
- Meeting goals and agenda.
- Confirmed owners and next steps.

## Actionable Steps
- Confirm the meeting agenda before the discussion.

## Executive Summary
Prioritize the barcode-scanning failures and five-minute synchronization
delay, confirm the pending deployment approval, and agree on owners for the
two high-priority actions.
"""


def _workflow_agents() -> dict[str, Any]:
    agents = {}

    def collect(agent):
        if hasattr(agent, "name"):
            agents[agent.name] = agent
        for child in getattr(agent, "sub_agents", []) or []:
            collect(child)
        graph = getattr(agent, "graph", None)
        for child in getattr(graph, "nodes", []) or []:
            collect(child)

    collect(root_agent)
    return agents


def _configure_adk_agents() -> tuple[
    list[tuple[Any, Any, Any]],
    dict[str, ScriptedAdkModel],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    saved = []
    configured_models = {}
    retrieval_calls: list[dict[str, Any]] = []
    aggregator_states: list[dict[str, Any]] = []
    workflow_agents = _workflow_agents()

    def set_model(agent, *steps):
        if not hasattr(agent, "model"):
            return
        previous = agent.model
        saved.append((agent, "model", previous))
        model = ScriptedAdkModel(label=agent.name, steps=list(steps))
        agent.model = model
        configured_models[agent.name] = model

    set_model(workflow_agents["planner_agent"], CLIENT)

    async def search_emails(
        client: str,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        retrieval_calls.append(
            {
                "tool": "search_emails",
                "client": client,
                "user_id": tool_context.state.get("user_id"),
                "tenant_id": tool_context.state.get("tenant_id"),
            }
        )
        return {
            "source": "fixture_gmail",
            "client": client,
            "count": 1,
            "emails": [
                {
                    "id": "test-email-1",
                    "subject": "Warehouse scanning test",
                    "date": "fixture date",
                    "body": "The team needs more tests for damaged barcode labels.",
                }
            ],
        }

    def search_client_documents(
        query: str,
        client: str,
        tool_context: ToolContext,
    ) -> list[dict[str, Any]]:
        retrieval_calls.append(
            {
                "tool": "search_client_documents",
                "client": client,
                "query": query,
                "user_id": tool_context.state.get("user_id"),
                "tenant_id": tool_context.state.get("tenant_id"),
            }
        )
        return [
            {
                "client": client,
                "title": "Acme Robotics Warehouse Pilot",
                "content": (
                    "Barcode scanning fails on damaged or low-quality labels. "
                    "Inventory synchronization has an approximately five-minute "
                    "delay. Deployment approval is pending. Barcode-scanning "
                    "improvements and synchronization investigation are "
                    "high-priority actions."
                ),
                "relevance_score": 0.9,
            }
        ]

    async def get_calendar(
        client: str,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        retrieval_calls.append(
            {
                "tool": "get_calendar",
                "client": client,
                "user_id": tool_context.state.get("user_id"),
                "tenant_id": tool_context.state.get("tenant_id"),
            }
        )
        return {
            "source": "fixture_calendar",
            "client": client,
            "count": 1,
            "meetings": [
                {
                    "id": "test-meeting-1",
                    "title": "Acme Robotics warehouse pilot review",
                    "date": "2026-11-05",
                    "participants": ["Maya Shah"],
                }
            ],
        }

    for agent, func in (
        (workflow_agents["email_agent"], search_emails),
        (workflow_agents["document_agent"], search_client_documents),
        (workflow_agents["calendar_agent"], get_calendar),
    ):
        saved.append((agent, "tools", agent.tools))
        agent.tools = [FunctionTool(func=func)]

    set_model(
        workflow_agents["email_agent"],
        {"tool": "search_emails", "args": {"client": CLIENT}},
        "A fixture Gmail discussion requests more tests for damaged barcode labels.",
    )
    set_model(
        workflow_agents["document_agent"],
        {
            "tool": "search_client_documents",
            "args": {
                "query": "project issues, risks and action items",
                "client": CLIENT,
            },
        },
        "The source document reports barcode scanning failures on damaged or "
        "low-quality labels, an approximately five-minute inventory sync delay, "
        "pending deployment approval, and two high-priority actions.",
    )
    set_model(
        workflow_agents["calendar_agent"],
        {"tool": "get_calendar", "args": {"client": CLIENT}},
        "The calendar contains the Acme Robotics warehouse pilot review on "
        "5 November 2026 with Maya Shah.",
    )

    context = {
        "client": CLIENT,
        "important_communication": [
            "Fixture Gmail discussion requests more tests for damaged barcode labels."
        ],
        "client_concerns": [],
        "relevant_documents": ["Acme Robotics Warehouse Pilot"],
        "important_document_facts": [
            "Barcode scanning fails on damaged or low-quality labels.",
            "Inventory synchronization is delayed by approximately five minutes.",
            "Deployment approval is pending.",
            "Barcode scanning and synchronization investigation are "
            "high-priority actions.",
        ],
        "meeting_title": "Acme Robotics warehouse pilot review",
        "meeting_date": "2026-11-05",
        "meeting_time": "Not found in available sources",
        "participants": ["Maya Shah"],
        "missing_information": [
            "The next meeting agenda is not confirmed."
        ],
    }
    set_model(
        workflow_agents["context_aggregator"],
        str(__import__("json").dumps(context)),
    )
    aggregator = workflow_agents["context_aggregator"]
    saved.append(
        (
            aggregator,
            "before_agent_callback",
            aggregator.before_agent_callback,
        )
    )

    async def capture_aggregator_state(callback_context):
        aggregator_states.append(
            {
                key: callback_context.state.get(key)
                for key in (
                    "email_context",
                    "document_context",
                    "calendar_context",
                )
            }
        )

    aggregator.before_agent_callback = capture_aggregator_state
    set_model(
        workflow_agents["information_checker"],
        "MISSING: The next meeting agenda is not confirmed.",
    )
    set_model(
        workflow_agents["research_agent"],
        {
            "tool": "run_crewai_research",
            "args": {
                "client": CLIENT,
                "missing_information": "meeting agenda",
            },
        },
        "CrewAI findings were reviewed by the remote A2A reviewer; "
        "no factual claims were independently verified.",
    )
    set_model(
        workflow_agents["analyst_agent"],
        "Fixture analysis: use only the agenda source and identify unknowns.",
    )
    set_model(workflow_agents["briefing_agent"], _briefing())
    set_model(workflow_agents["quality_checker"], "PASS")
    set_model(workflow_agents["rework_agent"], _briefing())
    set_model(
        workflow_agents["action_proposal_agent"],
        "No action proposed in this test.",
    )
    set_model(workflow_agents["action_executor_agent"], "ACTION NOT EXECUTED")
    return saved, configured_models, retrieval_calls, aggregator_states


async def _start_a2a_server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = to_a2a(
        remote_agent,
        host="127.0.0.1",
        port=port,
        rpc_path="a2a",
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            lifespan="on",
        )
    )
    task = asyncio.create_task(server.serve())
    for _ in range(300):
        if server.started:
            break
        await asyncio.sleep(0.01)
    if not server.started:
        server.should_exit = True
        await task
        raise RuntimeError("The local A2A test server did not start.")
    return port, server, task


def test_main_workflow_runs_crewai_and_real_a2a_branch(monkeypatch):
    async def scenario():
        port, a2a_server, server_task = await _start_a2a_server()
        monkeypatch.setenv(
            "OFFICEPILOT_A2A_AGENT_CARD_URL",
            f"http://127.0.0.1:{port}/a2a{AGENT_CARD_WELL_KNOWN_PATH}",
        )
        monkeypatch.setenv(
            "OFFICEPILOT_A2A_SHARED_SECRET",
            "test-a2a-secret-32-characters-long",
        )
        (
            saved_adk,
            adk_models,
            retrieval_calls,
            aggregator_states,
        ) = _configure_adk_agents()
        workflow_agents = _workflow_agents()
        assert workflow_agents["planner_agent"].model is adk_models["planner_agent"]
        assert all(
            isinstance(agent.model, ScriptedAdkModel)
            for agent in workflow_agents.values()
            if hasattr(agent, "model")
        )
        crew_agents = [
            crew_researcher_module.researcher_agent,
            crew_analyst_module.analyst_agent,
            crew_reviewer_module.reviewer_agent,
        ]
        saved_crew_models = [(agent, agent.llm, agent.verbose) for agent in crew_agents]
        crew_model = ScriptedCrewModel(model="officepilot-crewai-fixture")
        instrumented_crew_model = InstrumentedCrewLLM(
            model="officepilot-instrumented-crewai",
            delegate=crew_model,
        )
        for agent in crew_agents:
            agent.llm = instrumented_crew_model
            agent.verbose = False
        remote_requests = []
        original_remote_impl = type(remote_agent)._run_async_impl

        async def counted_remote(self, ctx):
            remote_requests.append("received")
            async for event in original_remote_impl(self, ctx):
                yield event

        monkeypatch.setattr(
            type(remote_agent),
            "_run_async_impl",
            counted_remote,
        )
        observations = []
        workflow_started_at = perf_counter()
        tokens = begin_execution_observation(
            "workflow-a2a-test",
            lambda event_type, data: observations.append(
                {
                    "type": event_type,
                    "data": data,
                    "occurred_at": perf_counter(),
                }
            ),
        )
        try:
            result = await run_officepilot(
                f"Prepare me for my {CLIENT} meeting on 5 November 2026.",
                user_id="test-workflow-user",
                tenant_id="test-workflow-tenant",
                execution_id="workflow-a2a-test",
            )
        finally:
            end_execution_observation(tokens)
            for agent, model, verbose in saved_crew_models:
                agent.llm = model
                agent.verbose = verbose
            for agent, attribute, value in reversed(saved_adk):
                setattr(agent, attribute, value)
            a2a_server.should_exit = True
            await server_task

        roles = Counter(crew_model.roles)
        event_pairs = {
            (item["type"], item["data"].get("agent"))
            for item in observations
        }
        event_types = [item["type"] for item in observations]

        assert roles["Client Research Specialist"] == 1
        assert roles["Research Analyst"] >= 1
        assert roles["Research Quality Reviewer"] >= 1
        assert adk_models["planner_agent"].calls >= 1
        assert adk_models["research_agent"].calls >= 1
        assert adk_models["briefing_agent"].calls >= 1
        assert adk_models["quality_checker"].calls >= 1
        assert any(
            "five-minute inventory sync delay" in prompt
            for prompt in crew_model.prompts
        )
        assert {item["tool"] for item in retrieval_calls} == {
            "search_emails",
            "search_client_documents",
            "get_calendar",
        }
        assert all(item["client"] == CLIENT for item in retrieval_calls)
        assert all(item["user_id"] == "test-workflow-user" for item in retrieval_calls)
        assert all(
            item["tenant_id"] == "test-workflow-tenant"
            for item in retrieval_calls
        )
        aggregator_prompt = "\n".join(
            adk_models["context_aggregator"].requests
        )
        assert aggregator_states
        assert "email_context" in aggregator_states[0]
        assert "document_context" in aggregator_states[0]
        assert "calendar_context" in aggregator_states[0]
        assert "damaged barcode labels" in str(aggregator_states[0]["email_context"])
        assert "five-minute inventory sync delay" in str(
            aggregator_states[0]["document_context"]
        )
        assert "5 November 2026" in str(aggregator_states[0]["calendar_context"])
        assert "damaged barcode labels" in aggregator_prompt
        assert "five-minute inventory sync delay" in aggregator_prompt
        assert "5 November 2026" in aggregator_prompt
        assert any(
            reference["source"] == "Gmail"
            for reference in result.metadata["sources"]
        )
        assert any(
            reference["source"] == "PostgreSQL / pgvector"
            for reference in result.metadata["sources"]
        )
        assert any(
            reference["source"] == "Google Calendar"
            for reference in result.metadata["sources"]
        )
        integration_statuses = {
            integration["name"]: integration["status"]
            for integration in result.metadata["integrations"]
        }
        assert integration_statuses["Gmail"] == "completed with 1 result"
        assert (
            integration_statuses["PostgreSQL / pgvector"]
            == "completed with 1 result"
        )
        assert (
            integration_statuses["Google Calendar"]
            == "completed with 1 result"
        )
        assert remote_requests == ["received"]
        assert "crewai_model_completed" in event_types
        assert "crewai_task_completed" in event_types
        assert "a2a_completed" in event_types
        a2a_events = [
            item
            for item in observations
            if item["type"] == "a2a_completed"
        ]
        assert len(a2a_events) == 1
        assert a2a_events[0]["data"]["response_received"] is True
        assert a2a_events[0]["data"]["duration_ms"] >= 0
        assert ("agent_started", "research_agent") in event_pairs
        assert ("agent_completed", "quality_checker") in event_pairs
        assert ("agent_completed", "quality_router") in event_pairs
        assert ("agent_completed", "final_response_agent") in event_pairs
        assert result.status == "completed_with_warnings"
        assert result.metadata["quality"]["status"] == "PASS"
        assert result.response.count("\n## ") == 11
        assert "action_executor_agent" not in {
            agent
            for event_type, agent in event_pairs
            if event_type == "agent_started"
        }
        assert not any(
            item["data"].get("tool")
            in {
                "create_followup_task",
                "execute_followup_task_via_mcp",
            }
            for item in observations
            if item["type"] in {"tool_started", "tool_completed"}
        )
        workflow_finished_at = perf_counter()
        completed_agents = {
            item["data"]["agent"]: item["data"].get("duration_ms")
            for item in observations
            if item["type"] == "agent_completed"
            and item["data"].get("duration_ms") is not None
        }
        completed_tools = [
            item
            for item in observations
            if item["type"] == "tool_completed"
        ]
        model_events = [
            item
            for item in observations
            if item["type"] in {"model_completed", "crewai_model_completed"}
        ]
        usage_events = [
            item["data"]
            for item in observations
            if item["type"] == "model_completed"
            and any(
                isinstance(item["data"].get(key), int)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
        ]
        final_response_events = [
            item
            for item in observations
            if item["type"] == "agent_completed"
            and item["data"].get("agent") == "final_response_agent"
        ]
        print(
            "OFFICEPILOT_E2E_METRICS="
            + json.dumps(
                {
                    "scenario": "deterministic full workflow with local A2A server",
                    "end_to_end_ms": round(
                        (workflow_finished_at - workflow_started_at) * 1000,
                        2,
                    ),
                    "agent_latency_ms": completed_agents,
                    "final_response_delivery_ms": (
                        round(
                            (
                                final_response_events[-1]["occurred_at"]
                                - workflow_started_at
                            )
                            * 1000,
                            2,
                        )
                        if final_response_events
                        else None
                    ),
                    "adk_model_calls": sum(
                        item["type"] == "model_completed"
                        for item in model_events
                    ),
                    "crewai_model_calls": sum(
                        item["type"] == "crewai_model_completed"
                        for item in model_events
                    ),
                    "adk_token_usage": (
                        {
                            key: sum(
                                int(item.get(key) or 0)
                                for item in usage_events
                            )
                            for key in (
                                "prompt_tokens",
                                "completion_tokens",
                                "total_tokens",
                            )
                        }
                        if usage_events
                        else None
                    ),
                    "tool_calls": Counter(
                        item["data"].get("tool", "unknown")
                        for item in completed_tools
                    ),
                    "a2a_calls": sum(
                        item["type"] == "a2a_completed"
                        for item in observations
                    ),
                    "a2a_latency_ms": [
                        item["data"].get("duration_ms")
                        for item in observations
                        if item["type"] == "a2a_completed"
                    ],
                    "database_retrieval_ms": None,
                    "google_tasks_writes": 0,
                    "errors": sum(
                        item["type"] in {"a2a_failed", "crewai_failed"}
                        for item in observations
                    ),
                },
                sort_keys=True,
                default=dict,
            ),
        )

    asyncio.run(scenario())
