import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = "giftwatch.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            person TEXT,
            occasion TEXT,
            notes TEXT,
            currency TEXT DEFAULT 'EUR',
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS price_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT DEFAULT 'EUR',
            source TEXT,
            FOREIGN KEY(idea_id) REFERENCES ideas(id)
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER NOT NULL,
            threshold REAL NOT NULL,
            active INTEGER DEFAULT 1,
            last_triggered_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(idea_id) REFERENCES ideas(id)
        )
        """)

def add_idea(title: str, url: str, person: str = "", occasion: str = "", notes: str = "", currency: str = "EUR") -> int:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO ideas (title, url, person, occasion, notes, currency, created_at, active) VALUES (?,?,?,?,?,?,?,1)",
            (title, url, person, occasion, notes, currency, now)
        )
        return int(cur.lastrowid)

def list_ideas(active_only: bool = True) -> List[Dict[str, Any]]:
    q = "SELECT * FROM ideas"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]

def get_idea(idea_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        return dict(row) if row else None

def update_idea(idea_id: int, title: str, url: str, person: str, occasion: str, notes: str, currency: str, active: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE ideas SET title=?, url=?, person=?, occasion=?, notes=?, currency=?, active=?
            WHERE id=?
        """, (title, url, person, occasion, notes, currency, active, idea_id))

def add_price_point(idea_id: int, price: float, currency: str = "EUR", source: str = "manual"):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO price_points (idea_id, timestamp, price, currency, source) VALUES (?,?,?,?,?)",
            (idea_id, now, float(price), currency, source)
        )

def get_price_history(idea_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT timestamp, price, currency, source
            FROM price_points
            WHERE idea_id=?
            ORDER BY timestamp ASC
        """, (idea_id,)).fetchall()
        return [dict(r) for r in rows]

def get_latest_price(idea_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT timestamp, price, currency, source
            FROM price_points
            WHERE idea_id=?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (idea_id,)).fetchone()
        return dict(row) if row else None

def set_alert(idea_id: int, threshold: float, active: int = 1):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM alerts WHERE idea_id=?", (idea_id,)).fetchone()
        if existing:
            conn.execute("UPDATE alerts SET threshold=?, active=? WHERE idea_id=?", (float(threshold), active, idea_id))
        else:
            conn.execute(
                "INSERT INTO alerts (idea_id, threshold, active, created_at) VALUES (?,?,?,?)",
                (idea_id, float(threshold), active, now)
            )

def get_alert(idea_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE idea_id=?", (idea_id,)).fetchone()
        return dict(row) if row else None
