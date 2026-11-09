# OfficePilot deployment guide

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

The HTTP API serves the frontend at `/`, readiness at `/health`, and
asynchronous workflow routes under `/executions`. `python main.py` remains
available for direct CLI workflow runs.

The execution store defaults to `~/.officepilot/executions.sqlite3`. It
persists requests, progress, and results locally, but its worker queue is
in-process: run one API process/replica, and use a persistent volume for
`OFFICEPILOT_EXECUTION_DB` before deploying a container. Jobs interrupted by a
service restart are marked failed rather than silently left running.

Set `OFFICEPILOT_MAX_CONCURRENT_WORKFLOWS` to a positive integer (default
`2`) to bound in-process work. `OFFICEPILOT_WORKFLOW_TIMEOUT_SECONDS` sets the
per-execution deadline (default `1800`).

## Container deployment

```bash
docker build -t officepilot .
docker run --rm -p 8000:8000 officepilot
```

For the API execution store, mount persistent storage and set
`OFFICEPILOT_EXECUTION_DB` to a file on that volume. SQLite and the in-process
worker are not a distributed queue and must not be shared across multiple
application replicas.

The HTTP API and the A2A research-review agent are served together. The A2A
agent card is available at
`http://localhost:8000/a2a/.well-known/agent-card.json`. The main workflow calls
this remote agent when it performs additional CrewAI research.

## Azure Container Apps

1. Install Azure Developer CLI (`azd`) and authenticate to your subscription.
2. Configure the required environment variables for your model and workspace mode.
3. Ensure the Azure Developer CLI infrastructure template is present and
   configured for the target subscription and region.
4. Run:

```bash
azd up
```

The repository includes an `azure.yaml` service definition and a Dockerfile.
These files do not themselves create Azure resources; a live deployment still
requires Azure authentication, infrastructure configuration, and a successful
`azd up` run.

## Required environment variables

```bash
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=llama3.1
export OFFICEPILOT_WORKSPACE_MODE=mock
export OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES=false
export LANGFUSE_ENABLED=false
```

ADK agents, CrewAI's Researcher/Analyst/Reviewer, and the ADK A2A client use
the same `LLM_PROVIDER` setting. The remote A2A reviewer is intentionally
deterministic and does not make an LLM request.
Set the provider variables before starting the API and restart it after
changing them; agent model instances are initialized during application
startup.

`mock` is for local development and tests. A deployment that must use live
Workspace data must explicitly set `OFFICEPILOT_WORKSPACE_MODE=google`, map
each authenticated user to a separate private OAuth token file, and authorize
that user. The shared project `token.json` is intentionally rejected. Do not
enable Google Tasks writes unless they are separately authorized; the default
is disabled.

To explicitly use Groq rather than local Ollama:

```bash
export LLM_PROVIDER=groq
export GROQ_API_KEY=<your-groq-api-key>
export GROQ_MODEL=openai/gpt-oss-120b
```

`openai/gpt-oss-120b` is the default Groq model. If it is unavailable for your
account, set `GROQ_MODEL=openai/gpt-oss-20b`. Model access and free-tier
quotas depend on the Groq account and are not verified by local tests. The
application makes no automatic switch to another provider when the key is
missing, a request fails, or a quota is reached; rate limits are reported and
Ollama can be selected explicitly with `LLM_PROVIDER=ollama`.

ADK requests retain a 180-second timeout and no provider retries. CrewAI
requests retain a 45-second timeout and one bounded retry. These limits apply
to all configured models.

Set `LANGFUSE_ENABLED=true` and provide `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` to enable Langfuse tracing.
OfficePilot fails startup/configuration when tracing is enabled without all
three values. A successful live trace must still be confirmed in the Langfuse
project.

## Authentication and tenant isolation

The UI, static assets, and all APIs except `/health` require HTTP Basic
authentication. Configure `OFFICEPILOT_AUTH_USERS` as a JSON object mapping
each username to a unique password, stable `user_id`, and `tenant_id`; use
passwords of at least 16 characters. Supply this configuration through a
secret manager or protected environment variables, never commit it. The
execution store persists both user and tenant ownership; a different user or
tenant receives `404` when requesting another execution, including its events
and briefing.

Run the database migration in `backend/sql/schema.sql` before enabling
retrieval. Documents are selected by both `tenant_id` and client name.
Existing rows without a tenant remain `NULL` and are intentionally excluded;
review and assign tenant ownership explicitly before re-ingestion. Ingestion
requires `OFFICEPILOT_INGEST_TENANT_ID`.

Google Workspace access is per authenticated user. In Google mode,
`OFFICEPILOT_WORKSPACE_TOKEN_FILES` must map each configured `user_id` to a
separate OAuth token file. Token files cannot be shared between user IDs, and
the legacy shared `token.json` is not accepted. The OAuth client file may be
shared; user access tokens may not. Mock email and calendar fixtures are
bound to the `local-demo` tenant and `officepilot-local-demo` user.

For a local Google connection, authorize the account assigned to the
authenticated OfficePilot user ID:

```bash
.venv/bin/python test_google_apis.py --user-id officepilot-local-demo
```

The script uses a private token under `~/.officepilot/tokens/`, performs only
read-only Gmail/Calendar checks by default, and prints the per-user mapping to
add to the protected environment. Google Tasks permission is requested only
when task writes are explicitly enabled. Set the mapping before starting the
API, then restart it. Do not copy or reuse the shared project `token.json`.

The internal A2A route requires `OFFICEPILOT_A2A_SHARED_SECRET` (at least 32
characters), which the built-in A2A client sends only on its service request.
Use HTTPS end-to-end or terminate TLS at a trusted reverse proxy that strips
untrusted forwarded headers. HTTP Basic credentials are not safe over
unencrypted public HTTP.

For Google Workspace production mode:

```bash
export OFFICEPILOT_WORKSPACE_MODE=google
export OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES=false
```

Do not expose the app publicly until authentication users, per-user Workspace
tokens, tenant-scoped document data, TLS, and execution-store persistence are
configured. Google Tasks writes remain disabled unless explicitly enabled;
the asynchronous API workflow also disallows action proposals. Azure
deployment requires an authenticated subscription and provisioned
infrastructure; the repository assets alone do not constitute a live
deployment.
