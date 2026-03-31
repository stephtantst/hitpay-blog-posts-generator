import click
import json
import os
import subprocess
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from src.generator import generate_blog_post
from src.database import (
    init_db, save_post, get_post, list_posts,
    update_post_status, update_post_fields, delete_post
)
from src.post_writer import (
    write_post_file, move_post_file, read_post_content,
    read_full_post_file, update_post_file, export_to_csv
)
from config import POSTS_DIR

console = Console()

STATUS_COLORS = {
    "writing": "yellow",
    "ready_to_publish": "bright_blue",
    "published": "green",
}
STATUS_ICONS = {
    "writing": "✏️",
    "ready_to_publish": "🔵",
    "published": "✅",
}
VALID_STATUSES = ["writing", "ready_to_publish", "published"]
EDITABLE_FIELDS = ["title", "meta_title", "meta_description", "overview", "categories", "tags", "slug"]


@click.group()
@click.version_option("1.0.0", prog_name="hitpay-blog")
def cli():
    """HitPay Blog Post Generator\n\nGenerate, manage, and publish GEO-optimised blog posts for SMBs."""
    init_db()
    for d in ["writing", "ready_to_publish", "published", "exports"]:
        Path(POSTS_DIR, d).mkdir(parents=True, exist_ok=True)


@cli.command()
@click.argument("keyword")
def generate(keyword):
    """Generate a new blog post for KEYWORD.\n\nExample: hitpay-blog generate "payment methods for F&B businesses in Singapore" """
    console.print()
    console.rule(f"[bold cyan]Generating blog post[/]")
    console.print(f"[dim]Keyword:[/] [yellow]{keyword}[/]\n")

    messages = []

    def on_status(msg):
        messages.append(msg)
        console.print(f"  [dim]→[/] {msg}")

    try:
        with console.status("[bold green]Working...[/]", spinner="dots"):
            post_data = generate_blog_post(keyword, on_status=on_status)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error parsing Claude response: {e}[/]")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]Generation failed: {e}[/]")
        raise click.Abort()

    # Check for slug collision
    from src.database import get_post_by_slug
    if get_post_by_slug(post_data["slug"]):
        import time
        post_data["slug"] = f"{post_data['slug']}-{int(time.time())}"

    file_path = write_post_file(post_data)
    post_id = save_post(post_data, file_path)

    word_count = len(post_data.get("content", "").split())
    cats = ", ".join(post_data.get("categories", []))
    tags = ", ".join(post_data.get("tags", []))

    console.print()
    console.print(Panel(
        f"[bold green]Blog post created successfully![/]\n\n"
        f"  [bold]ID:[/]          #{post_id}\n"
        f"  [bold]Title:[/]       {post_data['title']}\n"
        f"  [bold]Slug:[/]        {post_data['slug']}\n"
        f"  [bold]Status:[/]      [yellow]✏️  writing[/]\n"
        f"  [bold]Words:[/]       ~{word_count}\n"
        f"  [bold]Categories:[/]  {cats}\n"
        f"  [bold]Tags:[/]        {tags}\n"
        f"  [bold]File:[/]        {file_path}",
        title=f"[bold]Post #{post_id}[/]",
        border_style="green",
        padding=(1, 2)
    ))
    console.print(f"\n[dim]Run [cyan]python main.py view {post_id}[/] to read the full post.[/]\n")


