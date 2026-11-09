# OfficePilot requirements traceability

Date: 2026-10-31

| # | Requirement | Status | Evidence | Remaining gap |
|---|---|---|---|---|
| 1 | Context sharing and state updates | Met | ADK session state carries client identity, retrieved contexts, routing decisions, execution permissions, and quality state. The API correlates execution and session IDs. | A live full-workflow Workspace run has not been completed. |
| 2 | MCP integration and at least two external tools | Partially validated | MCP server exposes per-user Workspace tools; Calendar, Gmail, PostgreSQL, and pgvector have tenant/user filters. A live API attempt reached Google Calendar discovery. | The active Google-mode API has no `OFFICEPILOT_WORKSPACE_TOKEN_FILES` mapping, so the latest request failed before retrieving meeting data. Configure per-user OAuth and restart before live end-to-end validation. |
| 3 | Structured output using Pydantic | Met | `MeetingContext` is Pydantic-validated; deterministic briefing checks require all 11 sections; final response is structured Markdown. | No material gap in the tested local path. |
| 4 | Suitable agentic design patterns | Met | Workflow uses parallel retrieval, conditional research/analysis routing, CrewAI delegation, review/rework, deterministic quality routing, and human-gated actions. | Live provider execution remains separate from the deterministic workflow proof. |
| 5 | Callback monitoring and logging | Met | ADK callbacks report agent/tool/model lifecycle, errors, durations, and available token metadata; CrewAI and A2A stages emit correlated events. | Scripted models do not provide meaningful token usage; see benchmark. |
| 6 | Agent-to-agent communication using A2A | Conditionally met | The actual main workflow research branch sends an HTTP A2A request to a local ADK remote reviewer, receives a non-empty response, records completion, and continues through quality and final response. | The endpoint was local and deterministic, not a deployed remote service. |
| 7 | Use both CrewAI and ADK, without another agent framework | Met in tested path | The main ADK workflow invokes a three-role CrewAI crew (Researcher, Analyst, Reviewer) through the existing nested research tool. The test uses a scripted CrewAI LLM; no third agent framework was introduced. | Live model-backed CrewAI execution was not measured in this validation. |
| 8 | Guardrails and validation | Met for implemented controls; deployment configuration required | HTTP Basic authentication protects the UI/assets and application APIs; user/tenant identity is persisted on executions; status/events/results/errors are owner-checked; user-specific Workspace tokens and tenant-scoped PostgreSQL RLS protect source retrieval; action callbacks require an authenticated context and reject API task writes; prompt injection guardrails remain active. | Production users/passwords, per-user OAuth token files, database schema/RLS migration, and HTTPS must be configured and verified before exposure. |
| 9 | Observability/tracing with Langfuse | Partially implemented; live validation blocked | Disabled mode was verified; enabling without required configuration fails closed. Startup instrumentation and shutdown flush are present. | Langfuse keys/base URL are unavailable; no authenticated trace or flush to a live project was verified. |
| 10 | End-to-end performance, cost, and runtime evaluation | Partially met | A deterministic full-workflow measurement, per-agent timings, data-access benchmark, warm/cold retrieval measurements, and historical scenarios are recorded in [BENCHMARK_REPORT.md](./BENCHMARK_REPORT.md). | The deterministic fixture is not comparable to live LLM execution; production token cost, hardware cost, and full live latency remain unmeasured. |
| 11 | Cloud deployment | Not met | Dockerfile, `azure.yaml`, and deployment documentation exist. | No Azure deployment occurred; Azure CLI, `azd`, Docker, subscription authorization, and configured infrastructure were unavailable. |

## Evidence notes

- Full collected pytest suite: 48 passed, 68 warnings.
- Follow-up run reached the planner, but Google Calendar discovery failed
  because the active Google-mode API had no per-user token mapping. A
  regression test now verifies this failure is surfaced as actionable
  configuration guidance rather than a generic `ExceptionGroup`.
- The full CrewAI/A2A test reached the final response after quality checking.
  It used scripted model/source fixtures and a local HTTP A2A server.
- Read-only live checks found an upcoming Calendar event, four Gmail matches
  for the previously observed client, and zero indexed documents for that
  client. The current next Calendar event did not explicitly name that client.
- The separate offline workflow passed the deterministic quality gate and
  reached final response with the action approval rejected.
- No Google Tasks writes or Azure resources were created.

## Security audit evidence

- Unauthenticated UI, assets, execution submission, status/events, and A2A
  access are rejected; only the non-sensitive `/health` endpoint is public.
  Local HTTP/browser checks confirmed unauthenticated UI/assets/execution
  reads return 401 and authenticated UI/assets requests return 200.
- A different authenticated user/tenant receives `404` for another user's
  execution, progress events, result, and error; session IDs do not authorize
  access.
- Workspace API tokens are keyed to authenticated user IDs and duplicate
  token-file paths are rejected. Mock email/calendar fixtures are filtered by
  tenant and user.
- PostgreSQL retrieval sets a transaction-local tenant identifier and filters
  by tenant plus client. The schema enables and forces RLS; unscoped legacy
  rows remain unavailable until explicitly assigned.
- Prompt injection tests reject instruction override prompts. Tool callbacks
  reject source access without tenant context and task writes unless the
  workflow policy explicitly permits them; Google task writes remain disabled
  by default.
- The full suite, including cross-user ownership and tenant-isolation
  regression tests, completed with exit code 0: 48 passed, 68 warnings.

## Conclusion

The project must not be reported as satisfying all eleven requirements.
Conditional A2A execution and final response delivery are now demonstrated,
but live end-to-end Workspace execution, live Langfuse tracing, and cloud
deployment remain open.
