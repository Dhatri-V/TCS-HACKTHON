# Incident platform

Incident storage, operational dashboard, and human-approved local demo recovery.

```text
Agent / Classifier → REST → Express API → MongoDB (Mongoose)
                               ↑
                      React + Vite dashboard
```

The existing Python investigation bridge supplies incident analysis through REST. The backend persists operator decisions and spawns the private Python remediation worker. The browser never runs Docker. Only the controlled recovery endpoint can mark an incident RESOLVED after verified health.

For the rehearsal-ready startup, outage, reset, and shutdown commands, use the
repository-level [hackathon demo runbook](../DEMO.md).

## Setup

Use Node.js 22.12+ (Node 24 also supported), npm, and a reachable MongoDB deployment. Run commands from the indicated folders. No real `.env` is supplied or required; pass configuration in your shell. If you choose to use a local `.env`, it is ignored and must never be committed. Frontend variables are public browser configuration, never secrets.

### Backend

```bash
cd incident-platform/backend
npm ci
# For a local MongoDB already listening on loopback:
export MONGODB_URI='mongodb://127.0.0.1:27017/incident_platform'
npm run dev
# Or: npm start
```

| Variable          | Required / default                        |
| ----------------- | ----------------------------------------- |
| `MONGODB_URI`     | Required; local MongoDB or your Atlas URI |
| `PORT`            | `3000`                                    |
| `HOST`            | `127.0.0.1` (local only by default)       |
| `FRONTEND_ORIGIN` | `http://localhost:5173`                   |

`.env.example` contains a blank URI slot and non-secret defaults only. Startup waits for the database and unique index. Missing/unreachable MongoDB causes a generic startup error and nonzero exit without logging the URI. Runtime disconnection produces HTTP 503; `/health` actively pings MongoDB. Stop with Ctrl+C.

### MongoDB Atlas

Create an Atlas project/cluster, a database user with read/write access limited to the application database, and a network access entry for your current IP. In **Connect → Drivers**, obtain the Node.js connection URI, select `incident_platform` as the database, and substitute your database user's credentials locally. Percent-encode reserved characters in credentials. Supply the resulting URI as `MONGODB_URI` through your local environment or secret manager; never put it into source code or browser variables. The API creates the incidents collection and unique index on startup. Atlas is optional for tests.

### Frontend

In a second terminal:

```bash
cd incident-platform/frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Open `http://localhost:5173`. `VITE_API_BASE_URL` defaults to `http://localhost:3000`. To override: `VITE_API_BASE_URL=http://localhost:3001 npm run dev`. It is embedded at build time for production builds. Set `FRONTEND_ORIGIN` on the backend to the browser's exact origin if changing the frontend URL. `localhost` and `127.0.0.1` are different origins.

The dashboard fetches the incident list and selected incident from Express using browser `fetch`. It has loading, empty, API failure, missing-analysis and pending-approval states. Refresh is manual. The demo approval panel prepares a proposal and accepts authenticated approval/rejection. No normal-runtime mock data is used.

## Incident contract

Required fields: `incident_id`, `timestamp`, `service`, `log_level`, `message`, `classification` (nonempty strings). IDs use letters/numbers plus `_`, `-`, `.` and are at most 128 characters. Timestamps are ISO datetimes; timezone-free values are interpreted as UTC and responses normalize dates to UTC. List results sort newest first.

`status` defaults to `INVESTIGATING`; `analysis` defaults to `null`. Valid lifecycle states are exactly `INVESTIGATING`, `DIAGNOSED`, `PENDING_APPROVAL`, `REMEDIATING`, `VERIFYING`, `RESOLVED`, `FAILED`. Generic writes cannot claim RESOLVED or alter an incident once remediation owns it.

Analysis requires `incident_id`, `status` (`completed` or `insufficient_evidence`), `probable_root_cause` (nonempty string for completed, null for insufficient evidence), `explanation`, and arrays of strings named `remediation_steps`, `configuration_changes`, `references`, `missing_information`. The analysis ID must match the parent incident on both create and patch. Additive fields such as `grounded_claims` and `remediation_metadata` are preserved without interpreting them as approval or execution instructions. Evidence grounding remains the reasoner's responsibility. The backend does not invent a competing AI schema.

## API

Success responses are incident objects or an array for list; MongoDB `_id`/`__v` are omitted. Errors use `{"error":{"code":"...","message":"..."}}` without stack traces or connection credentials. Bodies are limited to 256 KB.

| Method | Endpoint                      | Result                                             |
| ------ | ----------------------------- | -------------------------------------------------- |
| GET    | `/health`                     | 200 healthy, 503 database unavailable              |
| GET    | `/api/incidents`              | 200 array, newest first                            |
| GET    | `/api/incidents/:id`          | 200 incident or 404                                |
| POST   | `/api/incidents`              | 201 created, 400 invalid, 409 duplicate ID         |
| PATCH  | `/api/incidents/:id/analysis` | 200 updated, 400 invalid/mismatched ID, 404 absent |
| PATCH  | `/api/incidents/:id/status`   | 200 updated, 400 invalid status, 404 absent        |

