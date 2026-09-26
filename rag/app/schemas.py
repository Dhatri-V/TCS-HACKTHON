
from dataclasses import dataclass
from typing import List, Optional

from pydantic import BaseModel, Field


# --------------------------------
# RAG data structures
# --------------------------------

@dataclass
class Document:
    text: str
    source: str
    metadata: dict


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: str
    metadata: dict


# --------------------------------
# Investigation response
# --------------------------------

class RootCause(BaseModel):
    hypothesis: str = "Unknown"
    status: str = "UNVERIFIED"


class Evidence(BaseModel):
    current: List[str] = Field(default_factory=list)
    historical: List[str] = Field(default_factory=list)


class RecommendedRemediation(BaseModel):
    status: str = "WAIT_FOR_VERIFICATION"
    action: Optional[str] = None


class InvestigationResponse(BaseModel):

    incident_summary: str = "No incident summary provided."

    root_cause: RootCause = Field(
        default_factory=RootCause
    )

    evidence: Evidence = Field(
        default_factory=Evidence
    )

    historical_similarity: str = (
        "No historical similarity information provided."
    )

    verification_steps: List[str] = Field(
        default_factory=list
    )

    recommended_remediation: RecommendedRemediation = Field(
        default_factory=RecommendedRemediation
    )

    confidence: str = "LOW"


