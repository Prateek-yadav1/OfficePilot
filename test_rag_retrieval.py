
from backend.tools.document_retriever import retrieve_documents


def main():
    query = "What did the client ask us to improve?"

    results = retrieve_documents(
        query=query,
        client="ABC Technologies",
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
