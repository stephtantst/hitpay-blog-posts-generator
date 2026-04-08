#!/usr/bin/env python3
"""FastAPI backend for HitPay Blog Post Generator UI."""

import asyncio
import json
import os
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from config import (
    ALLOWED_DOMAIN,
    BASE_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    POSTS_DIR,
    SECRET_KEY,
)
from src.database import (
    delete_post,
    get_audit_log,
    get_post,
    get_post_by_slug,
    init_db,
    list_feedback,
    list_logins,
    list_posts,
    log_audit,
    log_login,
    save_feedback,
    save_post,
    update_post_fields,
    update_post_status,
)
from src.generator import generate_blog_post, rewrite_blog_post
from src.post_writer import (
    export_bulk_to_csv,
    export_to_csv,
    move_post_file,
    read_post_content,
    update_post_file,
    write_post_file,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    for d in ["generated", "editing", "ready_to_publish", "published", "exports"]:
        try:
            Path(POSTS_DIR, d).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    yield


app = FastAPI(title="HitPay Blog Generator", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=BASE_URL.startswith("https://"),
    max_age=86400 * 30,  # 30 days
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Auth ───────────────────────────────────────────────────────────────────────

def require_auth(request: Request) -> str:
    """Dependency: returns email of authenticated user or raises 401."""
    email = request.session.get("email")
    if not email:
        raise HTTPException(401, "Not authenticated")
    return email


@app.get("/auth/login")
def auth_login(request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google OAuth is not configured (GOOGLE_CLIENT_ID missing)")
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{BASE_URL}/auth/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params))


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    if error or not code:
        return RedirectResponse("/?auth_error=1")

    expected = request.session.pop("oauth_state", None)
    if not expected or state != expected:
        return RedirectResponse("/?auth_error=1")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": f"{BASE_URL}/auth/callback",
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            return RedirectResponse("/?auth_error=1")

        access_token = token_res.json().get("access_token")
        userinfo_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_res.status_code != 200:
            return RedirectResponse("/?auth_error=1")

    user = userinfo_res.json()
    email = user.get("email", "").lower()

    if not email.endswith(f"@{ALLOWED_DOMAIN}"):
        return RedirectResponse("/?auth_error=domain")

    request.session["email"] = email
    request.session["name"] = user.get("name", "")
    try:
        log_login(email, user.get("name", ""))
    except Exception:
        pass  # Never block login due to logging failure
    return RedirectResponse("/")


@app.get("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@app.get("/auth/me")
def auth_me(request: Request):
    email = request.session.get("email")
    if not email:
        raise HTTPException(401, "Not authenticated")
    return {"email": email, "name": request.session.get("name", "")}


# ── Root ───────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse("static/index.html")


# ── Posts ─────────────────────────────────────────────────────────────────────

def _serialise(post: dict) -> dict:
    post = dict(post)
    post["categories"] = json.loads(post.get("categories") or "[]")
    post["tags"] = json.loads(post.get("tags") or "[]")
    return post


def _serialise_with_content(post: dict) -> dict:
    post = _serialise(post)
    # Prefer content stored in DB; fall back to file for local legacy posts
    if post.get("content"):
        return post
    file_path = post.get("file_path", "")
    post["content"] = read_post_content(file_path) if file_path and os.path.exists(file_path) else ""
    return post


@app.get("/api/posts")
def api_list_posts(status: str = None, _: str = Depends(require_auth)):
    posts = list_posts(status if status and status != "all" else None)
    return [_serialise(p) for p in posts]


@app.get("/api/posts/{post_id}")
def api_get_post(post_id: int, _: str = Depends(require_auth)):
    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return _serialise_with_content(post)


class UpdatePostRequest(BaseModel):
    title: str | None = None
    slug: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    overview: str | None = None
    categories: list[str] | None = None
    tags: list[str] | None = None
    date: str | None = None
    country: str | None = None
    content: str | None = None


@app.put("/api/posts/{post_id}")
def api_update_post(post_id: int, body: UpdatePostRequest, user_email: str = Depends(require_auth)):
    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    db_fields = {}
    file_updates = {}
    changed_fields = []

    for field in ("title", "slug", "meta_title", "meta_description", "overview", "date", "country"):
        val = getattr(body, field)
        if val is not None:
            db_fields[field] = val
            file_updates[field] = val
            changed_fields.append(field)

    if body.categories is not None:
        db_fields["categories"] = json.dumps(body.categories)
        file_updates["categories"] = body.categories
        changed_fields.append("categories")

    if body.tags is not None:
        db_fields["tags"] = json.dumps(body.tags)
        file_updates["tags"] = body.tags
        changed_fields.append("tags")

    if body.content is not None:
        word_count = len(body.content.split())
        db_fields["word_count"] = word_count
        db_fields["content"] = body.content
        changed_fields.append("content")

    if db_fields:
        update_post_fields(post_id, db_fields)

    file_path = post.get("file_path", "")
    if file_path and os.path.exists(file_path):
        if file_updates:
            update_post_file(file_path, file_updates)
        if body.content is not None:
            _rewrite_content(file_path, body.content)

    if changed_fields:
        log_audit(post_id, user_email, "edited", {"fields": changed_fields})

    return {"ok": True}


def _rewrite_content(file_path: str, new_content: str):
    """Replace the body section of a markdown file, preserving frontmatter."""
    import yaml
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()

    frontmatter_dict = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter_dict = yaml.safe_load(parts[1]) or {}

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(frontmatter_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.write("---\n\n")
        f.write(new_content)


class StatusRequest(BaseModel):
    status: str
    editor_email: str | None = None


class EditorRequest(BaseModel):
    editor_email: str


@app.post("/api/posts/{post_id}/status")
def api_change_status(post_id: int, body: StatusRequest, user_email: str = Depends(require_auth)):
    valid = ["generated", "editing", "ready_to_publish", "published"]
    if body.status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid}")

    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    old_file = post.get("file_path", "")
    old_status = post.get("status", "")
    slug = post["slug"]

    if old_file and os.path.exists(old_file):
        new_file = move_post_file(old_file, body.status, slug)
    else:
        new_file = str(Path(POSTS_DIR) / body.status / f"{slug}.md")

    editor_email = body.editor_email if body.status == "editing" else None
    update_post_status(post_id, body.status, old_file, new_file, editor_email=editor_email)
    log_audit(post_id, user_email, "status_changed", {"from": old_status, "to": body.status})
    return {"ok": True, "file_path": new_file}


@app.patch("/api/posts/{post_id}/editor")
def api_set_editor(post_id: int, body: EditorRequest, _: str = Depends(require_auth)):
    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    update_post_fields(post_id, {"editor_email": body.editor_email})
    return {"ok": True}


@app.delete("/api/posts/{post_id}")
def api_delete_post(post_id: int, user_email: str = Depends(require_auth)):
    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    file_path = post.get("file_path", "")
    log_audit(post_id, user_email, "deleted", {"title": post.get("title", "")})
    delete_post(post_id)
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    return {"ok": True}


@app.get("/api/posts/{post_id}/export")
def api_export_post(post_id: int, _: str = Depends(require_auth)):
    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    file_path = post.get("file_path", "")
    csv_path = export_to_csv(post, file_path)
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=f"{post['slug']}.csv",
    )


@app.get("/api/posts/{post_id}/audit-log")
def api_get_audit_log(post_id: int, _: str = Depends(require_auth)):
    return get_audit_log(post_id)


# ── Bulk Export ───────────────────────────────────────────────────────────────

class BulkExportRequest(BaseModel):
    post_ids: list[int]


@app.post("/api/posts/bulk-export")
def api_bulk_export(body: BulkExportRequest, _: str = Depends(require_auth)):
    if not body.post_ids:
        raise HTTPException(400, "No post IDs provided")

    posts_with_paths = []
    for pid in body.post_ids:
        post = get_post(pid)
        if post:
            file_path = post.get("file_path", "") or ""
            posts_with_paths.append((post, file_path if os.path.exists(file_path) else ""))

    if not posts_with_paths:
        raise HTTPException(400, "No valid posts found to export")

    from datetime import date as _date
    csv_path = export_bulk_to_csv(posts_with_paths)
    filename = f"bulk-export-{_date.today().isoformat()}.csv"
    return FileResponse(csv_path, media_type="text/csv", filename=filename)


# ── Bulk Delete ──────────────────────────────────────────────────────────────

@app.post("/api/posts/bulk-delete")
def api_bulk_delete(body: BulkExportRequest, user_email: str = Depends(require_auth)):
    if not body.post_ids:
        raise HTTPException(400, "No post IDs provided")
    deleted = 0
    for pid in body.post_ids:
        post = get_post(pid)
        if not post:
            continue
        file_path = post.get("file_path", "")
        log_audit(pid, user_email, "deleted", {"title": post.get("title", "")})
        delete_post(pid)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        deleted += 1
    return {"ok": True, "deleted": deleted}


# ── AI Edit ───────────────────────────────────────────────────────────────────

class AiEditRequest(BaseModel):
    instruction: str
    selection: str | None = None


@app.post("/api/posts/{post_id}/ai-edit")
def api_ai_edit(post_id: int, body: AiEditRequest, _: str = Depends(require_auth)):
    """Apply a targeted AI edit to a post. If selection is provided, only that text is sent to Claude."""
    from src.ai_editor import ai_edit_selection, ai_edit_full

    post = get_post(post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    if body.selection:
        edited = ai_edit_selection(body.selection, body.instruction)
        return {"edited_selection": edited}

    file_path = post.get("file_path", "")
    if file_path and os.path.exists(file_path):
        content = read_post_content(file_path)
    else:
        content = post.get("content", "")
        if not content:
            raise HTTPException(400, "Post file not found")

    try:
        edited = ai_edit_full(content, body.instruction)
    except Exception as e:
        raise HTTPException(500, f"AI edit failed: {e}")
    return {"edited_content": edited}


# ── Generate ──────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    keyword: str
    country: str | None = None


@app.post("/api/generate")
async def api_generate(body: GenerateRequest, user_email: str = Depends(require_auth)):
    """Generate a blog post and stream progress via SSE."""

    async def stream():
        messages: list[str] = []
        loop = asyncio.get_event_loop()

        def on_status(msg: str):
            messages.append(msg)

        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Starting generation...'})}\n\n"

            post_data = await loop.run_in_executor(
                None, lambda: generate_blog_post(body.keyword, country=body.country, on_status=on_status)
            )

            for msg in messages:
                yield f"data: {json.dumps({'type': 'status', 'message': msg})}\n\n"

            # Handle slug collision
            existing = get_post_by_slug(post_data["slug"])
            if existing:
                import time
                post_data["slug"] = f"{post_data['slug']}-{int(time.time())}"

            post_data["editor_email"] = user_email
            file_path = write_post_file(post_data)
            post_id = save_post(post_data, file_path)
            post_data["id"] = post_id

            log_audit(post_id, user_email, "created", {
                "keyword": body.keyword,
                "country": body.country or "",
            })

            yield f"data: {json.dumps({'type': 'done', 'post_id': post_id, 'title': post_data['title']})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


class RewriteRequest(BaseModel):
    url: str
    country: str | None = None


@app.post("/api/rewrite")
async def api_rewrite(body: RewriteRequest, user_email: str = Depends(require_auth)):
    """Scrape an existing blog post URL and rewrite it with all optimisation directives. Streams via SSE."""

    async def stream():
        messages: list[str] = []
        loop = asyncio.get_event_loop()

        def on_status(msg: str):
            messages.append(msg)

        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Starting rewrite...'})}\n\n"

            post_data = await loop.run_in_executor(
                None, lambda: rewrite_blog_post(body.url, country=body.country, on_status=on_status)
            )

            for msg in messages:
                yield f"data: {json.dumps({'type': 'status', 'message': msg})}\n\n"

            existing = get_post_by_slug(post_data["slug"])
            if existing:
                import time
                post_data["slug"] = f"{post_data['slug']}-rewrite-{int(time.time())}"

            post_data["editor_email"] = user_email
            file_path = write_post_file(post_data)
            post_id = save_post(post_data, file_path)
            post_data["id"] = post_id

            log_audit(post_id, user_email, "created", {
                "keyword": post_data.get("keyword", ""),
                "country": body.country or "",
                "source_url": body.url,
            })

            yield f"data: {json.dumps({'type': 'done', 'post_id': post_id, 'title': post_data['title']})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


class FeedbackRequest(BaseModel):
    message: str


@app.post("/api/feedback")
async def api_submit_feedback(body: FeedbackRequest, user_email: str = Depends(require_auth)):
    if not body.message.strip():
        raise HTTPException(400, "Message cannot be empty")
    fid = save_feedback(user_email, body.message.strip())
    return {"id": fid}


@app.get("/api/analytics/status-durations")
def api_status_durations(period: str = "month", _: str = Depends(require_auth)):
    """Return average hours each post spent in each status, grouped by period.

    period: 'day' | 'week' | 'month'
    Returns rows: { period, status, avg_hours }
    """
    if period not in ("day", "week", "month"):
        period = "month"

    trunc   = {"day": "day",   "week": "week",   "month": "month"}[period]
    fmt     = {"day": "YYYY-MM-DD", "week": "YYYY-MM-DD", "month": "YYYY-MM"}[period]
    n_back  = {"day": 14, "week": 12, "month": 12}[period]

    from src.database import get_connection, _rows_to_dicts
    conn = get_connection()
    rows = conn.run(f"""
        WITH transitions AS (
            SELECT
                post_id,
                details::json->>'from'  AS from_status,
                timestamp               AS transitioned_at,
                LAG(timestamp) OVER (PARTITION BY post_id ORDER BY timestamp) AS prev_ts
            FROM audit_log
            WHERE action = 'status_changed'
        ),
        durations AS (
            SELECT
                from_status                                              AS status,
                EXTRACT(EPOCH FROM (transitioned_at - prev_ts)) / 3600  AS hours,
                DATE_TRUNC('{trunc}', transitioned_at)                   AS period
            FROM transitions
            WHERE prev_ts IS NOT NULL AND from_status IS NOT NULL
              AND EXTRACT(EPOCH FROM (transitioned_at - prev_ts)) > 0
              AND transitioned_at >= NOW() - INTERVAL '{n_back} {trunc}s'
        )
        SELECT
            TO_CHAR(period, '{fmt}')       AS period,
            status,
            ROUND(AVG(hours)::numeric, 2)  AS avg_hours
        FROM durations
        GROUP BY period, status
        ORDER BY period, status
    """)
    return _rows_to_dicts(conn, rows)


@app.get("/api/feedback")
def api_list_feedback(_: str = Depends(require_auth)):
    return list_feedback()


@app.get("/api/logins")
def api_list_logins(_: str = Depends(require_auth)):
    return list_logins()


@app.post("/api/test-post")
async def api_test_post(user_email: str = Depends(require_auth)):
    """Create a placeholder test post instantly (no AI generation)."""
    import time
    ts = int(time.time())
    post_data = {
        "title": f"Test Post {ts}",
        "slug": f"test-post-{ts}",
        "keyword": "[TEST]",
        "country": "",
        "status": "generated",
        "date": __import__("datetime").date.today().isoformat(),
        "meta_title": "",
        "meta_description": "",
        "overview": "This is a placeholder test post.",
        "categories": [],
        "tags": [],
        "content": "This is a test post created for prototype testing purposes.\n\nReplace this content with your actual post body.",
    }
    post_data["editor_email"] = user_email
    file_path = write_post_file(post_data)
    post_id = save_post(post_data, file_path)
    log_audit(post_id, user_email, "created", {"keyword": "[TEST]", "country": ""})
    return {"post_id": post_id}


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
