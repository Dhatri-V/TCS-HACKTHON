# LLM reasoner

Python 3.11 investigation module: prepared incident context and agent-selected
read-only tools → LiteLLM → local Qwen2.5 3B through Ollama → validated analysis.
The historical tool uses local MiniLM embeddings and ChromaDB. Gemini remains the
backup for provider-call failures; no separate HTTP service is introduced.

## Setup

Use a separate environment for this module. From this directory:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install pytest==9.1.1
source .venv/bin/activate
python -m pytest
```

Tests use synthetic fixtures and mock every completion; no API key or real API call is needed. `tests/conftest.py` blocks socket connections during pytest collection and execution, including connections to local Ollama. They check code behavior, not real model diagnostic quality or resistance to prompt injection.

The repository specifies Python 3.11. Pydantic and LiteLLM were absent from the project; their pins record the versions resolved and tested for this module. Existing architecture pins for requests 2.32.3 and python-dotenv 1.0.1 are retained because LiteLLM also depends on them. No other team's dependency pins were changed. Tests include unittest-style cases and pytest functions. The setup above installs pytest separately because it is a test tool, not a runtime dependency. Setuptools is packaging tooling only.

## Contract and integration

```python
from llm_reasoner import analyze_incident

result = analyze_incident({
    "incident_id": "INC-101",
    "current_incident": "orders-api database connections fail",
    "logs": [{"id": "LOG-1", "text": "ECONNREFUSED db:5432"}],
    "system_context": [{"id": "CTX-1", "text": "Database is PostgreSQL"}],
    "similar_incidents": [{
        "id": "HIST-42",
        "text": "Past verified incident: database stopped; restoring it recovered connections."
    }]
})
json_payload = result.model_dump()
```

`incident_id` and `current_incident` are required nonempty strings. The three evidence lists default to empty. Each record is `{id, text}`; IDs must be unique across all lists. The Chroma adapter supplies selected historical descriptions, verified causes and outcomes in `text`. Supply timestamps, service/version and applicability details in the evidence text when available. Put facts needing citations in these lists. Send redacted context; the serialized input limit is 60,000 characters, with explicit rejection rather than silent truncation.

Output contains `incident_id`, `status`, `probable_root_cause`, `explanation`, `remediation_steps`, `configuration_changes`, `references`, `missing_information`, `grounded_claims`, and application-owned `remediation_metadata`. Steps, changes, references and missing information are lists of strings. Status is `completed` or `insufficient_evidence`; the latter requires a null cause. Configuration changes may be empty. Explanation should connect claims to IDs in references. Natural-language recommendations are never executed directly; the separate controlled workflow accepts only trusted typed proposals.

The module copies incident identity itself. Final explanations quote selected source records with application-owned references; see the grounding contract below. Source provenance does not establish source truth or prove causality.

The retrieval adapter is synchronous, like the existing Docker adapters; an async
host should run investigation outside its event loop. No separate FastAPI service
is included.

## Verified historical retrieval

The curated demo data is in `llm_reasoner/data/historical_incidents.json`. Only
records with `status=RESOLVED`, remediation `state=RESOLVED`, successful execution,
and healthy verification are indexed. Four records are eligible: PostgreSQL
connectivity, memory pressure, service/DNS connectivity, and object-storage
authorization. Two unresolved/failed examples demonstrate eligibility rejection.

Indexing is explicit and idempotent:

```sh
.venv/bin/python -m llm_reasoner.rag index-demo
.venv/bin/python -m llm_reasoner.rag query \
  'orders-api PostgreSQL connection failed database unavailable' \
  --service orders-api
```

The persistent index defaults to `.rag/chroma`, which is ignored. Set
`INCIDENT_RAG_PATH` to a different local directory when needed. Retrieval uses
`all-MiniLM-L6-v2`, cosine similarity, a no-match threshold, optional service
filtering, and at most five results. An empty match is a successful empty tool
result. Retrieved records retain `HIST-*` IDs and are labeled verified historical
incidents; downstream grounding labels them analogies rather than current proof.

The bridge registers this adapter in the existing `retrieve_similar_incidents`
tool seam. Qwen decides whether to call it and may still call logs/context tools or
finalize immediately. New resolved incidents are never automatically learned;
future additions require an explicit curated indexing operation.

## Configuration

`.env.example` documents environment variables; this module does not load it automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PRIMARY_MODEL` | `ollama_chat/qwen2.5:3b` | Local primary model via LiteLLM Ollama chat |
| `OLLAMA_API_BASE` | `http://localhost:11434` | Ollama server address |
| `LLM_PRIMARY_TIMEOUT_SECONDS` | `60` | Primary call timeout |
| `LLM_FALLBACK_MODEL` | `gemini/gemini-3.8-flash` | Backup model via LiteLLM |
| `LLM_FALLBACK_TIMEOUT_SECONDS` | `30` | Backup call timeout |
| `GEMINI_API_KEY` | unset | Required only when attempting Gemini backup |

