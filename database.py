"""
database.py — Постоянная память агента (SQLite)
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "drivevostoka.db"


def migrate_db():
    new_columns = [
        ("client_profiles", "goal",         "TEXT"),
        ("client_profiles", "budget_label", "TEXT"),
    ]
    with get_conn() as conn:
        for table, col, col_type in new_columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except Exception:
                pass


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                chat_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS client_profiles (
                chat_id         INTEGER PRIMARY KEY,
                budget_rub      REAL,
                budget_label    TEXT,
                city            TEXT,
                preferred_maker TEXT,
                preferred_model TEXT,
                body_type       TEXT,
                max_mileage     INTEGER,
                year_from       INTEGER,
                engine_type     TEXT,
                goal            TEXT,
                notes           TEXT,
                FOREIGN KEY (chat_id) REFERENCES clients(chat_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER,
                role        TEXT,
                content     TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (chat_id) REFERENCES clients(chat_id)
            );

            CREATE TABLE IF NOT EXISTS leads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER,
                name        TEXT,
                phone       TEXT,
                car_choice  TEXT,
                budget_rub  REAL,
                city        TEXT,
                status      TEXT DEFAULT 'new',
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (chat_id) REFERENCES clients(chat_id)
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER,
                maker           TEXT,
                model           TEXT,
                budget_rub      REAL,
                city            TEXT,
                active          INTEGER DEFAULT 1,
                last_checked    TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (chat_id) REFERENCES clients(chat_id)
            );
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_client(chat_id: int, username: str = "", first_name: str = ""):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO clients (chat_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                updated_at = datetime('now')
        """, (chat_id, username, first_name))


def save_profile(chat_id: int, **kwargs):
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [chat_id]
    with get_conn() as conn:
        conn.execute(f"""
            INSERT INTO client_profiles (chat_id, {', '.join(kwargs.keys())})
            VALUES ({', '.join(['?'] * (len(kwargs) + 1))})
            ON CONFLICT(chat_id) DO UPDATE SET {fields}
        """, [chat_id] + list(kwargs.values()) + list(kwargs.values()))


def get_profile(chat_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM client_profiles WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return dict(row) if row else {}


def save_message(chat_id: int, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )


def get_history(chat_id: int, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT role, content FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC LIMIT ?
        """, (chat_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_history(chat_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))


def save_lead(chat_id: int, name: str, phone: str,
              car_choice: str, budget_rub: float = 0, city: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO leads (chat_id, name, phone, car_choice, budget_rub, city)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, name, phone, car_choice, budget_rub, city))
        return cur.lastrowid


def get_leads(status: str = "new") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_leads(limit: int = 500) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_lead_by_id(lead_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
    return dict(row) if row else {}


def update_lead_status(lead_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status = ? WHERE id = ?",
            (status, lead_id)
        )


def get_stats() -> dict:
    with get_conn() as conn:
        total_clients = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        leads_new     = conn.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'").fetchone()[0]
        leads_work    = conn.execute("SELECT COUNT(*) FROM leads WHERE status = 'in_work'").fetchone()[0]
        leads_done    = conn.execute("SELECT COUNT(*) FROM leads WHERE status = 'done'").fetchone()[0]
        top_models = conn.execute("""
            SELECT car_choice, COUNT(*) as cnt
            FROM leads
            GROUP BY car_choice
            ORDER BY cnt DESC
            LIMIT 5
        """).fetchall()
        today_count = conn.execute("""
            SELECT COUNT(*) FROM leads
            WHERE date(created_at) = date('now')
        """).fetchone()[0]
        week_count = conn.execute("""
            SELECT COUNT(*) FROM leads
            WHERE created_at >= datetime('now', '-7 days')
        """).fetchone()[0]
    return {
        "total_clients": total_clients,
        "leads_new":     leads_new,
        "leads_in_work": leads_work,
        "leads_done":    leads_done,
        "leads_total":   leads_new + leads_work + leads_done,
        "today":         today_count,
        "week":          week_count,
        "top_models":    [(r["car_choice"], r["cnt"]) for r in top_models],
    }


def add_to_watchlist(chat_id: int, maker: str, model: str,
                     budget_rub: float, city: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO watchlist (chat_id, maker, model, budget_rub, city)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, maker, model, budget_rub, city))
        return cur.lastrowid


def get_active_watchlist() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def update_watchlist_checked(watch_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET last_checked = datetime('now') WHERE id = ?",
            (watch_id,)
        )