`:id` always means `incident_id`, never MongoDB `_id`. Analysis PATCH takes the analysis object directly and replaces the entire analysis, not a partial merge. It does not implicitly change lifecycle status. Unknown top-level incident/status fields are rejected.

```bash
curl -i http://localhost:3000/health

curl -i -X POST http://localhost:3000/api/incidents \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"INC-001","timestamp":"2026-09-25T10:30:00Z","service":"payment-service","log_level":"error","message":"MongoDB connection timeout","classification":"ERROR"}'

curl -i -X PATCH http://localhost:3000/api/incidents/INC-001/analysis \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"INC-001","status":"completed","probable_root_cause":"Database connection pool may be exhausted","explanation":"The service could not obtain a database connection [LOG-1].","remediation_steps":["Inspect active database connections"],"configuration_changes":[],"references":["LOG-1"],"missing_information":[]}'

curl -i -X PATCH http://localhost:3000/api/incidents/INC-001/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"PENDING_APPROVAL"}'

curl http://localhost:3000/api/incidents
curl http://localhost:3000/api/incidents/INC-001
```

## Verification

```bash
cd incident-platform/backend
npm ci
npm test
# From repository root in another terminal:
cd incident-platform/frontend
npm ci
npm run build
```

Backend tests use `mongodb-memory-server`: it downloads and starts a disposable **real MongoDB process** with a temporary database, then stops it. No Atlas credentials, application database, or pre-existing MongoDB is used. First run requires network access for the binary; dependencies/binary caches are ignored under node_modules. Supertest exercises Express over local HTTP, including persistence, unique-index conflicts, analysis compatibility, validation and database outage behavior. No AI calls occur. Build output (`dist/`), dependencies, logs, `.env` and caches are Git-ignored. Commit both package lockfiles for reproducible installs.

## Integration boundaries

The agent caller still needs to publish incidents, send its final analysis to the analysis endpoint, and publish lifecycle changes via the status endpoint. No agent/teammate modules were changed. Human decisions use the authenticated remediation endpoints below; recommendations and generic status changes never execute an action.

This is a local hackathon module, not an internet-ready authenticated service. Before production: add authentication/authorization for writers and readers, authorized lifecycle transitions, pagination, rate limits, deployment/TLS configuration and operational monitoring. CORS is browser configuration, not authentication. The existing Python approval gates are not replaced by setting a status here. The existing investigation bridge publishes real agent analysis. RAG integration remains owned by the RAG teammate.

