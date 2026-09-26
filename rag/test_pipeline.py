from app.ingestion import load_documents
from app.chunking import chunk_documents
from app.vector_store import EmbeddingModel, VectorStore
from app.retriever import Retriever
from app.pipeline import IncidentRAG


# 1. Load historical knowledge
documents = load_documents("data/knowledge")

print("Documents loaded:", len(documents))


# 2. Chunk documents
chunks = chunk_documents(documents)

print("Chunks created:", len(chunks))


# 3. Create embedding model
embedder = EmbeddingModel()


# 4. Build vector store
store = VectorStore(embedder)

store.build(chunks)


# 5. Create retriever
retriever = Retriever(store)


# 6. Create RAG pipeline
rag = IncidentRAG(retriever)


# 7. New incoming incident
incident = """
The payment API is experiencing intermittent failures.
Request latency is elevated and some requests are timing out.
Database connection usage is high, but connections have not
yet reached the configured maximum.
"""


# 8. Investigate
result = rag.investigate(incident)


# 9. Display retrieved historical incidents
print("\nRETRIEVED HISTORICAL INCIDENTS")
print("=" * 60)

for item in result["retrieved_incidents"]:

    print("Source:", item["chunk"].source)
    print("Similarity:", round(item["score"], 3))
    print(item["chunk"].text)
    print("-" * 60)


# 10. Display Qwen investigation
print("\nQWEN INVESTIGATION")
print("=" * 60)

print(result["answer"])
