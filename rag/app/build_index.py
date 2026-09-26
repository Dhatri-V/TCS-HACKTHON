from .ingestion import load_documents
from .chunking import chunk_documents
from .vector_store import EmbeddingModel, VectorStore


def build_index():

    print("Loading knowledge base...")

    documents = load_documents("data/knowledge")

    print("Documents loaded:", len(documents))

    chunks = chunk_documents(documents)

    print("Chunks created:", len(chunks))

    print("Creating embedding model...")

    embedder = EmbeddingModel()

    print("Building vector store...")

    store = VectorStore(embedder)

    store.build(chunks)

    print("Saving index...")

    store.save()

    print("Index successfully built and saved.")


if __name__ == "__main__":
    build_index()
    