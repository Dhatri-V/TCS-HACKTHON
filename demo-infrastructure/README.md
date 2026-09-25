# Local breakable orders demo

An isolated Docker Compose project: `orders-api -> PostgreSQL`.
It does not import or modify any Copilot module, and has no automated remediation.
Requires Docker with Compose and a running Docker daemon.

The API is exposed only on **127.0.0.1:18080** (container port 8000).
PostgreSQL uses port **5432 inside the Compose network only**; it has no host port.
The hardcoded `demo` / `demo-local-only` credentials are disposable local-demo
values, not production credentials. No `.env` file is needed or loaded explicitly.

Run all commands from this directory:

```sh
cd demo-infrastructure
docker compose up -d
docker compose ps
curl -i http://localhost:18080/health
docker compose logs orders-api
```

On the first start, Compose builds the API image and waits for PostgreSQL's health
check. Allow a few seconds for the API to start. Expected HTTP **200** body:

```json
{"service": "orders-api", "status": "healthy", "database": "healthy"}
```

## Cause a database outage

```sh
docker compose stop postgres
curl -i http://localhost:18080/health
docker compose logs --tail=10 orders-api
docker compose ps -a
```

Expected HTTP **503** body:

```json
{"service": "orders-api", "status": "unhealthy", "database": "unavailable"}
```

The API process remains running. Its own Docker health check also probes `/health`
every five seconds, so the outage produces error logs without a manual request.
Docker may mark the API container `unhealthy`; that does not stop/restart it.
Each failed probe writes one JSON line, for example:

```json
{"timestamp":"2026-09-25T12:00:00.000+00:00","service":"orders-api","level":"error","message":"PostgreSQL connection failed","dependency":"postgres","operation":"health_check","error_type":"OperationalError","sqlstate":null}
```

Connection credentials and raw provider exception strings are not logged.

## Recover manually

```sh
docker compose start postgres
docker compose ps
curl -i http://localhost:18080/health
```

Retry the curl after a few seconds while PostgreSQL starts. Expected response is
HTTP **200** with the original healthy JSON. No API restart is required: every
health request opens a fresh connection and runs `SELECT 1` with timeouts.

## Pause the demo

```sh
docker compose stop
```

This stops only this Compose project and retains its containers and named volume.
Use `docker compose up -d` to resume. No cleanup or volume-deletion command is
needed for the outage/recovery exercise. The project name is
`cloud-incident-copilot-demo`; do not change it while operating the demo.

The demo intentionally contains no classifier, RAG, frontend, MongoDB, cloud
logging integration, approval UI or agent/remediation connection.
