import os
import sqlite3
import requests
from typing import Optional, Dict, Any, List

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "https://pes-db-hossamfayad.aws-us-east-1.turso.io")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3OTIyMTU5NDIsImlkIjoiMDFhMTQ4NjMtYzkwMS03MGFmLWJhYzItNjI2M2ZjNWUxMWJkIiwia2lkIjoiT0F1Z3otdzZpNTlwVk9hMVFNclhLbnFQRGw0RWY4dm1BXy1FUnB4cG45MCIsInJpZCI6ImQ1ZTQ4NjJiLTQ3NzEtNDU5ZC05YTU5LTJjZWQ1M2M5MGJlMCJ9.YCVzUQRNc9kDdj5Pgc3jo7EGSqyz-W_h-CdzpO3yWm8b3JlkCB5IcEyWPEwVxX75zjbg6q9k_vrfohcQfhIWBg")

USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)

# Clean Turso base URL if provided with libsql://
if TURSO_URL and TURSO_URL.startswith("libsql://"):
    TURSO_URL = TURSO_URL.replace("libsql://", "https://")

if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/pes_bot.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "pes_bot.db")

# ----------------- Turso HTTP Client -----------------
def _format_arg(val: Any) -> Dict[str, Any]:
    if val is None:
        return {"type": "null"}
    elif isinstance(val, int):
        return {"type": "integer", "value": str(val)}
    elif isinstance(val, float):
        return {"type": "float", "value": val}
    else:
        return {"type": "text", "value": str(val)}

def turso_execute(sql: str, args: list = None) -> List[Dict[str, Any]]:
    if not args:
        args = []
    formatted_args = [_format_arg(a) for a in args]
    
    url = f"{TURSO_URL.rstrip('/')}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": formatted_args}},
            {"type": "close"}
        ]
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results and results[0].get("type") == "ok":
                exec_result = results[0]["response"]["result"]
                cols = [c["name"] for c in exec_result.get("cols", [])]
                out = []
                for row in exec_result.get("rows", []):
                    row_dict = {}
                    for col_name, col_val in zip(cols, row):
                        row_dict[col_name] = col_val.get("value")
                    out.append(row_dict)
                return out
        else:
            print(f"[TursoError] Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[TursoException] {e}")
    return []

# ----------------- SQLite Fallback -----------------
def get_sqlite_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------- Unified DB Interface -----------------
def init_db():
    sql1 = """
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
    """
    sql2 = """
    CREATE TABLE IF NOT EXISTS user_state (
        telegram_id INTEGER PRIMARY KEY,
        active_account_id INTEGER,
        last_checked_message_id TEXT
    )
    """
    sql3 = """
    CREATE TABLE IF NOT EXISTS admins (
        telegram_id INTEGER PRIMARY KEY,
        added_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    sql4 = """
    CREATE TABLE IF NOT EXISTS user_prompts (
        telegram_id INTEGER PRIMARY KEY,
        state TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    if USE_TURSO:
        turso_execute(sql1)
        turso_execute(sql2)
        turso_execute(sql3)
        turso_execute(sql4)
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute(sql1)
        cursor.execute(sql2)
        cursor.execute(sql3)
        cursor.execute(sql4)
        conn.commit()
        conn.close()

def save_account(telegram_id: int, email: str, password: str, account_id: str, token: str, note: str = "") -> int:
    if USE_TURSO:
        sql = """
        INSERT INTO accounts (telegram_id, email, password, account_id, token, note)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        turso_execute(sql, [telegram_id, email, password, account_id, token, note])
        
        # Get the new ID
        res = turso_execute("SELECT id FROM accounts WHERE email = ?", [email])
        new_id = int(res[0]["id"]) if res and res[0].get("id") else 0
        
        # Update user state
        turso_execute("""
            INSERT OR REPLACE INTO user_state (telegram_id, active_account_id)
            VALUES (?, ?)
        """, [telegram_id, new_id])
        return new_id
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO accounts (telegram_id, email, password, account_id, token, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (telegram_id, email, password, account_id, token, note))
        new_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO user_state (telegram_id, active_account_id)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET active_account_id=excluded.active_account_id
        """, (telegram_id, new_id))
        conn.commit()
        conn.close()
        return new_id

