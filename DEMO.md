# Hackathon demo runbook

The demo supervisor starts the existing Docker infrastructure, Express backend,
React dashboard, and automatic Docker log watcher. It does not change the
incident, investigation, approval, remediation, or verification architecture.

## One-time setup

Use Node.js 22.12 or newer, Python 3.11, Docker Desktop, Ollama, and Qwen 2.5 3B.
Install dependencies once:

```bash
cd /path/to/TCS-HACKTHON/incident-platform/backend && npm ci
cd ../frontend && npm ci
cd ../../llm-reasoner
python3.11 -m venv .venv
.venv/bin/pip install -e . pytest
ollama pull qwen2.5:3b
```

Create ignored local configuration files from the supplied examples. Keep all
real values local. The backend file needs `MONGODB_URI` and a generated
`REMEDIATION_OPERATOR_TOKEN` of at least 32 characters. The reasoner file may use
the non-secret local Ollama defaults from its example.

## Clean start tomorrow

From the repository root:

```bash
./scripts/demo.sh reset
./scripts/demo.sh start
./scripts/demo.sh status
```

`reset` stops supervisor-owned processes, restores PostgreSQL and orders-api to a
healthy baseline, removes only the reusable `INC-DEMO-001` record while the
backend is offline, and stops the Compose services. It refuses to remove an
incident with active approval or execution. MongoDB collections and Docker
volumes are retained.

`start` verifies Docker, dependencies, MongoDB configuration, the operator token,
Ollama, backend health, frontend health, and the exact healthy orders-api JSON.
It refuses to begin if the fixed demo incident already exists or either web port
is owned by another process. Logs and PID files are kept outside the repository
under the system temporary directory.

Open <http://localhost:5173>. Trigger the live outage only after `start` reports
that the watcher is ready:

```bash
./scripts/demo.sh fail
```

The command stops only PostgreSQL, verifies the exact HTTP 503 response, and
waits for the watcher to create and investigate `INC-DEMO-001`. When it reports
`DIAGNOSED`, refresh the dashboard, enter the same operator token configured on
the backend, prepare the recovery proposal, review it, and approve it. The
backend-controlled adapter starts PostgreSQL and the incident reaches `RESOLVED`
only after the verified orders-api HTTP 200 response.

Useful commands during rehearsal:

```bash
./scripts/demo.sh status
tail -f "${TMPDIR:-/tmp}/tcs-hackathon-demo-${UID}/watcher.log"
tail -f "${TMPDIR:-/tmp}/tcs-hackathon-demo-${UID}/backend.log"
./scripts/demo.sh stop
```

`stop` retains the MongoDB record and PostgreSQL volume. Run `reset` before the
next complete presentation. RAG remains optional and is not configured or
implemented by these scripts.
