
import json

from .config import TOP_K
from .llm import LLM
from .schemas import InvestigationResponse


class IncidentRAG:

    def __init__(self, retriever):
        self.retriever = retriever
        self.llm = LLM()

    def investigate(self, incident: str):

        # --------------------------------
        # 1. Retrieve historical incidents
        # --------------------------------

        results = self.retriever.retrieve(
            incident,
            top_k=TOP_K
        )

        if results:
            historical_context = ""

            for i, result in enumerate(results, start=1):
                chunk = result["chunk"]

                historical_context += f"""
Historical Incident {i}
Source: {chunk.source}
Similarity: {result["score"]:.3f}

{chunk.text}

--------------------------------
"""

            historical_match_found = True

        else:
            historical_context = """
NO RELIABLE HISTORICAL INCIDENT WAS FOUND.

Do not invent or assume a historical precedent.
"""

            historical_match_found = False

        # --------------------------------
        # 2. Build investigation prompt
        # --------------------------------

        prompt = f"""
You are an AI Incident Investigator.

Investigate the CURRENT INCIDENT using only the information
provided below.

IMPORTANT GROUNDING RULES:

1. CURRENT INCIDENT FACTS are statements explicitly present
   in the current incident.

2. HISTORICAL EVIDENCE comes only from the retrieved
   historical incidents.

3. A ROOT CAUSE is a HYPOTHESIS unless directly established
   by the current incident evidence.

4. Never claim that monitoring, logs, metrics, traces,
   dashboards, or databases confirmed something unless that
   evidence is explicitly provided.

5. Never invent facts, metrics, timestamps, services,
   infrastructure, or previous incidents.

6. Historical similarity does NOT prove that the current
   incident has the same root cause.

7. Verification steps must describe what an engineer should
   check to validate the hypothesis.

8. Remediation is only a recommendation.
   Do not claim that any fix was executed.

9. NEVER recommend a specific infrastructure action solely
   because a historical incident used that action.

10. If the root cause is only a hypothesis, remediation must
    first prioritize verification.

11. Only recommend a specific remediation when the CURRENT
    INCIDENT evidence supports that action.

12. Historical resolutions may be mentioned as possible
    approaches, but clearly label them as historical actions.

13. Do not recommend restarting pods, changing resource
    limits, increasing connection pools, modifying databases,
    changing configuration, or executing commands unless the
    current evidence supports that action.

14. If evidence is insufficient for a specific remediation,
    say that remediation should wait for verification.

15. Do not generate numerical confidence percentages.

16. Confidence must be exactly one of:

    LOW
    MEDIUM
    HIGH

17. The root-cause status must be exactly one of:

    UNVERIFIED
    VERIFIED

18. The remediation status must be exactly one of:

    WAIT_FOR_VERIFICATION
    RECOMMENDED
    NOT_APPLICABLE

IMPORTANT:

Return ONLY valid JSON.

Do not use Markdown.
Do not use ```json.
Do not add explanations before or after the JSON.

The JSON must follow EXACTLY this structure:

{{
    "incident_summary": "string",

    "root_cause": {{
        "hypothesis": "string",
        "status": "UNVERIFIED"
    }},

    "evidence": {{
        "current": [
            "string"
        ],
        "historical": [
            "string"
        ]
    }},

    "historical_similarity": "string",

    "verification_steps": [
        "string"
    ],

    "recommended_remediation": {{
        "status": "WAIT_FOR_VERIFICATION",
        "action": null
    }},

    "confidence": "MEDIUM"
}}

CURRENT INCIDENT:

{incident}

HISTORICAL EVIDENCE:

{historical_context}
"""

        # --------------------------------
        # 3. Ask Qwen for JSON
        # --------------------------------

        raw_answer = self.llm.generate(prompt)

        # Print raw response for debugging
        print("\n--- RAW QWEN RESPONSE ---")
        print(raw_answer)
        print("--- END RAW RESPONSE ---\n")

        # --------------------------------
        # 4. Parse JSON
        # --------------------------------

        try:
            parsed_answer = json.loads(raw_answer)

        except json.JSONDecodeError as e:
            raise ValueError(
                f"Qwen returned invalid JSON: {e}"
            )

        # --------------------------------
        # 5. Validate JSON with Pydantic
        # --------------------------------

        try:
            investigation = InvestigationResponse.model_validate(
                parsed_answer
            )

        except Exception as e:
            raise ValueError(
                f"Qwen JSON failed schema validation: {e}"
            )

        # --------------------------------
        # 6. Return structured result
        # --------------------------------

        return {
            "investigation": investigation.model_dump(),
            "historical_match_found": historical_match_found,
            "retrieved_incidents": results
        }


