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


# External link library keyed by market code (SG / MY / PH) and "SEA" for cross-regional.
# Each entry: {"name": str, "url": str, "use_when": str}
# Competitor entries also carry "competitor": True — they require rel="nofollow" and are only
# included in comparison / listicle articles.
EXTERNAL_LINKS: dict[str, dict[str, list[dict]]] = {
    "SG": {
        "regulators": [
            {"name": "Monetary Authority of Singapore (MAS)", "url": "https://www.mas.gov.sg", "use_when": "Any compliance, licensing, or regulatory mention"},
            {"name": "Payment Services Act", "url": "https://www.mas.gov.sg/regulation/acts/payment-services-act", "use_when": "Mentioning SG payment licensing"},
            {"name": "Enterprise Singapore", "url": "https://www.enterprisesg.gov.sg", "use_when": "SME growth or business support context"},
        ],
        "payment_methods": [
            {"name": "PayNow", "url": "https://www.mas.gov.sg/development/e-payments/paynow", "use_when": "Mentioning PayNow"},
            {"name": "GrabPay", "url": "https://www.grab.com/sg/pay/", "use_when": "Mentioning GrabPay"},
            {"name": "ShopeePay", "url": "https://shopee.sg/m/shopeepay", "use_when": "Mentioning ShopeePay"},
            {"name": "Atome", "url": "https://www.atome.sg", "use_when": "Mentioning Atome BNPL"},
            {"name": "Visa", "url": "https://www.visa.com.sg", "use_when": "Mentioning Visa card acceptance"},
            {"name": "Mastercard", "url": "https://www.mastercard.com.sg", "use_when": "Mentioning Mastercard acceptance"},
            {"name": "UPI", "url": "https://www.npci.org.in/what-we-do/upi/product-overview", "use_when": "Mentioning UPI for Indian tourists/expats"},
        ],
        "integrations": [
            {"name": "Shopify", "url": "https://help.shopify.com/en/manual/payments", "use_when": "Shopify integration articles"},
            {"name": "WooCommerce", "url": "https://woocommerce.com/documentation/", "use_when": "WooCommerce integration articles"},
            {"name": "Xero", "url": "https://central.xero.com", "use_when": "Xero accounting integration articles"},
            {"name": "Zapier", "url": "https://zapier.com/how-it-works", "use_when": "Automation articles"},
        ],
        "competitors": [
            {"name": "Airwallex", "url": "https://www.airwallex.com/sg", "competitor": True},
            {"name": "Fiuu", "url": "https://fiuu.com", "competitor": True},
            {"name": "Stripe", "url": "https://stripe.com", "competitor": True},
            {"name": "Red Dot Payment", "url": "https://reddotpayment.com", "competitor": True},
            {"name": "Adyen", "url": "https://www.adyen.com", "competitor": True},
            {"name": "Qashier", "url": "https://qashier.com/sg/", "competitor": True},
            {"name": "KPay", "url": "https://www.kpay-group.com/en-sg", "competitor": True},
            {"name": "EPOS", "url": "https://www.epos.com.sg", "competitor": True},
            {"name": "Koomi", "url": "https://koomi.com.sg", "competitor": True},
            {"name": "Revolut", "url": "https://www.revolut.com/en-SG", "competitor": True},
        ],
    },
    "MY": {
        "regulators": [
            {"name": "Bank Negara Malaysia", "url": "https://www.bnm.gov.my", "use_when": "Any compliance or regulatory mention"},
            {"name": "SME Corp Malaysia", "url": "https://www.smecorp.gov.my", "use_when": "SME growth or business support context"},
        ],
        "payment_methods": [
            {"name": "FPX", "url": "https://www.paynet.my/fpx.html", "use_when": "Mentioning FPX"},
            {"name": "DuitNow", "url": "https://www.paynet.my/duitnow.html", "use_when": "Mentioning DuitNow"},
            {"name": "GrabPay", "url": "https://www.grab.com/my/pay/", "use_when": "Mentioning GrabPay"},
            {"name": "Atome", "url": "https://www.atome.com.my", "use_when": "Mentioning Atome BNPL"},
            {"name": "Visa", "url": "https://www.visa.com.my", "use_when": "Mentioning Visa card acceptance"},
            {"name": "Mastercard", "url": "https://www.mastercard.com.my", "use_when": "Mentioning Mastercard acceptance"},
        ],
        "integrations": [
            {"name": "Shopify", "url": "https://help.shopify.com/en/manual/payments", "use_when": "Shopify integration articles"},
            {"name": "WooCommerce", "url": "https://woocommerce.com/documentation/", "use_when": "WooCommerce integration articles"},
            {"name": "Xero", "url": "https://central.xero.com", "use_when": "Xero accounting integration articles"},
            {"name": "QuickBooks", "url": "https://quickbooks.intuit.com/learn-support/", "use_when": "QuickBooks integration articles"},
        ],
        "competitors": [
            {"name": "Stripe", "url": "https://stripe.com", "competitor": True},
            {"name": "iPay88", "url": "https://www.ipay88.com", "competitor": True},
            {"name": "Razer Merchant Services", "url": "https://merchant.razer.com", "competitor": True},
            {"name": "Billplz", "url": "https://www.billplz.com", "competitor": True},
            {"name": "SenangPay", "url": "https://senangpay.com", "competitor": True},
            {"name": "eGHL", "url": "https://www.eghl.my", "competitor": True},
            {"name": "Fiuu", "url": "https://fiuu.com", "competitor": True},
            {"name": "StoreHub", "url": "https://www.storehub.com", "competitor": True},
            {"name": "Pine Labs", "url": "https://www.pinelabs.com", "competitor": True},
            {"name": "Curlec", "url": "https://curlec.com", "competitor": True},
        ],
    },
    "PH": {
        "regulators": [
            {"name": "Bangko Sentral ng Pilipinas", "url": "https://www.bsp.gov.ph", "use_when": "Any compliance or regulatory mention"},
        ],
        "payment_methods": [
            {"name": "GrabPay", "url": "https://www.grab.com/ph/pay/", "use_when": "Mentioning GrabPay"},
            {"name": "Maya", "url": "https://www.maya.ph", "use_when": "Mentioning Maya wallet"},
            {"name": "Visa", "url": "https://www.visa.com.ph", "use_when": "Mentioning Visa card acceptance"},
            {"name": "Mastercard", "url": "https://www.mastercard.com.ph", "use_when": "Mentioning Mastercard acceptance"},
        ],
        "integrations": [
            {"name": "Shopify", "url": "https://help.shopify.com/en/manual/payments", "use_when": "Shopify integration articles"},
            {"name": "WooCommerce", "url": "https://woocommerce.com/documentation/", "use_when": "WooCommerce integration articles"},
        ],
        "competitors": [
            {"name": "PayMongo", "url": "https://www.paymongo.com", "competitor": True},
            {"name": "Xendit", "url": "https://www.xendit.co", "competitor": True},
            {"name": "DragonPay", "url": "https://www.dragonpay.ph", "competitor": True},
            {"name": "Paynamics", "url": "https://paynamics.com", "competitor": True},
            {"name": "2C2P", "url": "https://www.2c2p.com", "competitor": True},
            {"name": "PayPal", "url": "https://www.paypal.com", "competitor": True},
            {"name": "PesoPay", "url": "https://www.pesopay.com", "competitor": True},
        ],
    },
    "SEA": {
        "regulators": [
            {"name": "World Bank financial inclusion data", "url": "https://www.worldbank.org/en/topic/financialinclusion", "use_when": "Articles on unbanked populations or financial access"},
            {"name": "Statista SEA e-commerce", "url": "https://www.statista.com/outlook/emo/ecommerce/southeast-asia", "use_when": "Market size or regional growth claims"},
        ],
        "payment_methods": [
            {"name": "Visa", "url": "https://www.visa.com", "use_when": "Mentioning Visa in a multi-market context"},
            {"name": "Mastercard", "url": "https://www.mastercard.com", "use_when": "Mentioning Mastercard in a multi-market context"},
        ],
        "integrations": [],
        "competitors": [
            {"name": "Stripe", "url": "https://stripe.com", "competitor": True},
            {"name": "Adyen", "url": "https://www.adyen.com", "competitor": True},
            {"name": "Airwallex", "url": "https://www.airwallex.com", "competitor": True},
            {"name": "2C2P", "url": "https://www.2c2p.com", "competitor": True},
            {"name": "Fiuu", "url": "https://fiuu.com", "competitor": True},
            {"name": "Xendit", "url": "https://www.xendit.co", "competitor": True},
        ],
    },
}