Implementation references: [Express error handling](https://expressjs.com/en/guide/error-handling/), [Mongoose validation and unique indexes](https://mongoosejs.com/docs/validation.html), [Vite setup](https://vite.dev/guide/).


## Human-approved PostgreSQL demo recovery

Configure `REMEDIATION_OPERATOR_TOKEN` with a locally generated secret of at least 32 characters on the backend. Enter it in the dashboard password field; never put it in frontend environment variables, incident text, or source control. The operator is `demo-operator`. Run the backend with Docker access and install the reasoner dependencies in `llm-reasoner/.venv` (Python 3.11).

Only `INC-DEMO-001`, service `orders-api`, is allowed. Proposal preparation requires DIAGNOSED and an analysis. It binds the existing PostgreSQL container ID into the immutable proposal fingerprint. Live checks must find exactly one PostgreSQL container in `cloud-incident-copilot-demo`, stopped, with orders-api reporting HTTP 503/database unavailable. A reviewed approval starts this same container; it cannot recreate it, change volumes, run arbitrary commands, or restart a running database.

- GET `/api/incidents/:id/remediation`: persisted state.
- POST `/api/incidents/:id/remediation/proposal`: empty JSON object, authenticated operator; persists a fingerprint-bound BLOCKED proposal without attesting readiness.
- POST `/api/incidents/:id/remediation/readiness`: exact `action_id` and `proposal_fingerprint`, authenticated operator; verifies the bound stopped container, fixed start-only impact/runbook, rollback plan, and the exact orders-api HTTP 503 outage before persisting PENDING_APPROVAL. Safe to retry while the proposal remains BLOCKED.
- POST `/api/incidents/:id/remediation/decision`: `action_id`, `proposal_fingerprint`, `decision` (APPROVED or REJECTED), and `reviewed: true`; authenticated operator.

MongoDB atomically reserves readiness checks and the later decision/execution attempt. The readiness worker reports every check and attests only the requirements whose trusted checks pass; the backend independently verifies that the true checks, attested requirements, missing requirements, eligibility and resulting state agree. The dashboard runs readiness immediately after proposal creation and offers “Verify readiness again” for a persisted BLOCKED proposal. Rejection executes nothing. The existing Python boundary revalidates scope, live preconditions, fingerprint, and authorization. After successful start, the worker waits until MongoDB acknowledges VERIFYING before probing health. RESOLVED requires both PostgreSQL running/Docker healthy and orders-api HTTP 200 with the expected healthy service/database payload. Failures and uncertain execution attempts remain consumed across restarts; readiness checks are read-only and may be retried while BLOCKED.

The exact Python history includes an initial BLOCKED state before live readiness attestation:
`DIAGNOSED → PROPOSED → BLOCKED → PENDING_APPROVAL → APPROVED → EXECUTING → VERIFYING → RESOLVED`.
The incident API maps execution to REMEDIATING and durably exposes VERIFYING.

## Structured log ingestion (adapted from PR #6)

`llm_reasoner.log_ingestion` accepts JSON lines containing `timestamp`, `level`, `service`, and `message`, matching Winston JSON output and the existing Python orders-api logger. INFO/DEBUG/WARN/WARNING create no incidents; ERROR/CRITICAL become the existing incident schema with `log_level`, INVESTIGATING, and null analysis. Raw logs, stack traces, arbitrary metadata, and caller-supplied lifecycle/approval fields are omitted. Application messages must be sanitized at source; common credential-bearing messages are rejected, but this is not a comprehensive secret detector.

From the repository root, process a retained application log file:

```bash
PYTHONPATH=llm-reasoner llm-reasoner/.venv/bin/python -m llm_reasoner.log_ingestion < application.log
```

The producer POSTs to the existing `/api/incidents` API. `--api-base` selects the backend. Stable content-derived IDs allow safe file replay; an existing ID is accepted only if its original event fields match, without resetting analysis/status. Failed finite-input delivery exits nonzero; retain and replay the source file. `--demo` explicitly maps the known orders-api PostgreSQL error to INC-DEMO-001 and refuses to overwrite a different prior event.

For the automatic demo pipeline, start the Docker watcher before producing an outage:

```bash
cd llm-reasoner
.venv/bin/python -m llm_reasoner.log_watcher \
  --compose-file ../demo-infrastructure/compose.yaml \
  --service orders-api --api-base http://localhost:3000 --demo
```

The watcher uses `docker compose logs --follow --since <startup-time>`, so it processes new records rather than replaying container history. It reuses the strict parser/classifier and shared incident API; after a new ERROR/CRITICAL incident is persisted, it invokes the existing LangGraph investigation, local Qwen configuration, read-only Docker tools, and the local Chroma historical-incident tool. INFO/DEBUG/WARN/WARNING records never create incidents. A duplicate event never resets or repeats a completed diagnosis. Use `--once` for an integration run that exits after one incident reaches DIAGNOSED.

The watcher is a foreground local process and should be run under a process supervisor for continuous operation. Transient backend delivery failures use bounded exponential retry and then enter a local durable outbox (by default under the system temporary directory, or `INCIDENT_OUTBOX_DIR`). The outbox stores only the strict sanitized shared incident contract with owner-only permissions; it never stores API URLs, credentials, headers, raw logs or arbitrary metadata. It is replayed before the watcher opens the Docker stream, and stable IDs prevent duplicate overwrite. Invalid or tampered records are reported with a stable code and never replayed. This is a single-watcher local-demo outbox, not a distributed claim/lease queue.

PR #6 itself remains untouched. Its level rules, parsing/incident-delivery pattern, and continuous tailing behavior were adapted. Do not merge its separate Express backend, React/product UI, product MongoDB model, simulations, or external `/api/analyze` client. Its Winston logger remains a useful pattern for a future JavaScript application, but the current application is the Python orders-api and already emits the same allowlisted JSON fields to Docker stdout. Adding Winston to incident-platform would instrument the control plane rather than the monitored application and could create an incident feedback loop. Do not copy PR #6's raw-log printing or unsupported incident metadata.

## Tests

```bash
# Repository root
PYTHONDONTWRITEBYTECODE=1 llm-reasoner/.venv/bin/python -m pytest llm-reasoner/tests
# incident-platform/backend
npm test
# incident-platform/frontend
npm test
npm run build
# incident-platform/backend: opt-in REAL demo outage, requires healthy demo and local Qwen
RUN_DEMO_LIFECYCLE=1 node scripts/demo-lifecycle.mjs
```

The opt-in test idempotently indexes the curated verified history, starts the automatic Docker watcher, then uses the existing Docker demo, local Qwen and LangGraph, real application logs, the actual backend/worker, and a temporary real MongoDB database. It verifies automatic log classification, shared-schema incident persistence, automatic investigation, persisted readiness/VERIFYING, health, RESOLVED after database reconnect, and replay rejection. It submits an authenticated reviewed operator decision as test automation, not a manual browser click. It restores original PostgreSQL availability on test failure without claiming resolution. It never alters existing incident records. Frontend tests cover rendering, review gating and the decision API contract; they are not a browser interaction suite.
