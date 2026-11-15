import os
import pathlib
import pytest

# Ensure safe HOME directory exists before any tests or imports access it
safe_home = pathlib.Path(os.getenv("OFFICEPILOT_TEST_HOME", "/tmp/officepilot_home"))
safe_home.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(safe_home)
os.environ["ADK_MODEL_TIMEOUT_SECONDS"] = "180"
os.environ["CREWAI_MODEL_TIMEOUT_SECONDS"] = "45"


@pytest.fixture(scope="session", autouse=True)
def ensure_safe_environment():
    """Ensure safe environment variables for test execution."""
    os.environ.setdefault("LANGFUSE_ENABLED", "false")
    os.environ.setdefault("OFFICEPILOT_WORKSPACE_MODE", "mock")
    os.environ.setdefault("OFFICEPILOT_LOCAL_USER_ID", "officepilot-local-demo")
    os.environ.setdefault("OFFICEPILOT_LOCAL_TENANT_ID", "local-demo")
    os.environ.setdefault("OFFICEPILOT_A2A_SHARED_SECRET", "officepilot-a2a-secret-key-32charsmin!")
