import sqlite3
import os
from datetime import datetime

if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/pes_bot.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "pes_bot.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            account_id TEXT,
            token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            note TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_state (
            telegram_id INTEGER PRIMARY KEY,
            active_account_id INTEGER,
            last_checked_message_id TEXT,
            FOREIGN KEY (active_account_id) REFERENCES accounts (id)
        )
    """)
    conn.commit()
    conn.close()

def save_account(telegram_id: int, email: str, password: str, account_id: str, token: str, note: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO accounts (telegram_id, email, password, account_id, token, note)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (telegram_id, email, password, account_id, token, note))
    new_id = cursor.lastrowid
    
    # Set as active account for this user
    cursor.execute("""
        INSERT INTO user_state (telegram_id, active_account_id)
        VALUES (?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET active_account_id=excluded.active_account_id
    """, (telegram_id, new_id))
    
    conn.commit()
    conn.close()
    return new_id

def get_active_account(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.* FROM accounts a
        JOIN user_state u ON a.id = u.active_account_id
        WHERE u.telegram_id = ?
    """, (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def set_active_account(telegram_id: int, account_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_state (telegram_id, active_account_id)
        VALUES (?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET active_account_id=excluded.active_account_id
    """, (telegram_id, account_id))
    conn.commit()
    conn.close()

def clear_active_account(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_state SET active_account_id = NULL WHERE telegram_id = ?
    """, (telegram_id,))
    conn.commit()
    conn.close()


def get_user_accounts(telegram_id: int, limit: int = 15):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM accounts
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (telegram_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_account_by_id(account_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_active_monitored_accounts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.* FROM accounts a
        JOIN user_state u ON a.id = u.active_account_id
        ORDER BY a.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