_COMPARISON_SIGNALS = {"vs", "versus", "comparison", "compare", "alternative", "alternatives", "best", "top ", "which is better", "vs.", "competitor"}


def _select_external_links(country: str | None, keyword: str, count: int = 3) -> list[dict]:
    """Score and pre-select the most relevant external links for this keyword.

    Strategy:
    1. Pull relevant scraped articles from external_links_db.json (specific blog posts)
    2. Fill remaining slots with curated static links (official pages, regulators)
    Competitor links are only included for comparison/listicle articles.
    """
    is_comparison = any(sig in keyword.lower() for sig in _COMPARISON_SIGNALS)
    market = country if country in EXTERNAL_LINKS else "SEA"
    links_data = EXTERNAL_LINKS[market]
    kw_lower = keyword.lower()
    markets_filter = [country] if country else None

    selected: list[dict] = []
    seen_urls: set[str] = set()

    def _add(link: dict):
        url = link.get("url", "")
        if url not in seen_urls and len(selected) < count:
            selected.append(link)
            seen_urls.add(url)

    # ── Step 1: scraped articles from DB ──────────────────────────────────────
    try:
        from src.external_link_scraper import search_articles
        db_articles = search_articles(
            keyword,
            markets=markets_filter,
            is_comparison=is_comparison,
            limit=count * 3,
        )
        for art in db_articles:
            _add({
                "name": f"{art['source_name']} — {art['title']}",
                "url": art["url"],
                "use_when": f"contextually relevant article from {art['source_name']}",
                "competitor": art.get("is_competitor", False),
            })
    except Exception:
        pass  # DB not yet built — fall through to static links

    # ── Step 2: curated static links — direct name match ──────────────────────
    def name_score(link: dict) -> int:
        return sum(1 for t in link["name"].lower().split() if len(t) > 2 and t in kw_lower)

    for cat in ("payment_methods", "integrations"):
        for link in links_data.get(cat, []):
            if name_score(link) > 0:
                _add(link)

    # Competitor static links (comparison only, direct name match)
    if is_comparison:
        for link in links_data.get("competitors", []):
            if name_score(link) > 0:
                _add(link)

    # ── Step 3: fill remaining slots with regulators / any static link ─────────
    for link in links_data.get("regulators", []):
        _add(link)

    for cat in ("payment_methods", "integrations"):
        for link in links_data.get(cat, []):
            _add(link)

    if is_comparison:
        for link in links_data.get("competitors", []):
            _add(link)

    return selected[:count]


