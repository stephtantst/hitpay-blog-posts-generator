import json
import random
import re
import time
from datetime import datetime as _datetime

import anthropic
import json
import requests

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.generator import COUNTRY_CONTEXT, _load_relevant_docs, _messages_create_with_retry

_SITEMAP_URL = "https://hitpayapp.com/sitemap_en.xml"
_blog_slugs_cache: list[str] | None = None
_blog_slugs_cache_ts: float = 0
_SLUG_CACHE_TTL = 3600  # 1 hour

_WRITING_STYLE_RULES = """PROSE ANTI-PATTERNS — avoid all of these:
- Marketing language, startup jargon, corporate phrasing, inspirational tone
- Performative vulnerability, forced relatability, fake conversational fillers
- Overwritten hooks, one-line paragraph spam, overuse of em dashes, constant rhetorical contrast
- Banned openers and structures: "Honestly…", "The truth is…", "Let that sink in.", "Here's the thing.", "It turns out…", "You're not alone.", "In a world where…", "Everything changed when…", "I used to think… now I…", "This isn't just about X. It's about Y.", "Most people don't realize…", "Read that again."
- Do not manufacture emotion or tension where none exists

PROSE STYLE:
- Use normal sentence structure. Full paragraphs are fine.
- Vary rhythm naturally, not intentionally.
- Prefer clarity over punchiness.
- Let observations stand without over-explaining them.
- Use concrete language and real examples. Keep transitions subtle.
- Allow mild imperfections in flow — they sound human.
- The writing can have personality, but should not constantly signal personality."""


def _fetch_live_blog_slugs() -> list[str]:
    """Return all live blog post slugs from the sitemap. Cached for 1 hour."""
    global _blog_slugs_cache, _blog_slugs_cache_ts
    if _blog_slugs_cache and (time.time() - _blog_slugs_cache_ts) < _SLUG_CACHE_TTL:
        return _blog_slugs_cache
    try:
        resp = requests.get(_SITEMAP_URL, timeout=8)
        resp.raise_for_status()
        all_urls = re.findall(r"<loc>(https://hitpayapp\.com/blog/[^<]+)</loc>", resp.text)
        slugs = [
            u.replace("https://hitpayapp.com/blog/", "")
            for u in all_urls
            if "/categories/" not in u and "/tags/" not in u and u != "https://hitpayapp.com/blog"
        ]
        if slugs:
            _blog_slugs_cache = slugs
            _blog_slugs_cache_ts = time.time()
            return slugs
    except Exception:
        pass
    # Fall back to hardcoded list
    return [url.replace("https://hitpayapp.com/blog/", "") for _, url in VALID_BLOG_URLS]


