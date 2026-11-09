"""SQLite-backed execution records for asynchronous OfficePilot workflows."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_path() -> Path:
    configured = os.getenv("OFFICEPILOT_EXECUTION_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".officepilot" / "executions.sqlite3"


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for a different request."""


class ExecutionStore:
    """Persist requests, lifecycle state, progress events, and final results."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_path()
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level="IMMEDIATE",
        )
        connection.row_factory = sqlite3.Row
        try:
            os.chmod(self.path, 0o600)
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA journal_mode = WAL")
            with connection:
                yield connection
        finally:
            connection.close()
            for sidecar in (
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            ):
                try:
                    os.chmod(sidecar, 0o600)
                except FileNotFoundError:
                    pass

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    request_hash TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    user_id TEXT,
                    tenant_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS execution_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY (execution_id)
                        REFERENCES executions(execution_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_execution_events_execution_id
                    ON execution_events(execution_id, event_id);
                """
            )
            execution_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(executions)"
                ).fetchall()
            }
            if "user_id" not in execution_columns:
                connection.execute("ALTER TABLE executions ADD COLUMN user_id TEXT")
            if "tenant_id" not in execution_columns:
                connection.execute("ALTER TABLE executions ADD COLUMN tenant_id TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_executions_owner
                ON executions(tenant_id, user_id, execution_id)
                """
            )

    def create(
        self,
        user_request: str,
        user_id: str,
        tenant_id: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if not user_id.strip() or not tenant_id.strip():
            raise ValueError("Execution ownership requires user_id and tenant_id.")
        scoped_idempotency_key = (
            hashlib.sha256(
                f"{tenant_id}\0{user_id}\0{idempotency_key}".encode("utf-8")
            ).hexdigest()
            if idempotency_key
            else None
        )
        request_hash = hashlib.sha256(
            f"{tenant_id}\0{user_id}\0{user_request}".encode("utf-8")
        ).hexdigest()
        now = _utc_now()
        execution_id = str(uuid4())

        with self._connect() as connection:
            if scoped_idempotency_key:
                existing = connection.execute(
                    """
                    SELECT execution_id, request_hash
                    FROM executions
                    WHERE idempotency_key = ?
                    """,
                    (scoped_idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["request_hash"] != request_hash:
                        raise IdempotencyConflictError(
                            "Idempotency key was already used for a different request."
                        )
                    existing_id = existing["execution_id"]
                    connection.commit()
                    return self.get(existing_id), False

            try:
                connection.execute(
                    """
                    INSERT INTO executions (
                        execution_id, idempotency_key, request_hash,
                        user_request, user_id, tenant_id, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        execution_id,
                        scoped_idempotency_key,
                        request_hash,
                        user_request,
                        user_id,
                        tenant_id,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                if not scoped_idempotency_key:
                    raise
                existing = connection.execute(
                    """
                    SELECT execution_id, request_hash
                    FROM executions
                    WHERE idempotency_key = ?
                    """,
                    (scoped_idempotency_key,),
                ).fetchone()
                if existing is None:
                    raise
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflictError(
                        "Idempotency key was already used for a different request."
                    )
                existing_id = existing["execution_id"]
                connection.rollback()
                return self.get(existing_id), False

            self._append_event(
                connection,
                execution_id,
                "queued",
                {"message": "Workflow request accepted."},
            )

        return self.get(execution_id), True

    def _append_event(
        self,
        connection: sqlite3.Connection,
        execution_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO execution_events
                (execution_id, event_type, occurred_at, data_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                execution_id,
                event_type,
                _utc_now(),
                json.dumps(data, separators=(",", ":"), default=str),
            ),
        )
        return int(cursor.lastrowid)

    def append_event(
        self,
        execution_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown execution ID: {execution_id}")
            if row["status"] not in {"queued", "running"}:
                return 0
            event_id = self._append_event(
                connection,
                execution_id,
                event_type,
                data,
            )
            connection.execute(
                "UPDATE executions SET updated_at = ? WHERE execution_id = ?",
                (_utc_now(), execution_id),
            )
        return event_id

    def mark_running(self, execution_id: str) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE executions
                SET status = 'running', started_at = ?, updated_at = ?
                WHERE execution_id = ? AND status = 'queued'
                """,
                (now, now, execution_id),
            )
            self._append_event(
                connection,
                execution_id,
                "running",
                {"message": "Workflow execution started."},
            )

    def complete(
        self,
        execution_id: str,
        status: str,
        result: dict[str, Any],
    ) -> None:
        if status not in {"completed", "completed_with_warnings"}:
            raise ValueError(f"Invalid successful execution status: {status}")
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE executions
                SET status = ?, updated_at = ?, completed_at = ?, result_json = ?
                WHERE execution_id = ?
                """,
                (
                    status,
                    now,
                    now,
                    json.dumps(result, separators=(",", ":"), default=str),
                    execution_id,
                ),
            )
            self._append_event(
                connection,
                execution_id,
                status,
                {"message": "Final briefing is available."},
            )

    def update_result(
        self,
        execution_id: str,
        result: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE executions
                SET result_json = ?, updated_at = ?
                WHERE execution_id = ?
                """,
                (
                    json.dumps(result, separators=(",", ":"), default=str),
                    _utc_now(),
                    execution_id,
                ),
            )

    def update_partial_data(
        self,
        execution_id: str,
        partial_data: dict[str, Any],
    ) -> None:
        """Persist caller-owned workflow findings separately from progress logs."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, result_json FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown execution ID: {execution_id}")
            if row["status"] not in {"queued", "running"}:
                return
            result = (
                json.loads(row["result_json"])
                if row["result_json"]
                else {}
            )
            previous = result.get("partial_data")
            current = previous if isinstance(previous, dict) else {}
            current.update(partial_data)
            result["partial_data"] = current
            connection.execute(
                """
                UPDATE executions
                SET result_json = ?, updated_at = ?
                WHERE execution_id = ?
                """,
                (
                    json.dumps(result, separators=(",", ":"), default=str),
                    _utc_now(),
                    execution_id,
                ),
            )

    def fail(
        self,
        execution_id: str,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE executions
                SET status = 'failed', updated_at = ?, completed_at = ?,
                    error = ?, result_json = ?
                WHERE execution_id = ?
                """,
                (
                    now,
                    now,
                    error,
                    json.dumps(result, separators=(",", ":"), default=str)
                    if result is not None
                    else None,
                    execution_id,
                ),
            )
            self._append_event(
                connection,
                execution_id,
                "failed",
                {"message": error},
            )

    def recover_orphaned(self) -> int:
        """Mark work interrupted by a process restart as failed, not pending."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT execution_id
                FROM executions
                WHERE status IN ('queued', 'running')
                """
            ).fetchall()
        for row in rows:
            self.fail(
                row["execution_id"],
                "Execution interrupted because the service restarted.",
            )
        return len(rows)

    def get_user_request(self, execution_id: str) -> str | None:
        """Return persisted work input for a local worker recovery routine."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_request FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return str(row["user_request"]) if row else None

    def get(
        self,
        execution_id: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            query = """
                SELECT execution_id, status, created_at, updated_at,
                    started_at, completed_at, result_json, error
                FROM executions
                WHERE execution_id = ?
            """
            parameters: list[str] = [execution_id]
            if user_id is not None:
                query += " AND user_id = ?"
                parameters.append(user_id)
            if tenant_id is not None:
                query += " AND tenant_id = ?"
                parameters.append(tenant_id)
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            return None

        result = dict(row)
        result["result"] = (
            json.loads(result.pop("result_json"))
            if result["result_json"]
            else None
        )
        result["error"] = result["error"]
        return result

    def events(
        self,
        execution_id: str,
        after_event_id: int = 0,
        limit: int = 500,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            query = """
                SELECT event_id, event_type, occurred_at, data_json
                FROM execution_events e
                WHERE execution_id = ? AND event_id > ?
            """
            parameters: list[Any] = [execution_id, after_event_id]
            if user_id is not None or tenant_id is not None:
                query += """
                    AND EXISTS (
                        SELECT 1 FROM executions x
                        WHERE x.execution_id = e.execution_id
                """
                if user_id is not None:
                    query += " AND x.user_id = ?"
                    parameters.append(user_id)
                if tenant_id is not None:
                    query += " AND x.tenant_id = ?"
                    parameters.append(tenant_id)
                query += ")"
            query += " ORDER BY event_id LIMIT ?"
            parameters.append(limit)
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "id": row["event_id"],
                "type": row["event_type"],
                "timestamp": row["occurred_at"],
                "data": json.loads(row["data_json"]),
            }
            for row in rows
        ]

    def latest_event_id(self, execution_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(event_id), 0) AS event_id
                FROM execution_events
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
        return int(row["event_id"])

    def metrics(self, execution_id: str) -> dict[str, Any]:
        """Aggregate sanitized performance events without reading user content."""
        events = self.events(execution_id, limit=5000)
        agents: dict[str, list[float]] = {}
        tool_counts: dict[str, int] = {}
        tool_durations: dict[str, list[float]] = {}
        model_count = 0
        crewai_model_count = 0
        model_failures = 0
        model_timeouts = 0
        crewai_model_failures = 0
        crewai_model_timeouts = 0
        crewai_model_durations: dict[str, list[float]] = {}
        crewai_task_calls: dict[str, int] = {}
        crewai_task_durations: dict[str, list[float]] = {}
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        a2a_calls = 0
        a2a_durations: list[float] = []
        crewai_durations: list[float] = []
        database_retrieval_ms: list[float] = []
        for event in events:
            data = event["data"]
            if event["type"] == "agent_completed":
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)):
                    agents.setdefault(data.get("agent", "unknown"), []).append(
                        float(duration)
                    )
            elif event["type"] == "tool_completed":
                tool = str(data.get("tool", "unknown"))
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)):
                    tool_durations.setdefault(tool, []).append(float(duration))
                    if tool in {"search_client_documents", "retrieve_documents"}:
                        database_retrieval_ms.append(float(duration))
            elif event["type"] == "model_completed":
                model_count += 1
                prompt_tokens += int(data.get("prompt_tokens") or 0)
                completion_tokens += int(data.get("completion_tokens") or 0)
                total_tokens += int(data.get("total_tokens") or 0)
            elif event["type"] in {"model_failed", "model_timed_out"}:
                model_failures += event["type"] == "model_failed"
                model_timeouts += event["type"] == "model_timed_out"
            elif event["type"] == "crewai_model_started":
                crewai_model_count += 1
                agent = str(data.get("agent", "unknown"))
                crewai_task_calls[agent] = crewai_task_calls.get(agent, 0) + 1
            elif event["type"] == "crewai_model_completed":
                agent = str(data.get("agent", "unknown"))
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)):
                    crewai_model_durations.setdefault(agent, []).append(
                        float(duration)
                    )
            elif event["type"] in {
                "crewai_model_failed",
                "crewai_model_timed_out",
            }:
                crewai_model_failures += event["type"] == "crewai_model_failed"
                crewai_model_timeouts += (
                    event["type"] == "crewai_model_timed_out"
                )
            elif event["type"] == "crewai_task_completed":
                task = str(data.get("task", "unknown"))
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)):
                    crewai_task_durations.setdefault(task, []).append(
                        float(duration)
                    )
            elif event["type"] == "a2a_completed":
                a2a_calls += 1
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)):
                    a2a_durations.append(float(duration))
            elif event["type"] == "crewai_completed":
                duration = data.get("duration_ms")
                if isinstance(duration, (int, float)):
                    crewai_durations.append(float(duration))

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT created_at, started_at, completed_at
                FROM executions
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
        end_to_end_ms = None
        queue_delay_ms = None
        if row is not None and row["completed_at"]:
            created = datetime.fromisoformat(row["created_at"])
            completed = datetime.fromisoformat(row["completed_at"])
            end_to_end_ms = round(
                (completed - created).total_seconds() * 1000,
                2,
            )
            if row["started_at"]:
                started = datetime.fromisoformat(row["started_at"])
                queue_delay_ms = round(
                    (started - created).total_seconds() * 1000,
                    2,
                )
        return {
            "end_to_end_latency_ms": end_to_end_ms,
            "queue_delay_ms": queue_delay_ms,
            "agent_duration_ms": {
                name: {
                    "calls": len(durations),
                    "total": round(sum(durations), 2),
                    "max": round(max(durations), 2),
                }
                for name, durations in agents.items()
            },
            "model_calls": (
                model_count
                + model_failures
                + model_timeouts
                + crewai_model_count
            ),
            "adk_model_calls": model_count + model_failures + model_timeouts,
            "crewai_model_calls": crewai_model_count,
            "crewai_model_calls_by_agent": crewai_task_calls,
            "crewai_model_duration_ms": {
                name: {
                    "calls": len(durations),
                    "total": round(sum(durations), 2),
                    "max": round(max(durations), 2),
                }
                for name, durations in crewai_model_durations.items()
            },
            "model_failures": model_failures,
            "model_timeouts": model_timeouts,
            "crewai_model_failures": crewai_model_failures,
            "crewai_model_timeouts": crewai_model_timeouts,
            "crewai_task_duration_ms": {
                name: {
                    "calls": len(durations),
                    "total": round(sum(durations), 2),
                    "max": round(max(durations), 2),
                }
                for name, durations in crewai_task_durations.items()
            },
            "token_usage": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
                "note": (
                    "Counts are from provider usage metadata; zero can mean "
                    "the provider did not return token usage."
                ),
            },
            "tool_calls": tool_counts,
            "tool_duration_ms": {
                name: {
                    "calls": len(durations),
                    "total": round(sum(durations), 2),
                    "max": round(max(durations), 2),
                }
                for name, durations in tool_durations.items()
            },
            "database_retrieval_ms": database_retrieval_ms,
            "a2a_calls": a2a_calls,
            "a2a_duration_ms": a2a_durations,
            "crewai_duration_ms": crewai_durations,
        }