def _build_external_links_section(country: str | None, keyword: str) -> str:
    """Build a mandatory external-links block with pre-selected links and exact syntax."""
    selected = _select_external_links(country, keyword)
    if not selected:
        return ""

    is_comparison = any(sig in keyword.lower() for sig in _COMPARISON_SIGNALS)

    lines = ["\n## Required External Links — You MUST Hyperlink All 3 Below"]
    lines.append("Embed each link naturally inside a sentence. Rules:")
    lines.append("- Do NOT list them at the end or in a reference block")
    lines.append("- Do NOT use the article title as anchor text — write your own descriptive anchor about the topic or insight")
    lines.append("- Do NOT make a competitor the subject of the sentence — frame them as industry context, not the focus")
    lines.append("  ✗ Bad: 'Understanding Xendit — Payment Gateway explains how gateways work'")
    lines.append("  ✓ Good: 'how a gateway's infrastructure determines settlement speed and reliability'")
    lines.append("- Competitor links must be woven in as supporting evidence for a broader point, never as a spotlight on the competitor")
    lines.append("- HitPay must remain the clear recommended solution; competitor references are context only\n")

    for i, link in enumerate(selected, 1):
        name = link["name"]
        url = link["url"]
        use_when = link.get("use_when", "when mentioned")
        is_competitor = link.get("competitor", False)
        if is_competitor:
            syntax = f'<a href="{url}" rel="nofollow">{name}</a>'
        else:
            syntax = f"[{name}]({url})"
        lines.append(f"{i}. {name} → {syntax}")
        lines.append(f"   Link when: {use_when}")

    return "\n".join(lines)

