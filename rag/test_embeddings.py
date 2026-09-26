from app.ingestion import load_documents
from app.chunking import chunk_documents
from app.vector_store import EmbeddingModel


documents = load_documents("data/knowledge")

chunks = chunk_documents(documents)

print("Chunks:", len(chunks))

texts = [chunk.text for chunk in chunks]

embedder = EmbeddingModel()

embeddings = embedder.encode(texts)

print("Embedding shape:", embeddings.shape)
print("First embedding:")
print(embeddings[0])
