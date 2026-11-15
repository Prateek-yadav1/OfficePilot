# OfficePilot benchmark report

Date: 2026-11-11

## Summary

The current full-workflow measurement is a **single deterministic test
scenario**, not a live model-backed performance result. Its ADK and CrewAI
responses and source retrieval are scripted; it does make one real local HTTP
A2A request to a local ADK reviewer.

| Measurement | Result | Scenario |
|---|---:|---|
| Full workflow to final response | 292.28 ms | Deterministic main-workflow fixture |
| Final response agent completion | 149.09 ms from workflow start | Same fixture |
| ADK model calls | 14 | Scripted models; no token usage metadata |
| CrewAI model calls | 4 | Scripted Researcher (two calls), Analyst, Reviewer |
| A2A calls | 1 | Local HTTP A2A server |
| A2A round trip | 14.80 ms | Local server, not a cloud endpoint |
| Tool calls | 4 | Fixture email, document, calendar, and CrewAI research tool |
| PostgreSQL calls in this fixture | 0 | Document retrieval was stubbed |
| Google Tasks writes | 0 | Action path remained disabled |
| Errors in this fixture | 0 | All asserted stages completed |
| Model tokens / hosted API cost | Not measured / $0.00 for this fixture | Scripted adapters made no hosted model calls; local compute/electricity excluded |

The 292.28 ms value is not a claimed improvement over the historical runs.
It is not comparable to real Google API, PostgreSQL, or LLM execution.

## Per-agent timings

Times are from the same single scripted run. `Meeting discovery` was skipped
because the test request named a client.

| Stage | Latency |
|---|---:|
| Planner | 36.37 ms |
| Meeting discovery | Not run |
| Email agent | 8.95 ms |
| Document agent (fixture) | 8.91 ms |
| Calendar agent (fixture) | 8.79 ms |
| Parallel retrieval group | 9.75 ms |
| Context aggregation | 0.81 ms |
| Information checking | 0.59 ms |
| CrewAI research agent stage | 82.40 ms |
| A2A reviewer round trip | 14.80 ms |
| Analyst | 0.63 ms |
| Briefing generation | 0.61 ms |
| Quality checker | 0.62 ms |
| Quality router | 0.13 ms |
| Final response agent | 0.13 ms |

These are harness/callback durations around scripted work. No prompt token
counts were available for the test adapters. The measured final-response
delivery time includes the preceding workflow stages.

## Separate data-access measurements

- A rerun of `backend/performance_eval.py` completed in **11.365 seconds**:
  two mock email results, one mock calendar result, and three indexed
  PostgreSQL documents for the benchmark client. This includes the mock
  email/calendar delays and cold embedding-model initialization; it is not a
  full workflow benchmark.
- Two sequential document retrievals in one process returned three matching
  documents. The first call took **6,658.31 ms** with cold model initialization;
  the second took **25.27 ms** with the cached model. These values include
  embedding plus database retrieval; pure SQL latency was not separately
  instrumented.
- Read-only live integration checks returned an upcoming Google Calendar
  event in **0.93 seconds** and four Gmail matches in **2.88 seconds** for the
  previously observed client. PostgreSQL returned **zero** documents for that
  client. The combined three-component check took about **12 seconds**,
  including embedding model initialization. The live event did not explicitly
  contain the previously observed client identifier.

## Historical scenarios (not directly comparable)

- A prior live Workspace run took approximately **642 seconds**, past the
  client's **600-second** timeout. Briefing generation was observed, but
  quality checking and final response delivery were not confirmed.
- The requested historical baseline is approximately **1,136.89 seconds**.
  Its test inputs and execution conditions are not documented here, so no
  percentage improvement or direct comparison is claimed.
- An existing `performance_report.json` records a prior **14.5-second**
  local retrieval run. The later 11.365-second retrieval-only rerun differs
  in environment/cache state; neither measures a full LLM workflow.

## Interpretation and limitations

The asynchronous API removes the need to hold the initial HTTP request open,
but does not by itself reduce model compute time. Replacing two deterministic
mapping-router LLM calls reduces avoidable work by design; no before/after
live LLM benchmark was available to quantify its impact. Fixed document
retrieval limits and cached embedding-model reuse are retained.

The test does not measure live model token usage, paid-model cost, full live
Workspace latency, production concurrency, pure SQL latency, or cloud
deployment behavior. Do not use the scripted 292.28 ms workflow result as a
service-level performance claim.

The retrieval-only evaluator in `backend/performance_eval.py` does not invoke
an LLM, so it now reports model cost as unavailable rather than applying a
fixed estimate to every hosted provider. A live model cost estimate requires
provider-reported token usage and the configured model's current pricing.

## 2026-11-11 read-only live component check

The local demo user's private read-only OAuth token successfully connected to
Gmail and Calendar. The MCP client exercised email search, client calendar
search, and next-event discovery; the first two returned zero matches for the
benchmark client, while discovery returned an upcoming event. No email or
event content was printed, and no Tasks API permission or write was used.
A tenant-filtered PostgreSQL/pgvector lookup returned three documents for the
same test client. These component checks are not a full workflow or an LLM
performance sample.