BLOG_SYSTEM_PROMPT_AUTHORITY = """You are a senior content strategist and writer for HitPay, a payment platform for SMEs across Southeast Asia, licensed by MAS (Singapore). Your role is to create authoritative, fact-grounded blog posts that help small business owners make informed decisions — not to sell HitPay's product.

## Writing Philosophy
- Lead with the business problem and factual context, not HitPay's features
- Write in a neutral, authoritative brand voice — as an industry reference, not a personal advisor
- Minimise use of "you" and "your". Refer to readers as "businesses", "merchants", "SMBs", "sellers", or "operators" instead. Where "you" would sound natural, prefer "a business" or "merchants"
- Occasional direct address ("your business", "your checkout") is acceptable for SMB relevance — but it should be the exception, not the default in every sentence
- Brand anchor HitPay with factual, declarative statements: "HitPay supports GCash as a payment method" rather than "you can use HitPay to accept GCash". Position HitPay as the reference-grade solution, not as a promotional insert
- Bring real operational insight: cash flow timing, customer behaviour, reconciliation, chargeback risk — grounded in fact, not empathy theatre
- Never write marketing copy. Never use words like "seamlessly", "unlock", "revolutionise", "game-changer", "cutting-edge"
- Use specific, concrete examples. "A Petaling Jaya café that accepts Touch 'n Go" beats "businesses across Malaysia"
- Short sentences. Active voice. Confident, declarative tone
- Write at the intelligence level of a busy business owner who reads fast and needs to act — but write as the authority, not the friend

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
| Malaysia 🇲🇾 | PayNow (Singapore), QRIS (Indonesia), QR Ph (Philippines), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea) |
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
- Open with a factual, declarative intro that establishes the business problem with data or context — not a personal appeal. Name the market reality first; address businesses, not individuals
- Include 3–5 H2 sections with practical, actionable insights
- Use H3 sparingly for sub-points
- Reference HitPay in 1–2 sections only — as a factual brand anchor ("HitPay supports…", "HitPay's payment links enable…"), not as a friendly recommendation ("you can use HitPay to…")
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
- Minimise second-person address in body copy. State facts and describe what businesses do, rather than telling "you" what to do. Use imperative action steps only in numbered process lists, not in prose paragraphs.
- FAQ answers must be self-contained factual paragraphs that an AI engine can extract standalone. Each answer should open with a declarative statement (not "Yes, you can…" but "HitPay supports…" or "Businesses in [market] can…"). Direct address is acceptable in FAQ answers but should not be the opening construction.

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

## External Backlinks (REQUIRED)
You will be given an External Link Library with outbound URLs. You MUST include exactly 3 of these as natural in-content links within the post body. Rules:
- Links must be woven naturally into sentences — never listed at the end
- Anchor text must contain the brand or entity name (exact wording flexible)
- Link on first mention only — never link the same entity more than once
- Only link where it is genuinely contextually relevant
- Spread across different sections — not clustered together
- For non-competitor links use standard markdown: [anchor text](URL)
- For competitor links (comparison articles only) use HTML with rel="nofollow": <a href="URL" rel="nofollow">Brand Name</a>
- Do NOT link competitors in any article that is not a comparison or listicle

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
  "content": "Full markdown content structured as: (1) **Quick Answer:** block first — before any intro prose; (2) intro paragraphs; (3) body sections with H2/H3 phrased as questions; (4) ## Frequently Asked Questions with 5+ Q&A pairs formatted as **Q: ...** on its own line followed by the answer paragraph; (5) [SCHEMA] block. No H1. 5 internal backlinks + 3 contextual external links. 900–1200 words excluding FAQ."
}
"""

BLOG_SYSTEM_PROMPT_EMPATHY = """You are a senior content strategist and writer for HitPay, a payment platform for SMEs across Southeast Asia, licensed by MAS (Singapore). Your role is to create blog posts that genuinely help small business owners grow and manage their businesses — not to sell HitPay's product.

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
| Malaysia 🇲🇾 | PayNow (Singapore), QRIS (Indonesia), QR Ph (Philippines), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea) |
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

## External Backlinks (REQUIRED)
You will be given an External Link Library with outbound URLs. You MUST include exactly 3 of these as natural in-content links within the post body. Rules:
- Links must be woven naturally into sentences — never listed at the end
- Anchor text must contain the brand or entity name (exact wording flexible)
- Link on first mention only — never link the same entity more than once
- Only link where it is genuinely contextually relevant
- Spread across different sections — not clustered together
- For non-competitor links use standard markdown: [anchor text](URL)
- For competitor links (comparison articles only) use HTML with rel="nofollow": <a href="URL" rel="nofollow">Brand Name</a>
- Do NOT link competitors in any article that is not a comparison or listicle

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
  "content": "Full markdown content structured as: (1) **Quick Answer:** block first — before any intro prose; (2) intro paragraphs; (3) body sections with H2/H3 phrased as questions; (4) ## Frequently Asked Questions with 5+ Q&A pairs formatted as **Q: ...** on its own line followed by the answer paragraph; (5) [SCHEMA] block. No H1. 5 internal backlinks + 3 contextual external links. 900–1200 words excluding FAQ."
}
"""