@cli.command("list")
@click.option("--status", "-s", type=click.Choice(VALID_STATUSES), help="Filter by status")
def list_cmd(status):
    """List all blog posts.\n\nFilter by status: writing, ready_to_publish, published"""
    posts = list_posts(status)

    if not posts:
        msg = f"No posts with status [yellow]{status}[/]." if status else "No posts yet."
        console.print(f"\n  {msg} Run [cyan]python main.py generate \"your keyword\"[/] to create one.\n")
        return

    title = f"HitPay Blog Posts — {status.replace('_', ' ').title()}" if status else "HitPay Blog Posts — All"

    table = Table(
        title=title,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=False,
        padding=(0, 1)
    )
    table.add_column("ID", style="dim", width=4, justify="right")
    table.add_column("Title", min_width=35, max_width=50)
    table.add_column("Keyword", style="dim", max_width=25)
    table.add_column("Status", width=20)
    table.add_column("Words", width=6, justify="right", style="dim")
    table.add_column("Date", width=12, style="dim")

    for post in posts:
        s = post["status"]
        color = STATUS_COLORS.get(s, "white")
        icon = STATUS_ICONS.get(s, "")
        label = s.replace("_", " ")

        table.add_row(
            str(post["id"]),
            post["title"],
            (post.get("keyword", "") or "")[:25],
            f"[{color}]{icon}  {label}[/]",
            str(post.get("word_count", 0)),
            (post.get("date") or "")[:10],
        )

    console.print()
    console.print(table)

    counts = {s: sum(1 for p in posts if p["status"] == s) for s in VALID_STATUSES}
    console.print(
        f"\n  [dim]Total: {len(posts)}  |  "
        f"✏️  Writing: {counts['writing']}  |  "
        f"🔵 Ready: {counts['ready_to_publish']}  |  "
        f"✅ Published: {counts['published']}[/]\n"
    )


@cli.command()
@click.argument("post_id", type=int)
def view(post_id):
    """View a blog post by ID."""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    file_path = post.get("file_path", "")
    content = read_post_content(file_path) if file_path and os.path.exists(file_path) else "[italic dim]File not found[/]"

    s = post["status"]
    color = STATUS_COLORS.get(s, "white")
    icon = STATUS_ICONS.get(s, "")
    cats = json.loads(post.get("categories") or "[]")
    tags = json.loads(post.get("tags") or "[]")

    console.print()
    console.print(Panel(
        f"[bold]{post['title']}[/]\n\n"
        f"  [dim]ID:[/] #{post['id']}    "
        f"[dim]Status:[/] [{color}]{icon}  {s.replace('_', ' ')}[/]    "
        f"[dim]Date:[/] {post.get('date', '')}    "
        f"[dim]Words:[/] ~{post.get('word_count', 0)}",
        border_style=color,
        padding=(1, 2)
    ))

    console.print(f"\n  [bold dim]SLUG[/]              {post.get('slug', '')}")
    console.print(f"  [bold dim]KEYWORD[/]           {post.get('keyword', '')}")
    console.print(f"  [bold dim]META TITLE[/]        {post.get('meta_title', '')}")
    console.print(f"  [bold dim]META DESCRIPTION[/]  {post.get('meta_description', '')}")
    console.print(f"  [bold dim]OVERVIEW[/]          {post.get('overview', '')}")
    console.print(f"  [bold dim]CATEGORIES[/]        {', '.join(cats)}")
    console.print(f"  [bold dim]TAGS[/]              {', '.join(tags)}")
    console.print(f"  [bold dim]FILE[/]              {file_path}")

    console.print()
    console.rule("[dim]Content[/]")
    console.print()

    try:
        console.print(Markdown(content))
    except Exception:
        console.print(content)

    console.print()


@cli.command()
@click.argument("post_id", type=int)
@click.option("--field", "-f", type=click.Choice(EDITABLE_FIELDS + ["content"]), help="Field to edit directly")
@click.option("--editor", "-e", is_flag=True, help="Open full file in system editor ($EDITOR or nano)")
def edit(post_id, field, editor):
    """Edit a blog post.\n\nUse --editor to open the markdown file in your system editor.\nUse --field to edit a specific metadata field inline."""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    file_path = post.get("file_path", "")

    if editor or field == "content":
        editor_cmd = os.environ.get("EDITOR", "nano")
        if not file_path or not os.path.exists(file_path):
            console.print(f"[red]File not found: {file_path}[/]")
            raise click.Abort()
        subprocess.run([editor_cmd, file_path])
        console.print(f"[green]✓ Opened in {editor_cmd}.[/] Changes saved to {file_path}")
        return

    if field:
        _inline_edit(post_id, post, field, file_path)
    else:
        # Interactive menu
        console.print(f"\n[bold]Edit Post #{post_id}: {post['title']}[/]\n")
        for i, f in enumerate(EDITABLE_FIELDS, 1):
            current = post.get(f, "")
            if f in ("categories", "tags"):
                current = ", ".join(json.loads(current or "[]"))
            console.print(f"  [cyan]{i}.[/] [bold]{f}[/]  [dim]{str(current)[:60]}[/]")
        console.print(f"  [cyan]{len(EDITABLE_FIELDS)+1}.[/] [bold]content[/]  [dim](opens in editor)[/]")
        console.print(f"  [cyan]0.[/] Cancel\n")

        choice = click.prompt("Edit field", type=int, default=0)
        if choice == 0:
            return
        if choice == len(EDITABLE_FIELDS) + 1:
            editor_cmd = os.environ.get("EDITOR", "nano")
            subprocess.run([editor_cmd, file_path])
            console.print(f"[green]✓ Saved.[/]")
        elif 1 <= choice <= len(EDITABLE_FIELDS):
            _inline_edit(post_id, post, EDITABLE_FIELDS[choice - 1], file_path)