## 2026-11-11 live Ollama checks and workflow attempt

- Sanitized provider diagnostics reached Ollama at
  `http://127.0.0.1:11434` and confirmed the configured ADK `llama3.1` and
  CrewAI `llama3.1:latest` models are available. The Groq path was not tested
  against a live provider because `GROQ_API_KEY` is unset.
- The actual ADK smoke test passed ordinary generation, one real test-tool
  invocation, and Pydantic structured-output validation. The final model text
  did not echo the synthetic tool-result marker. Token usage and cost were not
  returned by the probe and were not estimated.
- A read-only authenticated workflow using live Gmail, Calendar, and
  tenant-scoped PostgreSQL/pgvector reached seven ADK model completions and
  then failed before CrewAI completed. Elapsed time was about 310 seconds.
  No successful CrewAI completion, A2A review, or final briefing was observed.
- A separate real three-role CrewAI run against the same Ollama endpoint, with
  harmless fixture input, timed out after about 231.69 seconds with one of
  three tasks complete. A prior isolated CrewAI-compatible generation had
  succeeded, but that does not establish that the full crew works reliably.
- No live token count, hosted-model cost, or full-workflow success is claimed.
  The result is a measured timeout, not a latency or cost benchmark.

## 2026-11-11 CrewAI role profiling and optimization

All model-backed CrewAI measurements below used Ollama `llama3.1:latest` and
small factual fixture text. They are local measurements, not hosted-provider
cost or production latency estimates. CrewAI's synchronous calls do not expose
time-to-first-token, so TTFT is unavailable.

### Initial isolated role profiles

| Role | Status | Model-call duration | Total role duration | Output chars | Model calls | Error |
|---|---|---:|---:|---:|---:|---|
| Researcher | Completed | 70.42 s | 70.62 s | 359 | 1 | None |
| Analyst | Completed | 30.91 s | 31.13 s | 368 | 1 | None |
| Reviewer | Completed | 15.19 s | 15.40 s | 343 | 1 | None |

### Initial three-role failure

The first chained run took 159.63 seconds and failed with `TimeoutError` after
only the Researcher task was recorded complete. Researcher's model call took
30.60 seconds and produced 703 characters. The Analyst call then took 128.14
seconds for 1,261 output characters; it completed at the model layer but the
task timed out before its output was committed. Only two model calls occurred.

Inspection of the installed CrewAI implementation showed that its synchronous
task timeout waits for the worker thread to exit. Therefore the configured
task limit did not promptly stop a slow synchronous model request. The
measured Analyst duration exceeded its then-current 45-second bound.

### Final optimized standalone chain

The final chain kept all three CrewAI roles, sequential execution, one
iteration per agent, and the existing 300-second overall limit. It reduced
the output cap to 128 tokens, shortened duplicated task instructions, passed
only the immediately preceding task's output to each downstream role, and
disabled model retries after timeouts/rate limits (one bounded retry remains
for connection errors).

| Role | Status | Input chars | Model-call duration | Task duration | Output chars | Calls |
|---|---|---:|---:|---:|---:|---:|
| Researcher | Completed | 1,278 | 17.92 s | 18.03 s | 291 | 1 |
| Analyst | Completed | 1,260 | 24.21 s | 24.29 s | 645 | 1 |
| Reviewer | Completed | 1,491 | 22.08 s | 22.14 s | 573 | 1 |

All three task-completion events were observed; the crew returned a 611-
character result in **64.74 seconds**. The slowest role in this successful
chain was the Analyst at 24.21 seconds.

The same real CrewAI-to-A2A path was then run with the local authenticated HTTP
A2A reviewer. It completed in **66.28 seconds** total: three CrewAI model
calls, three task completions, and one A2A exchange measured at **512 ms**.
The final report included the A2A response. The A2A reviewer explicitly
disclaims independent source verification.

The successful fixture runs do not establish that the previously failed live
Gmail/Calendar/PostgreSQL workflow now completes. That full Workspace workflow
was not rerun here. Token usage and model cost remain unavailable and are not
estimated.

## 2026-11-11 final live workflow preflight (blocked)

- Ollama `/api/tags` returned HTTP 200; sanitized provider diagnostics reported
  ADK `llama3.1` and CrewAI `llama3.1:latest` ready.
- PostgreSQL connectivity and `SELECT 1` succeeded. No tenant-scoped document
  query was attempted during this preflight.
- Authentication configuration validation stopped with
  `OFFICEPILOT_AUTH_USERS is required`. The script emitted no user IDs,
  passwords, token paths, or token contents.
- The local application health request to `http://127.0.0.1:8000/health`
  could not connect (HTTP status `000`). The API was not started.
- Because authenticated user configuration was missing, no Google OAuth
  mapping check, Gmail or Calendar API request, A2A request, execution-store
  check, meeting discovery, or workflow submission was made. No execution ID,
  meeting result, per-stage duration, token usage, or cost is available from
  this attempt. A full live end-to-end success is not claimed.
