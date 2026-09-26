from app.ingestion import load_documents
from app.chunking import chunk_documents
from app.vector_store import EmbeddingModel, VectorStore


# 1. Load documents
documents = load_documents("data/knowledge")

# 2. Create chunks
chunks = chunk_documents(documents)

print("Chunks:", len(chunks))


# 3. Load BGE-M3
embedder = EmbeddingModel()


# 4. Create FAISS store
store = VectorStore(embedder)


# 5. Build FAISS index
store.build(chunks)


# 6. Search for a similar incident
query = """
Payment API is returning 503 errors.
Database connections are exhausted.
"""

results = store.search(query, top_k=3)


# 7. Display results
print("\nSEARCH RESULTS")
print("=" * 50)

for result in results:

    print("Similarity:", result["score"])

    print("Source:", result["chunk"].source)

    print("Text:")
    print(result["chunk"].text)

    print("=" * 50)
    