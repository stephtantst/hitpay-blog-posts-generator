import anthropic
import json
import re
import time
from datetime import date
from pathlib import Path
from slugify import slugify
import yaml
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL


def _messages_create_with_retry(client, max_retries=4, **kwargs):
    """Call client.messages.create with exponential backoff on overloaded errors."""
    for attempt in range(max_retries):
        try:
            return client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                time.sleep(wait)
                continue
            raise
from src.mcp_client import search_knowledge, get_changelog, get_news
from src.competitor_db import get_relevant_competitors, format_for_prompt


def _load_relevant_docs(keyword: str, max_chars: int = 30000) -> str:
    """Pull sections from hitpay_docs.md that are relevant to the keyword."""
    docs_path = Path(__file__).parent.parent / "hitpay_docs.md"
    if not docs_path.exists():
        return ""

    with open(docs_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split into sections by ## headers
    raw_sections = re.split(r'\n(?=## )', content)

    # Score each section by how many keyword terms appear in it
    terms = [t.lower() for t in re.split(r'\W+', keyword) if len(t) > 2]
    scored = []
    for section in raw_sections:
        text_lower = section.lower()
        score = sum(text_lower.count(t) for t in terms)
        if score > 0:
            scored.append((score, section))

    scored.sort(key=lambda x: x[0], reverse=True)

    parts = []
    total = 0
    for _, section in scored:
        if total + len(section) > max_chars:
            break
        parts.append(section.strip())
        total += len(section)

    if not parts:
        return ""

    return "\n\n---\n\n".join(parts)


def _load_blog_links() -> list[dict]:
    """Load the HitPay blog post reference links from blog_links.yaml."""
    links_path = Path(__file__).parent.parent / "blog_links.yaml"
    if not links_path.exists():
        return []
    with open(links_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("posts", [])

BLOG_SYSTEM_PROMPT = """You are a senior content strategist and writer for HitPay, a payment platform for SMEs across Southeast Asia, licensed by MAS (Singapore). Your role is to create blog posts that genuinely help small business owners grow and manage their businesses — not to sell HitPay's product.

## Writing Philosophy
- Lead with the reader's PROBLEM, not HitPay's features
- Write like a trusted advisor who has seen hundreds of SMBs succeed and struggle
- Bring real operational insight: cash flow timing, customer behaviour, reconciliation headaches, chargeback stress
- Reference HitPay naturally and sparingly — it should feel like a useful tool, not the hero of every paragraph
- Never write marketing copy. Never use words like "seamlessly", "unlock", "revolutionise", "game-changer", "cutting-edge"
- Use specific, concrete examples. "A Petaling Jaya café that accepts Touch 'n Go" beats "businesses across Malaysia"
- Short sentences. Active voice. Confident, direct tone
- Write at the intelligence level of a busy business owner who reads fast and needs to act

## About HitPay (factual reference only)
- Singapore-headquartered, MAS-licensed payment gateway (PS20200643)
- Operates across 11 markets in Southeast Asia including Singapore, Malaysia, Philippines
- No monthly fees, no setup fees — pay per transaction only
- Next business day payouts in SG (SGD), MY (MYR), and PH (PHP) for domestic transactions; T+3 for cross-border payments
- Free to sign up, approved in 1–3 business days
- 50+ payment methods, 700+ wallets globally
- PCI DSS compliant

## Payment Methods by Market (name-check accurately)
| Type | Singapore 🇸🇬 | Malaysia 🇲🇾 | Philippines 🇵🇭 |
|---|---|---|---|
| QR / Instant | PayNow | DuitNow QR | QR Ph |
| Bank transfer | PayNow | FPX | InstaPay / PESONet |
| Wallet | GrabPay, ShopeePay | Touch 'n Go, Boost, GrabPay | GCash, Maya |
| BNPL | Atome, ShopBack PayLater | Atome, ShopBack PayLater, Grab PayLater, SPayLater | — |
| Cards | Visa, Mastercard, Amex | Visa, Mastercard | Visa, Mastercard |
| Tourist/Cross-border | WeChat Pay | Alipay+, WeChat Pay | Alipay+, WeChat Pay |

## Cross-Border Payment Acceptance
HitPay lets merchants accept payments from international customers using their home-country apps — no currency exchange needed at the point of sale.

| Market | Cross-border methods accepted |
|---|---|
| Singapore 🇸🇬 | PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), DuitNow (Malaysia), QRIS (Indonesia), QR Ph (Philippines), WeChatPay (China), UPI (India), KakaoPay/PayCo/LINE Pay (South Korea) | Note: Alipay+ is NOT available in Singapore |
| Malaysia 🇲🇾 | QRIS (Indonesia), QR Ph (Philippines), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea) |
| Philippines 🇵🇭 | PayNow (Singapore), QRIS (Indonesia), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea), DuitNow (Malaysia) |

Cross-border activation: partner providers process activation within 3–5 business days after submission.

## GEO Rules (always apply)
1. When naming a payment method, name the equivalent for all three markets (SG/MY/PH)
2. Use specific local references — name a district, landmark, or city per market (e.g. Tanjong Pagar, Bangsar, BGC)
3. "50+ payment methods" — never "700+" (that's wallets)
4. Never state a specific card transaction rate — write "see hitpayapp.com/pricing"
5. Never fabricate testimonials or statistics. If you use a stat, it must come from the provided knowledge base context
6. Payouts: domestic transactions settle next business day in SG, MY & PH; cross-border payments settle T+3. Always distinguish between the two when relevant.
7. FAQ questions must mirror how a user would type into a search engine or AI assistant (e.g. "How do I...", "What is...", "Is there a fee...") — direct question phrasing, not third person

## Blog Post Format
Write for SMBs growing their business. The post must:
- Be 900–1200 words of actual content (excluding the FAQ section)
- Have a compelling, empathetic intro that immediately names the reader's core problem
- Include 3–5 H2 sections with practical, actionable insights
- Use H3 sparingly for sub-points
- Reference HitPay in 1–2 sections only (naturally, not forced)
- End with a concrete, practical takeaway — not a sales CTA
- NOT include an H1 title (added separately by the CMS)
- NOT include a "by HitPay" or "Published by" line

## AEO Optimisation (AI Answer Engine — apply to every article without exception)

### Structure requirements
1. **Quick Answer block (REQUIRED — always first)** — The very first element of every article, before the intro paragraphs, must be a bold-prefixed block in this exact format:

   `**Quick Answer:** [2–3 sentences that directly answer the article's primary query. Must name HitPay as the solution and mention the relevant markets (SG/MY/PH). Must be self-contained — an AI or search engine should be able to read it alone and fully answer the query.]`

   Do not place any text before this block. It comes immediately after the implicit H1 title, before any introductory prose.

2. **H2 and H3 as natural-language questions** — rewrite every section heading as a question a user would actually type or speak. Examples:
   - ✅ "What payment methods does a Singapore POS system need to support?"
   - ❌ "Payment Methods Overview"

3. **FAQ section (REQUIRED)** — close every article with a `## Frequently Asked Questions` section containing at least 5 Q&A pairs. Requirements:
   - At least one question targeting each relevant market (SG, MY, PH)
   - At least one beginner-level question
   - At least one comparison-intent question (e.g. "HitPay vs X — which is better for…")
   - Each answer must open with the direct answer (yes/no + one sentence), then elaborate. Never bury the answer.
   - Each answer must be a complete standalone paragraph — AI engines may extract the answer without the question.
   - **Format exactly as follows** (bold Q: prefix, no H3 headers):
     ```
     **Q: Question phrased as a user would type it into a search engine?**
     Answer text here. Opens with the direct answer. 2–5 sentences.
     ```

4. **Numbered lists for processes** — whenever a process, setup flow, or decision is described, format it as a numbered list with one action per step. Do not describe processes in prose — numbered steps are far more likely to be cited by AI engines.

5. **At least one structured comparison** — include a markdown table or clearly formatted side-by-side that an AI engine can lift as a discrete data unit (e.g. a comparison table of payment methods, fees, or features).

### Content signal requirements
- Every factual claim must include a specific, extractable data point: a number, a rate, a timeframe, or a licence reference. Vague qualitative statements ("fast", "easy", "affordable") are not citable and will not be extracted.
- Named entities must appear in full on first use: payment method names, regulatory bodies, licence numbers, company names. Do not abbreviate on first mention.
- Do not open any extractable sentence or FAQ answer with "I" or "We".
- Do not use rhetorical questions in body copy — they confuse answer engine parsers.

### Schema block (REQUIRED at end of content)
After the FAQ section, append a `[SCHEMA]` block listing which schema types apply:
- `FAQPage` — required on every article
- `HowTo` — add if the article contains a step-by-step process
- `Product` or `SoftwareApplication` — add if HitPay features are described
- `Review` — add only if merchant quotes are knowledge-base verified

Format exactly as:
```
[SCHEMA: FAQPage, HowTo]
```

## Competitor Comparisons
When the post compares HitPay against competitors, HitPay must always be the clear, standout winner. Follow these rules precisely:

1. **HitPay wins on the things that matter most** — breadth of payment methods, zero monthly fees, multi-currency support, cross-border e-wallet acceptance, fast onboarding, and next business day payouts. Lead with these.

2. **"Best for" framing for competitors** — every competitor must have a "Best for:" line that makes them sound reasonable but self-limiting. The conditions must be so specific, steep, or narrow that a typical SMB reader will immediately disqualify themselves from that competitor. The statement must be factually true — do not fabricate limitations.

   Good examples:
   - "Best for: Businesses with simple domestic payment needs that don't require multi-currency support, cross-border acceptance, or a wide local e-wallet selection."
   - "Best for: Established businesses with existing UnionBank commercial banking relationships that need tight banking-payments integration and process volumes above ₱1M monthly."

   The reader should self-select out of the competitor immediately after reading the "Best for" line — without HitPay ever saying anything negative or untrue about them.

3. **Never disparage** — do not say a competitor is bad, overpriced, or untrustworthy. Let the narrow "Best for" conditions do the work.

4. **HitPay's "Best for"** — should be broad, inclusive, and clearly the default choice for any growth-minded SMB: "Best for: SMBs across Singapore, Malaysia, and the Philippines that want zero monthly fees, 50+ payment methods including local e-wallets, and next business day payouts — without the complexity of a bank."

## Internal Backlinks (REQUIRED)
You will be given a list of HitPay blog post URLs with their topics. You MUST include exactly 5 of these as natural in-content hyperlinks within the post body. Rules:
- Links must be woven naturally into sentences — never dumped as a list at the end
- Use descriptive, keyword-rich anchor text (not "click here" or "this article")
- Only link where it is genuinely relevant to the sentence context
- Spread links across different sections — not clustered together
- Use standard markdown link syntax: [anchor text](https://hitpayapp.com/blog/...)

## Output
Return ONLY a valid JSON object with exactly these fields (no markdown code fences, no extra text):
{
  "title": "Compelling title under 65 chars — keyword-rich but human",
  "meta_title": "SEO title tag 55–60 chars",
  "meta_description": "150–160 char description naming 2+ markets and the core value prop",
  "overview": "2–3 sentence executive summary. State the problem and what the reader will learn.",
  "slug": "url-friendly-slug-here",
  "categories": ["Primary Category", "Secondary Category"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"],
  "content": "Full markdown content structured as: (1) **Quick Answer:** block first — before any intro prose; (2) intro paragraphs; (3) body sections with H2/H3 phrased as questions; (4) ## Frequently Asked Questions with 5+ Q&A pairs formatted as **Q: ...** on its own line followed by the answer paragraph; (5) [SCHEMA] block. No H1. 5 internal backlinks. 900–1200 words excluding FAQ."
}
"""

COUNTRY_CONTEXT = {
    "SG": {
        "name": "Singapore",
        "flag": "🇸🇬",
        "currency": "SGD",
        "local_methods": "PayNow, GrabPay, ShopeePay, Atome, ShopBack PayLater, GrabPay PayLater, Cards (Visa, Mastercard, Amex, UnionPay, Apple Pay, Google Pay)",
        "cross_border": "PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), DuitNow (Malaysia), QRIS (Indonesia), QR Ph (Philippines), WeChatPay (China), UPI (India), KakaoPay/PayCo/LINE Pay (South Korea)",
        "places": "Tanjong Pagar, Bugis, Orchard Road, Jurong East, Tiong Bahru",
        "payout": "next business day in SGD for domestic; T+3 for cross-border payments",
        "avoid": [
            "FPX, Touch 'n Go, Boost, MayBank QR — these are Malaysia-only methods",
            "GCash, Maya, PESONet, InstaPay, QR Ph (as a local method) — Philippines-only",
            "Do not use DuitNow as a local SG payment method (it's cross-border only from SG)",
            "Alipay+ is NOT available in Singapore — do not mention it as a SG payment method",
        ],
    },
    "MY": {
        "name": "Malaysia",
        "flag": "🇲🇾",
        "currency": "MYR",
        "local_methods": "DuitNow QR, FPX, Touch 'n Go, GrabPay, ShopeePay, Boost, MayBank QR, WeChat Pay, Atome, ShopBack PayLater, GrabPay PayLater, AliPay, Cards (Visa, Mastercard)",
        "cross_border": "QRIS (Indonesia), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea)",
        "places": "Bangsar, Petaling Jaya, KLCC, Johor Bahru, Bukit Bintang",
        "payout": "next business day in MYR for domestic; T+3 for cross-border payments",
        "avoid": [
            "PayNow — Singapore-only; do not present as a MY method",
            "GCash, Maya, QR Ph, PESONet, InstaPay — Philippines-only",
            "Do not use QR Ph or PayNow as local MY payment examples",
        ],
    },
    "PH": {
        "name": "Philippines",
        "flag": "🇵🇭",
        "currency": "PHP",
        "local_methods": "QR Ph, GCash, Maya, Cards (Visa, Mastercard, online and in-person), ShopeePay, SPayLater, UnionBank Online, PESONet, InstaPay, BillEase, GrabPay, over-the-counter (Bayad, ECPay, Palawan)",
        "cross_border": "PayNow (Singapore), QRIS (Indonesia), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea), DuitNow (Malaysia)",
        "places": "BGC (Bonifacio Global City), Makati, Quezon City, Cebu, Davao",
        "payout": "next business day in PHP for domestic; T+3 for cross-border payments",
        "avoid": [
            "PayNow — Singapore-only; do not use as a PH payment method",
            "FPX, Touch 'n Go, Boost — Malaysia-only",
            "Do not present DuitNow as a local PH method (cross-border only)",
        ],
    },
}


def generate_blog_post(keyword: str, country: str = None, on_status=None) -> dict:
    """Generate a blog post for the given keyword.

    Args:
        keyword: The topic/keyword to write about
        on_status: Optional callback(message: str) for progress updates
    """
    def status(msg):
        if on_status:
            on_status(msg)

    # Step 1: Gather MCP knowledge
    status("Querying HitPay knowledge base...")
    mcp_context = _gather_mcp_context(keyword, status)

    # Step 1c: Load relevant product docs
    status("Loading relevant product documentation...")
    product_docs = _load_relevant_docs(keyword)
    if product_docs:
        status("Found relevant sections in product docs")

    # Step 1b: Load relevant competitor data
    status("Loading competitor research...")
    country_name = COUNTRY_CONTEXT[country]["name"] if country and country in COUNTRY_CONTEXT else None
    competitors = get_relevant_competitors(keyword, market=country_name)
    competitor_context = format_for_prompt(competitors) if competitors else ""
    if competitors:
        status(f"Found data for {len(competitors)} relevant competitors")

    # Step 2: Build blog links reference — filtered to target market
    blog_links = _load_blog_links()
    links_section = ""
    if blog_links:
        # Keep links that match the target market, SEA (always relevant), or have no market tag.
        # Exclude links specific to OTHER markets to avoid cross-market backlink errors.
        other_markets = {"SG", "MY", "PH"} - ({country} if country else set())
        def _link_ok(link):
            markets = link.get("markets", [])
            if not markets:
                return True
            for m in markets:
                if m in ("SEA", "Global") or m == country:
                    return True
            # Exclude if ALL market tags are for other specific markets
            return not any(m in other_markets for m in markets) or any(
                m in ("SEA", "Global") for m in markets
            )
        filtered_links = [l for l in blog_links if _link_ok(l)]
        links_section = "\n## HitPay URLs — Use 5 as Internal Backlinks\n"
        links_section += f"Market: {country or 'SEA'}. Pick the 5 most relevant URLs. Link naturally in-content — never dump as a list.\n\n"
        for link in filtered_links:
            topics_str = ", ".join(link.get("topics", []))
            markets_str = "/".join(link.get("markets", []))
            links_section += f"- [{link['title']}]({link['url']}) [{markets_str}] — {topics_str}\n"

    # Step 2b: Build country-specific context
    country_section = ""
    if country and country in COUNTRY_CONTEXT:
        ctx = COUNTRY_CONTEXT[country]
        avoid_list = "\n".join(f"  - {r}" for r in ctx["avoid"])
        country_section = f"""
## Country Focus: {ctx['flag']} {ctx['name']} ({country}) — STRICT REQUIREMENT
This post must be written EXCLUSIVELY for the {ctx['name']} market.

Local payment methods to reference: {ctx['local_methods']}
Cross-border methods available to {ctx['name']} merchants: {ctx['cross_border']}
Currency: {ctx['currency']}
Payout: {ctx['payout']}
Place name examples: {ctx['places']}

FACT CHECK — Do NOT include these market mismatches:
{avoid_list}

Before returning your JSON, verify every payment method name, currency, and place name is correct for {ctx['name']}. Correct any mismatches.
"""
        status(f"Country focus set to {ctx['flag']} {ctx['name']}")

    # Step 3: Generate with Claude
    status("Generating blog post with Claude Opus...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    docs_section = f"\n## HitPay Product Documentation — Feature & Flow Accuracy\n{product_docs}\n" if product_docs else ""

    user_prompt = f"""Write a blog post about: "{keyword}"
{country_section}
## HitPay Knowledge Base — Use for Factual Accuracy
{mcp_context}
{docs_section}
{competitor_context}
{links_section}
Ground your post in the knowledge base and product documentation above. If they contain specific features, merchant use cases, flows, or product details relevant to this topic, incorporate them naturally. Do not invent facts or statistics not present in these sources or the system prompt.

Remember: include exactly 5 internal backlinks from the URL list above, woven naturally into the content.

Return the JSON object now."""

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=BLOG_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    try:
        post_data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Response was truncated or malformed (max_tokens may be too low). JSON error: {e}")

    # Add metadata
    post_data["date"] = date.today().isoformat()
    post_data["keyword"] = keyword
    post_data["country"] = country or ""
    post_data["status"] = "generated"

    # Ensure slug is clean
    if not post_data.get("slug"):
        post_data["slug"] = slugify(post_data["title"])
    else:
        post_data["slug"] = slugify(post_data["slug"])

    return post_data


def _scrape_blog_url(url: str) -> dict:
    """Fetch a HitPay blog page and return {title, keyword, content} as plain text."""
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(url, timeout=20, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (compatible; HitPayRewriter/1.0)"
    })
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Remove nav, footer, scripts, styles
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Try to find the article title
    title = ""
    for sel in ["h1", "article h2", ".post-title", ".entry-title", "title"]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break

    # Try to find the main article body
    body_el = soup.select_one("article") or soup.select_one("main") or soup.body
    content = body_el.get_text(separator="\n", strip=True) if body_el else soup.get_text(separator="\n", strip=True)

    # Derive keyword from title (strip common suffixes)
    keyword = title or url.split("/")[-1].replace("-", " ").strip()

    return {"title": title, "keyword": keyword, "content": content}


def rewrite_blog_post(url: str, country: str = None, on_status=None) -> dict:
    """Scrape an existing blog post URL and rewrite it with all optimisation directives.

    Args:
        url: Public URL of the existing HitPay blog post
        country: Optional market code (SG/MY/PH) to lock the rewrite to a market
        on_status: Optional callback(message: str) for progress updates
    """
    def status(msg):
        if on_status:
            on_status(msg)

    status("Fetching existing blog post...")
    scraped = _scrape_blog_url(url)
    keyword = scraped["keyword"]
    existing_title = scraped["title"]
    existing_content = scraped["content"]
    status(f"Fetched: \"{existing_title}\"")

    # Gather the same enrichment context as a fresh generate
    status("Querying HitPay knowledge base...")
    mcp_context = _gather_mcp_context(keyword, status)

    status("Loading relevant product documentation...")
    product_docs = _load_relevant_docs(keyword)
    if product_docs:
        status("Found relevant sections in product docs")

    status("Loading competitor research...")
    country_name = COUNTRY_CONTEXT[country]["name"] if country and country in COUNTRY_CONTEXT else None
    competitors = get_relevant_competitors(keyword, market=country_name)
    competitor_context = format_for_prompt(competitors) if competitors else ""
    if competitors:
        status(f"Found data for {len(competitors)} relevant competitors")

    blog_links = _load_blog_links()
    links_section = ""
    if blog_links:
        other_markets = {"SG", "MY", "PH"} - ({country} if country else set())
        def _link_ok_rw(link):
            markets = link.get("markets", [])
            if not markets:
                return True
            for m in markets:
                if m in ("SEA", "Global") or m == country:
                    return True
            return not any(m in other_markets for m in markets) or any(
                m in ("SEA", "Global") for m in markets
            )
        filtered_links = [l for l in blog_links if _link_ok_rw(l)]
        links_section = "\n## HitPay URLs — Use 5 as Internal Backlinks\n"
        links_section += f"Market: {country or 'SEA'}. Pick the 5 most relevant URLs. Link naturally in-content — never dump as a list.\n\n"
        for link in filtered_links:
            topics_str = ", ".join(link.get("topics", []))
            markets_str = "/".join(link.get("markets", []))
            links_section += f"- [{link['title']}]({link['url']}) [{markets_str}] — {topics_str}\n"

    country_section = ""
    if country and country in COUNTRY_CONTEXT:
        ctx = COUNTRY_CONTEXT[country]
        avoid_list = "\n".join(f"  - {r}" for r in ctx["avoid"])
        country_section = f"""
## Country Focus: {ctx['flag']} {ctx['name']} ({country}) — STRICT REQUIREMENT
This post must be written EXCLUSIVELY for the {ctx['name']} market.

Local payment methods to reference: {ctx['local_methods']}
Cross-border methods available to {ctx['name']} merchants: {ctx['cross_border']}
Currency: {ctx['currency']}
Payout: {ctx['payout']}
Place name examples: {ctx['places']}

FACT CHECK — Do NOT include these market mismatches:
{avoid_list}

Before returning your JSON, verify every payment method name, currency, and place name is correct for {ctx['name']}. Correct any mismatches.
"""
        status(f"Country focus set to {ctx['flag']} {ctx['name']}")

    status("Rewriting blog post with Claude Opus...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    docs_section = f"\n## HitPay Product Documentation — Feature & Flow Accuracy\n{product_docs}\n" if product_docs else ""

    user_prompt = f"""You are rewriting an existing HitPay blog post. The goal is to produce a significantly improved version of the same article using all system prompt directives (AEO optimisation, GEO rules, competitor comparisons, internal backlinks, etc.).

## Existing Article to Rewrite
URL: {url}
Title: {existing_title}

--- EXISTING CONTENT START ---
{existing_content[:6000]}
--- EXISTING CONTENT END ---

Keep the same core topic and keyword focus: "{keyword}"
Preserve any accurate facts, data points, or useful examples from the original.
Remove outdated information, weak sections, and anything that violates the system prompt rules.
Fully apply all AEO, GEO, and competitor comparison directives from the system prompt.
{country_section}
## HitPay Knowledge Base — Use for Factual Accuracy
{mcp_context}
{docs_section}
{competitor_context}
{links_section}
Ground your rewrite in the knowledge base and product documentation above. Do not invent facts or statistics not present in these sources or the system prompt.

Remember: include exactly 5 internal backlinks from the URL list above, woven naturally into the content.

Return the JSON object now."""

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=BLOG_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    raw = raw.strip()

    try:
        post_data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Response was truncated or malformed (max_tokens may be too low). JSON error: {e}")
    post_data["date"] = date.today().isoformat()
    post_data["keyword"] = keyword
    post_data["country"] = country or ""
    post_data["status"] = "generated"
    post_data["source_url"] = url

    if not post_data.get("slug"):
        post_data["slug"] = slugify(post_data["title"])
    else:
        post_data["slug"] = slugify(post_data["slug"])

    return post_data


def _gather_mcp_context(keyword: str, status_cb=None) -> str:
    """Query HitPay MCP to gather relevant knowledge for the keyword."""
    parts = []

    queries = [
        (keyword, "all", 5),
        (keyword, "product", 3),
        (keyword, "guide", 3),
    ]

    for query, category, limit in queries:
        label = f"[{category}]" if category != "all" else "[general]"
        try:
            result = search_knowledge(query, category=category, limit=limit)
            if result and not result.get("error"):
                parts.append(f"### Knowledge {label}: '{query}'")
                parts.append(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception:
            pass

    if not parts:
        return "No specific knowledge base results found. Use general HitPay knowledge from your system prompt."

    return "\n\n".join(parts)
