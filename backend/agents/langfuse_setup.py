"""Optional Langfuse tracing setup for OfficePilot."""

import os


def configure_langfuse():
    """Enable Langfuse only when explicitly requested in the environment."""

    enabled = (
        os.getenv("LANGFUSE_ENABLED", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )

    if not enabled:
        print("Langfuse tracing disabled.")
        return None

    required = (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
    )
    missing = [name for name in required if not os.getenv(name, "").strip()]

    if missing:
        raise RuntimeError(
            "Langfuse is enabled but required environment variables "
            f"are missing: {', '.join(missing)}"
        )

    from langfuse import get_client
    from openinference.instrumentation.google_adk import (
        GoogleADKInstrumentor,
    )

    client = get_client()

    if not client.auth_check():
        raise RuntimeError(
            "Langfuse authentication failed. Check your credentials "
            "and LANGFUSE_BASE_URL."
        )

    GoogleADKInstrumentor().instrument()

    print("Langfuse tracing enabled.")
    print(
        "Privacy notice: traces may include prompts, retrieved context, "
        "tool calls, and model responses."
    )

    return client