BLOG_SYSTEM_PROMPTS = {
    "authority": BLOG_SYSTEM_PROMPT_AUTHORITY,
    "empathy": BLOG_SYSTEM_PROMPT_EMPATHY,
}

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
        "cross_border": "PayNow (Singapore), QRIS (Indonesia), QR Ph (Philippines), PromptPay (Thailand), TrueMoney (Thailand), Rabbit LINE Pay (Thailand), KakaoPay/PayCo/LINE Pay (South Korea)",
        "places": "Bangsar, Petaling Jaya, KLCC, Johor Bahru, Bukit Bintang",
        "payout": "next business day in MYR for domestic; T+3 for cross-border payments",
        "avoid": [
            "PayNow — cross-border only in MY (Singapore customers paying MY merchants); do not present as a local MY payment method",
            "GCash, Maya, PESONet, InstaPay — Philippines-only",
            "Do not use PayNow as a local MY payment example; it is cross-border only",
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
            "PayNow — cross-border only in PH (Singapore customers paying PH merchants); do not present as a local PH payment method",
            "FPX, Touch 'n Go, Boost — Malaysia-only",
            "Do not present DuitNow as a local PH method (cross-border only)",
        ],
    },
}


def generate_blog_post(keyword: str, country: str = None, prompt_style: str = "authority", on_status=None) -> dict:
    """Generate a blog post for the given keyword.

    Args:
        keyword: The topic/keyword to write about
        country: Optional market code (SG/MY/PH)
        prompt_style: "authority" (brand voice, AI-optimised) or "empathy" (human-first, trusted advisor)
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
    system_prompt = BLOG_SYSTEM_PROMPTS.get(prompt_style, BLOG_SYSTEM_PROMPT_AUTHORITY)
    status("Generating blog post with Claude Opus...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    docs_section = f"\n## HitPay Product Documentation — Feature & Flow Accuracy\n{product_docs}\n" if product_docs else ""
    external_links_section = _build_external_links_section(country, keyword)

    user_prompt = f"""Write a blog post about: "{keyword}"
{country_section}
## HitPay Knowledge Base — Use for Factual Accuracy
{mcp_context}
{docs_section}
{competitor_context}
{links_section}
{external_links_section}
Ground your post in the knowledge base and product documentation above. If they contain specific features, merchant use cases, flows, or product details relevant to this topic, incorporate them naturally. Do not invent facts or statistics not present in these sources or the system prompt.

Remember: include exactly 5 internal backlinks from the HitPay URL list above and exactly 3 external links from the External Link Library above. All links must be woven naturally into the content — never listed at the end.

Return the JSON object now."""

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=system_prompt,
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


def rewrite_blog_post(url: str, country: str = None, prompt_style: str = "authority", on_status=None) -> dict:
    """Scrape an existing blog post URL and rewrite it with all optimisation directives.

    Args:
        url: Public URL of the existing HitPay blog post
        country: Optional market code (SG/MY/PH) to lock the rewrite to a market
        prompt_style: "authority" (brand voice, AI-optimised) or "empathy" (human-first, trusted advisor)
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

    system_prompt = BLOG_SYSTEM_PROMPTS.get(prompt_style, BLOG_SYSTEM_PROMPT_AUTHORITY)
    status("Rewriting blog post with Claude Opus...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    docs_section = f"\n## HitPay Product Documentation — Feature & Flow Accuracy\n{product_docs}\n" if product_docs else ""
    external_links_section = _build_external_links_section(country, keyword)

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
{external_links_section}
Ground your rewrite in the knowledge base and product documentation above. Do not invent facts or statistics not present in these sources or the system prompt.

Remember: include exactly 5 internal backlinks from the HitPay URL list above and exactly 3 external links from the External Link Library above. All links must be woven naturally into the content — never listed at the end.

Return the JSON object now."""

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=system_prompt,
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
