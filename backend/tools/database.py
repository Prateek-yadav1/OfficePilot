"""Shared PostgreSQL connection helper for local and cloud environments."""

import os

import psycopg


def connect_database():
    """Connect using DATABASE_URL, or the existing local database by default."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    connect_timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT", "10"))

    dsn = database_url or "dbname=officepilot_db"

    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]

    return psycopg.connect(dsn, connect_timeout=connect_timeout)
