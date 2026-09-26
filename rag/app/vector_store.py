from pathlib import Path
import pickle

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from .config import EMBEDDING_MODEL, INDEX_DIR


class EmbeddingModel:

    def __init__(self):
        print("Loading embedding model...")

        self.model = SentenceTransformer(EMBEDDING_MODEL)

        print("Embedding model loaded.")

    def encode(self, texts):

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True
        )

        return np.asarray(embeddings, dtype="float32")


class VectorStore:

    def __init__(self, embedding_model):

        self.embedding_model = embedding_model
        self.index = None
        self.chunks = []

    def build(self, chunks):

        self.chunks = chunks

        texts = [chunk.text for chunk in chunks]

        embeddings = self.embedding_model.encode(texts)

        dimension = embeddings.shape[1]

        print("Embedding dimension:", dimension)

        self.index = faiss.IndexFlatIP(dimension)

        self.index.add(embeddings)

        print("FAISS index built.")
        print("Vectors stored:", self.index.ntotal)

    def search(self, query, top_k=5):

        query_embedding = self.embedding_model.encode([query])

        scores, indices = self.index.search(
            query_embedding,
            top_k
        )

        results = []

        for score, index in zip(scores[0], indices[0]):

            if index == -1:
                continue

            results.append({
                "score": float(score),
                "chunk": self.chunks[index]
            })

        return results

    def save(self):

        INDEX_DIR.mkdir(parents=True, exist_ok=True)

        faiss.write_index(
            self.index,
            str(INDEX_DIR / "incidents.faiss")
        )

        with open(INDEX_DIR / "chunks.pkl", "wb") as f:
            pickle.dump(self.chunks, f)

        print("FAISS index saved.")

    def load(self):

        self.index = faiss.read_index(
            str(INDEX_DIR / "incidents.faiss")
        )

        with open(INDEX_DIR / "chunks.pkl", "rb") as f:
            self.chunks = pickle.load(f)

        print("FAISS index loaded.")
        print("Vectors stored:", self.index.ntotal)
        