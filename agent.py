"""ADK deployment entry point for OfficePilot."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Ensure the project's backend package is importable when ADK
# loads this directory as the "officepilot" Python package.
project_path = str(PROJECT_ROOT)

if project_path not in sys.path:
    sys.path.insert(0, project_path)

from backend.agents.workflow import root_agent

__all__ = ["root_agent"]
