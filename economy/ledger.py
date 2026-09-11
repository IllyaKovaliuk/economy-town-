"""SQLite ledger: transactions, agent states, prices, crisis events, deaths."""

import json
import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL,
    agent TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    target_agent TEXT,
    resource TEXT,
    amount REAL,
    price_per_unit REAL,
    reasoning TEXT,
    public_message TEXT,
    dm_target TEXT,
    private_message TEXT,
    stance TEXT,
    stance_target TEXT,
    location TEXT,
    thought TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS deaths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL,
    agent TEXT NOT NULL,
    role TEXT NOT NULL,
    cause TEXT NOT NULL,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS agent_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL,
    agent TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    resources_json TEXT NOT NULL,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL,
    resource TEXT NOT NULL,
    price REAL NOT NULL,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS crisis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    resource TEXT,
    magnitude REAL,
    affects TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS debt_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_opened INTEGER NOT NULL,
    borrower TEXT NOT NULL,
    lender TEXT NOT NULL,
    principal REAL NOT NULL,
    collateral_gold REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    round_closed INTEGER,
    timestamp TEXT
);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Adds a column to an existing table if it's missing — lets old economy.db files
    from before this column existed keep working instead of erroring on SELECT *."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db(path=DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    _ensure_column(conn, "transactions", "location", "TEXT")
    _ensure_column(conn, "transactions", "thought", "TEXT")
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_transaction(conn: sqlite3.Connection, round_num: int, agent, action, thought: str | None = None) -> None:
    conn.execute(
        """INSERT INTO transactions
           (round, agent, role, action, target_agent, resource, amount, price_per_unit,
            reasoning, public_message, dm_target, private_message, stance, stance_target,
            location, thought, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            round_num, agent.name, agent.role.value, action.action, action.target_agent,
            action.resource, action.amount, action.price_per_unit, action.reasoning,
            action.public_message, action.dm_target, action.private_message,
            action.stance, action.stance_target, action.location, thought, _now(),
        ),
    )
    conn.commit()


def save_death(conn: sqlite3.Connection, round_num: int, agent, cause: str) -> None:
    conn.execute(
        "INSERT INTO deaths (round, agent, role, cause, timestamp) VALUES (?, ?, ?, ?, ?)",
        (round_num, agent.name, agent.role.value, cause, _now()),
    )
    conn.commit()


def save_agent_state(conn: sqlite3.Connection, round_num: int, agent) -> None:
    conn.execute(
        """INSERT INTO agent_states (round, agent, role, status, resources_json, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (round_num, agent.name, agent.role.value, agent.status, json.dumps(agent.resources), _now()),
    )
    conn.commit()


def save_prices(conn: sqlite3.Connection, round_num: int, prices: dict) -> None:
    for resource, price in prices.items():
        conn.execute(
            "INSERT INTO prices (round, resource, price, timestamp) VALUES (?, ?, ?, ?)",
            (round_num, resource, price, _now()),
        )
    conn.commit()


def save_debt_position(
    conn: sqlite3.Connection, round_num: int, borrower: str, lender: str,
    principal: float, collateral_gold: float,
) -> int:
    cur = conn.execute(
        """INSERT INTO debt_positions (round_opened, borrower, lender, principal, collateral_gold, status, timestamp)
           VALUES (?, ?, ?, ?, ?, 'open', ?)""",
        (round_num, borrower, lender, principal, collateral_gold, _now()),
    )
    conn.commit()
    return cur.lastrowid


def close_debt_position(conn: sqlite3.Connection, position_id: int, round_num: int, status: str) -> None:
    conn.execute(
        "UPDATE debt_positions SET status = ?, round_closed = ? WHERE id = ?",
        (status, round_num, position_id),
    )
    conn.commit()


def save_crisis(conn: sqlite3.Connection, crisis) -> None:
    if crisis is None:
        return
    conn.execute(
        """INSERT INTO crisis_events (round, type, description, resource, magnitude, affects, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (crisis.round, crisis.type, crisis.description, crisis.resource, crisis.magnitude, crisis.affects, _now()),
    )
    conn.commit()
