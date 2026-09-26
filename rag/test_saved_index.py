from app.vector_store import EmbeddingModel, VectorStore
from app.retriever import Retriever
from app.pipeline import IncidentRAG


print("Loading embedding model...")

embedder = EmbeddingModel()


print("Loading saved FAISS index...")

store = VectorStore(embedder)
store.load()


print("Creating retriever...")

retriever = Retriever(store)


print("Creating RAG pipeline...")

rag = IncidentRAG(retriever)


incident = """
The payment API is experiencing intermittent failures.
Request latency is elevated and some requests are timing out.
Database connection usage is high, but connections have not
yet reached the configured maximum.
"""


print("\nInvestigating incident...")

result = rag.investigate(incident)


print("\nRETRIEVED HISTORICAL INCIDENTS")
print("=" * 60)

for item in result["retrieved_incidents"]:

    print("Source:", item["chunk"].source)
    print("Similarity:", round(item["score"], 3))
    print(item["chunk"].text)
    print("-" * 60)


print("\nQWEN INVESTIGATION")
print("=" * 60)

print(result["answer"])