These settings replace the earlier `LLM_MODEL` and `LLM_TIMEOUT_SECONDS` settings; the old names are no longer read. Timeout values must be finite and positive. Backup settings are checked only if the primary call fails, so local success does not require a Gemini key.

Both providers receive the same messages and requested schema: `DiagnosisDraft` for final diagnosis or `Decision` for investigation; the low-level client also retains `Analysis` as its compatibility default. LiteLLM's Ollama chat adapter maps the schema into Ollama's `format` parameter. No extra dependencies, proxy, or separate SDK were added. The primary model setting is intended for Ollama models; the backup model must support JSON-schema output and have its provider credentials configured.

## Primary and fallback behavior

1. Try Qwen through Ollama once.
2. If the completion call raises (for example, connection failure, timeout, missing model, or provider error), try Gemini once.
3. If both provider calls raise, return a clean `ReasoningError("provider_error")`.
4. If a provider returns empty/truncated output, malformed JSON, invalid schema, or invalid references, preserve the existing validation error. Do not call another provider to repair an answer.
5. A valid `insufficient_evidence` answer is returned normally, without fallback.

Missing backup credentials raise `missing_api_key`; invalid timeout configuration raises `invalid_timeout`. These are configuration errors, not model diagnoses. There are at most two provider attempts per completion request and no provider retries or answer-repair loops; investigation can make multiple completion requests. With default settings, both call timeouts together allow approximately 90 seconds plus processing overhead.

Fallback sends the same prepared incident context to Gemini's external API when the local call fails. Callers should supply context suitable for that configured backup. Local Qwen smoke tests with synthetic incidents and mock read-only adapters have been performed, including dynamic tool choices, an independent finalization in one run, and deterministic grounding in the final run. Other runs reached guards or validation failures; the final run exhausted the tool budget and returned insufficient_evidence after preserving an unsupported hypothesis as unverified. No live Gemini validation or real infrastructure integration is claimed. The automated suite remains fully mocked/offline.

## Failure handling

Invalid caller inputs raise Pydantic `ValidationError`. Technical failures raise `ReasoningError`; read its `code`: `context_too_large`, `missing_api_key`, `invalid_timeout`, `provider_error`, `invalid_model_response`, `unknown_reference`, `missing_references`, `unattributed_references`, or `invalid_agent_decision`. The backend decides how these map to HTTP/job errors. Provider exception payloads are not exposed by this module. A valid insufficient-evidence result is not a technical failure.

Mocked tests cover primary success, fallback success, both providers failing, and configuration errors. They also cover truncated output, bad JSON, unknown citations and contradictory status. The prompt treats supplied text as untrusted evidence, separates historical analogy from proof, and requests uncertainty and diagnostic checks rather than fabricated fixes.

## Issue #4: bounded investigation agent

`investigate_incident(incident, tools)` adds a LangGraph decide → execute_tool →
decide loop, followed by the existing `analyze_incident()` finalizer. The original diagnosis entry point remains available; the current output includes
grounded claims and application-owned safety assessments, described below.
RAG is optional; zero-tool finalization is supported. Three executions maximum;
repeated identical validated requests finalize without executing again. Invalid
or unregistered tool decisions raise `invalid_agent_decision` before dispatch.

Pass a dictionary of adapter callables keyed by `get_logs`, `get_incident_context`,
and/or `retrieve_similar_incidents`. Each callable receives `(incident_id, args)`;
identity comes from the trusted request, not the model. `args` is the validated
Pydantic class in tools.py. Return a ToolResult or matching dictionary:
`{"status": "ok", "evidence": [{"id": "source-id", "text": "verified observation"}]}`.
Non-success statuses are `unavailable` or `error` and must have no evidence. The
bridge supplies the existing Docker adapters and verified Chroma adapter; tests
may inject alternate adapters.

