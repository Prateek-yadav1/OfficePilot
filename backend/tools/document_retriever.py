
import psycopg
from psycopg.rows import dict_row
from sentence_transformers import SentenceTransformer


MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def retrieve_documents(
    query: str,
    client: str = "",
    limit: int = 3,
) -> list[dict]:
    """Retrieve relevant documents using PostgreSQL and pgvector."""

    query_embedding = MODEL.encode(query)
    vector_text = "[" + ",".join(
        f"{float(value):.8f}" for value in query_embedding
    ) + "]"

    with psycopg.connect("dbname=officepilot_db") as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    client,
                    title,
                    document_type AS type,
                    content,
                    1 - (embedding <=> %s::vector) AS relevance_score
                FROM office_documents
                WHERE (%s = '' OR client = %s)
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector_text, client, client, vector_text, limit),
            )
            results = cur.fetchall()

    for result in results:
        result["relevance_score"] = round(
            float(result["relevance_score"]), 4
        )

    return [dict(result) for result in results]
