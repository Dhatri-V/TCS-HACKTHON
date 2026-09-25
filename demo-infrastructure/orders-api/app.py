"""Tiny local demo: database outages affect health, not the HTTP process."""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg


def log(level, message, **fields):
    print(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "service": "orders-api",
        "level": level,
        "message": message,
        **fields,
    }), flush=True)


def database_healthy():
    try:
        # libpq reads PG* settings from Compose. Never log the connection string.
        # No pool: every probe can reconnect after PostgreSQL is restarted.
        with psycopg.connect(connect_timeout=2, options="-c statement_timeout=2000") as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except psycopg.Error as error:
        log("error", "PostgreSQL connection failed", dependency="postgres",
            operation="health_check", error_type=type(error).__name__,
            sqlstate=error.sqlstate)
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.respond(404, {"error": "not_found"})
            return
        healthy = database_healthy()
        self.respond(200 if healthy else 503, {
            "service": "orders-api",
            "status": "healthy" if healthy else "unhealthy",
            "database": "healthy" if healthy else "unavailable",
        })

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Keep application stdout as structured JSON, not HTTP access-log text.
        pass


if __name__ == "__main__":
    log("info", "orders-api listening", port=8000)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