The state holds incident evidence, tool observations, call signatures, pending
decision, stop reason, and final response. Tool evidence IDs are namespaced by
execution and tool; original source IDs remain as their suffix. Results are
limited to 100 records and 12,000 serialized characters. Decision context is
limited to 60,000 characters. Errors are sanitized, shown to the decision node,
and excluded from final factual evidence. Investigation limitations are appended
to missing_information. Existing citation validation checks the accumulated IDs.

Assumptions: adapters are trusted read-only Python callables scoped to the supplied
incident and must enforce their own I/O deadlines. The graph bounds execution
count, not a hung synchronous adapter's wall-clock duration. No persistent state,
HTTP endpoint or teammate service is implemented in the investigator. The separate
controlled remediation interfaces below are tested with fake adapters only. Native model
function-calling is not required: LiteLLM requests a validated Decision schema.
The existing Qwen/Gemini provider policy applies to both decision and diagnosis.

LangGraph 0.2.76 was resolved with langchain-core 0.3.86, compatible with the root
README's LangChain 0.3.14 core range. The explicit core bound preserves that
compatibility on future installs; it is a LangGraph transitive dependency, not
an added retrieval stack. This requires packaging 25.0 in place of 26.3.
No application dependency pins were upgraded and the existing .venv was reused.
Tests use scripted decisions and stub adapters. Local Qwen smoke testing is not
a comprehensive model-quality evaluation or evidence of production readiness.


## Investigation hardening

Tool queries are plain-language evidence descriptions, never executable queries.
`get_logs` accepts `query` (1–500 characters) and `limit` (integer 1–100,
default 20). Recognizable SQL/code/command syntax is rejected; this heuristic is
not a sandbox. Adapters must never execute model-supplied text as code or SQL.
Incident identity is always supplied separately by trusted application code.

`get_incident_context.fields` accepts only these categories:

| Field | Supported information |
| --- | --- |
| `service_health` | Service/container status, health checks and listeners |
| `storage` | Capacity, filesystem usage and storage health |
| `network` | DNS resolution, connectivity and network status |
| `configuration` | Relevant redacted service/connection configuration |
| `recent_changes` | Known deployments and configuration/infrastructure changes |

A successful nonempty context response means all requested categories were
answered (explicitly unknown facts may be reported as unknown). An adapter that
cannot satisfy the request should return unavailable/error, not silently return
partial coverage. Successful categories are tracked for this investigation:
repeated subsets finalize; overlapping requests fetch only new categories.
Empty/failed results do not mark categories collected. Exact repeat protection
still applies; case/whitespace-only query changes are also duplicates. Distinct
queries and new categories remain allowed; arbitrary semantic paraphrases are
not classified by a second model. This is a bounded snapshot investigation,
not polling for changing state.

`retrieve_similar_incidents` accepts `query` (plain language), `k` (integer 1–5,
default 3) and `service` (optional known service name, at most 100 characters).
The previous retrieval `limit` argument is rejected. No database syntax is
exposed in these contracts.

The decision prompt explicitly asks the model to finalize when a grounded
probable diagnosis is supported, even if budget remains. The three-call budget
remains a fallback. Observations include executed arguments and the decision
payload includes collected context fields.

Legacy free-form model responses retain their original citation checks, including
`unattributed_references`. The preferred numbered-catalog path constructs citations
in application code, as described below.

Recommendation guidance prioritizes inspection. State/data changes require
specific safeguards, operator approval, impact assessment, backups/rollback
where relevant and verification. Casual database-data deletion is prohibited
by the prompt. This prompt guidance does not grant execution permission. The separate controlled
workflow below requires application readiness checks and explicit human approval.

### Decision gaps and recommendation metadata

Each model tool decision now requires `information_gap`: a specific unanswered
question that could materially change the diagnosis (10–500 characters).
`finalize` uses an empty string. All decision fields are required in the model schema. Action-specific JSON-schema branches constrain tool arguments and require a nonempty gap for tools, or empty arguments/gap for finalize. Invalid decisions are rejected before dispatch; the budget
and redundancy guards remain. Prompt guidance distinguishes a grounded probable
diagnosis from exhaustive certainty. Validation checks shape, not whether the
model's stated gap is genuinely material.

Preferred explanation format is a factual claim followed immediately by an exact
bracketed evidence ID, e.g. `Connection was refused [LOG-1].` References must match
the IDs used in the explanation. Unknown bracketed IDs are rejected. Existing
unbracketed inline citations remain accepted for compatibility; references-only
answers are still rejected. This does not prove semantic support of each claim.

### Deterministic grounding and safety assessment

