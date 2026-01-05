from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Iterator

# Allow override via env (nützlich für Deployments)
DB_PATH = os.getenv("DB_PATH", "giftwatch.db")


def _utc_now_iso() -> str:
    # ISO8601 in UTC, Sekundenauflösung (stabil für Sortierung / Anzeige)
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    # timeout verhindert "database is locked" bei kurzen Konkurrenzzugriffen
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        # Wichtig für Datenintegrität + bessere Parallelität
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")  # 30s
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            person TEXT,
            occasion TEXT,
            notes TEXT,
            currency TEXT NOT NULL DEFAULT 'EUR',
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS price_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'EUR',
            source TEXT,
            FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER NOT NULL UNIQUE,
            threshold REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            last_triggered_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE
        );
        """)

        # Indizes für Geschwindigkeit
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_active_created ON ideas(active, created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_idea_time ON price_points(idea_id, timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_idea ON alerts(idea_id);")


def add_idea(
    title: str,
    url: str,
    person: str = "",
    occasion: str = "",
    notes: str = "",
    currency: str = "EUR"
) -> int:
    now = _utc_now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO ideas (title, url, person, occasion, notes, currency, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (title, url, person, occasion, notes, currency, now)
        )
        return int(cur.lastrowid)


def list_ideas(active_only: bool = True) -> List[Dict[str, Any]]:
    q = "SELECT * FROM ideas"
    params: tuple[Any, ...] = ()
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY created_at DESC"

    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def get_idea(idea_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (int(idea_id),)).fetchone()
        return dict(row) if row else None


def update_idea(
    idea_id: int,
    title: str,
    url: str,
    person: str,
    occasion: str,
    notes: str,
    currency: str,
    active: int
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE ideas
            SET title=?, url=?, person=?, occasion=?, notes=?, currency=?, active=?
            WHERE id=?
            """,
            (title, url, person, occasion, notes, currency, int(active), int(idea_id))
        )


def add_price_point(
    idea_id: int,
    price: float,
    currency: str = "EUR",
    source: str = "manual"
) -> None:
    now = _utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO price_points (idea_id, timestamp, price, currency, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(idea_id), now, float(price), currency, source)
        )


def get_price_history(idea_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, price, currency, source
            FROM price_points
            WHERE idea_id=?
            ORDER BY timestamp ASC
            """,
            (int(idea_id),)
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_price(idea_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT timestamp, price, currency, source
            FROM price_points
            WHERE idea_id=?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (int(idea_id),)
        ).fetchone()
        return dict(row) if row else None


def set_alert(idea_id: int, threshold: float, active: int = 1) -> None:
    now = _utc_now_iso()
    with get_conn() as conn:
        # idea_id ist UNIQUE in alerts, daher Upsert möglich
        conn.execute(
            """
            INSERT INTO alerts (idea_id, threshold, active, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(idea_id) DO UPDATE SET
                threshold=excluded.threshold,
                active=excluded.active
            """,
            (int(idea_id), float(threshold), int(active), now)
        )


def get_alert(idea_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE idea_id=?", (int(idea_id),)).fetchone()
        return dict(row) if row else None
