"""Explicit, verified historical-incident retrieval for the investigation agent."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable, Literal

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.types import EmbeddingFunction
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pydantic import Field

from .schemas import Contract, Evidence
from .tools import RetrievalArgs, ToolResult


COLLECTION_NAME = "verified_historical_incidents_v1"
MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_MAX_COSINE_DISTANCE = 0.55
PACKAGE_DIR = Path(__file__).resolve().parent
DEMO_DATA_PATH = PACKAGE_DIR / "data" / "historical_incidents.json"


class HistoricalAnalysis(Contract):
    probable_root_cause: str = Field(min_length=1, max_length=2000)


class HistoricalExecution(Contract):
    service: str = Field(min_length=1, max_length=100)
    status: Literal["succeeded", "failed", "unknown"]


class HistoricalHealth(Contract):
    service: str = Field(min_length=1, max_length=100)
    status: Literal["healthy", "unhealthy", "unknown"]
    details: str = Field(min_length=1, max_length=2000)


class HistoricalRemediation(Contract):
    state: str = Field(min_length=1, max_length=100)
    execution: HistoricalExecution
    health: HistoricalHealth
    resolution_summary: str = Field(min_length=1, max_length=2000)


class HistoricalIncident(Contract):
    """Curated export shaped around the existing incident/remediation contract."""

    incident_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    timestamp: str = Field(min_length=1, max_length=64)
    service: str = Field(min_length=1, max_length=100)
    log_level: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)
    classification: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    analysis: HistoricalAnalysis
    remediation: HistoricalRemediation

    @property
    def eligible(self) -> bool:
        return (
            self.status == "RESOLVED"
            and self.remediation.state == "RESOLVED"
            and self.remediation.execution.status == "succeeded"
            and self.remediation.health.status == "healthy"
            and self.remediation.execution.service == self.remediation.health.service
        )

    def retrieval_document(self) -> str:
        # The fixed wording makes provenance and historical scope unambiguous to
        # both the embedding model and the downstream reasoning model.
        message = self.message.rstrip(". ")
        cause = self.analysis.probable_root_cause.rstrip(". ")
        resolution = self.remediation.resolution_summary.rstrip(". ")
        verification = self.remediation.health.details.rstrip(". ")
        return (
            f"Verified historical incident {self.incident_id}. "
            f"Affected service: {self.service}. "
            f"Observed symptom: {message}. "
            f"Verified historical root cause: {cause}. "
            f"Verified resolution: {resolution}. "
            f"Post-resolution verification: {verification}."
        )


def default_persist_directory() -> Path:
    configured = os.getenv("INCIDENT_RAG_PATH")
    return Path(configured).expanduser().resolve() if configured else PACKAGE_DIR.parent / ".rag" / "chroma"


def load_historical_incidents(path: str | Path = DEMO_DATA_PATH) -> list[HistoricalIncident]:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("historical_incidents_must_be_a_list")
    return [HistoricalIncident.model_validate(item) for item in raw]


class HistoricalIncidentStore:
    def __init__(
        self,
        *,
        persist_directory: str | Path | None = None,
        embedding_function: EmbeddingFunction | None = None,
        client: ClientAPI | None = None,
        max_cosine_distance: float = DEFAULT_MAX_COSINE_DISTANCE,
    ):
        if not 0 <= max_cosine_distance <= 2:
            raise ValueError("invalid_similarity_threshold")
        self.max_cosine_distance = max_cosine_distance
        self.embedding_function = embedding_function or SentenceTransformerEmbeddingFunction(
            model_name=MODEL_NAME,
            device="cpu",
            normalize_embeddings=True,
        )
        self.client = client or chromadb.PersistentClient(
            path=str(persist_directory or default_persist_directory()),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    def index(self, incidents: Iterable[HistoricalIncident | dict[str, Any]]) -> int:
        records = [item if isinstance(item, HistoricalIncident) else HistoricalIncident.model_validate(item)
                   for item in incidents]
        ineligible_ids = [item.incident_id for item in records if not item.eligible]
        if ineligible_ids:
            # Re-indexing a corrected source must not leave formerly eligible
            # records in the reusable knowledge base.
            self.collection.delete(ids=ineligible_ids)
        eligible = [item for item in records if item.eligible]
        if eligible:
            self.collection.upsert(
                ids=[item.incident_id for item in eligible],
                documents=[item.retrieval_document() for item in eligible],
                metadatas=[{
                    "incident_id": item.incident_id,
                    "service": item.service,
                    "status": item.status,
                    "verification": "VERIFIED",
                    "timestamp": item.timestamp,
                } for item in eligible],
            )
        return len(eligible)

    def retrieve_similar_incidents(
        self,
        query: str,
        *,
        top_k: int = 3,
        service: str | None = None,
        exclude_incident_id: str | None = None,
    ) -> list[Evidence]:
        args = RetrievalArgs(query=query, k=top_k, service=service)
        count = self.collection.count()
        if count == 0:
            return []
        where = {"service": args.service} if args.service else None
        requested = min(count, args.k + (1 if exclude_incident_id else 0))
        result = self.collection.query(
            query_texts=[args.query],
            n_results=requested,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        evidence: list[Evidence] = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            if not document or not metadata or distance is None or distance > self.max_cosine_distance:
                continue
            incident_id = str(metadata.get("incident_id", ""))
            if not incident_id or incident_id == exclude_incident_id:
                continue
            if metadata.get("status") != "RESOLVED" or metadata.get("verification") != "VERIFIED":
                continue
            evidence.append(Evidence(id=incident_id, text=document))
            if len(evidence) == args.k:
                break
        return evidence


_default_store: HistoricalIncidentStore | None = None


def get_default_store() -> HistoricalIncidentStore:
    global _default_store
    if _default_store is None:
        _default_store = HistoricalIncidentStore()
    return _default_store


def retrieve_similar_incidents(
    query: str,
    top_k: int = 3,
    *,
    service: str | None = None,
    store: HistoricalIncidentStore | None = None,
) -> list[Evidence]:
    """Retrieve verified historical analogies; an empty list is a valid no-match."""
    return (store or get_default_store()).retrieve_similar_incidents(
        query, top_k=top_k, service=service,
    )


def rag_tool_adapter(
    incident_id: str,
    args: RetrievalArgs,
    *,
    store: HistoricalIncidentStore | None = None,
) -> ToolResult:
    evidence = (store or get_default_store()).retrieve_similar_incidents(
        args.query,
        top_k=args.k,
        service=args.service,
        exclude_incident_id=incident_id,
    )
    return ToolResult(status="ok", evidence=evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index and query verified historical incidents.")
    parser.add_argument("operation", choices=["index-demo", "query"])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--persist-directory")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--service")
    options = parser.parse_args()
    store = HistoricalIncidentStore(persist_directory=options.persist_directory)
    if options.operation == "index-demo":
        indexed = store.index(load_historical_incidents())
        print(json.dumps({"indexed": indexed, "collection": COLLECTION_NAME}))
        return 0
    if not options.query:
        parser.error("query operation requires a query")
    matches = store.retrieve_similar_incidents(options.query, top_k=options.top_k,
                                               service=options.service)
    print(json.dumps([item.model_dump() for item in matches]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
