import json

import psycopg2
import psycopg2.extras

from config import DATABASE_URL


def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    """No-op: tables are pre-created in Supabase."""
    pass


def save_feedback(user_email: str, message: str) -> int:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO feedback (user_email, message) VALUES (%s, %s) RETURNING id",
                (user_email, message),
            )
            fid = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    return fid


def list_feedback() -> list:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM feedback ORDER BY submitted_at DESC")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def log_audit(post_id, user_email: str, action: str, details: dict = None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if action == "edited":
                cur.execute(
                    """
                    SELECT id FROM audit_log
                    WHERE post_id = %s AND user_email = %s AND action = 'edited'
                    AND timestamp > NOW() - INTERVAL '5 minutes'
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    (post_id, user_email),
                )
                recent = cur.fetchone()
                if recent:
                    cur.execute(
                        "UPDATE audit_log SET timestamp = NOW(), details = %s WHERE id = %s",
                        (json.dumps(details) if details else None, recent["id"]),
                    )
                    conn.commit()
                    return
            cur.execute(
                "INSERT INTO audit_log (post_id, user_email, action, details) VALUES (%s, %s, %s, %s)",
                (post_id, user_email, action, json.dumps(details) if details else None),
            )
        conn.commit()
    finally:
        conn.close()


def get_audit_log(post_id: int) -> list:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM audit_log WHERE post_id = %s ORDER BY timestamp DESC LIMIT 50",
                (post_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def save_post(post_data: dict, file_path: str) -> int:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO posts (title, slug, keyword, country, status, date, meta_title,
                                   meta_description, overview, categories, tags, file_path, word_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
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
                    len(post_data.get("content", "").split()),
                ),
            )
            post_id = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    return post_id


def get_post(post_id: int) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_post_by_slug(slug: str) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM posts WHERE slug = %s", (slug,))
            row = cur.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_posts(status: str = None) -> list:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute(
                    "SELECT * FROM posts WHERE status = %s ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cur.execute("SELECT * FROM posts ORDER BY created_at DESC")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def update_post_status(post_id: int, new_status: str, old_file_path: str, new_file_path: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE posts SET status = %s, file_path = %s, updated_at = NOW() WHERE id = %s",
                (new_status, new_file_path, post_id),
            )
        conn.commit()
    finally:
        conn.close()


def update_post_fields(post_id: int, fields: dict):
    if not fields:
        return
    set_clauses = ", ".join([f"{k} = %s" for k in fields.keys()])
    values = list(fields.values()) + [post_id]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE posts SET {set_clauses}, updated_at = NOW() WHERE id = %s",
                values,
            )
        conn.commit()
    finally:
        conn.close()


def delete_post(post_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM posts WHERE id = %s", (post_id,))
        conn.commit()
    finally:
        conn.close()
