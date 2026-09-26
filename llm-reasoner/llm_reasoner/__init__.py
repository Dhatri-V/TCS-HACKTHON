from .client import ReasoningError
from .reasoner import analyze_incident
from .schemas import ReasoningRequest, ReasoningResponse

__all__ = ["analyze_incident", "ReasoningRequest", "ReasoningResponse", "ReasoningError"]


def investigate_incident(incident, tools):
    """Lazy import keeps the original diagnosis entry point independent."""
    from .agent import investigate_incident as investigate
    return investigate(incident, tools)

__all__.append("investigate_incident")
