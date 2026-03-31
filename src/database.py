import json
import urllib.parse

import pg8000.native

from config import DATABASE_URL


def _parse_url(url: str) -> dict:
    """Parse a postgres:// URL into pg8000.native.Connection kwargs."""
    p = urllib.parse.urlparse(url)
    kwargs = {
        "host": p.hostname,
        "port": p.port or 5432,
        "database": p.path.lstrip("/"),
        "user": p.username,
        "password": p.password,
        "ssl_context": True,
    }
    return kwargs


def get_connection():
    return pg8000.native.Connection(**_parse_url(DATABASE_URL))


def _rows_to_dicts(conn, rows) -> list:
    """pg8000.native returns rows as lists; use conn.columns for names."""
    if not rows:
        return []
    keys = [c["name"] for c in conn.columns]
    return [dict(zip(keys, row)) for row in rows]


def init_db():
    """No-op: tables are pre-created in Supabase."""
    pass


def save_feedback(user_email: str, message: str) -> int:
    conn = get_connection()
    rows = conn.run(
        "INSERT INTO feedback (user_email, message) VALUES (:user_email, :message) RETURNING id",
        user_email=user_email,
        message=message,
    )
    return rows[0][0]


def list_feedback() -> list:
    conn = get_connection()
    rows = conn.run("SELECT * FROM feedback ORDER BY submitted_at DESC")
    return _rows_to_dicts(conn, rows)


def log_audit(post_id, user_email: str, action: str, details: dict = None):
    conn = get_connection()
    if action == "edited":
        rows = conn.run(
            """
            SELECT id FROM audit_log
            WHERE post_id = :post_id AND user_email = :user_email AND action = 'edited'
            AND timestamp > NOW() - INTERVAL '5 minutes'
            ORDER BY timestamp DESC LIMIT 1
            """,
            post_id=post_id,
            user_email=user_email,
        )
        if rows:
            conn.run(
                "UPDATE audit_log SET timestamp = NOW(), details = :details WHERE id = :id",
                details=json.dumps(details) if details else None,
                id=rows[0][0],
            )
            return
    conn.run(
        "INSERT INTO audit_log (post_id, user_email, action, details) VALUES (:post_id, :user_email, :action, :details)",
        post_id=post_id,
        user_email=user_email,
        action=action,
        details=json.dumps(details) if details else None,
    )


def get_audit_log(post_id: int) -> list:
    conn = get_connection()
    rows = conn.run(
        "SELECT * FROM audit_log WHERE post_id = :post_id ORDER BY timestamp DESC LIMIT 50",
        post_id=post_id,
    )
    return _rows_to_dicts(conn, rows)


def save_post(post_data: dict, file_path: str) -> int:
    conn = get_connection()
    rows = conn.run(
        """
        INSERT INTO posts (title, slug, keyword, country, status, date, meta_title,
                           meta_description, overview, categories, tags, file_path, word_count, content)
        VALUES (:title, :slug, :keyword, :country, :status, :date, :meta_title,
                :meta_description, :overview, :categories, :tags, :file_path, :word_count, :content)
        RETURNING id
        """,
        title=post_data["title"],
        slug=post_data["slug"],
        keyword=post_data.get("keyword", ""),
        country=post_data.get("country", ""),
        status=post_data.get("status", "writing"),
        date=post_data["date"],
        meta_title=post_data.get("meta_title", ""),
        meta_description=post_data.get("meta_description", ""),
        overview=post_data.get("overview", ""),
        categories=json.dumps(post_data.get("categories", [])),
        tags=json.dumps(post_data.get("tags", [])),
        file_path=file_path,
        word_count=len(post_data.get("content", "").split()),
        content=post_data.get("content", ""),
    )
    return rows[0][0]


def get_post(post_id: int) -> dict | None:
    conn = get_connection()
    rows = conn.run("SELECT * FROM posts WHERE id = :id", id=post_id)
    result = _rows_to_dicts(conn, rows)
    return result[0] if result else None


def get_post_by_slug(slug: str) -> dict | None:
    conn = get_connection()
    rows = conn.run("SELECT * FROM posts WHERE slug = :slug", slug=slug)
    result = _rows_to_dicts(conn, rows)
    return result[0] if result else None


def list_posts(status: str = None) -> list:
    conn = get_connection()
    if status:
        rows = conn.run(
            "SELECT * FROM posts WHERE status = :status ORDER BY created_at DESC",
            status=status,
        )
    else:
        rows = conn.run("SELECT * FROM posts ORDER BY created_at DESC")
    return _rows_to_dicts(conn, rows)


def update_post_status(post_id: int, new_status: str, old_file_path: str, new_file_path: str):
    conn = get_connection()
    conn.run(
        "UPDATE posts SET status = :status, file_path = :file_path, updated_at = NOW() WHERE id = :id",
        status=new_status,
        file_path=new_file_path,
        id=post_id,
    )


def update_post_fields(post_id: int, fields: dict):
    if not fields:
        return
    set_clauses = ", ".join([f"{k} = :{k}" for k in fields.keys()])
    conn = get_connection()
    conn.run(
        f"UPDATE posts SET {set_clauses}, updated_at = NOW() WHERE id = :id",
        **fields,
        id=post_id,
    )


def delete_post(post_id: int):
    conn = get_connection()
    conn.run("DELETE FROM posts WHERE id = :id", id=post_id)
