# OfficePilot requirements traceability

Date: 2026-11-11

| # | Requirement | Status | Evidence | Remaining gap |
|---|---|---|---|---|
| 1 | Context sharing and state updates | Met in tested paths; live Workspace completion pending | ADK session state carries client identity, retrieved contexts, routing decisions, permissions, and quality state. API execution/session IDs and partial-result events are persisted; regression tests cover failed-workflow retention. Live CrewAI passes retrieved fixture context through all three sequential roles. | The live Gmail/Calendar/PostgreSQL workflow has not been rerun since the CrewAI fix; preservation in its earlier failed result was not confirmed. |
| 2 | MCP integration and at least two external tools | Met for integration; live joined workflow incomplete | Read-only Gmail, Calendar, and tenant-scoped PostgreSQL/pgvector retrieval succeeded in prior checks. CrewAI now completes on a factual fixture and its A2A exchange succeeds. MCP outputs are Pydantic-validated. | A complete live Workspace workflow joining retrieval, CrewAI, A2A, and briefing generation remains unverified. |
| 3 | Structured output using Pydantic | Met in local and live provider probe | `MeetingContext` is Pydantic-validated; deterministic briefing checks require all 11 sections; final response is structured Markdown. A real Ollama smoke test also validated model-generated Pydantic output. | No completed live briefing was produced. |
| 4 | Suitable agentic design patterns | Met | Workflow uses parallel retrieval, conditional research/analysis routing, CrewAI delegation, review/rework, deterministic quality routing, and human-gated actions. | Live provider execution remains separate from the deterministic workflow proof. |
| 5 | Callback monitoring and logging | Met | ADK callbacks report agent/tool/model lifecycle, errors, durations, and available token metadata. CrewAI emits safe role-level task start/completion/failure and model timing events, including input/output character counts but no prompt/response text. | Provider token usage remains unavailable; see benchmark. |
| 6 | Agent-to-agent communication using A2A | Met in tested and live local exchange; cloud deployment pending | A real CrewAI fixture report was sent over authenticated HTTP to the local ADK A2A reviewer; a response was received and `a2a_completed` recorded in 512 ms. The end-to-end scripted workflow also exercises the actual HTTP A2A branch. | A2A reviewer is local and deterministic, and the full live Workspace workflow has not been rerun. |
| 7 | Use both CrewAI and ADK, without another agent framework | Met in framework tests and live CrewAI/A2A slice | A real Ollama CrewAI chain completed all three roles in 64.74 seconds; its production research path then completed an actual HTTP A2A exchange in 66.28 seconds total. The main ADK→CrewAI→A2A workflow passes the existing scripted integration test. No third agent framework was introduced. | A full model-backed ADK workflow over live Gmail, Calendar, and PostgreSQL through final briefing remains unverified. |
| 8 | Guardrails and validation | Met for local controls; production setup outstanding | HTTP Basic authentication protects the UI/assets and application APIs; user/tenant identity is persisted on executions; status/events/results/errors are owner-checked; user-specific Workspace tokens and tenant-scoped PostgreSQL RLS protect source retrieval; action callbacks require an authenticated context and reject API task writes; prompt injection guardrails remain active; MCP read responses are type- and shape-checked. | Production users/passwords, per-user OAuth token files, database schema/RLS migration, and HTTPS must be configured and verified before exposure. |
| 9 | Observability/tracing with Langfuse | Met locally; hosted Langfuse unverified | Correlated callback events, timings, errors, safe source references, and workflow state updates are persisted with each API execution. Optional Langfuse instrumentation is implemented, fails closed if enabled without configuration, and now has a documented local setup and live trace verification procedure. | No Langfuse endpoint/keys are configured; hosted trace delivery was not verified. |
| 10 | End-to-end performance, cost, and runtime evaluation | Partially met | [BENCHMARK_REPORT.md](./BENCHMARK_REPORT.md) records deterministic workflow timings, live isolated CrewAI role timings, a successful three-role live chain, and a live local HTTP A2A exchange. Retrieval-only evaluation does not invent provider cost. | Full live Workspace latency, provider token usage/cost, and production hardware cost remain unmeasured. |
| 11 | Cloud deployment | Not met | Dockerfile and `azure.yaml` are supplemented by a new Bicep template, azd parameter file, private-by-default ingress, managed registry-pull identity, and deployment runbook. Azure provisioning/deployment has not been run. | Azure CLI, `azd`, Docker, subscription authorization, and production execution-store persistence are unavailable or unconfigured; Bicep has not been compiled or deployed. |

