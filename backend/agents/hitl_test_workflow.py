from google.adk.workflow import Workflow, START

from .action_proposal import action_proposal_agent
from .action_executor import action_executor_agent
from .final_response import final_response_agent


root_agent = Workflow(
    name="officepilot_hitl_test",

    description=(
        "Minimal OfficePilot workflow used to test "
        "human-in-the-loop approval and action execution."
    ),

    edges=[
        (
            START,
            action_proposal_agent,
            action_executor_agent,
            final_response_agent,
        ),
    ],
)
