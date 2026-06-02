"""
hitpay-content-reference MCP Server

Exposes curated HitPay content knowledge as MCP tools for use by the marketing
team in Claude Desktop or any MCP-compatible client.

Run locally (stdio — for Claude Desktop):
    python hitpay_content_reference_mcp.py

Run as shared HTTP server:
    python hitpay_content_reference_mcp.py sse

Vercel deployment:
    The `app` export at the bottom is the ASGI entry point.
    Configure vercel.json to route /api/mcp → this file.
    Marketing team connects Claude Desktop to:
    https://<your-project>.vercel.app/api/mcp
"""

import json
import re
import sys
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

from src.brand_config import get_brand_config
from src.competitor_db import format_for_prompt, get_relevant_competitors
from src.external_links import EXTERNAL_LINKS

BASE_DIR = Path(__file__).parent

mcp = FastMCP("hitpay-content-reference")


def _score_sections(content: str, topic: str, max_chars: int = 15000) -> str:
    """Return the most topic-relevant markdown sections from a document."""
    sections = re.split(r'\n(?=## )', content)
    terms = [t.lower() for t in re.split(r'\W+', topic) if len(t) > 2]
    scored = [(sum(s.lower().count(t) for t in terms), s) for s in sections]
    scored = [(score, s) for score, s in scored if score > 0]
    scored.sort(reverse=True)

    parts, total = [], 0
    for _, section in scored:
        if total + len(section) > max_chars:
            break
        parts.append(section.strip())
        total += len(section)
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def get_product_facts(topic: str, market: str = "SEA", brand: str = "hitpay") -> str:
    """
    Return verified HitPay product facts, payment rates, and features for a topic and market.

    Use this before writing any content that references HitPay rates, payment methods,
    supported markets, fees, or product capabilities. Never guess — always pull from here.

    Args:
        topic:  What you need facts about (e.g. "PayNow rates", "invoicing", "Shopify integration")
        market: SG | MY | PH | SEA  (default: SEA)
        brand:  hitpay | smegrowthhub  (default: hitpay)
    """
    try:
        config = get_brand_config(brand)
    except ValueError as e:
        return str(e)

    docs_path = BASE_DIR / config.docs_file
    if not docs_path.exists():
        return f"Docs file not found: {config.docs_file}"

    content = docs_path.read_text(encoding="utf-8")
    search_query = f"{topic} {market}" if market.upper() != "SEA" else topic
    result = _score_sections(content, search_query)

    if not result:
        return f"No sections found in {config.docs_file} matching '{topic}' for market '{market}'."

    return f"# Product Facts — {topic} ({market.upper()})\nSource: {config.docs_file}\n\n{result}"


@mcp.tool()
def search_competitors(keyword: str, market: str = None) -> str:
    """
    Return competitor profiles relevant to a keyword and optional market.

    Includes pricing, payment methods, features, and positioning. Use for comparison
    articles, competitor pages, or any content that references alternatives to HitPay.
    All competitor links require rel="nofollow" in published content.

    Args:
        keyword: Topic or product area (e.g. "payment gateway", "QR payments", "BNPL")
        market:  Optional — SG | MY | PH  (omit for SEA-wide results)
    """
    competitors = get_relevant_competitors(keyword, market=market)
    if not competitors:
        return "No competitor profiles found matching that keyword and market."
    return format_for_prompt(competitors)


