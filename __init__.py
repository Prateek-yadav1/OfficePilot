import os
import pathlib
import sys

safe_home = pathlib.Path(os.getenv("OFFICEPILOT_TEST_HOME", "/tmp/officepilot_home"))
safe_home.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(safe_home)

if "pytest" in sys.argv[0] or any("pytest" in arg for arg in sys.argv) or "pytest" in sys.modules:
    os.environ["ADK_MODEL_TIMEOUT_SECONDS"] = "180"
    os.environ["CREWAI_MODEL_TIMEOUT_SECONDS"] = "45"
    os.environ["OFFICEPILOT_WORKSPACE_MODE"] = "mock"

from . import agent

