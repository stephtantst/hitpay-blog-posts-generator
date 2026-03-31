import sqlite3
import json
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            keyword TEXT,
            country TEXT DEFAULT '',
            status TEXT DEFAULT 'writing',
            date TEXT,
            meta_title TEXT,
            meta_description TEXT,
            overview TEXT,
            categories TEXT,
            tags TEXT,
            file_path TEXT,
            word_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            user_email TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrate existing databases: add country column if missing
    try:
        conn.execute("ALTER TABLE posts ADD COLUMN country TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # Column already exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            message TEXT NOT NULL,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_feedback(user_email: str, message: str) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO feedback (user_email, message) VALUES (?, ?)",
        (user_email, message)
    )
    fid = cursor.lastrowid
    conn.commit()
    conn.close()
    return fid


def list_feedback() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM feedback ORDER BY submitted_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def log_audit(post_id, user_email: str, action: str, details: dict = None):
    conn = get_connection()
    # Deduplicate 'edited' actions: update the entry if one exists within the last 5 minutes
    if action == "edited":
        recent = conn.execute("""
            SELECT id FROM audit_log
            WHERE post_id = ? AND user_email = ? AND action = 'edited'
            AND timestamp > datetime('now', '-5 minutes')
            ORDER BY timestamp DESC LIMIT 1
        """, (post_id, user_email)).fetchone()
        if recent:
            conn.execute(
                "UPDATE audit_log SET timestamp = CURRENT_TIMESTAMP, details = ? WHERE id = ?",
                (json.dumps(details) if details else None, recent["id"])
            )
            conn.commit()
            conn.close()
            return
    conn.execute(
        "INSERT INTO audit_log (post_id, user_email, action, details) VALUES (?, ?, ?, ?)",
        (post_id, user_email, action, json.dumps(details) if details else None)
    )
    conn.commit()
    conn.close()


def get_audit_log(post_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE post_id = ? ORDER BY timestamp DESC LIMIT 50",
        (post_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_post(post_data: dict, file_path: str) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO posts (title, slug, keyword, country, status, date, meta_title, meta_description,
                          overview, categories, tags, file_path, word_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        post_data["title"],
        post_data["slug"],
        post_data.get("keyword", ""),
        post_data.get("country", ""),
        post_data.get("status", "writing"),
        post_data["date"],
        post_data.get("meta_title", ""),
        post_data.get("meta_description", ""),
        post_data.get("overview", ""),
        json.dumps(post_data.get("categories", [])),
        json.dumps(post_data.get("tags", [])),
        file_path,
        len(post_data.get("content", "").split())
    ))
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return post_id

def get_post(post_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_post_by_slug(slug: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None

def list_posts(status: str = None) -> list:
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_post_status(post_id: int, new_status: str, old_file_path: str, new_file_path: str):
    conn = get_connection()
    conn.execute("""
        UPDATE posts SET status = ?, file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
    """, (new_status, new_file_path, post_id))
    conn.commit()
    conn.close()

def update_post_fields(post_id: int, fields: dict):
    if not fields:
        return
    set_clauses = ", ".join([f"{k} = ?" for k in fields.keys()])
    values = list(fields.values()) + [post_id]
    conn = get_connection()
    conn.execute(
        f"UPDATE posts SET {set_clauses}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()

def delete_post(post_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
