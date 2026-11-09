"""Index JSON and Markdown client documents into PostgreSQL with pgvector."""

import json
import os
from pathlib import Path

from sentence_transformers import SentenceTransformer

from backend.tools.database import connect_database


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS_FILE = PROJECT_ROOT / "backend" / "data" / "documents.json"
MARKDOWN_DIRECTORY = PROJECT_ROOT / "backend" / "data" / "test_documents"
MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)
REQUIRED_FIELDS = ("tenant_id", "client", "title", "type", "content")


def _parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse the scalar YAML-style metadata used by Markdown fixtures."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(
            f"{path}: expected YAML frontmatter starting with '---'."
        )

    try:
        closing_index = next(
            index
            for index in range(1, len(lines))
            if lines[index].strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError(
            f"{path}: YAML frontmatter has no closing '---' delimiter."
        ) from exc

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(
                f"{path}:{line_number}: expected a 'key: value' frontmatter entry."
            )
        key = key.strip()
        value = value.strip()
        if not key or key in metadata:
            raise ValueError(
                f"{path}:{line_number}: frontmatter keys must be non-empty "
                "and unique."
            )
        if value.startswith('"') and value.endswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid double-quoted value."
                ) from exc
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        metadata[key] = value

    metadata["content"] = "\n".join(lines[closing_index + 1:]).strip()
    return metadata


def _load_documents() -> tuple[list[dict[str, str]], int, int]:
    with DOCUMENTS_FILE.open("r", encoding="utf-8") as file:
        json_documents = json.load(file)
    if not isinstance(json_documents, list):
        raise ValueError(f"{DOCUMENTS_FILE}: expected a JSON array of documents.")

    markdown_files = sorted(MARKDOWN_DIRECTORY.rglob("*.md"))
    markdown_documents = [
        _parse_frontmatter(path)
        for path in markdown_files
    ]
    documents = [*json_documents, *markdown_documents]
    return documents, len(json_documents), len(markdown_documents)


def _validate_documents(
    documents: list[dict[str, str]],
    tenant_id: str,
) -> None:
    for index, document in enumerate(documents, start=1):
        if not isinstance(document, dict):
            raise ValueError(f"Document {index} must be a JSON/YAML object.")
        for field in REQUIRED_FIELDS:
            value = document.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Document {index} must have a non-empty '{field}' field."
                )
        if document["tenant_id"].strip() != tenant_id:
            raise ValueError(
                f"Document {index} tenant_id does not match "
                "OFFICEPILOT_INGEST_TENANT_ID."
            )


def main() -> None:
    tenant_id = os.getenv("OFFICEPILOT_INGEST_TENANT_ID", "").strip()
    if not tenant_id:
        raise RuntimeError(
            "Set OFFICEPILOT_INGEST_TENANT_ID before indexing documents."
        )

    documents, json_count, markdown_count = _load_documents()
    _validate_documents(documents, tenant_id)
    if not documents:
        print(
            "Loaded 0 JSON documents and 0 Markdown documents; "
            "indexed 0 documents."
        )
        return

    model = SentenceTransformer(MODEL_NAME)
    texts = [
        f"{document['title']}. {document['type']}. {document['content']}"
        for document in documents
    ]
    embeddings = model.encode(texts)
    if len(embeddings) != len(documents):
        raise RuntimeError(
            "The embedding model returned a different number of embeddings "
            "than input documents."
        )

    with connect_database() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, true);",
                (tenant_id,),
            )
            for document, embedding in zip(documents, embeddings, strict=True):
                vector_text = "[" + ",".join(
                    f"{float(value):.8f}" for value in embedding
                ) + "]"
                cur.execute(
                    """
                    INSERT INTO office_documents
                        (tenant_id, client, title, document_type, content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (tenant_id, client, title)
                    DO UPDATE SET
                        document_type = EXCLUDED.document_type,
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding;
                    """,
                    (
                        tenant_id,
                        document["client"].strip(),
                        document["title"].strip(),
                        document["type"].strip(),
                        document["content"].strip(),
                        vector_text,
                    ),
                )

    print(
        f"Loaded {json_count} JSON documents and {markdown_count} Markdown "
        f"documents; indexed {len(documents)} documents."
    )


if __name__ == "__main__":
    main()