## Evidence notes

- Previous full-suite result: 83 passed, 90 warnings in 21.40 seconds
  (2026-11-11), including MCP response validation and benchmark cost reporting.
  The tenant-isolation fixture now uses future-relative meeting dates.
- Latest full-suite result after CrewAI optimization: 90 passed, 90 warnings
  in 26.37 seconds using
  `.venv/bin/python -m pytest -q`. Python compilation,
  parameter JSON/YAML parsing, frontend syntax, and `git diff --check` passed.
- On 2026-11-11, a read-only Google smoke test connected to Gmail and Calendar
  using the private token assigned to the local demo user; it read counts only
  and created no tasks. Live MCP reads returned zero email and calendar matches
  for the benchmark client; next-event discovery returned an event. A
  tenant-scoped PostgreSQL/pgvector query returned three documents without
  exposing their contents.
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
- The latest sanitized `backend.llm_diagnostics` check reached Ollama and
  confirmed both configured tags (`llama3.1` for ADK and `llama3.1:latest`
  for CrewAI) are available. Groq is unconfigured; credentials were not
  requested or printed.
- A real Ollama ADK smoke run passed ordinary generation, invoked the test tool
  exactly once, and validated Pydantic output. The model did not echo the
  synthetic tool-result marker, recorded separately as
  `tool_result_echoed: false`.
- A live authenticated, read-only Gmail/Calendar/PostgreSQL workflow completed
  retrieval and recorded seven ADK model completions, but timed out after about
  310 seconds before CrewAI, A2A, and final briefing. A separate three-role
  CrewAI probe timed out after about 231.69 seconds with one task complete.
- A later live CrewAI profile identified a slow Analyst call (128.14 seconds,
  1,261 output characters); only the Researcher task committed. After
  shortening task prompts, limiting outputs to 128 tokens, explicitly
  chaining only each prior task's output, and avoiding timeout retries, the
  real three-role chain completed in 64.74 seconds. A separate call through
  `run_crewai_research` completed the three-role chain and an authenticated
  local HTTP A2A exchange in 66.28 seconds.
- The final successful CrewAI chain recorded one model call and a completion
  event per role. The existing actual HTTP A2A workflow test remains green.
  No live Gmail/Calendar/PostgreSQL workflow was rerun and no successful live
  final briefing is claimed.
- Final live-workflow preflight on 2026-11-11: Ollama responded successfully
  and both configured model tags were present; a PostgreSQL connection and
  `SELECT 1` succeeded. Authentication preflight failed because
  `OFFICEPILOT_AUTH_USERS` is absent from the private runtime configuration.
  The local API health check also failed because nothing was listening on
  `127.0.0.1:8000`. Consequently per-user token mapping, Gmail/Calendar access,
  tenant-scoped live retrieval, A2A authentication/endpoint health, and
  execution-store availability were not verified in this attempt. No live
  workflow was submitted, no meeting was discovered, and no UI result or
  execution ID exists for this attempt.
- API regression tests cover retention of successful partial findings and
  source references during failure and timeout; preservation in the failed
  live attempt was not confirmed by its harness output. The deterministic
  CrewAI/A2A end-to-end test remains distinct from live-provider evidence.
- Azure Bicep and azd deployment files are now present, but Azure tools and
  subscription authorization are absent. No Bicep compilation, cloud
  provisioning, or deployment claim is made.

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
- The earlier full suite at that validation checkpoint, including cross-user
  ownership, tenant-isolation, MCP response-shape, benchmark-cost, and
  A2A/CrewAI regression tests,
  completed with exit code 0: 83 passed, 90 warnings in 21.40 seconds.
- The latest full suite completed with exit code 0: 88 passed, 90 warnings in
  21.65 seconds, including the new provider configuration and diagnostics
  tests.

## Reassessment conclusion

Most requirements are demonstrated locally, including an actual read-only
Workspace/MCP/database integration check and a conditional ADK/CrewAI/A2A
workflow. The project still does not satisfy all eleven requirements as a
deployed system: live model-backed end-to-end execution, hosted Langfuse trace
delivery, and cloud deployment remain unverified or blocked.
