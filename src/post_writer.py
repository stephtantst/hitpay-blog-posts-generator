import yaml
import json
import csv
import os
import re
from pathlib import Path
import markdown as md_parser
from config import POSTS_DIR


# Framer CMS expects these exact column headers — match your collection field names
FRAMER_CSV_FIELDS = [
    "Name",           # Title — string (required)
    "Slug",           # URL slug — string
    "Date",           # ISO date YYYY-MM-DD — date field
    "Meta Title",     # string, 55–60 chars
    "Meta Description",  # string, 150–160 chars
    "Overview",       # Excerpt — plain text string
    "Category",       # string (comma-separated if multiple)
    "Tags",           # string (comma-separated)
    "Body",           # Rich text — must be HTML, not Markdown
]


def _md_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML for Framer's rich text field.

    Returns a single-line HTML string — newlines inside the HTML body would
    create multi-line CSV fields that break most CSV parsers (including
    Framer's CSV Import plugin).
    """
    html = md_parser.markdown(
        markdown_text,
        extensions=["tables", "fenced_code"]
    )
    # Collapse all newlines to a single space so the Body field stays on one
    # CSV line. This is the most common cause of failed Framer CSV imports.
    return " ".join(html.split())

def write_post_file(post_data: dict, target_dir: str = None) -> str:
    slug = post_data["slug"]
    status = post_data.get("status", "writing")

    if target_dir:
        dir_path = Path(target_dir)
    else:
        dir_path = Path(POSTS_DIR) / status
    dir_path.mkdir(parents=True, exist_ok=True)

    file_path = dir_path / f"{slug}.md"

    frontmatter = {
        "title": post_data["title"],
        "slug": slug,
        "date": post_data["date"],
        "status": status,
        "keyword": post_data.get("keyword", ""),
        "meta_title": post_data.get("meta_title", ""),
        "meta_description": post_data.get("meta_description", ""),
        "overview": post_data.get("overview", ""),
        "categories": post_data.get("categories", []),
        "tags": post_data.get("tags", []),
        "word_count": len(post_data.get("content", "").split()),
    }

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(frontmatter, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.write("---\n\n")
        f.write(post_data.get("content", ""))

    return str(file_path)

def move_post_file(old_path: str, new_status: str, slug: str) -> str:
    new_dir = Path(POSTS_DIR) / new_status
    new_dir.mkdir(parents=True, exist_ok=True)
    new_path = new_dir / f"{slug}.md"

    # Read, update status in frontmatter, write to new location
    post_data = read_full_post_file(old_path)
    post_data["status"] = new_status

    # Write to new path
    with open(new_path, "w", encoding="utf-8") as f:
        frontmatter = {k: v for k, v in post_data.items() if k != "content"}
        f.write("---\n")
        yaml.dump(frontmatter, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.write("---\n\n")
        f.write(post_data.get("content", ""))

    # Remove old file
    if os.path.exists(old_path) and old_path != str(new_path):
        os.remove(old_path)

    return str(new_path)

def read_post_content(file_path: str) -> str:
    """Read only the content (below frontmatter)."""
    if not os.path.exists(file_path):
        return ""
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return raw

def read_full_post_file(file_path: str) -> dict:
    """Read frontmatter + content from markdown file."""
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()

    data = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            data = yaml.safe_load(parts[1]) or {}
            data["content"] = parts[2].strip()
    else:
        data["content"] = raw
    return data

def update_post_file(file_path: str, updates: dict):
    """Update specific frontmatter fields in a markdown file."""
    post_data = read_full_post_file(file_path)
    post_data.update(updates)

    content = post_data.pop("content", "")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(post_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.write("---\n\n")
        f.write(content)

def _build_framer_row(post: dict, file_path: str) -> dict:
    """Build a single Framer CMS CSV row from a post dict + its markdown file."""
    if file_path and os.path.exists(file_path):
        markdown_content = read_post_content(file_path)
    else:
        markdown_content = post.get("content", "")
    html_body = _md_to_html(markdown_content)
    def _to_list(val):
        if isinstance(val, list): return val
        try: return json.loads(val or "[]")
        except Exception: return []
    cats = _to_list(post.get("categories"))
    tags = _to_list(post.get("tags"))

    return {
        "Name": post.get("title", ""),
        "Slug": post.get("slug", ""),
        "Date": post.get("date", ""),
        "Meta Title": post.get("meta_title", ""),
        "Meta Description": post.get("meta_description", ""),
        "Overview": post.get("overview", ""),
        "Category": ", ".join(cats),
        "Tags": ", ".join(tags),
        "Body": html_body,
    }


def _write_framer_csv(path: Path, rows: list[dict]):
    """Write rows to a Framer-compatible CSV file.

    - UTF-8 BOM so Excel / Framer CSV Import detects encoding correctly
    - QUOTE_ALL so every field is quoted — prevents parsing errors with HTML content
    - Single-line HTML Body (handled in _md_to_html) to avoid multi-line field issues
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FRAMER_CSV_FIELDS,
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export_to_csv(post: dict, file_path: str) -> str:
    """Export a single post to CSV for Framer CMS import."""
    export_dir = Path(POSTS_DIR) / "exports"
    export_dir.mkdir(exist_ok=True)
    csv_path = export_dir / f"{post['slug']}.csv"
    _write_framer_csv(csv_path, [_build_framer_row(post, file_path)])
    return str(csv_path)


def export_bulk_to_csv(posts_with_paths: list[tuple]) -> str:
    """Export multiple posts into a single CSV for bulk Framer CMS import.

    Args:
        posts_with_paths: list of (post_dict, file_path) tuples
    Returns:
        path to the generated CSV file
    """
    export_dir = Path(POSTS_DIR) / "exports"
    export_dir.mkdir(exist_ok=True)

    from datetime import date
    csv_path = export_dir / f"bulk-export-{date.today().isoformat()}.csv"
    rows = [_build_framer_row(post, fp) for post, fp in posts_with_paths]
    _write_framer_csv(csv_path, rows)
    return str(csv_path)