def _inline_edit(post_id: int, post: dict, field: str, file_path: str):
    current = post.get(field, "")
    if field in ("categories", "tags"):
        current = ", ".join(json.loads(current or "[]"))

    console.print(f"\n[bold]Current {field}:[/] [dim]{current}[/]")
    new_val = Prompt.ask(f"New value", default=current)

    if new_val == current:
        console.print("[dim]No change.[/]")
        return

    db_val = new_val
    if field in ("categories", "tags"):
        db_val = json.dumps([v.strip() for v in new_val.split(",") if v.strip()])

    # Update DB
    update_post_fields(post_id, {field: db_val})

    # Update file frontmatter
    if file_path and os.path.exists(file_path):
        file_update = {field: new_val}
        if field in ("categories", "tags"):
            file_update[field] = [v.strip() for v in new_val.split(",") if v.strip()]
        update_post_file(file_path, file_update)

    console.print(f"[green]✓ {field} updated.[/]")


@cli.command()
@click.argument("post_id", type=int)
@click.argument("new_status", type=click.Choice(VALID_STATUSES), metavar="STATUS")
def status(post_id, new_status):
    """Update the status of a post.\n\nSTATUS: writing | ready_to_publish | published"""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    old_status = post["status"]
    if old_status == new_status:
        console.print(f"[yellow]Post #{post_id} is already '{new_status}'.[/]")
        return

    old_file = post.get("file_path", "")
    slug = post["slug"]

    # Move file to new status folder
    if old_file and os.path.exists(old_file):
        new_file = move_post_file(old_file, new_status, slug)
    else:
        # Just build the new path even if old file doesn't exist
        new_file = str(Path(POSTS_DIR) / new_status / f"{slug}.md")

    update_post_status(post_id, new_status, old_file, new_file)

    color = STATUS_COLORS.get(new_status, "white")
    icon = STATUS_ICONS.get(new_status, "")
    console.print(
        f"[green]✓ Post #{post_id}[/] status: "
        f"[dim]{old_status}[/] → [{color}]{icon}  {new_status}[/]"
    )


@cli.command()
@click.argument("post_id", type=int, required=False)
@click.option("--all", "export_all", is_flag=True, help="Export ALL ready/published posts as one bulk CSV for Framer.")
@click.option("--status", "-s", type=click.Choice(VALID_STATUSES), default=None,
              help="Filter by status when using --all (default: ready_to_publish + published).")
@click.option("--format", "fmt", type=click.Choice(["markdown", "csv"]), default="csv", show_default=True,
              help="Export format. CSV is optimised for Framer CMS import.")
