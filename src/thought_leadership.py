import json
import re

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.generator import COUNTRY_CONTEXT, _load_relevant_docs, _messages_create_with_retry


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

_VALID_URL_SET = {url for _, url in VALID_BLOG_URLS}
_FALLBACK_URL = "https://hitpayapp.com/blog/hitpay-rates"


def _build_thought_leadership_prompt(thread_size: int) -> str:
    urls_list = "\n".join(f'  - "{title}": {url}' for title, url in VALID_BLOG_URLS)

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
You MUST set link_url to one of the following verified HitPay blog URLs only.
Do NOT invent or guess any other URL. Pick the most topically relevant one.
If no clear match, default to the Rates & Pricing URL.

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


def generate_thought_leadership_thread(
    market: str = None,
    topic_hint: str = None,
    thread_size: int = 7,
) -> dict:
    """Generate a standalone thought leadership X post or thread on a payments topic.

    Args:
        market: Optional market code (SG, MY, PH)
        topic_hint: Optional topic to focus on
        thread_size: Number of tweets — 1 (single post), 3, 5, or 7

    Returns: {"topic": str, "tweets": list[str], "link_url": str, "visual_note": str | None}
    """
    if thread_size not in (1, 3, 5, 7):
        raise ValueError(f"thread_size must be 1, 3, 5, or 7 — got {thread_size}")

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

    msg = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=_build_thought_leadership_prompt(thread_size),
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
    if link_url not in _VALID_URL_SET:
        link_url = _FALLBACK_URL

    return {
        "topic": data.get("topic", ""),
        "tweets": tweets,
        "link_url": link_url,
        "visual_note": data.get("visual_note"),
    }
