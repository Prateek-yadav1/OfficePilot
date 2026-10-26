from google.adk.workflow import Workflow, START

from .planner import planner_agent
from .parallel_agents import parallel_research
from .aggregator import aggregator_agent
from .information_checker import information_checker

from .router import (
    router_agent,
    route_decision,
    quality_router_agent,
    quality_route_decision,
)

from .research_agent import research_agent
from .analyst import analyst_agent
from .briefing_agent import briefing_agent
from .quality_checker import quality_checker
from .rework_agent import rework_agent
from .final_response import final_response_agent

# Phase 5 - Human-in-the-Loop
from .action_proposal import action_proposal_agent
from .action_executor import action_executor_agent


root_agent = Workflow(
    name="officepilot_phase6",

    description=(
        "Hierarchical multi-agent OfficePilot workflow demonstrating "
        "sequential orchestration, parallel research, conditional "
        "routing, nested CrewAI research, analysis, briefing generation, "
        "quality checking, iterative refinement, action proposal, "
        "and human-in-the-loop action execution."
    ),

    edges=[

        # ============================================================
        # INITIAL OFFICE RESEARCH
        # ============================================================

        (
            START,
            planner_agent,
            parallel_research,
            aggregator_agent,
            information_checker,
            router_agent,
            route_decision,
        ),

        # ============================================================
        # CONDITIONAL ROUTING
        # ============================================================

        (
            route_decision,
            {
                "RESEARCH": research_agent,
                "ANALYSIS": analyst_agent,
            },
        ),

        # ============================================================
        # ADDITIONAL RESEARCH
        # ============================================================

        (
            research_agent,
            analyst_agent,
        ),

        # ============================================================
        # ANALYSIS → BRIEFING
        # ============================================================

        (
            analyst_agent,
            briefing_agent,
        ),

        # ============================================================
        # QUALITY CHECK
        # ============================================================

        (
            briefing_agent,
            quality_checker,
        ),

        (
            quality_checker,
            quality_router_agent,
        ),

        (
            quality_router_agent,
            quality_route_decision,
        ),

        # ============================================================
        # QUALITY ROUTING
        # ============================================================

        (
            quality_route_decision,
            {
                "REVISE": rework_agent,
                "PASS": action_proposal_agent,
            },
        ),

        # ============================================================
        # REFLECTION / REWORK LOOP
        # ============================================================

        (
            rework_agent,
            quality_checker,
        ),

        # ============================================================
        # PHASE 5 - ACTION PROPOSAL
        # ============================================================

        (
            action_proposal_agent,
            action_executor_agent,
        ),

        # ============================================================
        # FINAL RESPONSE
        # ============================================================

        (
            action_executor_agent,
            final_response_agent,
        ),
    ],
)