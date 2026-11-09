"""ShackBoard backend — a small task-board API for the DevOps Shack OpenShift project.

Runs on OpenShift with the Python S2I builder (gunicorn picks up wsgi.py automatically).
All settings come from environment variables, so the same image runs in every environment.
"""
import os
import socket
import time

import psycopg
from flask import Flask, jsonify, request

app = Flask(__name__)

DB = {
    "host": os.getenv("DB_HOST", "postgresql"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "shackboard"),
    "user": os.getenv("DB_USER", "shackboard"),
    "password": os.getenv("DB_PASSWORD", ""),
}
APP_VERSION = os.getenv("APP_VERSION", "v1")
STATUSES = ("todo", "doing", "done")


def connect():
    return psycopg.connect(connect_timeout=3, **DB)


def init_db(retries=20):
    """Create the table on startup. The database may still be starting, so retry."""
    for attempt in range(1, retries + 1):
        try:
            with connect() as conn, conn.cursor() as cur:
                # Several pods/workers start at once: a lock makes only one of them create and seed.
                cur.execute("SELECT pg_advisory_xact_lock(4242)")
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS tasks (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'todo',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )"""
                )
                count = cur.execute("SELECT count(*) FROM tasks").fetchone()[0]
                if count == 0:
                    cur.executemany(
                        "INSERT INTO tasks (title, status) VALUES (%s, %s)",
                        [
                            ("Create an OpenShift project", "done"),
                            ("Build the backend with Source-to-Image", "doing"),
                            ("Expose the app with a Route", "todo"),
                        ],
                    )
            app.logger.info("database ready")
            return True
        except psycopg.OperationalError as exc:
            app.logger.warning("database not ready (attempt %s): %s", attempt, exc)
            time.sleep(3)
    return False


def row_to_task(row):
    return {"id": row[0], "title": row[1], "status": row[2], "created_at": row[3].isoformat()}


@app.get("/healthz")
def healthz():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: only receive traffic when the database answers."""
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ready"}
    except psycopg.Error as exc:
        return {"status": "not ready", "error": str(exc)}, 503


@app.get("/api/info")
def info():
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        db_status = "connected"
    except psycopg.Error:
        db_status = "unreachable"
    return {"pod": socket.gethostname(), "version": APP_VERSION, "database": db_status}


@app.get("/api/tasks")
def list_tasks():
    with connect() as conn:
        rows = conn.execute("SELECT id, title, status, created_at FROM tasks ORDER BY id").fetchall()
    return jsonify([row_to_task(r) for r in rows])


@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return {"error": "title is required"}, 400
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO tasks (title) VALUES (%s) RETURNING id, title, status, created_at", (title[:200],)
        ).fetchone()
    return row_to_task(row), 201


@app.patch("/api/tasks/<int:task_id>")
def update_task(task_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in STATUSES:
        return {"error": f"status must be one of {', '.join(STATUSES)}"}, 400
    with connect() as conn:
        row = conn.execute(
            "UPDATE tasks SET status=%s WHERE id=%s RETURNING id, title, status, created_at", (status, task_id)
        ).fetchone()
    if not row:
        return {"error": "task not found"}, 404
    return row_to_task(row)


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id):
    with connect() as conn:
        deleted = conn.execute("DELETE FROM tasks WHERE id=%s", (task_id,)).rowcount
    if not deleted:
        return {"error": "task not found"}, 404
    return "", 204


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
