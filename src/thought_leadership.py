import json
import random
import re
import time

import anthropic
import requests

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.generator import COUNTRY_CONTEXT, _load_relevant_docs, _messages_create_with_retry

_SITEMAP_URL = "https://hitpayapp.com/sitemap_en.xml"
_blog_slugs_cache: list[str] | None = None
_blog_slugs_cache_ts: float = 0
_SLUG_CACHE_TTL = 3600  # 1 hour


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


def generate_random_x_post(market: str = None, topic_hint: str = None) -> dict:
    """Pick a random style + thread_size and generate a standalone X post.

    Designed as the single entry point for automated 3x/week scheduling.

    Returns: {
        "topic": str, "tweets": list[str], "link_url": str, "visual_note": str | None,
        "style": str, "thread_size": int, "market": str | None
    }
    """
    style, thread_size = random.choice(_AUTOMATION_VARIANTS)
    chosen_market = market if market is not None else random.choice(_AUTOMATION_MARKETS)
    result = generate_thought_leadership_thread(
        market=chosen_market,
        topic_hint=topic_hint,
        thread_size=thread_size,
        style=style,
    )
    result["style"] = style
    result["thread_size"] = thread_size
    result["market"] = chosen_market
    return result


def generate_thought_leadership_thread(
    market: str = None,
    topic_hint: str = None,
    thread_size: int = 7,
    style: str = "educational",
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
        product_docs = _load_relevant_docs(topic_hint, max_chars=8000)
        if product_docs:
            context_parts.append(f"HITPAY PRODUCT CONTEXT:\n{product_docs}")
        context_parts.append(f"TOPIC: Write the content about: {topic_hint}")
    else:
        context_parts.append("Pick the best topic from the topic pool for a general SEA payments audience.")

    context_parts.append(
        f"FORMAT: Generate exactly {thread_size} tweet(s) as specified."
    )

    user_message = "\n\n".join(context_parts)

    prompt_builder = _build_storytelling_prompt if style == "storytelling" else _build_thought_leadership_prompt
    msg = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=prompt_builder(thread_size),
        messages=[{"role": "user", "content": user_message}],
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

    # Enforce verified URL — no dead links
    link_url = data.get("link_url") or _FALLBACK_URL
    if not _is_valid_blog_url(link_url):
        link_url = _FALLBACK_URL

    return {
        "topic": data.get("topic", ""),
        "tweets": tweets,
        "link_url": link_url,
        "visual_note": data.get("visual_note"),
    }