@mcp.tool()
def get_approved_links(market: str = "SEA", link_type: str = "all") -> str:
    """
    Return curated, approved external links for use as citations in content.

    These are pre-vetted authoritative sources — regulators, official payment method
    pages, integration docs, research bodies, and competitor homepages. Always use
    these rather than finding your own sources, to ensure accuracy and avoid hallucinated URLs.

    Args:
        market:    SG | MY | PH | SEA  (default: SEA)
        link_type: regulators | payment_methods | integrations | research | competitors | competitor_articles | all
    """
    market = market.upper()
    if market not in EXTERNAL_LINKS:
        market = "SEA"

    links_data = EXTERNAL_LINKS[market]
    sections = []

    type_map = {
        "regulators": ("regulators", "## Regulators"),
        "payment_methods": ("payment_methods", "## Payment Methods"),
        "integrations": ("integrations", "## Integrations"),
        "research": ("research", "## Research & Statistics"),
        "competitors": ("competitors", "## Competitors (rel=nofollow, comparison articles only)"),
    }

    for key, (data_key, heading) in type_map.items():
        if link_type not in ("all", key):
            continue
        links = links_data.get(data_key, [])
        if not links:
            continue
        lines = []
        for l in links:
            use_when = f" — Use when: {l['use_when']}" if l.get("use_when") else ""
            lines.append(f"- [{l['name']}]({l['url']}){use_when}")
        sections.append(f"{heading}\n" + "\n".join(lines))

    if link_type in ("all", "competitor_articles"):
        db_path = BASE_DIR / "external_links_db.json"
        if db_path.exists():
            db = json.loads(db_path.read_text())
            articles = [
                a for a in db.get("articles", [])
                if market == "SEA" or market in a.get("markets", [])
            ]
            if articles:
                lines = [
                    f"- [{a['title']}]({a['url']}) — Topics: {', '.join(a.get('topics', []))}"
                    for a in articles[:15]
                ]
                sections.append("## Competitor Articles (for research/comparison context)\n" + "\n".join(lines))

    if not sections:
        return f"No links found for market='{market}', type='{link_type}'."

    return f"# Approved Links — {market} ({link_type})\n\n" + "\n\n".join(sections)


@mcp.tool()
def get_blog_links(topic: str, brand: str = "hitpay") -> str:
    """
    Return approved internal blog post URLs relevant to a topic, for use as cross-links.

    These are verified live URLs — safe to link to without risk of 404s or hallucinated slugs.
    Use these whenever adding internal links to blog posts, landing pages, or email content.

    Args:
        topic: Content topic to match (e.g. "PayNow", "invoicing", "ecommerce", "Shopify")
        brand: hitpay | smegrowthhub  (default: hitpay)
    """
    try:
        config = get_brand_config(brand)
    except ValueError as e:
        return str(e)

    links_path = BASE_DIR / config.blog_links_file
    if not links_path.exists():
        return f"Blog links file not found: {config.blog_links_file}"

    with open(links_path, "r") as f:
        data = yaml.safe_load(f)

    posts = data.get("posts", []) if data else []
    if not posts:
        return "No blog links found."

    terms = [t.lower() for t in re.split(r'\W+', topic) if len(t) > 2]
    scored = []
    for post in posts:
        post_text = " ".join([
            post.get("title", ""),
            " ".join(post.get("topics", [])),
            " ".join(post.get("markets", [])),
        ]).lower()
        score = sum(post_text.count(t) for t in terms)
        if score > 0:
            scored.append((score, post))

    scored.sort(reverse=True)
    top = [p for _, p in scored[:10]]

    if not top:
        return f"No blog links found matching '{topic}' for brand '{brand}'."

    lines = []
    for post in top:
        markets = ", ".join(post.get("markets", [])) or "All markets"
        topics = ", ".join(post.get("topics", []))
        lines.append(f"- [{post['title']}]({post['url']})\n  Markets: {markets} | Topics: {topics}")

    return f"# Internal Blog Links — {topic} ({brand})\n\n" + "\n".join(lines)


@mcp.tool()
def get_brand_guidelines(brand: str = "hitpay") -> str:
    """
    Return the writing guidelines, tone rules, and brand voice for content creation.

    Read this before writing any content — it defines what words to avoid, how to
    reference HitPay, GEO rules for markets, and the overall editorial philosophy.

    Args:
        brand: hitpay | smegrowthhub  (default: hitpay)
    """
    file_map = {
        "hitpay": "hitpay_brand_guidelines.md",
        "smegrowthhub": "smegrowthhub_writing_philosophy.md",
    }

    filename = file_map.get(brand)
    if not filename:
        return f"Unknown brand: {brand!r}. Must be 'hitpay' or 'smegrowthhub'."

    path = BASE_DIR / filename
    if not path.exists():
        return f"Brand guidelines file not found: {filename}"

    return path.read_text(encoding="utf-8")


# Vercel ASGI entry point.
# Mounts FastMCP's /mcp handler under /api so Vercel routes
# /api/mcp → this app → /mcp handler correctly.
app = Starlette(routes=[Mount("/api", app=mcp.streamable_http_app())])

if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    mcp.run(transport=transport)
