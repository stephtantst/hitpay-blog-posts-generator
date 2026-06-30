"""
Reusable repurpose-and-schedule logic.

Generates X, Threads, and LinkedIn drafts from a published blog post and assigns
them all to the same next available weekday slot (09:00 SGT = 01:00 UTC).

Usage:
    from src.repurpose_scheduler import repurpose_and_schedule
    result = repurpose_and_schedule(post, user_email="steph@hit-pay.com")
    # {"ok": True/False, "date": datetime, "x_id": int, "threads_id": int, "linkedin_id": int, "errors": dict}
"""
import random
from datetime import datetime, timezone, timedelta

POST_HOUR_UTC = 1   # 09:00 SGT = 01:00 UTC
THREAD_SEP = "\n\n---\n\n"
BLOG_BASE = "https://hitpayapp.com/blog"


def get_next_schedule_date() -> datetime:
    """Return the next weekday after the latest scheduled draft across all platforms."""
    from src.database import get_connection

    conn = get_connection()
    rows = conn.run(
        "SELECT GREATEST("
        "  (SELECT MAX(scheduled_at) FROM x_posts       WHERE scheduled_at IS NOT NULL),"
        "  (SELECT MAX(scheduled_at) FROM threads_posts  WHERE scheduled_at IS NOT NULL),"
        "  (SELECT MAX(scheduled_at) FROM linkedin_posts WHERE scheduled_at IS NOT NULL)"
        ")"
    )
    max_date = rows[0][0] if rows and rows[0][0] else None

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if max_date:
        last_day = max_date.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        base = last_day + timedelta(days=1)
        start = max(base, today + timedelta(days=1))
    else:
        start = today + timedelta(days=1)

    while start.weekday() >= 5:
        start += timedelta(days=1)

    return start.replace(hour=POST_HOUR_UTC, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def _ensure_url(content: str, blog_url: str) -> str:
    """Append blog_url to content if not already present."""
    if blog_url and blog_url not in content:
        return content.rstrip() + f"\n\n{blog_url}"
    return content


def repurpose_and_schedule(post: dict, user_email: str, override_date: datetime = None) -> dict:
    """
    Generate X, Threads, and LinkedIn drafts for *post* and set their
    scheduled_at to the same next available weekday (or override_date if given).

    Only published posts should be passed in; raises ValueError otherwise.

    Returns a dict with keys: ok, date, x_id, threads_id, linkedin_id, errors.
    """
    if post.get("status") not in ("published",):
        raise ValueError(
            f"Post #{post.get('id')} has status '{post.get('status')}' — only 'published' posts can be repurposed."
        )

    from src.x_database import create_x_post
    from src.threads_database import create_threads_post
    from src.linkedin_database import create_linkedin_post
    from src.repurposer import repurpose_post_as_thread, _cap_tweet_post_url
    from src.threads_thought_leadership import generate_threads_story
    from src.linkedin_generator import generate_linkedin_post as _gen_li

    post_id    = post["id"]
    market     = (post.get("country") or "SG").upper()
    brand      = post.get("brand") or "hitpay"
    topic_hint = (post.get("title") or "")[:150]
    slug       = (post.get("slug") or "").strip()
    blog_url   = f"{BLOG_BASE}/{slug}" if slug else ""

    slot_date = override_date if override_date is not None else get_next_schedule_date()
    errors: dict = {}

    # --- X ---
    x_id = None
    try:
        thread_size = random.choice([1, 3, 5])
        r = repurpose_post_as_thread(post, thread_size)
        link = r.get("link_url") or blog_url
        tweets = [
            _cap_tweet_post_url(t.replace("[URL]", link))
            for t in (r.get("tweets") or [])
        ]
        x_id = create_x_post(
            content=THREAD_SEP.join(tweets),
            market=market,
            editor_email=user_email,
            source_blog_post_id=post_id,
            brand=brand,
            scheduled_at=slot_date,
        )
    except Exception as exc:
        errors["x"] = str(exc)

    # --- Threads ---
    threads_id = None
    try:
        r = generate_threads_story(market=market, topic_hint=topic_hint, thread_size=3, brand=brand)
        ps = r.get("posts") or []
        content = THREAD_SEP.join(ps) if len(ps) > 1 else (ps[0] if ps else "")
        content = _ensure_url(content, blog_url)
        threads_id = create_threads_post(
            content=content,
            market=market,
            editor_email=user_email,
            source_blog_post_id=post_id,
            brand=brand,
            scheduled_at=slot_date,
        )
    except Exception as exc:
        errors["threads"] = str(exc)

    # --- LinkedIn ---
    linkedin_id = None
    try:
        r = _gen_li(market=market, topic_hint=topic_hint, brand=brand)
        content = r.get("content", "")
        content = _ensure_url(content, blog_url)
        linkedin_id = create_linkedin_post(
            content=content,
            market=market,
            editor_email=user_email,
            source_blog_post_id=post_id,
            brand=brand,
            scheduled_at=slot_date,
        )
    except Exception as exc:
        errors["linkedin"] = str(exc)

    return {
        "ok":          not errors,
        "date":        slot_date,
        "x_id":        x_id,
        "threads_id":  threads_id,
        "linkedin_id": linkedin_id,
        "errors":      errors,
    }
