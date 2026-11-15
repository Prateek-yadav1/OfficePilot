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

The repository now includes a Bicep template in `infra/main.bicep` and an
`azd` parameter file. The template creates Azure Container Registry, a
Container Apps environment, a single-replica Container App, a user-assigned
identity for registry pulls, and Log Analytics. The app is private by default;
external HTTPS ingress is enabled only in a separate step after image
deployment is verified.

The provided deployment is a **smoke-test foundation, not production
deployment**. Its execution SQLite database uses container-local `/tmp`
storage and is lost when the container is replaced. The current SQLite WAL
store is not configured for Azure Files. Do not expose this deployment to
users or rely on it for durable execution records until the execution store
uses a supported durable database.

1. Install Azure CLI (`az`) and Azure Developer CLI (`azd`), then authenticate
   to an Azure subscription with permission to create the listed resources and
   push images to Azure Container Registry.
2. Create and select a private azd environment. Set `AZURE_SUBSCRIPTION_ID`,
   `AZURE_LOCATION`, and the following values in that environment:
   `OFFICEPILOT_AUTH_USERS` (valid JSON with unique strong passwords,
   `user_id`, and `tenant_id`), `OFFICEPILOT_A2A_SHARED_SECRET` (at least 32
   characters), `GROQ_API_KEY`, `OFFICEPILOT_EXTERNAL_INGRESS=false`,
   `DATABASE_URL`, `LANGFUSE_ENABLED`, `LANGFUSE_PUBLIC_KEY`,
   `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`. Set optional database and
   Langfuse values to empty strings when unused; set `LANGFUSE_ENABLED=false`
   unless trace delivery is configured. Keep these values in a protected
   local environment; `.azure/` is git-ignored. Do not put secrets in source
   control or chat.
   For example, after loading secret values into the local shell from a
   protected source, pass them to azd without placing values in command
   history:

```bash
azd env new officepilot-dev
azd auth login
azd env set AZURE_SUBSCRIPTION_ID "$AZURE_SUBSCRIPTION_ID"
azd env set AZURE_LOCATION "$AZURE_LOCATION"
azd env set OFFICEPILOT_AUTH_USERS "$OFFICEPILOT_AUTH_USERS"
azd env set OFFICEPILOT_A2A_SHARED_SECRET "$OFFICEPILOT_A2A_SHARED_SECRET"
azd env set GROQ_API_KEY "$GROQ_API_KEY"
azd env set OFFICEPILOT_EXTERNAL_INGRESS false
azd env set DATABASE_URL ""
azd env set LANGFUSE_ENABLED false
azd env set LANGFUSE_PUBLIC_KEY ""
azd env set LANGFUSE_SECRET_KEY ""
azd env set LANGFUSE_BASE_URL https://cloud.langfuse.com
```

The local azd environment contains deployment values; protect it like a
secrets file and remove or rotate credentials when it is no longer needed.
3. Run:

```bash
azd up
```

`azd up` provisions the infrastructure, builds the Dockerfile remotely in
ACR, and deploys the app. It requires the Azure deployment identity to be
allowed to push to the provisioned registry. Before enabling external ingress,
verify the deployed app image is the OfficePilot image, not the private
bootstrap image. Keep the app private if provisioning or deployment fails.

After confirming the image and Basic Auth configuration, set
`OFFICEPILOT_EXTERNAL_INGRESS=true` in the same private azd environment and
run `azd provision` to enable HTTPS ingress. The app still requires
`OFFICEPILOT_AUTH_USERS`; `/health` is the only public route. The template
pins the app to one replica and disables Google Tasks writes.

This template defaults Workspace access to `mock`, has no per-user Google
token-file mount, and does not create PostgreSQL/pgvector. A live Workspace
deployment additionally needs user-to-token-file mapping and private,
per-user OAuth token delivery, plus a tenant-scoped PostgreSQL connection.
Those resources and token files must be configured separately before
switching to Google mode. The Bicep template's optional `databaseUrl` and
Langfuse parameters are sourced from the protected azd environment; parameter
values are not checked into the repository.

The default container image in Bicep is only a private bootstrap image; `azd`
replaces it during service deployment. Never enable external ingress until
the replacement is confirmed.

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

## Provider verification

The shared provider switch is `LLM_PROVIDER=ollama` (default) or
`LLM_PROVIDER=groq`. Ollama accepts `OLLAMA_API_BASE` or the common
`OLLAMA_BASE_URL`; an optional trailing `/v1` is normalized for ADK, while
CrewAI receives the OpenAI-compatible `/v1` URL. `OLLAMA_API_BASE` takes
precedence if both root aliases are set. `OLLAMA_OPENAI_BASE_URL` can override
CrewAI's derived endpoint. Groq uses `GROQ_API_KEY` and `GROQ_MODEL`; it does
not silently fall back to Ollama.

Run the credential-safe connectivity and model-presence check:

```bash
.venv/bin/python -m backend.llm_diagnostics
```

The report contains selected provider, consumer model IDs, endpoint status,
and model availability only. It does not print API keys, response bodies, or
provider error text. `ready` confirms that the provider listed the configured
model; it does not prove generation, tool calling, structured output, or
account quota.

To explicitly make one real ADK model request that invokes a local probe tool
and validates the returned Pydantic JSON schema:

```bash
.venv/bin/python -m backend.llm_smoke_test
```

This smoke test can consume model quota or incur cost. It emits no cost or
token estimate because it does not establish trusted pricing/usage evidence.
A passing result proves only the selected provider's ADK request, tool-call,
and Pydantic-output path; it does not constitute a full Gmail/Calendar/database
workflow.

For Ollama, start the service, pull the configured model (`OLLAMA_MODEL` and
`CREWAI_OLLAMA_MODEL`), then run both commands. For Groq, configure the key in
a private `.env` or secret manager, select `LLM_PROVIDER=groq`, and set the
account-accessible model ID. Never include secret values in command output,
screenshots, tickets, or chat.

On macOS, if Ollama is not already running, start it in one terminal:

```bash
ollama serve
```

In another terminal, pull and verify the configured Ollama tag. The ADK
`llama3.1` name resolves to the same `latest` tag used by CrewAI:

```bash
ollama pull llama3.1:latest
ollama list
curl -fsS http://127.0.0.1:11434/api/tags
.venv/bin/python -m backend.llm_diagnostics
.venv/bin/python -m backend.llm_smoke_test
```

If `ollama serve` reports that port 11434 is already in use, a service is
already listening; verify it with the health/model-list requests instead of
starting a second server.

## Langfuse verification

Langfuse is opt-in. In a private local `.env`, set `LANGFUSE_ENABLED=true`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` for the
correct hosted region or self-hosted instance. Keep the secret key out of
source control. Startup performs an authentication check and fails closed if
configuration or authentication is invalid. The server flushes the client
during shutdown.

For verification, start the API with those settings, submit an authenticated
workflow, confirm its correlated trace/spans appear in the intended Langfuse
project, and stop the API cleanly so the flush hook runs. Do not treat
successful local startup or callback logs as proof that hosted trace ingestion
succeeded. Traces may contain prompts, retrieved context, tool calls, and
model responses; review Langfuse access and retention settings accordingly.

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