def _cap_tweet(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    cutoff = text.rfind(" ", 0, limit - 1)
    if cutoff <= 0:
        cutoff = limit - 1
    return text[:cutoff] + "…"


# Verified HitPay blog post URLs — only these are safe to use as link_url
VALID_BLOG_URLS: list[tuple[str, str]] = [
    # General / SEA
    ("What is HitPay", "https://hitpayapp.com/blog/what-is-hitpay"),
    ("HitPay Rates & Pricing (fees, MDR, transaction costs)", "https://hitpayapp.com/blog/hitpay-rates"),
    ("Payment Gateway Guide SEA", "https://hitpayapp.com/blog/payment-gateway"),
    ("Payment Processing for Online Stores SEA", "https://hitpayapp.com/blog/payment-processing-online-store"),
    ("Payment Link — send & get paid instantly", "https://hitpayapp.com/blog/payment-link"),
    ("QR Code Payments Explained", "https://hitpayapp.com/blog/qr-code-payments"),
    ("Alternative Payment Methods in Southeast Asia", "https://hitpayapp.com/blog/alternative-payment-methods-southeast-asia"),
    ("Ecommerce Payment Solutions SEA", "https://hitpayapp.com/blog/ecommerce-payment-solutions-southeast-asia"),
    ("Credit Card Payment for Businesses SEA", "https://hitpayapp.com/blog/credit-card-payment"),
    # SG
    ("Payment Gateway Singapore", "https://hitpayapp.com/blog/payment-gateway-singapore"),
    ("HitPay Singapore Overview", "https://hitpayapp.com/blog/hitpay-singapore"),
    ("Recurring Billing Singapore", "https://hitpayapp.com/blog/recurring-billing-sg"),
    # MY
    ("Best Payment Gateway Malaysia", "https://hitpayapp.com/blog/best-payment-gateway-malaysia"),
    ("Best Online Payment Solution Malaysia", "https://hitpayapp.com/blog/best-online-payment-solution-malaysia"),
    ("Payment Link Malaysia", "https://hitpayapp.com/blog/payment-link-malaysia"),
    ("Recurring Billing Malaysia", "https://hitpayapp.com/blog/recurring-billing-my"),
    # PH
    ("Best Payment Gateway Philippines", "https://hitpayapp.com/blog/best-payment-gateway-philippines"),
    ("QR Code Payments Philippines", "https://hitpayapp.com/blog/how-to-accept-qr-code-payments-philippines"),
    ("QR Ph No Monthly Fee Comparison", "https://hitpayapp.com/blog/accept-qrph-with-no-monthly-fees-gateway-comparison-2025"),
    ("Ecommerce Payment Gateways Philippines", "https://hitpayapp.com/blog/ecommerce-payment-gateways-philippines"),
    ("Recurring Billing Philippines", "https://hitpayapp.com/blog/recurring-billing-ph"),
    ("Payment Link Philippines", "https://hitpayapp.com/blog/how-to-create-payment-link-philippines"),
]

_FALLBACK_URL = "https://hitpayapp.com/blog/hitpay-rates"
_SME_FALLBACK_URL = "https://smegrowthhub.com/blog"


def _is_valid_blog_url(url: str) -> bool:
    """Accept any hitpayapp.com/blog/{slug} URL — not just the old hardcoded 22."""
    return bool(re.match(r"^https://hitpayapp\.com/blog/[a-zA-Z0-9_\-()]+$", url))


def _build_storytelling_prompt(thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)

    if thread_size == 1:
        format_section = """CONTENT FORMAT: Single standalone tweet
- Exactly 1 tweet, no numbering
- 200–280 chars
- A compact narrative arc: observation → insight → resolution
- Ends with a natural HitPay mention + [URL] as a literal placeholder"""
        output_example = (
            '{"topic": "borderless payments", '
            '"tweets": ["Payment infrastructure was built around where you are, not who walks through your door. '
            'That mismatch costs merchants silently every day. HitPay fixes the gap: [URL]"], '
            '"link_url": "https://hitpayapp.com/blog/hitpay-rates", "visual_note": null}'
        )
    else:
        format_section = (
            f"CONTENT FORMAT: Storytelling thread of exactly {thread_size} tweets\n"
            f"- Exactly {thread_size} tweets numbered \"1/{thread_size} ...\", "
            f"\"2/{thread_size} ...\", etc. No more, no fewer.\n"
            "- Tweet 1: open with an observation or tension — a truth about the world that feels slightly wrong. "
            "No product mention. Conversational, grounded. Optionally end with 🧵\n"
            "- Middle tweets (if any): deepen the tension with a concrete scenario or implication. "
            "Still no product pitch. Let the reader feel the problem.\n"
            f"- Final tweet ({thread_size}/{thread_size}): resolve the tension — what it should look like, "
            "and where HitPay fits in naturally. End with [URL] as a literal placeholder.\n"
            "- Each tweet: 180–280 chars, short punchy sentences, no stats or lists\n"
            "- Tone: philosophical but grounded — like a founder reflecting after a long week, not a marketer"
        )
        example_tweets = [f'"{i}/{thread_size} ..."' for i in range(1, thread_size + 1)]
        example_tweets[-1] = f'"{thread_size}/{thread_size} ... [URL]"'
        output_example = (
            '{"topic": "...", "tweets": [' + ", ".join(example_tweets) + '], '
            '"link_url": "https://hitpayapp.com/blog/hitpay-rates", "visual_note": null}'
        )

    return f"""You are the voice behind @hitpay_app on X (Twitter).
Your job is to write storytelling posts that make merchants pause and think — not to educate them with data, but to name something they already feel but couldn't articulate.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH). No monthly fees. 50+ payment methods. Next business day payouts.
TONE: Reflective, honest, slightly philosophical. Like a founder talking to another founder — not a brand talking to a customer.
AUDIENCE: SME founders and merchants in Southeast Asia (SG/MY/PH).

{format_section}

STYLE RULES:
- No statistics or percentages in any tweet except the final one (and even then, sparingly)
- Short declarative sentences. Fragments are fine.
- Em-dashes (—) are fine, used sparingly
- No hashtags, no @ mentions
- No URLs except the final tweet — use [URL] as a literal placeholder there only
- No promotional language until the final tweet
- The final tweet resolves the tension; HitPay is the answer, not the pitch
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust

NARRATIVE THEMES — pick the most resonant if no hint is given:
- Payment systems built for where you are, not who you serve
- The silent cost of cash that nobody talks about
- Why your invoice tool doesn't feel like yours
- The gap between "accepted" and "paid"
- Cross-border payments from a customer's perspective
- What a tourist feels when their card gets declined
- The moment a business realises their checkout is losing them customers
- Reconciliation as a symptom, not a problem
- Why "no monthly fee" changes how merchants take risks
- The difference between a payment tool and payment infrastructure

LINK URL RULE — critical, no exceptions:
Set link_url to https://hitpayapp.com/blog/{{slug}} using the most topically relevant slug below.
All slugs are live pages. Pick the closest match to the topic. If no clear match, default to: hitpay-rates
Do NOT invent slugs not in this list.

LIVE BLOG SLUGS:
{urls_list}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{output_example}

IMPORTANT: [URL] in the tweet(s) is a literal placeholder — never substitute the real URL into the tweet text itself."""


def _build_thought_leadership_prompt(thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)

    if thread_size == 1:
        format_section = """CONTENT FORMAT: Single standalone tweet
- Exactly 1 tweet, no numbering
- 200–280 chars, fully self-contained
- Ends with a natural HitPay mention + [URL] as a literal placeholder"""
        output_example = (
            '{"topic": "MDR explained", '
            '"tweets": ["Most merchants pay 2–3% per card transaction without knowing what '
            'it covers. That fee — MDR — is split between your bank, card network, and '
            'processor. HitPay\'s card MDR starts at 2.8% + S$0.50, no monthly fees: [URL]"], '
            '"link_url": "https://hitpayapp.com/blog/hitpay-rates", "visual_note": null}'
        )
    elif thread_size == 2:
        format_section = (
            "CONTENT FORMAT: Thread of exactly 2 tweets\n"
            "- Exactly 2 tweets numbered \"1/2 ...\" and \"2/2 ...\"\n"
            "- Tweet 1/2: introduce the concept clearly with a key fact or insight — end with 🧵\n"
            "- Tweet 2/2: concrete example or actionable takeaway + natural HitPay mention + [URL]\n"
            "- Each tweet: 200–280 chars, self-contained"
        )
        output_example = (
            '{"topic": "...", "tweets": ["1/2 ... 🧵", "2/2 ... [URL]"], '
            '"link_url": "https://hitpayapp.com/blog/hitpay-rates", "visual_note": null}'
        )
    else:
        format_section = (
            f"CONTENT FORMAT: Thread of exactly {thread_size} tweets\n"
            f"- Exactly {thread_size} tweets numbered \"1/{thread_size} ...\", "
            f"\"2/{thread_size} ...\", etc. No more, no fewer.\n"
            "- Tweet 1: introduce the concept clearly — definition or hook — end with 🧵\n"
            "- Middle tweets: break down with specific facts, numbers, concrete examples\n"
            "- Weave in relevant local payment methods where they fit (PayNow/SG, DuitNow/MY, QR Ph/PH)\n"
            f"- Final tweet ({thread_size}/{thread_size}): actionable takeaway + natural HitPay "
            "mention + [URL] as a literal placeholder\n"
            "- Each tweet: 200–280 chars, self-contained"
        )
        example_tweets = [f'"{i}/{thread_size} ..."' for i in range(1, thread_size + 1)]
        example_tweets[-1] = f'"{thread_size}/{thread_size} ... [URL]"'
        output_example = (
            '{"topic": "...", "tweets": [' + ", ".join(example_tweets) + '], '
            '"link_url": "https://hitpayapp.com/blog/hitpay-rates", "visual_note": null}'
        )

    return f"""You are the payments education writer for @hitpay_app on X (Twitter).
Write authoritative, educational content that teaches SME founders, merchants, and finance managers something genuinely useful about payments — the way a CFO explains it to a first-time founder.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH). No monthly fees. 50+ payment methods. Next business day payouts for domestic transactions.
TONE: Direct, factual, educational. Conversational but expert. Not corporate. Not promotional until the final tweet.
AUDIENCE: SME founders and merchants in Southeast Asia (SG/MY/PH).

{format_section}

STYLE RULES:
- Use specific numbers: "A 2% MDR on a $100 sale means you receive $98"
- Em-dashes (—) are fine for flow, used sparingly
- No hashtags, no @ mentions
- No URLs in any tweet except the final one — use [URL] as a literal placeholder there only
- No promotional language or feature pitching until the final tweet
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust

TOPIC POOL — pick the most relevant if no hint is given:
- MDR (Merchant Discount Rate) and interchange fees explained
- Payment settlement timelines: T+0, T+1, T+2 and why they matter
- QR vs card payments: cost and speed comparison for SMEs
- How chargebacks work and how merchants can fight them
- Cross-border payment fees in SEA and how to reduce them
- The hidden cost of "free" payment terminals
- Buy Now Pay Later economics from the merchant's perspective
- Cash flow impact of choosing the wrong payment method
- POS vs online vs invoice payments — when to use which
- Real-time payments in SEA: PayNow, DuitNow, QR Ph adoption
- Payment reconciliation: how to stop losing hours to manual matching
- Recurring billing and subscription payment mechanics

LINK URL RULE — critical, no exceptions:
Set link_url to https://hitpayapp.com/blog/{{slug}} using the most topically relevant slug below.
All slugs are live pages. Pick the closest match to the topic. If no clear match, default to: hitpay-rates
Do NOT invent slugs not in this list.

LIVE BLOG SLUGS:
{urls_list}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{output_example}

IMPORTANT: [URL] in the tweet(s) is a literal placeholder — never substitute the real URL into the tweet text itself."""


SME_TOPIC_POOL = [
    "How to manage cash flow when customers pay late",
    "When to hire your first employee — and what it actually costs",
    "Business registration in Singapore: sole proprietor vs Pte Ltd",
    "How to reduce payment processing fees without switching everything",
    "E-commerce in SEA: marketplace vs own store — the real trade-off",
    "Why your payment gateway choice affects your cash position",
    "What SMBs get wrong about B2B invoicing",
    "GST/SST registration: when you need it and when you don't",
    "Digital marketing on a tight budget for SEA SMBs",
    "How to pick accounting software you'll actually use",
    "Cross-border payments for small businesses — simpler than you think",
    "The hidden cost of cash for small businesses",
]

SME_STORYTELLING_TOPIC_POOL = [
    "The moment you realised cash was silently costing you",
    "Hiring your first employee — what nobody tells you",
    "The accounting tool switch that changed everything",
    "Late payments and what they actually cost",
    "When a sale nearly didn't happen because of payment friction",
    "The invoice that never got paid — and what you learned",
    "Why moving from marketplace to own store felt impossible at first",
    "The week you realised your pricing was wrong",
    "What changed when you started separating business and personal finances",
    "The supplier payment that nearly broke the relationship",
]


def _build_sme_educational_prompt(thread_size: int) -> str:
    from src.brand_config import get_brand_config
    bc = get_brand_config("smegrowthhub")

    if thread_size == 1:
        format_section = """CONTENT FORMAT: Single standalone tweet
- Exactly 1 tweet, no numbering
- 200–280 chars, fully self-contained
- Ends with a reference to the article + [URL] as a literal placeholder"""
        output_example = (
            '{"topic": "cash flow management", '
            '"tweets": ["Most Singapore SMBs invoice at the end of the month. '
            'That habit alone adds 14 days to your average collection time. Invoice immediately after delivery: [URL]"], '
            f'"link_url": "{bc.blog_base_url}/cash-flow-invoicing", "visual_note": null}}'
        )
    elif thread_size == 2:
        format_section = (
            "CONTENT FORMAT: Thread of exactly 2 tweets\n"
            "- Tweet 1/2: introduce the concept clearly with a key fact — end with 🧵\n"
            "- Tweet 2/2: concrete example or actionable takeaway + article reference + [URL]\n"
            "- Each tweet: 200–280 chars"
        )
        output_example = (
            '{"topic": "...", "tweets": ["1/2 ... 🧵", "2/2 ... [URL]"], '
            f'"link_url": "{bc.blog_base_url}/article-slug", "visual_note": null}}'
        )
    else:
        format_section = (
            f"CONTENT FORMAT: Thread of exactly {thread_size} tweets\n"
            f"- {thread_size} tweets numbered \"1/{thread_size} ...\", etc.\n"
            "- Tweet 1: introduce the concept clearly — definition or hook — end with 🧵\n"
            "- Middle tweets: specific facts, numbers, concrete examples from the SEA context\n"
            f"- Final tweet: actionable takeaway + article reference + [URL] as literal placeholder\n"
            "- Each tweet: 200–280 chars, self-contained"
        )
        example_tweets = [f'"{i}/{thread_size} ..."' for i in range(1, thread_size + 1)]
        example_tweets[-1] = f'"{thread_size}/{thread_size} ... [URL]"'
        output_example = (
            '{"topic": "...", "tweets": [' + ", ".join(example_tweets) + '], '
            f'"link_url": "{bc.blog_base_url}/article-slug", "visual_note": null}}'
        )

    return f"""You are the X content writer for SME Growth Hub, an independent editorial resource for small business operators across Southeast Asia.
Write practical, peer-to-peer content that teaches SEA SME owners something genuinely useful — the kind a trusted peer would share after doing the research.

VOICE: Independent advisor, not a brand account. Direct, warm, specific.
AUDIENCE: SME owners and operators in SG/MY/PH across F&B, retail, services, e-commerce, freelancing.

{format_section}

STYLE RULES:
- Use specific numbers and concrete examples — "a 2-week delay on RM3,000 invoice" beats "late payments are costly"
- Em-dashes (—) are fine, sparingly
- No hashtags, no @ mentions
- No URLs in any tweet except the final one — use [URL] as a literal placeholder there only
- No promotional language
- HitPay may be mentioned in payment-related content as a peer recommendation — e.g. "For Singapore SMBs, HitPay is the simplest starting point". Never as the main subject.
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust

TOPIC POOL — pick the most relevant if no hint is given:
{chr(10).join(f'- {t}' for t in SME_TOPIC_POOL)}

LINK URL RULE:
Set link_url to {bc.blog_base_url}/{{slug}} using a descriptive slug matching the topic.
If no specific slug is available, default to: {bc.blog_base_url}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{output_example}

IMPORTANT: [URL] in the tweet(s) is a literal placeholder — never substitute the real URL into the tweet text itself."""


def _build_sme_storytelling_prompt(thread_size: int) -> str:
    from src.brand_config import get_brand_config
    bc = get_brand_config("smegrowthhub")

    if thread_size == 1:
        format_section = """CONTENT FORMAT: Single standalone tweet
- Exactly 1 tweet, no numbering
- 200–280 chars
- A compact narrative arc: observation → insight or tension → resolution
- Ends with a reference to the article + [URL] as literal placeholder"""
        output_example = (
            '{"topic": "late payments", '
            '"tweets": ["Most SMBs track late invoices. Few track what they cost in working capital. '
            'A 30-day delay on a S$5,000 invoice is roughly S$25 of lost cash value at the bank. '
            'The fix is simpler than chasing: [URL]"], '
            f'"link_url": "{bc.blog_base_url}/late-payments", "visual_note": null}}'
        )
    else:
        format_section = (
            f"CONTENT FORMAT: Storytelling thread of exactly {thread_size} tweets\n"
            f"- {thread_size} tweets numbered \"1/{thread_size} ...\", etc.\n"
            "- Tweet 1: open with an observation or tension — something a business owner feels but rarely names. End with 🧵\n"
            "- Middle tweets: deepen with a concrete scenario. Still no pitch.\n"
            f"- Final tweet: resolution or reframe. Where the article's insight fits naturally. End with [URL].\n"
            "- Each tweet: 180–280 chars, short punchy sentences"
        )
        example_tweets = [f'"{i}/{thread_size} ..."' for i in range(1, thread_size + 1)]
        example_tweets[-1] = f'"{thread_size}/{thread_size} ... [URL]"'
        output_example = (
            '{"topic": "...", "tweets": [' + ", ".join(example_tweets) + '], '
            f'"link_url": "{bc.blog_base_url}/article-slug", "visual_note": null}}'
        )

    return f"""You are the X storytelling writer for SME Growth Hub, an independent resource for Southeast Asian business operators.
Write posts that make SMB owners pause and recognise something they already feel but couldn't quite name.

VOICE: Peer who has spent time around these businesses. Reflective, honest, slightly philosophical. Not a brand.
AUDIENCE: SME founders and operators in Southeast Asia (SG/MY/PH).

{format_section}

STYLE RULES:
- No statistics in middle tweets (sparingly in final only)
- Short declarative sentences. Fragments are fine.
- No hashtags, no @ mentions
- No URLs except final tweet — use [URL] as literal placeholder
- No promotional language until the final tweet
- HitPay may appear in the final tweet only if the topic is payment-related — as a natural peer recommendation, never as a pitch
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust

NARRATIVE THEMES — pick the most resonant if no hint is given:
{chr(10).join(f'- {t}' for t in SME_STORYTELLING_TOPIC_POOL)}

LINK URL RULE:
Set link_url to {bc.blog_base_url}/{{slug}} using a descriptive slug matching the topic.
If no specific slug is available, default to: {bc.blog_base_url}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{output_example}

IMPORTANT: [URL] in the tweet(s) is a literal placeholder — never substitute the real URL."""



def _build_stat_hook_prompt(thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)
    example = json.dumps({
        "topic": "DuitNow QR vs card terminal cost",
        "tweets": [
            "Accepting DuitNow QR via HitPay costs 1.2%. "
            "A RM 500 sale costs you RM 6.00 in fees — nothing else. "
            "No terminal rental. No monthly minimum. No setup fee. "
            "Just scan and get paid: [URL]"
        ],
        "link_url": "https://hitpayapp.com/blog/hitpay-rates",
        "visual_note": "Side-by-side: HitPay DuitNow QR 1.2% vs traditional card terminal monthly fee + MDR",
    }, ensure_ascii=False)
    return f"""You are the @hitpay_app content writer for X (Twitter) — Tuesday slot: Did You Know? fact post.
Write a single tweet that surfaces a concrete, verifiable fact about payment costs or merchant operations — using only HitPay's own published rates and features.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH). No monthly fees. 50+ payment methods. Next business day payouts.
TONE: Sharp, factual, practical. Make a merchant think "I didn't know that."
AUDIENCE: SME founders, merchants, and finance managers in Southeast Asia.

CONTENT FORMAT: Single tweet
- Exactly 1 tweet, no numbering
- 200-270 chars (leave room — do not pad to the limit)
- Lead with a concrete cost or operational fact
- Follow with one line on what that means for the merchant
- End with HitPay as the fix + [URL] as a literal placeholder
- Suggest a visual in visual_note

APPROVED FACTS — use only these, pick whichever fits the angle best:
MALAYSIA (MY):
  - DuitNow QR: 1.2% per transaction, no monthly fee, BNM-approved
  - FPX online banking: 1.8% + RM 0.40 per transaction
  - Visa/Mastercard card: 2.8% + RM 0.50 per transaction
  - HitPay: no setup fee, no monthly fee, no terminal rental
  - Accepts 30+ payment methods including DuitNow QR, FPX, GrabPay, TnG eWallet, Shopee Pay
  - Next business day payouts to Malaysian bank accounts

SINGAPORE (SG):
  - PayNow: 0.65% + S$0.30 per transaction, MAS-licensed
  - Visa/Mastercard card: 2.8% + S$0.50 per transaction
  - HitPay: no setup fee, no monthly fee
  - Accepts 50+ payment methods including PayNow, GrabPay, PayLah!, NETS
  - Next business day payouts

PHILIPPINES (PH):
  - QR Ph: 1.0% per transaction or ₱20 minimum, BSP OPS-licensed
  - GCash: 2.3% per transaction
  - HitPay: no setup fee, no monthly fee
  - Accepts 30+ payment methods including GCash, Maya, QR Ph

ANGLES that work well (pick one):
  - Cost comparison: DuitNow QR 1.2% vs cards 2.8%+RM0.50 — on RM 10,000/month that is RM X saved
  - Fee transparency: what a merchant actually pays per RM 500 / S$500 sale
  - Setup friction eliminated: no terminal, no application, start today
  - Payout speed: next business day vs typical 3–5 day bank settlement
  - Multi-method: one integration covers QR, e-wallets, cards, online banking

DO NOT INVENT any adoption rates, market share figures, abandonment percentages, or SMB statistics.
Do not use any external research numbers — only the approved facts above.
A wrong stat damages brand credibility; a precise product fact builds it.

STYLE RULES:
- Numbers must be exact from the approved list above: "1.2%", "RM 0.40", not "roughly 1%"
- Implication is one direct sentence
- No hashtags, no @ mentions
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust
- [URL] is a literal placeholder — never substitute the real URL

LINK URL RULE:
Set link_url to https://hitpayapp.com/blog/{{slug}} using the most topically relevant slug.
If no clear match, default to: hitpay-rates

LIVE BLOG SLUGS:
{urls_list}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{example}"""


def _build_case_study_prompt(thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)
    example = json.dumps({
        "topic": "F&B payment reconciliation",
        "tweets": [
            "1/3 A restaurant owner in KL was spending every Monday morning reconciling "
            "weekend sales — 4 hours matching card, e-wallet, and cash receipts by hand. "
            "Meanwhile, tables waited for menus. 🧵",
            "2/3 She switched to a single POS connected to all payment methods. "
            "Reconciliation became automatic. Monday mornings went back to prepping for the week.",
            "3/3 Result: 4 hours reclaimed every week. RM 0 in reconciliation errors. "
            "HitPay does this for F&B businesses across Malaysia: [URL]",
        ],
        "link_url": "https://hitpayapp.com/blog/best-payment-gateway-malaysia",
        "visual_note": None,
    }, ensure_ascii=False)
    return f"""You are the @hitpay_app content writer for X (Twitter) — Wednesday slot: Customer Case Study.
Write a 3-tweet before-and-after case study about a real-type Southeast Asian merchant problem that HitPay solves.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH). No monthly fees. 50+ payment methods.
TONE: Narrative, empathetic, specific. Like a journalist telling a business story — not a brand writing a press release.
AUDIENCE: SME founders and merchants in Singapore, Malaysia, or Philippines.

CONTENT FORMAT: Before-and-after thread of exactly 3 tweets
- Exactly 3 tweets numbered "1/3 ...", "2/3 ...", "3/3 ..."
- Tweet 1/3: Set up the merchant before state — name the business type, the pain, the hidden cost. Specific and visceral. End with 🧵
- Tweet 2/3: The turning point — what changed when they switched. One concrete improvement per sentence. No product pitch.
- Tweet 3/3: The outcome — specific time or money saved + HitPay as the reason + [URL]
- Each tweet: 200-280 chars

MERCHANT ARCHETYPES — use one specific type:
- F&B: cafe, restaurant, hawker stall, catering business
- Retail: boutique fashion store, electronics shop, pharmacy
- Services: freelance designer, tuition centre, cleaning company, personal trainer
- E-commerce: Shopify/WooCommerce seller, social commerce seller

PAIN POINTS — pick the most impactful scenario:
- Manual reconciliation eating hours every week
- Late invoices hurting cash flow
- Customers unable to pay due to missing payment methods
- High card fees on every transaction
- Checkout abandonment from a slow or broken payment page

STYLE RULES:
- Name a real-feeling archetype (e.g. "A cafe owner in Orchard Road") — not "Company X"
- Include specific numbers in tweet 3: hours saved, cost reduced
- Short punchy sentences, no jargon
- No hashtags, no @ mentions
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust
- [URL] is a literal placeholder in tweet 3 only

LINK URL RULE:
Set link_url to https://hitpayapp.com/blog/{{slug}} using the most topically relevant slug.
If no clear match, default to: hitpay-rates

LIVE BLOG SLUGS:
{urls_list}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{example}"""


def _build_feature_update_prompt(thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)
    example = json.dumps({
        "topic": "payment link with reminders",
        "tweets": [
            "1/2 Ever sent an invoice, followed up, resent when the link expired, then chased again. "
            "All for a payment that should have taken 30 seconds. 🧵",
            "2/2 HitPay payment links now support custom expiry, auto-reminders, and one-click resend. "
            "Less chasing, more getting paid. Set yours up in two minutes: [URL]",
        ],
        "link_url": "https://hitpayapp.com/blog/payment-link",
        "visual_note": "Annotated screenshot of the payment link dashboard",
    }, ensure_ascii=False)
    return f"""You are the @hitpay_app content writer for X (Twitter) — Thursday slot: Product Feature / Shipping Update.
Write a 2-tweet post about a HitPay feature. Lead with the customer problem — not the technology.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH). No monthly fees. 50+ payment methods.
TONE: Direct, builder's pride. Problem-first, feature-second. Like a founder explaining what they just shipped.
AUDIENCE: SME founders and merchants in Southeast Asia.

CONTENT FORMAT: Product update thread of exactly 2 tweets
- Exactly 2 tweets numbered "1/2 ...", "2/2 ..."
- Tweet 1/2: Lead with the customer pain point — not the solution. The merchant should feel seen before sold to. End with 🧵
- Tweet 2/2: Introduce what HitPay built to solve it. Focus on merchant outcome, not tech specs. End with [URL]
- Each tweet: 200-280 chars

HITPAY FEATURES TO DRAW FROM (verified from changelog — use these, not generic descriptions):
- Tap to Pay on iPhone: accept in-person card & e-wallet payments using your iPhone as the terminal — no hardware needed
- Recurring Bulk Subscriptions: create subscriptions for multiple customers at once from one dashboard upload (launched Sep 2025)
- Shareable Carts: generate a cart link pre-loaded with items that customers open and pay instantly
- Touch 'n Go Offline (MY): accept TnG e-wallet in-person via POS terminal (launched Apr 2025)
- GrabPay & PayLater by Grab Offline (MY): accept Grab wallets in-person at checkout (launched Apr 2025)
- GCash Offline (PH): accept GCash in-person via HitPay POS terminal (launched Apr 2025)
- ShopeePay for Subscriptions (SG & PH): charge ShopeePay for recurring/subscription payments
- PayLater by Grab Online (MY): merchants can offer Grab BNPL at online checkout
- HitPay Payout Rails: own settlement infrastructure for SG, MY, PH — domestic payouts next business day
- Save Payment Details: returning customers pay in one tap — card details saved securely (tokenisation)
- Online Store Templates: launch a branded online store without a developer using built-in templates
- Payment links (shareable, one-click payment for any amount or invoice)
- PayNow / DuitNow / QR Ph QR code generation for in-person or remote collection
- WooCommerce, Shopify, Wix, Magento integrations
- Multi-currency checkout for cross-border sales across 12 APAC markets
- Automatic payment reconciliation and export
- Invoice generation with payment tracking

CRITICAL — NEVER DISPARAGE HITPAY'S OWN PRODUCTS:
HitPay sells card terminals (Ingenico S1F2, DX4000) and supports in-person card payments.
NEVER frame card terminals, POS hardware, or in-person card acceptance as expensive, outdated, or inferior.
The problem in tweet 1 must be a PROCESS pain (reconciliation, checkout friction, multi-market complexity, chasing invoices) — not a dig at any payment method or hardware HitPay offers.

STYLE RULES:
- Tweet 1 names the pain only — no solution hint
- Tweet 2 opens with "Just shipped:", "Now available:", or "We built this because:"
- No hashtags, no @ mentions
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust
- visual_note should suggest a dashboard screenshot or short demo clip
- [URL] is a literal placeholder in tweet 2 only

LINK URL RULE:
Set link_url to https://hitpayapp.com/blog/{{slug}} using the most topically relevant slug.
If no clear match, default to: hitpay-rates

LIVE BLOG SLUGS:
{urls_list}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{example}"""


def _build_hot_take_prompt(thread_size: int) -> str:
    example = json.dumps({
        "topic": "paper cheques in 2026",
        "tweets": [
            "If your vendor payment process still involves printing a cheque, "
            "waiting for it to clear, and calling to confirm — you are not saving money. "
            "You are paying 3 hours of salary to move RM 500."
        ],
        "link_url": None,
        "visual_note": None,
    }, ensure_ascii=False)
    return f"""You are the @hitpay_app content writer for X (Twitter) — Friday slot: Hot Take / Market Rant.
Write a single, text-only tweet with a direct, slightly contrarian stance on broken or outdated payment practices in Southeast Asia.

BRAND: HitPay — the voice is authoritative but not preachy. This is the founder talking.
TONE: Opinionated, direct, confident. Like a CFO who has run out of patience with legacy systems.
AUDIENCE: SME owners, finance managers, and founders in SEA who already feel the pain you are naming.

CONTENT FORMAT: Single text-only tweet (no URL)
- Exactly 1 tweet, no numbering
- 200-280 chars
- Contrarian, direct, slightly provocative
- NO URL in tweet — text-only format performs best for opinion posts on brand accounts
- No HitPay product mention — the brand speaks through the opinion, not a pitch

CRITICAL — NEVER ATTACK HITPAY'S OWN PRODUCTS:
HitPay sells card terminals (Ingenico S1F2, DX4000) and supports in-person card payments.
NEVER write anything that frames card terminals, POS hardware, or in-person card acceptance as outdated, legacy, or inferior.
The hot take must attack PROCESSES or BEHAVIOURS, not payment methods or hardware that HitPay offers.

HOT TAKE TOPICS — pick the sharpest angle if no hint is given:
- Paper cheques in 2026 (still common in MY/PH businesses)
- Manual bank transfer reconciliation eating finance team hours
- Businesses that only accept one payment method in a market with 50+
- Late payment culture and the damage it does to SME cash flow
- The myth that cash is simpler for a growing business
- The hidden labour cost of chasing unpaid invoices
- Finance teams spending hours on manual reconciliation that software eliminates
- Checkout pages with 1 payment method losing customers who prefer QR or e-wallets
- Businesses that delay going digital losing customers to competitors who already have

STYLE RULES:
- One clear argument — not a list
- Specific enough to feel real: include a cost, timeframe, or concrete scenario
- Can be framed as: "If X still happens in your business in 2026, here is what it is costing you"
- No hashtags, no @ mentions, no URL of any kind
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
Set link_url to null. Set visual_note to null.
{example}"""


def _build_behind_scenes_prompt(thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)
    example = json.dumps({
        "topic": "transaction milestone",
        "tweets": [
            "Our engineering team just processed the 10 millionth PayNow transaction on HitPay. "
            "No fanfare — just merchants getting paid in real time, every day. "
            "That is the whole point. ☕"
        ],
        "link_url": None,
        "visual_note": "Milestone counter screenshot or team photo",
    }, ensure_ascii=False)
    return f"""You are the @hitpay_app content writer for X (Twitter) — Sunday slot: Behind the Scenes / Build in Public.
Write a single humanizing tweet that celebrates a HitPay milestone, team moment, or honest reflection on building the product.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH).
TONE: Warm, honest, proud without bragging. Like a founder reflecting on a quiet Sunday.
AUDIENCE: Anyone following HitPay — merchants, investors, other founders, team members.

CONTENT FORMAT: Single humanizing tweet
- Exactly 1 tweet, no numbering
- 200-280 chars
- One concrete detail anchors it: a number, a milestone, a specific moment
- Tone: genuine pride, not marketing polish
- A small emoji is fine if natural (coffee cup, celebration, wrench) — one maximum
- [URL] only if the milestone naturally links to a resource — otherwise set link_url to null

MILESTONE IDEAS — pick the most resonant if no hint is given:
- Transaction volume milestone (millions processed, payouts sent)
- New regulatory approval or licence milestone
- Feature shipped after months of work
- Team growth milestone
- Merchant count milestone
- A stat reflecting real impact (dollars processed this year)
- Honest reflection on building payments infrastructure
- A customer who grew significantly using HitPay

STYLE RULES:
- Warmth over polish — imperfect is more human
- One concrete anchor per tweet
- No hashtags, no @ mentions
- Banned words: seamlessly, unlock, revolutionise, game-changer, cutting-edge, empower, leverage, utilise, transformative, innovative, robust

LINK URL RULE (optional):
Set link_url to https://hitpayapp.com/blog/{{slug}} only if it fits naturally. Otherwise null.

LIVE BLOG SLUGS:
{urls_list}

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{example}"""


TOPIC_POOL = [
    "MDR (Merchant Discount Rate) and interchange fees explained",
    "Payment settlement timelines: T+0, T+1, T+2 and why they matter",
    "QR vs card payments: cost and speed comparison for SMEs",
    "How chargebacks work and how merchants can fight them",
    "Cross-border payment fees in SEA and how to reduce them",
    "The hidden cost of free payment terminals",
    "Buy Now Pay Later economics from the merchant's perspective",
    "Cash flow impact of choosing the wrong payment method",
    "POS vs online vs invoice payments — when to use which",
    "Real-time payments in SEA: PayNow, DuitNow, QR Ph adoption",
    "Payment reconciliation: how to stop losing hours to manual matching",
    "Recurring billing and subscription payment mechanics",
]

STORYTELLING_TOPIC_POOL = [
    "Payment systems built for where you are, not who you serve",
    "The silent cost of cash that nobody talks about",
    "Why your invoice tool doesn't feel like yours",
    "The gap between 'accepted' and 'paid'",
    "Cross-border payments from a customer's perspective",
    "What a tourist feels when their card gets declined",
    "The moment a business realises their checkout is losing them customers",
    "Reconciliation as a symptom, not a problem",
    "Why 'no monthly fee' changes how merchants take risks",
    "The difference between a payment tool and payment infrastructure",
    "What getting paid really means for a small business",
    "How payment friction becomes a business culture problem",
]

# Shared topic pool used for automated X and Threads generation when no topic_hint is supplied
HITPAY_TOPIC_POOL: list[str] = [
    # How payments work
    "MDR explained: who keeps your 2.8% card fee and why",
    "Payment settlement timelines: T+0, T+1, T+2 and what they mean for cash flow",
    "How a payment gateway differs from a payment processor",
    "How chargebacks work and what merchants can do to fight them",
    "Buy Now Pay Later economics from the merchant's perspective",
    "How recurring billing and subscription payments actually work",
    "What interchange fees are and why they vary by card type",
    "How QR code payments work end-to-end for a merchant",
    # Costs & fees
    "The real cost of accepting cash: errors, time, and operational risk",
    "Why free payment terminals are rarely actually free",
    "How to reduce card processing fees without rebuilding your stack",
    "The hidden cost of a slow or broken checkout page",
    "What 'no monthly fee' really means for a growing business",
    "Fee transparency: understanding every line item on your payment provider invoice",
    "Paying 3% MDR when real-time alternatives cost under 1.5%: the maths",
    # Operations
    "Payment reconciliation: why it eats hours and how to automate it",
    "POS vs payment link vs invoice: when to use which",
    "How to handle a payment dispute and protect your revenue",
    "How to accept cross-border payments from tourists in Southeast Asia",
    "Multi-currency checkout: when it makes sense for a small business",
    "How to create and share a payment link for instant collections",
    "Setting up PayNow, DuitNow, or QR Ph for your business: what to expect",
    # Cash flow & business impact
    "How late invoices damage SME cash flow more than transaction fees do",
    "Why next business day payouts matter for small business working capital",
    "The checkout abandonment problem: how missing payment methods cost you sales",
    "How accepting e-wallets changes customer spending behaviour in SEA",
    "How payment method choice affects customer trust at checkout",
    "Cash flow impact of T+1 vs T+2 settlement: what the difference adds up to",
    "The gap between a sale and the money in your account — and how to close it",
    # Market & adoption
    "Real-time payments in Southeast Asia: PayNow, DuitNow, and QR Ph compared",
    "E-wallet landscape in Malaysia: GrabPay, TnG eWallet, ShopeePay for merchants",
    "QR code payments replacing card terminals in SG, MY, and PH",
    "Cross-border QR payments: accepting tourists from Thailand, Indonesia, and China",
    "How digital payments are changing F&B businesses across Southeast Asia",
    "The shift from cash to QR in Philippine sari-sari stores and wet markets",
    # Merchant-specific
    "Payment strategy for Shopify and WooCommerce stores in SEA",
    "How subscription businesses should think about their payment method mix",
    "Invoice payment best practices for service businesses in SEA",
    "Why B2B merchants lose more to late payment than to high fees",
    "How to optimise checkout for mobile-first customers in Southeast Asia",
    # Real HitPay product features (from changelog)
    "Tap to Pay on iPhone: accepting card payments in-person without a card terminal",
    "How recurring bulk subscriptions save time for businesses with many subscribers",
    "Shareable cart links: a faster way to sell without a full online store",
    "Touch n Go, GrabPay, and PayLater by Grab now available offline for Malaysian merchants",
    "GCash offline payments: what it means for Philippine merchants at the counter",
    "ShopeePay for subscriptions: accepting recurring payments via e-wallet in SG and PH",
    "PayLater by Grab for online merchants in Malaysia: offering BNPL without building anything",
    "How HitPay Payout Rails give SG, MY, and PH merchants faster, more reliable settlements",
    "Save payment details: how one-tap checkout for returning customers increases conversion",
    "Launching an online store without a developer using HitPay's built-in templates",
]

# All valid (style, thread_size) combinations — used for randomized automation
_AUTOMATION_VARIANTS: list[tuple[str, int]] = [
    ("educational", 1),
    ("educational", 3),
    ("educational", 5),
    ("educational", 7),
    ("storytelling", 1),
    ("storytelling", 2),
    ("storytelling", 3),
    ("storytelling", 5),
]

_AUTOMATION_MARKETS = ["SG", "MY", "PH", None]  # None = SEA broadly

CONTENT_TYPE_BY_WEEKDAY: dict[int, str] = {
    0: "educational_breakdown",  # Monday
    1: "stat_hook",              # Tuesday
    2: "case_study",             # Wednesday
    3: "feature_update",         # Thursday
    4: "hot_take",               # Friday
    5: "deep_dive",              # Saturday
    6: "behind_scenes",          # Sunday
}

CONTENT_TYPE_CONFIGS: dict[str, dict] = {
    "educational_breakdown": {"thread_size": 3, "style": "educational"},
    "stat_hook":             {"thread_size": 1, "style": "educational"},
    "case_study":            {"thread_size": 3, "style": "storytelling"},
    "feature_update":        {"thread_size": 2, "style": "educational"},
    "hot_take":              {"thread_size": 1, "style": "storytelling"},
    "deep_dive":             {"thread_size": 7, "style": "educational"},
    "behind_scenes":         {"thread_size": 1, "style": "storytelling"},
}



# Monday and Tuesday use a published blog post as source instead of a random topic.
_BLOG_REPURPOSE_CONTENT_TYPES = {"educational_breakdown", "stat_hook"}


def generate_random_x_post(
    market: str = None,
    topic_hint: str = None,
    brand: str = "hitpay",
    content_type: str | None = None,
) -> dict:
    """Generate an X post using day-of-week content type (hitpay) or random variant (other brands).

    Monday (educational_breakdown) and Tuesday (stat_hook) repurpose a published blog post
    and mark it as used so it won't be repeated. Falls back to topic-pool generation if no
    unpublished posts are available.

    Pass content_type to override day-of-week detection (useful for testing specific formats).
    Returns dict with keys: topic, tweets, link_url, visual_note, style, thread_size, market, content_type
    """
    if brand == "hitpay":
        if topic_hint is None:
            topic_hint = random.choice(HITPAY_TOPIC_POOL)
        if content_type is None:
            weekday = _datetime.utcnow().weekday()
            content_type = CONTENT_TYPE_BY_WEEKDAY.get(weekday, "educational_breakdown")
        config = CONTENT_TYPE_CONFIGS[content_type]
        thread_size = config["thread_size"]
        style = config["style"]
    else:
        style, thread_size = random.choice(_AUTOMATION_VARIANTS)
        content_type = None

    chosen_market = market if market is not None else random.choice(_AUTOMATION_MARKETS)

    if brand == "hitpay" and content_type in _BLOG_REPURPOSE_CONTENT_TYPES:
        from src.database import get_unrepurposed_published_post, mark_post_x_repurposed
        from src.repurposer import repurpose_post_as_thread
        post = get_unrepurposed_published_post(brand=brand)
        if post:
            result = repurpose_post_as_thread(post, thread_size)
            mark_post_x_repurposed(post["id"])
            result["style"] = style
            result["thread_size"] = thread_size
            result["market"] = post.get("country") or chosen_market
            result["content_type"] = content_type
            result["source_post_id"] = post["id"]
            return result
        # No published posts left — fall through to topic-pool generation

    result = generate_thought_leadership_thread(
        market=chosen_market,
        topic_hint=topic_hint,
        thread_size=thread_size,
        style=style,
        content_type=content_type,
        brand=brand,
    )
    result["style"] = style
    result["thread_size"] = thread_size
    result["market"] = chosen_market
    result["content_type"] = content_type
    return result


def generate_thought_leadership_thread(
    market: str = None,
    topic_hint: str = None,
    thread_size: int = 7,
    style: str = "educational",
    content_type: str | None = None,
    brand: str = "hitpay",
) -> dict:
    """Generate a standalone thought leadership X post or thread on a payments topic.

    Args:
        market: Optional market code (SG, MY, PH)
        topic_hint: Optional topic to focus on
        thread_size: Number of tweets — 1, 2 (storytelling), 3, 5, or 7
        style: "educational" (data-driven) or "storytelling" (narrative arc)

    Returns: {"topic": str, "tweets": list[str], "link_url": str, "visual_note": str | None}
    """
    if style not in ("educational", "storytelling"):
        raise ValueError(f"style must be 'educational' or 'storytelling' — got {style!r}")

    if thread_size not in (1, 2, 3, 5, 7):
        raise ValueError(f"thread_size must be one of (1, 2, 3, 5, 7) — got {thread_size}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    context_parts = []

    from src.brand_config import get_brand_config
    bc = get_brand_config(brand)

    if market and market in COUNTRY_CONTEXT:
        ctx = COUNTRY_CONTEXT[market]
        context_parts.append(
            f"TARGET MARKET: {ctx['name']} ({market})\n"
            f"Local payment methods: {ctx['local_methods']}\n"
            f"Cross-border: {ctx['cross_border']}\n"
            f"Payout timing: {ctx['payout']}"
        )
    else:
        context_parts.append("TARGET MARKET: Southeast Asia broadly (SG, MY, PH)")

    if topic_hint:
        product_docs = _load_relevant_docs(topic_hint, docs_file=bc.docs_file, max_chars=8000)
        if product_docs:
            context_parts.append(f"KNOWLEDGE BASE CONTEXT:\n{product_docs}")
        context_parts.append(f"TOPIC: Write the content about: {topic_hint}")
    else:
        default_pool = "topic pool for a general SEA SMB audience" if brand == "smegrowthhub" else "topic pool for a general SEA payments audience"
        context_parts.append(f"Pick the best topic from the {default_pool}.")

    context_parts.append(
        f"FORMAT: Generate exactly {thread_size} tweet(s) as specified."
    )

    user_message = "\n\n".join(context_parts)

    if brand == "smegrowthhub":
        prompt_builder = _build_sme_storytelling_prompt if style == "storytelling" else _build_sme_educational_prompt
    elif content_type:
        _ct_map = {
            "educational_breakdown": _build_thought_leadership_prompt,
            "stat_hook":             _build_stat_hook_prompt,
            "case_study":            _build_case_study_prompt,
            "feature_update":        _build_feature_update_prompt,
            "hot_take":              _build_hot_take_prompt,
            "deep_dive":             _build_thought_leadership_prompt,
            "behind_scenes":         _build_behind_scenes_prompt,
        }
        prompt_builder = _ct_map.get(content_type, _build_thought_leadership_prompt)
    else:
        prompt_builder = _build_storytelling_prompt if style == "storytelling" else _build_thought_leadership_prompt

    msg = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=prompt_builder(thread_size) + "\n\n" + _WRITING_STYLE_RULES,
        messages=[{"role": "user", "content": user_message}],
        metadata={"user_id": "x-generation"}
    )

    raw = msg.content[0].text.strip()

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        raw = json_match.group(0)
    else:
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            data = json.loads(repair_json(raw))
        except Exception as e:
            raise ValueError(f"Could not parse thought leadership response: {e}")

    tweets = data.get("tweets")
    if not isinstance(tweets, list) or len(tweets) < 1:
        raise ValueError(f"Expected tweets array, got: {tweets!r}")

    # Trim if model over-generates
    tweets = tweets[:thread_size]

    if len(tweets) < thread_size:
        raise ValueError(f"Expected {thread_size} tweet(s), got {len(tweets)}")

    tweets = [_cap_tweet(t) for t in tweets]

    # hot_take posts are intentionally text-only — no URL attached
    if content_type == "hot_take":
        link_url = None
        # Strip any stray [URL] or ellipsis Claude may have added
        tweets[-1] = tweets[-1].replace("[URL]", "").rstrip()\
            .rstrip("…").rstrip(".").rstrip()
    else:
        fallback = _SME_FALLBACK_URL if brand == "smegrowthhub" else _FALLBACK_URL
        link_url = data.get("link_url") or fallback
        if brand != "smegrowthhub" and not _is_valid_blog_url(link_url):
            link_url = fallback

        # Ensure the last tweet carries the [URL] placeholder.
        # Claude sometimes outputs … (U+2026) or ... instead of [URL].
        last = tweets[-1]
        if "[URL]" not in last:
            for ellipsis in ("…", "..."):
                if last.endswith(ellipsis):
                    tweets[-1] = last[: -len(ellipsis)].rstrip() + " [URL]"
                    break
            else:
                # No ellipsis either — append [URL] after a space
                tweets[-1] = _cap_tweet(last.rstrip() + " [URL]")

    return {
        "topic": data.get("topic", ""),
        "tweets": tweets,
        "link_url": link_url,
        "visual_note": data.get("visual_note"),
    }