def export(post_id, export_all, status, fmt):
    """Export posts for Framer CMS bulk import.

    Single post:   python main.py export 3
    Bulk export:   python main.py export --all
    By status:     python main.py export --all --status ready_to_publish
    """
    from src.post_writer import export_bulk_to_csv

    if export_all:
        # Bulk export — default to ready_to_publish + published
        if status:
            posts = list_posts(status)
        else:
            posts = [p for p in list_posts() if p["status"] in ("ready_to_publish", "published")]

        if not posts:
            console.print("[yellow]No posts found to export.[/]")
            return

        pairs = []
        skipped = 0
        for post in posts:
            fp = post.get("file_path", "")
            if fp and os.path.exists(fp):
                pairs.append((post, fp))
            else:
                skipped += 1

        csv_path = export_bulk_to_csv(pairs)

        console.print(f"\n[green]✓ Bulk export complete[/]")
        console.print(f"  [bold]Posts exported:[/] {len(pairs)}")
        if skipped:
            console.print(f"  [yellow]Skipped (file missing):[/] {skipped}")
        console.print(f"  [bold]File:[/] {csv_path}")
        console.print(f"\n  [dim]Import via Framer CMS → Collections → your blog collection → ··· → Import CSV[/]\n")
        return

    # Single post export
    if not post_id:
        console.print("[red]Provide a post ID or use --all for bulk export.[/]")
        raise click.Abort()

    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    file_path = post.get("file_path", "")

    if fmt == "csv":
        if not file_path or not os.path.exists(file_path):
            console.print(f"[red]Post file not found at: {file_path}[/]")
            raise click.Abort()
        csv_path = export_to_csv(post, file_path)
        console.print(f"\n[green]✓ Exported to Framer CMS CSV:[/] {csv_path}")
        console.print(f"[dim]Import via Framer CMS → Collections → your blog collection → ··· → Import CSV[/]\n")
    else:
        console.print(f"\n[green]✓ Markdown file:[/] {file_path}\n")


@cli.command()
@click.argument("competitors", nargs=-1, metavar="[COMPETITOR...]")
@click.option("--list-available", "-l", is_flag=True, help="List available competitors to scrape")
def research(competitors, list_available):
    """Scrape competitor websites to build the research database.

    Run without arguments to scrape all competitors.
    Pass specific names to scrape only those: research stripe adyen xendit

    Available: stripe, adyen, airwallex, 2c2p, paypal, xendit, maya, paymongo
    """
    if list_available:
        console.print("\n[bold]Available competitors:[/]")
        available = ["stripe", "adyen", "airwallex", "2c2p", "paypal", "xendit", "maya", "paymongo"]
        for c in available:
            from pathlib import Path
            exists = Path(f"competitors/{c}.json").exists()
            status = "[green]✓ scraped[/]" if exists else "[dim]not yet scraped[/]"
            console.print(f"  [cyan]{c}[/]  {status}")
        console.print()
        return

    from competitor_scraper import main as run_scraper, COMPETITOR_URLS

    targets = list(competitors) if competitors else None

    if targets:
        invalid = [t for t in targets if t not in COMPETITOR_URLS]
        if invalid:
            console.print(f"[red]Unknown competitors: {', '.join(invalid)}[/]")
            console.print(f"[dim]Available: {', '.join(COMPETITOR_URLS.keys())}[/]")
            return
        console.print(f"\n[bold cyan]Scraping:[/] {', '.join(targets)}\n")
    else:
        console.print(f"\n[bold cyan]Scraping all {len(COMPETITOR_URLS)} competitors...[/]\n")
        console.print("[dim]This will take several minutes. Sit tight.[/]\n")

    with console.status("[bold green]Scraping competitor websites...[/]", spinner="dots"):
        run_scraper(targets)

    # Show summary
    from src.competitor_db import get_index
    index = get_index()

    table = Table(title="Competitor Research Database", border_style="cyan", header_style="bold cyan")
    table.add_column("Competitor", min_width=15)
    table.add_column("Markets")
    table.add_column("Positioning")
    table.add_column("Updated", width=12)

    for key, info in index.items():
        table.add_row(
            info.get("name", key),
            ", ".join((info.get("markets") or [])[:3]),
            (info.get("positioning") or "")[:60],
            info.get("last_updated", ""),
        )

    console.print()
    console.print(table)


@cli.command()
@click.argument("post_id", type=int)
def delete(post_id):
    """Delete a blog post and its file."""
    post = get_post(post_id)
    if not post:
        console.print(f"[red]Post #{post_id} not found.[/]")
        raise click.Abort()

    console.print(f"\n  [bold]Title:[/] {post['title']}")
    console.print(f"  [bold]File:[/]  {post.get('file_path', '')}\n")

    if not Confirm.ask("[red]Delete this post permanently?[/]"):
        console.print("[dim]Cancelled.[/]")
        return

    file_path = post.get("file_path", "")
    delete_post(post_id)

    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    console.print(f"[green]✓ Post #{post_id} deleted.[/]")
