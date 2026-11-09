"""DevOps Shack Command Center — backend API.

A Flask API for the DevOps Shack OpenShift project. It runs on OpenShift with the
Python Source-to-Image builder (gunicorn picks up wsgi.py automatically).

Everything is configured through environment variables, so the same image runs in
every environment. The /api/chaos endpoints exist only to demonstrate how OpenShift
reacts to failures; they are switched on with CHAOS_ENABLED=true.
"""
import os
import platform
import signal
import socket
import threading
import time
from datetime import datetime, timezone

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
APP_ENV = os.getenv("APP_ENV", "dev")
CHAOS_ENABLED = os.getenv("CHAOS_ENABLED", "false").lower() == "true"
STARTED_AT = time.time()
UNREADY_FLAG = "/tmp/unready-until"  # shared by all gunicorn workers in the pod

STATUSES = ("todo", "doing", "review", "done")
PRIORITIES = ("low", "medium", "high", "critical")

SEED_TASKS = [
    ("Create the OpenShift project", "done", "high", "Aditya", "openshift"),
    ("Store DB credentials in a Secret", "done", "critical", "Priya", "security"),
    ("Build the backend with Source-to-Image", "review", "high", "Rahul", "build"),
    ("Expose the frontend with an HTTPS Route", "doing", "medium", "Aditya", "networking"),
    ("Add readiness and liveness probes", "doing", "high", "Sneha", "reliability"),
    ("Connect a GitHub webhook to the BuildConfig", "todo", "medium", "Rahul", "ci-cd"),
    ("Scale the backend to 3 replicas", "todo", "low", "Priya", "scaling"),
    ("Run the Chaos Lab and watch OpenShift self-heal", "todo", "critical", "Sneha", "chaos"),
]


def connect():
    return psycopg.connect(connect_timeout=3, **DB)


def pod_name():
    return socket.gethostname()


def init_db(retries=20):
    """Create tables and sample data. The database may still be starting, so retry."""
    for attempt in range(1, retries + 1):
        try:
            with connect() as conn, conn.cursor() as cur:
                # Several pods and workers start together: a lock lets only one of them set up the schema.
                cur.execute("SELECT pg_advisory_xact_lock(4242)")
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS tasks (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'todo',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )"""
                )
                # Columns added in v2 — safe to run on a v1 database.
                cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'medium'")
                cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee TEXT NOT NULL DEFAULT 'Unassigned'")
                cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tag TEXT NOT NULL DEFAULT 'general'")
                cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS activity (
                        id SERIAL PRIMARY KEY,
                        action TEXT NOT NULL,
                        detail TEXT NOT NULL,
                        pod TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )"""
                )
                count = cur.execute("SELECT count(*) FROM tasks").fetchone()[0]
                if count == 0:
                    cur.executemany(
                        "INSERT INTO tasks (title, status, priority, assignee, tag) VALUES (%s, %s, %s, %s, %s)",
                        SEED_TASKS,
                    )
                    cur.execute(
                        "INSERT INTO activity (action, detail, pod) VALUES (%s, %s, %s)",
                        ("setup", "Database initialised with sample sprint tasks", pod_name()),
                    )
            app.logger.info("database ready")
            return True
        except psycopg.OperationalError as exc:
            app.logger.warning("database not ready (attempt %s): %s", attempt, exc)
            time.sleep(3)
    return False


def log_activity(conn, action, detail):
    conn.execute("INSERT INTO activity (action, detail, pod) VALUES (%s, %s, %s)", (action, detail, pod_name()))


TASK_COLUMNS = "id, title, status, priority, assignee, tag, created_at, updated_at"


def row_to_task(row):
    return {
        "id": row[0],
        "title": row[1],
        "status": row[2],
        "priority": row[3],
        "assignee": row[4],
        "tag": row[5],
        "created_at": row[6].isoformat(),
        "updated_at": row[7].isoformat(),
    }


def clean(value, default, limit):
    text = str(value or "").strip()
    return text[:limit] if text else default


# ---------------------------------------------------------------- health ---

def unready_seconds_left():
    try:
        with open(UNREADY_FLAG) as f:
            return max(0, float(f.read().strip()) - time.time())
    except (OSError, ValueError):
        return 0


