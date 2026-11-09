
import os

import pytest

from backend.tools import document_retriever
from backend.tools.document_retriever import retrieve_documents


def test_document_retrieval_is_scoped_to_the_requested_client(monkeypatch):
    rows = [
        {
            "tenant_id": "tenant-a",
            "client": "ABC Technologies",
            "title": "ABC notes",
            "type": "meeting",
            "content": "ABC-only fixture.",
            "relevance_score": 0.9,
        },
        {
            "tenant_id": "tenant-b",
            "client": "ABC Technologies",
            "title": "ABC confidential notes",
            "type": "meeting",
            "content": "Tenant B-only fixture.",
            "relevance_score": 0.95,
        },
        {
            "tenant_id": "tenant-a",
            "client": "XYZ Solutions",
            "title": "XYZ notes",
            "type": "meeting",
            "content": "XYZ-only fixture.",
            "relevance_score": 0.8,
        },
    ]

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, query, parameters):
            if "set_config('app.tenant_id'" in query:
                self.tenant_id = parameters[0]
                return
            assert "WHERE tenant_id = %s" in query
            assert "AND LOWER(client) = LOWER(%s)" in query
            self.tenant_id = parameters[1]
            self.client = parameters[2]

        def fetchall(self):
            return [
                row
                for row in rows
                if row["tenant_id"] == self.tenant_id
                and row["client"].casefold() == self.client.casefold()
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self, row_factory=None):
            return FakeCursor()

    class FakeEmbeddingModel:
        def encode(self, query):
            assert query == "deployment milestones"
            return [0.1, 0.2]

    monkeypatch.setattr(document_retriever, "_get_model", FakeEmbeddingModel)
    monkeypatch.setattr(
        document_retriever,
        "connect_database",
        FakeConnection,
    )

    results = retrieve_documents(
        query="deployment milestones",
        client="ABC Technologies",
        tenant_id="tenant-a",
    )

    assert results
    assert {document["client"] for document in results} == {"ABC Technologies"}
    assert {document["title"] for document in results} == {"ABC notes"}


def test_document_retrieval_requires_an_authenticated_tenant():
    with pytest.raises(ValueError, match="authenticated tenant ID"):
        retrieve_documents(
            query="deployment milestones",
            client="ABC Technologies",
        )


def main():
    query = "What did the client ask us to improve?"
    tenant_id = os.getenv("OFFICEPILOT_LOCAL_TENANT_ID", "").strip()
    if not tenant_id:
        raise RuntimeError("Set OFFICEPILOT_LOCAL_TENANT_ID before retrieval.")

    results = retrieve_documents(
        query=query,
        client="ABC Technologies",
        tenant_id=tenant_id,
    )

    assert results, "FAIL: No documents retrieved."

    print("\nRetrieved documents:")
    for document in results:
        print(
            f"{document['title']} | "
            f"Similarity: {document['relevance_score']}"
        )

    assert results[0]["title"] == "Previous Meeting Notes", (
        "FAIL: Expected Previous Meeting Notes to rank first."
    )

    print("\nRAG RETRIEVAL TEST PASSED")


if __name__ == "__main__":
    main()
