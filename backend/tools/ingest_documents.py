import json
from pathlib import Path

import psycopg
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS_FILE = PROJECT_ROOT / "backend" / "data" / "documents.json"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    with DOCUMENTS_FILE.open("r", encoding="utf-8") as file:
        documents = json.load(file)

    if not documents:
        print("No documents found.")
        return

    model = SentenceTransformer(MODEL_NAME)

    texts = [
        f"{doc['title']}. {doc['type']}. {doc['content']}"
        for doc in documents
    ]

    embeddings = model.encode(texts)

    with psycopg.connect("dbname=officepilot_db") as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_office_documents_client_title
                ON office_documents (client, title);
            """)

            for doc, embedding in zip(documents, embeddings):
                vector_text = "[" + ",".join(
                    f"{float(value):.8f}" for value in embedding
                ) + "]"

                cur.execute(
                    """
                    INSERT INTO office_documents
                        (client, title, document_type, content, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    ON CONFLICT (client, title)
                    DO UPDATE SET
                        document_type = EXCLUDED.document_type,
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding;
                    """,
                    (
                        doc["client"],
                        doc["title"],
                        doc["type"],
                        doc["content"],
                        vector_text,
                    ),
                )

    print(f"Successfully indexed {len(documents)} documents.")


if __name__ == "__main__":
    main()