The final model call now requests `DiagnosisDraft`: `evidence_numbers`,
`probable_root_cause`, `remediation_steps`, `configuration_changes`, and
`missing_information`. This is an internal provider format; the investigation
Decision schema/graph and tool adapters are unchanged. The model receives a
compact numbered catalog with source category and full text, without source IDs.
The application maintains the request-local number-to-ID map. Integers must be
strict positive integers in that catalog; booleans, numeric strings and unknown
numbers are rejected. There is no fuzzy matching or correction of invented IDs.

For selected records, application code copies the ENTIRE source text into
`grounded_claims` and a quoted explanation, inserts exact original IDs, and builds
`references` in matching order. Duplicated selections are collapsed, and historical
records are explicitly labeled analogies. Model-authored explanatory prose is not
accepted as factual output. This prevents negation loss, wrong-source attribution,
and fabricated claims being attached to real IDs. It establishes provenance only:
source records may themselves be wrong, stale or malicious and remain untrusted.

A proposed cause is retained only when it exactly equals a selected full current
record; it is labeled a reported diagnostic observation, not independently proven
causality. Other hypotheses are retained in `missing_information` as unverified,
with null `probable_root_cause` and `insufficient_evidence`. This conservative
tradeoff intentionally favors grounded observations over fluent unsupported
causal conclusions. Model-suggested missing information is also labeled unverified.

For compatibility, legacy `Analysis` JSON is still parsed with ALL previous
schema, risk-metadata and citation checks before extraction. Legacy explanation
prose is moved to unverified missing information; only original selected source
records become final factual claims. Recognizable invented citations in proposals
are also rejected. Legacy responses with missing required change metadata can
still fail; the new draft path does not request or trust model safety metadata.

The external response preserves incident_id, status, probable_root_cause,
explanation, remediation_steps, configuration_changes, references and
missing_information. It adds `grounded_claims`, and changes `remediation_metadata`
to APPLICATION-OWNED assessments. Each assessment contains source/index,
action_type, required_preconditions, required_safeguards, missing_requirements,
approval_eligible and executable. Text lists remain proposals, never trusted facts
or actions. Consumers of the earlier metadata structure must update accordingly.

Every proposal gets a deterministic conservative classification. Obvious mixed
change/delete steps receive the higher risk; unfamiliar text is treated as
state-changing. Configuration suggestions are at least state-changing. The model
cannot supply a safety label, assert that a backup exists, or clear requirements.
Application code specifies target/scope and operator-review requirements; changes
also require impact, rollback and verification plans; destructive proposals add
backup/restore and data-scope/retention checks.

All assessments currently have approval_eligible=false and executable=false,
including inspections: the diagnosis path does not accept trusted operational
scope/safeguard attestations. Missing safety information does not discard a grounded
diagnosis, but these text proposals cannot enter approval directly. Trusted
application code must create a separate scoped ActionProposal and complete the
controlled workflow readiness checks described below. These text classifications are conservative
triage, not a natural-language execution sandbox. The diagnosis output never grants approval or execution. Typed application
proposals enter the separate workflow below; model text does not enter an executor.


## Human approval and controlled remediation (local interfaces only)

New modules are `remediation_contracts.py`, `remediation.py` and
`remediation_workflow.py`. Existing agent/reasoner/grounding contracts are unchanged.
The diagnosis continues to return non-executable, approval-ineligible natural-language
recommendations. Trusted application code must separately create an `ActionProposal`;
there is no automatic conversion of model prose into an operation.

### Lifecycle

```text
DIAGNOSED -> PROPOSED -> readiness validation
                          | missing -> BLOCKED
                          | satisfied -> PENDING_APPROVAL
                                           | REJECTED -> stop
                                           | APPROVED -> execution boundary
                                                          | failed/unknown -> FAILED
                                                          | succeeded -> VERIFYING
                                                                           | healthy -> RESOLVED
                                                                           | unhealthy/unknown
                                                                           v
                                                           budget available -> REINVESTIGATING
                                                                                -> DIAGNOSED
                                                                                -> NEW proposal + approval
                                                           budget exhausted -> FAILED
```

The default budget is one re-investigation; an integer 0–3 is accepted. At most
budget+1 action attempts occur through a workflow. Execution failure/unknown
outcome stops immediately; only successful execution followed by unhealthy or
unknown health can enter re-investigation. Missing/failing re-investigation also
stops with FAILED. The model cannot mark a workflow RESOLVED. Only the health
adapter result for the exact target service can do so.

### Explicit, allowlisted operations

