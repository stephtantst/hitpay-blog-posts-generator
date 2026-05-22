import json
import re

import anthropic


def _cap_tweet(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    cutoff = text.rfind(" ", 0, limit - 1)
    if cutoff <= 0:
        cutoff = limit - 1
    return text[:cutoff] + "…"

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.generator import COUNTRY_CONTEXT, _load_relevant_docs, _messages_create_with_retry

THOUGHT_LEADERSHIP_PROMPT = """You are the payments education writer for @hitpay_app on X (Twitter).
Write authoritative, educational threads that teach SME founders, merchants, and finance managers something genuinely useful about payments — the way a CFO would explain it to a first-time founder.

BRAND: HitPay — MAS-licensed (SG), BNM-approved (MY), BSP OPS-licensed (PH). No monthly fees. 50+ payment methods. Next business day payouts for domestic transactions.
TONE: Direct, factual, educational. Conversational but expert. Not corporate. Not promotional until the final tweet.
AUDIENCE: SME founders and merchants in Southeast Asia (SG/MY/PH).

THREAD FORMAT:
- 6–7 tweets numbered "1/7 ...", "2/7 ...", etc. (adjust N to match actual count)
- First tweet: introduce the concept clearly — definition or hook — end with 🧵
- Middle tweets: break down the concept with specific facts, numbers, concrete examples
- Weave in relevant local payment methods naturally where they fit (PayNow for SG, DuitNow for MY, QR Ph for PH)
- Final tweet: actionable takeaway + natural HitPay mention + [URL] as literal placeholder for the link
- Each tweet: 200–280 chars, self-contained, addresses the reader as "you" (the merchant)

STYLE RULES:
- Use specific numbers: "A 2% MDR on a $100 sale means you receive $98"
- Em-dashes (—) are fine for flow, used sparingly
- No hashtags, no @ mentions
- No URLs in any tweet except the final one — use [URL] as a literal placeholder there
- No promotional language, feature pitching, or "HitPay does X" until the final tweet
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

OUTPUT: Return a raw JSON object only. No markdown fences, no preamble.
{
  "topic": "<short topic name, e.g. MDR and interchange fees>",
  "tweets": ["1/7 ...", "2/7 ...", "3/7 ...", "4/7 ...", "5/7 ...", "6/7 ...", "7/7 ... [URL]"],
  "link_url": "<most relevant HitPay page URL — pricing page by default: https://hitpayapp.com/pricing>",
  "visual_note": "<suggestion for screenshot/image to attach, or null>"
}

link_url guidance: use https://hitpayapp.com/pricing for general/cost topics, https://hitpayapp.com/payment-link for invoice/link topics, https://hitpayapp.com/point-of-sale for POS topics.
IMPORTANT: [URL] in the final tweet is a literal placeholder — never substitute the real URL into the tweet text."""


def generate_thought_leadership_thread(
    market: str = None,
    topic_hint: str = None,
) -> dict:
    """Generate a standalone thought leadership X thread on a payments topic.

    Returns: {"topic": str, "tweets": list[str], "link_url": str, "visual_note": str | None}
    """
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
        context_parts.append(f"TOPIC: Write the thread about: {topic_hint}")
    else:
        context_parts.append("Pick the best topic from the topic pool above for a general SEA payments audience.")

    user_message = "\n\n".join(context_parts)

    msg = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=THOUGHT_LEADERSHIP_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = msg.content[0].text.strip()

    # Extract the first JSON object regardless of any preamble/fence the model adds
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
    if not isinstance(tweets, list) or len(tweets) < 5:
        raise ValueError(f"Expected at least 5 tweets, got: {tweets!r}")

    tweets = [_cap_tweet(t) for t in tweets]

    return {
        "topic": data.get("topic", ""),
        "tweets": tweets,
        "link_url": data.get("link_url") or "https://hitpayapp.com/pricing",
        "visual_note": data.get("visual_note"),
    }
