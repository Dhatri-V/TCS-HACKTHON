"""Read-only tool contracts. Real services are supplied by teammates."""
import re
from typing import Callable, Literal
from pydantic import Field, field_validator, model_validator
from .schemas import Contract, Evidence

class SearchArgs(Contract):
    query: str = Field(min_length=1, max_length=500, description="Natural-language description of evidence to find. No SQL, code, commands or database syntax.")

    @field_validator('query')
    @classmethod
    def natural_language(cls, value):
        # Reject recognizable executable/query syntax, not technical log terms.
        # This is an input guard, not a security boundary: adapters never execute query.
        if re.search(r"\bselect\b[\s\S]*\bfrom\b|\b(?:delete\s+from|insert\s+into|update\s+\w+\s+set|drop\s+table)\b|```|[;{}]|\$\(|\b(?:sudo|curl)\s|\b(?:def|import)\s|\b(?:print|exec|eval)\s*\(|(?:^|\s)(?:rm|grep|cat)\s+-", value, re.I):
            raise ValueError('Use a natural-language search description, not SQL or code')
        return value

class LogsArgs(SearchArgs):
    limit: int = Field(default=20, ge=1, le=100, strict=True)

ContextField = Literal['service_health', 'storage', 'network', 'configuration', 'recent_changes']

class ContextArgs(Contract):
    fields: list[ContextField] = Field(min_length=1, max_length=5, description="Supported context categories only: service_health, storage, network, configuration, recent_changes.")

    @field_validator('fields')
    @classmethod
    def canonical_fields(cls, value):
        return sorted(set(value))

class RetrievalArgs(SearchArgs):
    k: int = Field(default=3, ge=1, le=5, strict=True)
    service: str | None = Field(default=None, min_length=1, max_length=100, description="Optional known service name from incident evidence.")

ARGUMENTS = {"get_logs": LogsArgs, "get_incident_context": ContextArgs,
             "retrieve_similar_incidents": RetrievalArgs}

class ToolResult(Contract):
    status: Literal["ok", "unavailable", "error"]
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.status != "ok" and self.evidence:
            raise ValueError("Failed tools cannot supply evidence")
        ids = [e.id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate evidence IDs")
        return self

# Adapters receive trusted incident identity and validated tool-specific arguments.
ToolAdapter = Callable[[str, Contract], ToolResult | dict]
ToolRegistry = dict[str, ToolAdapter]