- `restart_service(service)` takes no additional parameters.
- `rollback_deployment(service, version)` requires an exact allowed version.
- `apply_allowed_config_change(service, change)` receives a typed ConfigChange
  with one key/value pair matching an exact service-specific allowlist.
- `check_service_health(service)` returns HealthResult with matching service and
  status healthy/unhealthy/unknown.

Registry entries are trusted Python callables, not model-generated implementations.
No shell/code/command operation exists. Extra arguments and command-bearing service,
version or config values are rejected. Values are never evaluated. Adapters receive
only the validated service and operation-specific typed arguments; descriptions,
model prose and approval flags are never forwarded as executable inputs.

ActionProposal contains action_id, incident_id, action_type, service, parameters
and description. RemediationAction snapshots add approval_required (always true),
approval_status, approval_eligible, executable, missing_requirements and a SHA-256
proposal fingerprint. Action IDs cannot be reused in the same boundary. Snapshots
and caller dictionaries do not control stored approval/eligibility flags.

### Trusted application entry points

1. Construct ControlledRegistry with ServiceScope policies, registered operation
   adapters and a health adapter. Construct ExecutionBoundary with an explicit
   authorized-operator allowlist. None are registered with the LLM agent.
2. Construct RemediationWorkflow with the incident, validated diagnosis and boundary.
   Supply `reinvestigate=lambda context: investigate_incident(context, read_only_tools)`
   to reuse the existing agent. No changes to its dynamic decisions are required.
3. Call `workflow.propose(ActionProposal(...))`. Initially it is BLOCKED because
   readiness requirements have not been attested.
4. After trusted checks, application code calls
   `boundary.attest_readiness(action_id, actor=authenticated_operator,
   satisfied_requirements=verified_requirement_names)` and
   `workflow.refresh_eligibility()`. Do NOT populate these from LLM text.
5. Present the exact immutable proposal snapshot/fingerprint to the human. Only
   their explicit decision may call `workflow.decide(HumanDecision(...))` with
   APPROVED or REJECTED. Missing/pending decisions never count as approval.
6. Call `workflow.execute_approved()`. The boundary independently revalidates the
   operation, arguments, target scope, readiness, approval fingerprint and all
   execution flags. It reserves the action ID before dispatch and returns a
   structured ExecutionResult. A successful adapter result triggers actual health
   verification. A new proposal after re-investigation starts without approval.

Readiness requirements are application policy: target scope, impact, rollback plan
and health verification readiness for every action; version compatibility and
backup/restore readiness for rollback; configuration review and backup/restore
readiness for config changes. These are trusted attestations of performed checks,
not proofs generated from language. Updating readiness invalidates approval.
Rejection closes the action. Suspending an action or disabling a service blocks
execution even after approval. Revocation cannot cancel an already-dispatched
adapter call.

### Safety, testing and production limits

`tests/test_remediation.py` uses only fake Python adapters and mocked model calls.
It covers the complete lifecycle, no/missing/rejected approvals, ineligible and
suspended actions, bad arguments, command injection attempts, unknown actions,
service/version/config scope, stale approvals, failures, malformed health/results,
bounded retries, fresh approval per retry, snapshot mutation, and concurrent
at-most-once dispatch. One integration test reuses the actual LangGraph graph with
mocked completions. No Docker/cloud/network remediation is connected or tested. The sibling
`demo-infrastructure/` project was separately verified manually for a database
outage and recovery; it is not connected to these adapters.

All state, approval records, readiness attestations and execution reservations are
in memory. Locks prevent concurrent duplicate dispatch within this process, and
failed/unknown attempts cannot be replayed with the same action ID. This is NOT
crash-safe or distributed exactly-once execution. Production still needs durable
transactional state/idempotency, recoverable audit/event history, authenticated
human UI/API identity (the actor string here assumes a trusted caller), authorization
and tenant scope, real readiness checks, real controlled adapters, adapter I/O
and health timeouts, outcome reconciliation, cancellation/expiry policies and
infrastructure integration tests. Synchronous adapters must enforce their own
time limits; a bounded loop does not interrupt a hung external call.


## Repository scope

The root README and architecture image describe the intended full Copilot system,
not a claim that every service is implemented. This module implements reasoning,
read-only investigation interfaces, grounding, and an in-memory human-gated
remediation workflow. Production service adapters, authenticated approval UI/API,
durable execution state, classifier, retrieval implementation, frontend and
MongoDB integration are not supplied here. The isolated Docker demo is separate.
