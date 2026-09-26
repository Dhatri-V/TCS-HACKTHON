"""Qwen/Ollama first; Gemini fallback only on provider-call failures."""
import math
import os

from .schemas import Analysis


class ReasoningError(RuntimeError):
    """Safe integration error with a stable code (no provider payload/secrets)."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _timeout(name: str, default: str) -> float:
    try:
        value = float(os.getenv(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError:
        raise ReasoningError("invalid_timeout") from None


def complete(messages: list[dict[str, str]], *, response_schema=Analysis) -> str:
    primary_model = os.getenv("LLM_PRIMARY_MODEL", "ollama_chat/qwen2.5:3b")
    primary_timeout = _timeout("LLM_PRIMARY_TIMEOUT_SECONDS", "60")

    # Lazy import keeps provider setup out of schema/prompt consumers.
    from litellm import completion

    common = {
        "messages": messages,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "incident_analysis", "schema": response_schema.model_json_schema(),
            "strict": True,
        }},
        "num_retries": 0,
    }
    try:
        response = completion(
            model=primary_model,
            api_base=os.getenv("OLLAMA_API_BASE", "http://localhost:11434"),
            timeout=primary_timeout,
            **common,
        )
    except Exception:
        # Only inspect backup configuration when primary actually fails.
        fallback_model = os.getenv("LLM_FALLBACK_MODEL", "gemini/gemini-3.8-flash")
        fallback_timeout = _timeout("LLM_FALLBACK_TIMEOUT_SECONDS", "30")
        if fallback_model.startswith("gemini/") and not os.getenv("GEMINI_API_KEY"):
            raise ReasoningError("missing_api_key") from None
        try:
            response = completion(
                model=fallback_model,
                timeout=fallback_timeout,
                **common,
            )
        except Exception:
            raise ReasoningError("provider_error") from None

    # Malformed/truncated output is not a provider outage: do not fall back.
    # JSON/schema and evidence checks remain in the provider-independent reasoner.
    try:
        choice = response.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            raise ValueError
        return choice.message.content
    except (AttributeError, IndexError, TypeError, ValueError):
        raise ReasoningError("invalid_model_response") from None
