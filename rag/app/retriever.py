from .config import TOP_K, MIN_SIMILARITY
from .vector_store import VectorStore


class Retriever:

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    def retrieve(self, query: str, top_k: int = TOP_K):

        results = self.vector_store.search(
            query,
            top_k=top_k
        )

        relevant_results = []

        for result in results:

            if result["score"] >= MIN_SIMILARITY:
                relevant_results.append(result)

        return relevant_results
    