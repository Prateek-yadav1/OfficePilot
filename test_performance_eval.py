from backend import performance_eval


def test_retrieval_benchmark_does_not_invent_hosted_model_cost(monkeypatch):
    monkeypatch.setenv("OFFICEPILOT_LOCAL_TENANT_ID", "tenant-test")
    monkeypatch.setenv("OFFICEPILOT_LOCAL_USER_ID", "user-test")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setattr(
        performance_eval,
        "search_emails",
        lambda *args, **kwargs: {"emails": []},
    )
    monkeypatch.setattr(
        performance_eval,
        "get_calendar",
        lambda *args, **kwargs: {"meetings": []},
    )
    monkeypatch.setattr(
        performance_eval,
        "retrieve_documents",
        lambda **kwargs: [],
    )

    report = performance_eval.evaluate_officepilot_performance()

    assert report["provider"] == "groq"
    assert report["estimated_model_cost_usd"] is None
    assert report["cost_estimate_status"] == "not_available"
    assert "does not invoke an LLM" in report["notes"]
