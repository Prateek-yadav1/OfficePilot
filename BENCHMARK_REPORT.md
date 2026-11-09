# OfficePilot benchmark report

Date: 2026-10-31

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