def get_active_account(telegram_id: int) -> Optional[Dict[str, Any]]:
    if USE_TURSO:
        sql = """
        SELECT a.* FROM accounts a
        JOIN user_state u ON a.id = u.active_account_id
        WHERE u.telegram_id = ?
        """
        rows = turso_execute(sql, [telegram_id])
        return rows[0] if rows else None
    else:
        conn = get_sqlite_conn()
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
    if USE_TURSO:
        turso_execute("""
            INSERT OR REPLACE INTO user_state (telegram_id, active_account_id)
            VALUES (?, ?)
        """, [telegram_id, account_id])
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_state (telegram_id, active_account_id)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET active_account_id=excluded.active_account_id
        """, (telegram_id, account_id))
        conn.commit()
        conn.close()

def clear_active_account(telegram_id: int):
    if USE_TURSO:
        turso_execute("UPDATE user_state SET active_account_id = NULL WHERE telegram_id = ?", [telegram_id])
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE user_state SET active_account_id = NULL WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        conn.close()

def get_user_accounts(telegram_id: int, limit: int = 15) -> List[Dict[str, Any]]:
    if USE_TURSO:
        sql = "SELECT * FROM accounts WHERE telegram_id = ? ORDER BY id DESC LIMIT ?"
        return turso_execute(sql, [telegram_id, limit])
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE telegram_id = ? ORDER BY id DESC LIMIT ?", (telegram_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

def get_account_by_id(account_id: int) -> Optional[Dict[str, Any]]:
    if USE_TURSO:
        rows = turso_execute("SELECT * FROM accounts WHERE id = ?", [account_id])
        return rows[0] if rows else None
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

def get_all_active_monitored_accounts() -> List[Dict[str, Any]]:
    if USE_TURSO:
        sql = """
        SELECT a.* FROM accounts a
        JOIN user_state u ON a.id = u.active_account_id
        ORDER BY a.id DESC
        """
        return turso_execute(sql)
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.* FROM accounts a
            JOIN user_state u ON a.id = u.active_account_id
            ORDER BY a.id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

def set_prompt_state(telegram_id: int, state: str):
    if USE_TURSO:
        turso_execute("INSERT OR REPLACE INTO user_prompts (telegram_id, state) VALUES (?, ?)", [telegram_id, state])
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_prompts (telegram_id, state) VALUES (?, ?)", (telegram_id, state))
        conn.commit()
        conn.close()

def get_prompt_state(telegram_id: int) -> Optional[str]:
    if USE_TURSO:
        res = turso_execute("SELECT state FROM user_prompts WHERE telegram_id = ?", [telegram_id])
        return res[0].get("state") if res else None
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT state FROM user_prompts WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

def clear_prompt_state(telegram_id: int):
    if USE_TURSO:
        turso_execute("DELETE FROM user_prompts WHERE telegram_id = ?", [telegram_id])
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_prompts WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        conn.close()

SUPER_ADMINS = [5575156113]

def is_admin(telegram_id: int) -> bool:
    try:
        t_id = int(telegram_id)
        if t_id in SUPER_ADMINS:
            return True
        if USE_TURSO:
            res = turso_execute("SELECT 1 FROM admins WHERE telegram_id = ?", [t_id])
            return bool(res)
        else:
            conn = get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (t_id,))
            row = cursor.fetchone()
            conn.close()
            return bool(row)
    except Exception:
        return False

def add_admin(new_admin_id: int, added_by: int) -> bool:
    try:
        t_id = int(new_admin_id)
        if USE_TURSO:
            turso_execute("INSERT OR IGNORE INTO admins (telegram_id, added_by) VALUES (?, ?)", [t_id, added_by])
        else:
            conn = get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO admins (telegram_id, added_by) VALUES (?, ?)", (t_id, added_by))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[AddAdminError] {e}")
        return False

def get_all_accounts_admin(limit: int = 20) -> List[Dict[str, Any]]:
    if USE_TURSO:
        sql = "SELECT * FROM accounts ORDER BY id DESC LIMIT ?"
        return turso_execute(sql, [limit])
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

def get_bot_stats() -> Dict[str, Any]:
    try:
        if USE_TURSO:
            res = turso_execute("SELECT COUNT(*) as total_accounts, COUNT(DISTINCT telegram_id) as total_users FROM accounts")
            if res:
                return {
                    "total_accounts": int(res[0].get("total_accounts", 0)),
                    "total_users": int(res[0].get("total_users", 0))
                }
        else:
            conn = get_sqlite_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total_accounts, COUNT(DISTINCT telegram_id) as total_users FROM accounts")
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "total_accounts": row[0],
                    "total_users": row[1]
                }
    except Exception as e:
        print(f"[StatsError] {e}")
    return {"total_accounts": 0, "total_users": 0}

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully! USE_TURSO =", USE_TURSO)

