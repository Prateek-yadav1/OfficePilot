"""Retrieve relevant office documents using PostgreSQL and pgvector."""

import os

from psycopg.rows import dict_row
from sentence_transformers import SentenceTransformer

from backend.tools.database import connect_database


MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)

_MODEL = None


def _get_model():
    """Load the embedding model only when retrieval is first requested."""
    global _MODEL

    if _MODEL is None:
        _MODEL = SentenceTransformer(MODEL_NAME)

    return _MODEL


def retrieve_documents(
    query: str,
    client: str = "",
    tenant_id: str = "",
    limit: int = 3,
) -> list[dict]:
    """Retrieve relevant documents using PostgreSQL and pgvector."""
    # A client identifier is mandatory to prevent cross-client
    # document leakage.
    if not isinstance(client, str) or not client.strip():
        raise ValueError(
            "A non-empty client name is required for document retrieval."
        )
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError(
            "A non-empty authenticated tenant ID is required for document retrieval."
        )

    if not isinstance(query, str) or not query.strip():
        raise ValueError("A non-empty document search query is required.")

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer.")

    client = client.strip()
    tenant_id = tenant_id.strip()
    query = query.strip()

    query_embedding = _get_model().encode(query)

    vector_text = "[" + ",".join(
        f"{float(value):.8f}" for value in query_embedding
    ) + "]"

    with connect_database() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, true);",
                (tenant_id,),
            )
            cur.execute(
                """
                SELECT
                    client,
                    title,
                    document_type AS type,
                    content,
                    1 - (embedding <=> %s::vector) AS relevance_score
                FROM office_documents
                WHERE tenant_id = %s
                    AND LOWER(client) = LOWER(%s)
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector_text, tenant_id, client, vector_text, limit),
            )
            results = cur.fetchall()

    for result in results:
        result["relevance_score"] = round(
            float(result["relevance_score"]), 4
        )

    return [dict(result) for result in results]


def list_indexed_clients(tenant_id: str) -> list[str]:
    """List only client labels represented by a tenant's indexed documents."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("A non-empty authenticated tenant ID is required.")
    with connect_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, true);",
                (tenant_id.strip(),),
            )
            cur.execute(
                """
                SELECT DISTINCT client
                FROM office_documents
                WHERE tenant_id = %s
                ORDER BY client;
                """,
                (tenant_id.strip(),),
            )
            return [str(row[0]) for row in cur.fetchall()]
