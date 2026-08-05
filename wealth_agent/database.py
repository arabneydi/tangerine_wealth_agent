"""
Mock database layer for the wealth management assistant.

Two tables, exactly as specified in the assignment:
  - users(user_id, security_question, security_answer)
  - accounts(user_id, checking_balance, savings_balance)

SQLite file lives alongside this module so the whole project is self
contained and reproducible with no external setup.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "wealth.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    security_question TEXT NOT NULL,
    security_answer TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    checking_balance REAL NOT NULL,
    savings_balance REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

# Seed data: two users so the evalset can exercise more than one identity.
SEED_USERS = [
    ("user_001", "What city were you born in?", "toronto"),
    ("user_002", "What is your pet's name?", "biscuit"),
]

SEED_ACCOUNTS = [
    ("user_001", 2500.00, 10000.00),
    ("user_002", 800.00, 3200.00),
]


@contextmanager
def get_connection():
    """Yield a connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Concurrent writers (e.g. two overlapping transfer requests) should wait
    # for each other rather than fail immediately with "database is locked".
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
    finally:
        conn.close()


def init_db(reset: bool = False) -> None:
    """Create tables and seed data. If reset=True, wipe existing data first."""
    with get_connection() as conn:
        if reset:
            conn.executescript("DROP TABLE IF EXISTS accounts; DROP TABLE IF EXISTS users;")
        conn.executescript(SCHEMA)

        existing = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if existing == 0:
            conn.executemany(
                "INSERT INTO users (user_id, security_question, security_answer) VALUES (?, ?, ?)",
                SEED_USERS,
            )
            conn.executemany(
                "INSERT INTO accounts (user_id, checking_balance, savings_balance) VALUES (?, ?, ?)",
                SEED_ACCOUNTS,
            )
        conn.commit()


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Initialized database at {DB_PATH}")
