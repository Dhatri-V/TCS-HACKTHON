from app.ingestion import load_documents
from app.chunking import chunk_documents
from app.vector_store import EmbeddingModel, VectorStore
from app.retriever import Retriever


documents = load_documents("data/knowledge")

chunks = chunk_documents(documents)

embedder = EmbeddingModel()

store = VectorStore(embedder)

store.build(chunks)

retriever = Retriever(store)


query = """
Kafka authentication certificate has expired.
Consumers cannot connect to the Kafka cluster.
"""

results = retriever.retrieve(query)


print("\nRETRIEVED RESULTS")
print("=" * 50)

for result in results:

    print("Similarity:", result["score"])
    print("Source:", result["chunk"].source)
    print(result["chunk"].text)
    print("=" * 50)
