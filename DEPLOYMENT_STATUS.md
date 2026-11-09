# OfficePilot deployment status

Date: 2026-10-31

## Status

**Not deployed to Azure.** The repository contains a Dockerfile, `azure.yaml`,
and deployment instructions, but no cloud resources were created. Azure CLI
(`az`), Azure Developer CLI (`azd`), and Docker are not available in the
current environment. No paid resources were provisioned.

## Security work completed

- HTTP Basic authentication protects the UI, static assets, and application
  APIs; `/health` is the only public route and returns only a status value.
- Authenticated user and tenant identities are stored with each execution.
  Status, progress, result, and error reads are owner-scoped and return 404
  when the requesting user or tenant does not own the execution.
- Google Workspace OAuth tokens are configured per authenticated user; the
  same token path cannot be assigned to multiple users. Legacy shared
  `token.json` is rejected in the application path.
- PostgreSQL document retrieval filters by tenant and client. It sets a
  transaction-local tenant identifier, and `schema.sql` enables and forces
  row-level security. Existing rows without a tenant are not returned.
- Calendar meeting-to-client matching is exact and evidence-based against
  tenant-scoped indexed client names; ambiguous or unsupported matches remain
  unidentified instead of guessed.
- Prompt-injection validation, tenant-aware tool callbacks, and action policy
  are covered by tests. API workflows disallow action proposals, and Google
  Tasks writes remain disabled by default.

The implementation is not yet a production identity provider. No production
user/password map, per-user Google token files, or tenant-owned document
migration has been configured or verified.

## Current local validation

- Authenticated local FastAPI UI and static assets returned 200; unauthenticated
  UI, assets, and execution reads returned 401. The non-sensitive `/health`
  endpoint returned 200.
- The integrated browser submitted a request through the UI and polled fixture
  progress/status responses, then rendered a deterministic 11-section
  `completed_with_warnings` result with client/meeting details, match evidence,
  missing information, source/integration labels, and final content. API
  responses were intercepted for this UI check; this was not a live workflow.
- Full collected pytest suite: 48 passed, 68 warnings (exit code 0), including
  authorization, tenant-isolation, prompt-guardrail, async API, and conditional
  CrewAI/A2A coverage. Exact validation scope and limits are in
  [IMPLEMENTATION_REPORT.md](./IMPLEMENTATION_REPORT.md).
- The latest live API request reached the planner but failed during Google
  Calendar discovery. Investigation confirmed the active API was configured
  for Google mode without an `OFFICEPILOT_WORKSPACE_TOKEN_FILES` mapping. The
  per-user OAuth setup command is now documented; authorization and restart
  are still required.
- Google Calendar/Gmail read-only calls succeeded separately; no complete live
  Workspace workflow was submitted.
- Langfuse live tracing was not enabled or verified.

## Required before deployment

1. Provide an authenticated Azure subscription and configured infrastructure,
   then validate an authorized deployment.
2. Configure `OFFICEPILOT_AUTH_USERS` with unique strong passwords (minimum
   16 characters), stable user IDs, and tenant IDs using a secret manager.
3. Configure `OFFICEPILOT_A2A_SHARED_SECRET` with at least 32 random
   characters. Use HTTPS end-to-end or terminate TLS at a trusted proxy.
4. Run `backend/sql/schema.sql` before retrieval. Review and explicitly assign
   tenant ownership to existing database rows before those rows are
   re-ingested; do not make unscoped rows visible by default.
5. Set `OFFICEPILOT_WORKSPACE_MODE=google` for live Workspace data and map
   each authenticated user ID to a distinct OAuth token file in
   `OFFICEPILOT_WORKSPACE_TOKEN_FILES`. The default backend remains `mock`.
6. Keep `OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES=false` unless real task creation
   is explicitly approved. No Google Tasks write was performed.
7. Configure a reachable model provider. Ollama remains the default;
   Groq can be selected explicitly with `LLM_PROVIDER=groq`.
8. Configure Langfuse keys and base URL if live tracing is required, then
   verify trace ingestion and flush.
9. Configure `OFFICEPILOT_EXECUTION_DB` on persistent storage. The worker is
   in-process and SQLite-backed; run one replica only. Restarted executions
   are marked failed rather than resumed.
10. Run authorization tests against the intended users, tenants, Workspace
    connections, and production database before public exposure.

## Environment evidence

- Existing Google OAuth client/token files were used only for the earlier
  read-only component checks. The new application path requires dedicated
  per-user token files and rejects the shared legacy token.
- The current shell defaults to mock mode, but the active API process was
  explicitly running Google mode without a per-user token mapping.
  Langfuse configuration was unset during the prior validation. Groq calls
  have not been live-validated; provider tests use mocked responses.
- The integrated browser Playwright tool was usable for UI fixture
  validation. The separate local Playwright launcher lacked its Chromium
  executable at
  `/Users/prateekyadav/Library/Caches/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-mac-arm64/chrome-headless-shell`.

## Decision

Deployment remains blocked pending cloud infrastructure, production auth and
per-user Workspace configuration, tenant-owned document review/migration,
HTTPS, and (if required) live Langfuse credentials. Local test results do not
constitute a live cloud deployment or production-readiness approval.
