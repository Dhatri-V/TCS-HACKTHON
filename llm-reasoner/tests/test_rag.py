import hashlib
import json
import re
from functools import partial
from unittest.mock import patch

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from llm_reasoner.agent import Decision, investigate_incident
from llm_reasoner.rag import (
    HistoricalIncidentStore,
    load_historical_incidents,
    rag_tool_adapter,
    retrieve_similar_incidents,
)
from llm_reasoner.schemas import DiagnosisDraft
from llm_reasoner.tools import RetrievalArgs
from llm_reasoner.bridge import create_investigation_tools


class TokenEmbedding(EmbeddingFunction[Documents]):
    """Small deterministic test embedding; production uses MiniLM."""

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vector = np.zeros(256, dtype=np.float32)
            for token in re.findall(r"[a-z0-9]+", text.casefold()):
                index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:2], "big") % len(vector)
                vector[index] += 1
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm else vector)
        return vectors

    @staticmethod
    def name() -> str:
        return "test-token-embedding"

    @staticmethod
    def build_from_config(config):
        return TokenEmbedding()

    def get_config(self):
        return {}

    def default_space(self):
        return "cosine"


def store(tmp_path, *, threshold=0.75):
    return HistoricalIncidentStore(
        persist_directory=tmp_path / "chroma",
        embedding_function=TokenEmbedding(),
        max_cosine_distance=threshold,
    )


def seed(tmp_path, *, threshold=0.75):
    value = store(tmp_path, threshold=threshold)
    records = load_historical_incidents()
    assert value.index(records) == 4
    return value, records


def decision(action="finalize", **arguments):
    return json.dumps({
        "action": action,
        "arguments": arguments,
        "reason": "Resolve the remaining evidence gap",
        "information_gap": "" if action == "finalize" else
            "Which verified historical incident has the same database outage symptoms?",
    })


def draft(*numbers):
    return json.dumps({
        "evidence_numbers": list(numbers),
        "probable_root_cause": None,
        "remediation_steps": ["Inspect current service health before proposing a change."],
        "configuration_changes": [],
        "missing_information": ["Confirm the current incident cause independently."],
    })


INCIDENT = {
    "incident_id": "INC-CURRENT-001",
    "current_incident": "orders-api cannot connect to PostgreSQL",
    "logs": [{"id": "LOG-1", "text": "PostgreSQL connection failed and database is unavailable"}],
}


def test_indexing_is_eligible_only_and_idempotent(tmp_path):
    value, records = seed(tmp_path)
    assert len(records) == 6
    assert value.collection.count() == 4
    assert value.index(records) == 4
    assert value.collection.count() == 4
    stored = value.collection.get(include=["metadatas"])
    assert set(stored["ids"]) == {"HIST-DB-001", "HIST-MEM-001", "HIST-NET-001", "HIST-STORAGE-001"}
    assert all(item["status"] == "RESOLVED" and item["verification"] == "VERIFIED"
               for item in stored["metadatas"])


def test_reindex_removes_record_that_is_no_longer_eligible(tmp_path):
    value, records = seed(tmp_path)
    no_longer_resolved = records[0].model_copy(update={"status": "DIAGNOSED"})
    assert value.index([no_longer_resolved]) == 0
    assert value.collection.get(ids=[records[0].incident_id])["ids"] == []
    assert value.collection.count() == 3


def test_retrieves_verified_postgres_history(tmp_path):
    value, _ = seed(tmp_path)
    matches = retrieve_similar_incidents(
        "orders-api PostgreSQL connection failed database unavailable HTTP 503",
        top_k=3,
        service="orders-api",
        store=value,
    )
    assert [item.id for item in matches] == ["HIST-DB-001"]
    assert matches[0].text.startswith("Verified historical incident HIST-DB-001")
    assert "HTTP 200" in matches[0].text


def test_unrelated_query_is_clean_no_match(tmp_path):
    value, _ = seed(tmp_path, threshold=0.45)
    assert retrieve_similar_incidents(
        "quantum compiler optimization for satellite image rendering",
        top_k=3,
        store=value,
    ) == []
    result = rag_tool_adapter("INC-CURRENT-001", RetrievalArgs(query="unrelated quantum compiler"), store=value)
    assert result.status == "ok" and result.evidence == []


def test_langgraph_calls_real_rag_adapter(tmp_path):
    value, _ = seed(tmp_path)
    adapter = partial(rag_tool_adapter, store=value)
    tools, calls = create_investigation_tools(rag_adapter=adapter, use_docker_demo=False)
    sequence = [
        decision("retrieve_similar_incidents",
                 query="orders-api PostgreSQL connection failed database unavailable",
                 k=2, service="orders-api"),
        decision(),
        draft(1, 2),
    ]
    with patch("llm_reasoner.client.complete", side_effect=sequence):
        result = investigate_incident(INCIDENT, tools)
    assert [(call.tool, call.status) for call in calls] == [("retrieve_similar_incidents", "ok")]
    historical = [claim for claim in result.grounded_claims if claim.source == "similar_incidents"]
    assert len(historical) == 1
    assert historical[0].evidence_id.endswith(":HIST-DB-001")
    assert "Historical analogy only" in result.explanation


def test_langgraph_continues_when_rag_returns_nothing(tmp_path):
    value, _ = seed(tmp_path, threshold=0.2)
    adapter = partial(rag_tool_adapter, store=value)
    tools, calls = create_investigation_tools(rag_adapter=adapter, use_docker_demo=False)
    sequence = [
        decision("retrieve_similar_incidents", query="quantum compiler optimization", k=2),
        decision(),
        draft(1),
    ]
    with patch("llm_reasoner.client.complete", side_effect=sequence) as model:
        result = investigate_incident(INCIDENT, tools)
    second_decision_payload = json.loads(model.call_args_list[1].args[0][1]["content"])
    assert second_decision_payload["observations"][0]["status"] == "ok"
    assert second_decision_payload["observations"][0]["evidence"] == []
    assert calls[0].status == "ok"
    assert result.references == ["LOG-1"]
    assert all(claim.source != "similar_incidents" for claim in result.grounded_claims)
