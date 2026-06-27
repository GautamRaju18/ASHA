"""
Server-side audit log of each case for clinical review / history / debugging.
De-identified: stores the structured profile, retrieved citations, triage and
override, but the worker controls what free text is entered. No PII in URLs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional

from app.config import AUDIT_DB

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(AUDIT_DB)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id      TEXT PRIMARY KEY,
                session_id   TEXT,
                worker_id    TEXT,
                created_at   REAL,
                language     TEXT,
                age_group    TEXT,
                triage_category TEXT,
                refer_flag   INTEGER,
                danger_override INTEGER,
                status       TEXT,
                profile_json TEXT,
                citations_json TEXT,
                result_json  TEXT
            )
            """
        )


def log_case(case_id: str, session_id: str, worker_id: Optional[str],
             result: dict, profile: Optional[dict]) -> None:
    citations = result.get("citations", [])
    with _lock, _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO cases
               (case_id, session_id, worker_id, created_at, language, age_group,
                triage_category, refer_flag, danger_override, status,
                profile_json, citations_json, result_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                case_id,
                session_id,
                worker_id,
                time.time(),
                result.get("language"),
                (profile or {}).get("age_group"),
                result.get("triage_category"),
                1 if result.get("refer_flag") else 0,
                1 if result.get("danger_sign_override") else 0,
                result.get("status"),
                json.dumps(profile or {}, ensure_ascii=False),
                json.dumps(citations, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
            ),
        )


def list_cases(session_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    with _lock, _conn() as c:
        if session_id:
            rows = c.execute(
                "SELECT case_id, created_at, language, triage_category, refer_flag, "
                "danger_override, status FROM cases WHERE session_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT case_id, created_at, language, triage_category, refer_flag, "
                "danger_override, status FROM cases ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_case(case_id: str) -> Optional[dict]:
    with _lock, _conn() as c:
        row = c.execute("SELECT result_json FROM cases WHERE case_id=?",
                        (case_id,)).fetchone()
    if not row:
        return None
    return json.loads(row["result_json"])
