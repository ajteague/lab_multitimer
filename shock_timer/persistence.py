"""Durable experiment and subject storage.

SQLite is used locally and PostgreSQL is selected when a database URL is
configured.  The public functions deliberately operate on ``st.session_state``
so the UI remains a thin adapter instead of owning persistence details.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import streamlit as st

from . import state
from .settings import STATE_VERSION


def configured_database_url():
    value = os.environ.get("SHOCK_TIMER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if value:
        return str(value).strip()
    try:
        value = st.secrets.get("SHOCK_TIMER_DATABASE_URL") or st.secrets.get("DATABASE_URL")
        return str(value).strip() if value else None
    except Exception:
        return None


DATABASE_URL = configured_database_url()
DATABASE_KIND = "postgres" if DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite"
LOCAL_DATABASE_PATH = os.environ.get(
    "SHOCK_TIMER_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "shock_timer_sessions.db"),
)


def _adapt_sql(sql):
    return sql.replace("?", "%s") if DATABASE_KIND == "postgres" else sql


def _new_connection():
    if DATABASE_KIND == "postgres":
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL persistence requires psycopg. Add psycopg[binary]>=3.2,<4 to requirements.txt."
            ) from exc
        return psycopg.connect(DATABASE_URL, connect_timeout=10)

    path = Path(LOCAL_DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


@st.cache_resource(show_spinner=False)
def _db_resource():
    return {"conn": _new_connection(), "lock": threading.RLock()}


def _run_db(operation):
    resource = _db_resource()
    with resource["lock"]:
        for attempt in range(2):
            connection = resource["conn"]
            try:
                result = operation(connection)
                connection.commit()
                return result
            except Exception:
                try:
                    connection.rollback()
                except Exception:
                    pass
                if attempt == 0:
                    try:
                        connection.close()
                    except Exception:
                        pass
                    resource["conn"] = _new_connection()
                    continue
                raise


def db_execute(sql, params=()):
    def operation(connection):
        cursor = connection.cursor()
        cursor.execute(_adapt_sql(sql), params)
        return cursor.rowcount

    return _run_db(operation)


def db_execute_many(statements):
    def operation(connection):
        cursor = connection.cursor()
        for sql, params in statements:
            cursor.execute(_adapt_sql(sql), params)
        return True

    return _run_db(operation)


def db_query(sql, params=()):
    def operation(connection):
        cursor = connection.cursor()
        cursor.execute(_adapt_sql(sql), params)
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    return _run_db(operation)


@st.cache_resource(show_spinner=False)
def initialize_database():
    db_execute_many(
        [
            (
                """CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, mouse_count INTEGER NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
                    completed_at DOUBLE PRECISION
                )""",
                (),
            ),
            (
                """CREATE TABLE IF NOT EXISTS subjects (
                    experiment_id TEXT NOT NULL, mouse_index INTEGER NOT NULL,
                    state_json TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (experiment_id, mouse_index)
                )""",
                (),
            ),
            ("CREATE INDEX IF NOT EXISTS idx_experiments_updated_at ON experiments(updated_at)", ()),
        ]
    )
    try:
        db_query("SELECT completed_at FROM experiments LIMIT 1")
    except Exception:
        try:
            db_execute("ALTER TABLE experiments ADD COLUMN completed_at DOUBLE PRECISION")
        except Exception:
            pass
    return True


def default_subject_payload(i):
    return {key: state.copy_value(value) for key, value in state.mouse_defaults(i).items()}


def subject_payload(i):
    return {
        key: state.copy_value(st.session_state.get(key, value))
        for key, value in state.mouse_defaults(i).items()
    }


def load_subject_payload(i, payload):
    merged = default_subject_payload(i)
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in merged:
                merged[key] = value
    for key, value in merged.items():
        st.session_state[key] = state.copy_value(value)


def create_experiment_record(name, configured_mice):
    name = (name or "").strip()
    if not name:
        raise ValueError("Experiment name cannot be blank.")
    if not configured_mice:
        raise ValueError("At least one mouse is required.")

    experiment_id = uuid.uuid4().hex
    now = time.time()
    statements = [
        (
            "INSERT INTO experiments(id,name,mouse_count,created_at,updated_at,completed_at) VALUES(?,?,?,?,?,NULL)",
            (experiment_id, name, len(configured_mice), now, now),
        )
    ]
    for i, mouse in enumerate(configured_mice, start=1):
        payload = default_subject_payload(i)
        payload[f"subject_name_{i}"] = str(mouse["name"]).strip() or f"Mouse {i}"
        payload[f"mouse_weight_g_{i}"] = round(float(mouse["weight_g"]), 1)
        payload[f"display_order_{i}"] = i
        statements.append(
            (
                "INSERT INTO subjects(experiment_id,mouse_index,state_json,updated_at) VALUES(?,?,?,?)",
                (experiment_id, i, json.dumps(payload, separators=(",", ":")), now),
            )
        )
    db_execute_many(statements)
    return experiment_id


def list_experiment_records():
    return db_query(
        "SELECT id,name,mouse_count,created_at,updated_at,completed_at FROM experiments "
        "ORDER BY CASE WHEN completed_at IS NULL THEN 0 ELSE 1 END,updated_at DESC,created_at DESC"
    )


def get_experiment_record(experiment_id):
    rows = db_query(
        "SELECT id,name,mouse_count,created_at,updated_at,completed_at FROM experiments WHERE id=?",
        (experiment_id,),
    )
    return rows[0] if rows else None


def get_subject_records(experiment_id):
    return db_query(
        "SELECT mouse_index,state_json,updated_at FROM subjects WHERE experiment_id=? ORDER BY mouse_index",
        (experiment_id,),
    )


def load_experiment_into_session(experiment_id):
    experiment = get_experiment_record(experiment_id)
    if not experiment:
        return False
    rows = get_subject_records(experiment_id)
    st.session_state.clear()
    st.session_state.update(
        {
            "_state_version": STATE_VERSION,
            "_active_experiment_id": str(experiment_id),
            "_active_experiment_name": str(experiment["name"]),
            "_mouse_count": int(experiment["mouse_count"]),
            "_sticky_alerts": {},
            "_pending_dialog": None,
            "_needs_full_rerun": False,
            "_unsaved_subjects": [],
            "_global_undo_history": [],
            "_db_experiment_updated": float(experiment["updated_at"]),
        }
    )
    by_index = {int(row["mouse_index"]): row for row in rows}
    for i in range(1, int(experiment["mouse_count"]) + 1):
        row = by_index.get(i)
        payload = {}
        if row:
            try:
                payload = json.loads(row["state_json"])
            except Exception:
                payload = {}
            st.session_state[f"_db_subject_updated_{i}"] = float(row["updated_at"])
        load_subject_payload(i, payload)
    state.initialize_state()
    return True


def _mark_storage_failure(indices, error):
    pending = set(st.session_state.get("_unsaved_subjects", []))
    pending.update(int(i) for i in indices)
    st.session_state["_unsaved_subjects"] = sorted(pending)
    st.session_state["_storage_error"] = str(error)


def _bulk_update_subject_payloads(experiment_id, payloads, now, completed_at=None):
    items = sorted((int(i), payload) for i, payload in payloads.items())
    if not items:
        return True
    statements = [
        (
            "UPDATE subjects SET state_json=?,updated_at=? WHERE experiment_id=? AND mouse_index=?",
            (json.dumps(payload, separators=(",", ":")), now, experiment_id, i),
        )
        for i, payload in items
    ]
    if completed_at is None:
        statements.append(("UPDATE experiments SET updated_at=? WHERE id=?", (now, experiment_id)))
    else:
        statements.append(
            (
                "UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",
                (completed_at, now, experiment_id),
            )
        )
    db_execute_many(statements)
    return True


def persist_subjects(indices):
    experiment_id = st.session_state.get("_active_experiment_id")
    if not experiment_id:
        return False
    indices = sorted({int(i) for i in indices})
    now = time.time()
    payloads = {i: subject_payload(i) for i in indices}
    try:
        _bulk_update_subject_payloads(experiment_id, payloads, now)
    except Exception as error:
        _mark_storage_failure(indices, error)
        return False
    for i in indices:
        st.session_state[f"_db_subject_updated_{i}"] = now
    st.session_state["_db_experiment_updated"] = now
    pending = set(st.session_state.get("_unsaved_subjects", []))
    pending.difference_update(indices)
    st.session_state["_unsaved_subjects"] = sorted(pending)
    if not pending:
        st.session_state.pop("_storage_error", None)
    return True


def persist_subject(i):
    return persist_subjects([i])


def add_subject_to_experiment(i):
    """Insert the current session payload for a newly added subject."""
    experiment_id = st.session_state.get("_active_experiment_id")
    if not experiment_id:
        return False, "No active experiment."
    now = time.time()
    try:
        db_execute_many(
            [
                (
                    "INSERT INTO subjects(experiment_id,mouse_index,state_json,updated_at) VALUES(?,?,?,?)",
                    (experiment_id, int(i), json.dumps(subject_payload(i), separators=(",", ":")), now),
                ),
                (
                    "UPDATE experiments SET mouse_count=?,updated_at=? WHERE id=?",
                    (int(i), now, experiment_id),
                ),
            ]
        )
    except Exception as error:
        _mark_storage_failure([i], error)
        return False, str(error)
    return True, None


def retry_unsaved_subjects():
    pending = list(st.session_state.get("_unsaved_subjects", []))
    if pending:
        persist_subjects(pending)


def rename_experiment_record(experiment_id, new_name):
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    db_execute("UPDATE experiments SET name=?,updated_at=? WHERE id=?", (new_name, time.time(), experiment_id))
    return True


def delete_experiment_record(experiment_id):
    db_execute_many(
        [
            ("DELETE FROM subjects WHERE experiment_id=?", (experiment_id,)),
            ("DELETE FROM experiments WHERE id=?", (experiment_id,)),
        ]
    )


def _append_payload_event(payload, i, event_name, details, epoch):
    key = f"event_log_{i}"
    log = list(payload.get(key, []))
    log.append(
        {
            "_id": uuid.uuid4().hex,
            "Event": event_name,
            "Absolute time": state.wall_datetime(epoch).strftime("%Y-%m-%d %H:%M:%S"),
            "Details": details,
            "_epoch": float(epoch),
        }
    )
    payload[key] = log


def end_experiment_record(experiment_id):
    rows = get_subject_records(experiment_id)
    now = time.time()
    payloads = {}
    for row in rows:
        i = int(row["mouse_index"])
        try:
            payload = json.loads(row["state_json"])
        except Exception:
            payload = default_subject_payload(i)
        if not bool(payload.get(f"ended_{i}", False)):
            payload[f"ended_{i}"] = True
            payload[f"end_time_{i}"] = payload.get(f"pause_started_{i}") or now
            payload[f"paused_{i}"] = False
            payload[f"pause_started_{i}"] = None
            _append_payload_event(payload, i, "Experiment ended", "Ended from experiment management", now)
        payloads[i] = payload
    _bulk_update_subject_payloads(experiment_id, payloads, now, completed_at=now)


def maybe_mark_experiment_complete():
    if not all(state.is_ended(i) for i in range(1, state.mouse_count() + 1)):
        return
    experiment_id = st.session_state.get("_active_experiment_id")
    if experiment_id:
        now = time.time()
        db_execute(
            "UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",
            (now, now, experiment_id),
        )