@app.get("/healthz")
def healthz():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: receive traffic only when the database answers (and no chaos drill is running)."""
    left = unready_seconds_left()
    if left > 0:
        return {"status": "not ready", "reason": f"chaos drill, {int(left)}s left"}, 503
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ready"}
    except psycopg.Error as exc:
        return {"status": "not ready", "error": str(exc)}, 503


@app.get("/api/info")
def info():
    db_status, latency_ms = "unreachable", None
    try:
        start = time.perf_counter()
        with connect() as conn:
            conn.execute("SELECT 1")
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        db_status = "connected"
    except psycopg.Error:
        pass
    return {
        "pod": pod_name(),
        "version": APP_VERSION,
        "environment": APP_ENV,
        "namespace": os.getenv("POD_NAMESPACE", "local"),
        "node": os.getenv("NODE_NAME", "local"),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "python": platform.python_version(),
        "database": db_status,
        "db_latency_ms": latency_ms,
        "chaos_enabled": CHAOS_ENABLED,
        "unready_seconds_left": int(unready_seconds_left()),
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# ----------------------------------------------------------------- tasks ---

@app.get("/api/tasks")
def list_tasks():
    with connect() as conn:
        rows = conn.execute(f"SELECT {TASK_COLUMNS} FROM tasks ORDER BY id").fetchall()
    return jsonify([row_to_task(r) for r in rows])


@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True) or {}
    title = clean(data.get("title"), "", 200)
    if not title:
        return {"error": "title is required"}, 400
    priority = data.get("priority", "medium")
    if priority not in PRIORITIES:
        return {"error": f"priority must be one of {', '.join(PRIORITIES)}"}, 400
    assignee = clean(data.get("assignee"), "Unassigned", 40)
    tag = clean(data.get("tag"), "general", 30).lower()
    with connect() as conn:
        row = conn.execute(
            f"INSERT INTO tasks (title, priority, assignee, tag) VALUES (%s, %s, %s, %s) RETURNING {TASK_COLUMNS}",
            (title, priority, assignee, tag),
        ).fetchone()
        log_activity(conn, "created", f'"{title}" added for {assignee}')
    return row_to_task(row), 201


@app.patch("/api/tasks/<int:task_id>")
def update_task(task_id):
    data = request.get_json(silent=True) or {}
    fields, values = [], []
    if "status" in data:
        if data["status"] not in STATUSES:
            return {"error": f"status must be one of {', '.join(STATUSES)}"}, 400
        fields.append("status=%s")
        values.append(data["status"])
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            return {"error": f"priority must be one of {', '.join(PRIORITIES)}"}, 400
        fields.append("priority=%s")
        values.append(data["priority"])
    if not fields:
        return {"error": "nothing to update (send status or priority)"}, 400
    with connect() as conn:
        row = conn.execute(
            f"UPDATE tasks SET {', '.join(fields)}, updated_at=now() WHERE id=%s RETURNING {TASK_COLUMNS}",
            (*values, task_id),
        ).fetchone()
        if not row:
            return {"error": "task not found"}, 404
        if "status" in data:
            log_activity(conn, "moved", f'"{row[1]}" moved to {data["status"]}')
        if "priority" in data:
            log_activity(conn, "priority", f'"{row[1]}" set to {data["priority"]} priority')
    return row_to_task(row)


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id):
    with connect() as conn:
        row = conn.execute("DELETE FROM tasks WHERE id=%s RETURNING title", (task_id,)).fetchone()
        if not row:
            return {"error": "task not found"}, 404
        log_activity(conn, "deleted", f'"{row[0]}" removed')
    return "", 204


@app.get("/api/stats")
def stats():
    with connect() as conn:
        by_status = dict(conn.execute("SELECT status, count(*) FROM tasks GROUP BY status").fetchall())
        by_priority = dict(conn.execute("SELECT priority, count(*) FROM tasks GROUP BY priority").fetchall())
        by_assignee = conn.execute(
            "SELECT assignee, count(*) FROM tasks GROUP BY assignee ORDER BY count(*) DESC LIMIT 6"
        ).fetchall()
        activity_today = conn.execute(
            "SELECT count(*) FROM activity WHERE created_at > now() - interval '24 hours'"
        ).fetchone()[0]
    total = sum(by_status.values())
    done = by_status.get("done", 0)
    return {
        "total": total,
        "by_status": {s: by_status.get(s, 0) for s in STATUSES},
        "by_priority": {p: by_priority.get(p, 0) for p in PRIORITIES},
        "by_assignee": [{"name": n, "count": c} for n, c in by_assignee],
        "completion": round(done * 100 / total) if total else 0,
        "activity_24h": activity_today,
    }


@app.get("/api/activity")
def activity():
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, action, detail, pod, created_at FROM activity ORDER BY id DESC LIMIT 25"
        ).fetchall()
    return jsonify(
        [{"id": r[0], "action": r[1], "detail": r[2], "pod": r[3], "created_at": r[4].isoformat()} for r in rows]
    )


# ----------------------------------------------------------------- chaos ---

def chaos_guard():
    if not CHAOS_ENABLED:
        return {"error": "Chaos Lab is disabled. Set CHAOS_ENABLED=true on the Deployment."}, 403
    return None


def record_chaos(detail):
    try:
        with connect() as conn:
            log_activity(conn, "chaos", detail)
    except psycopg.Error:
        pass


@app.post("/api/chaos/cpu")
def chaos_cpu():
    """Keep one CPU core busy for a while, so the pod's CPU graph climbs in the console."""
    if (blocked := chaos_guard()):
        return blocked
    seconds = min(max(int(request.args.get("seconds", 30)), 5), 120)

    def burn(until):
        while time.time() < until:
            sum(i * i for i in range(10_000))

    threading.Thread(target=burn, args=(time.time() + seconds,), daemon=True).start()
    record_chaos(f"CPU load started on {pod_name()} for {seconds}s")
    return {"pod": pod_name(), "message": f"Burning CPU for {seconds}s"}


@app.post("/api/chaos/unready")
def chaos_unready():
    """Fail the readiness probe for a while: OpenShift stops sending this pod traffic, but keeps it running."""
    if (blocked := chaos_guard()):
        return blocked
    seconds = min(max(int(request.args.get("seconds", 30)), 10), 120)
    with open(UNREADY_FLAG, "w") as f:
        f.write(str(time.time() + seconds))
    record_chaos(f"{pod_name()} marked not ready for {seconds}s")
    return {"pod": pod_name(), "message": f"Readiness will fail for {seconds}s"}


@app.post("/api/chaos/crash")
def chaos_crash():
    """Kill the whole container shortly after replying: OpenShift restarts it and the restart count goes up."""
    if (blocked := chaos_guard()):
        return blocked
    record_chaos(f"{pod_name()} crashed on purpose")
    under_gunicorn = "gunicorn" in request.environ.get("SERVER_SOFTWARE", "")

    def die():
        time.sleep(1)
        if under_gunicorn:
            # Under gunicorn the parent is the master process (PID 1 in the container): stopping it ends the container.
            os.kill(os.getppid(), signal.SIGINT)
        else:
            os._exit(1)

    threading.Thread(target=die, daemon=True).start()
    return {"pod": pod_name(), "message": "Crashing in 1 second. Watch the restart count."}


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
