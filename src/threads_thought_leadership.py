import json
import random
import re

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.generator import _messages_create_with_retry
from src.thought_leadership import _fetch_live_blog_slugs

_FALLBACK_URL = "https://hitpayapp.com/blog/hitpay-rates"

# (business_type, location, customer_type, hitpay_product)
_STORY_SEEDS: dict[str, list[tuple]] = {
    "MY": [
        ("textile shop", "Penang George Town", "tourists from Japan, South Korea, and China", "Borderless QR"),
        ("batik fabric shop", "Melaka", "tourists from mainland China", "Borderless QR"),
        ("night market vendor", "Kuala Lumpur", "customers who only had foreign cards or cash", "payment link"),
        ("homestay", "Cameron Highlands", "foreign guests booking from abroad", "payment link"),
        ("kopitiam", "Ipoh", "regular customers transitioning from cash to QR", "HitPay QR"),
        ("handicraft shop", "Langkawi", "duty-free shoppers and international tourists", "Borderless QR"),
        ("dental clinic", "Petaling Jaya", "patients wanting to pay in instalments", "payment links"),
    ],
    "SG": [
        ("heritage craft shop", "Chinatown", "tourists from mainland China and Japan", "Borderless QR"),
        ("hawker stall", "Maxwell Food Centre", "lunchtime office workers", "HitPay QR"),
        ("provision shop", "Toa Payoh", "longtime regulars and younger neighbours", "QR payments"),
        ("tailoring shop", "Little India", "customers ordering custom pieces from abroad", "payment link"),
        ("florist", "Tiong Bahru", "corporate clients with recurring flower subscriptions", "payment links"),
        ("bookshop", "Bukit Timah", "parents paying for tuition materials", "payment links"),
    ],
    "PH": [
        ("beach resort", "El Nido, Palawan", "foreign tourists from the US, Australia, and Europe", "Borderless QR"),
        ("craft market stall", "Intramuros, Manila", "tourists using WeChat Pay or Alipay", "Borderless QR"),
        ("surf school", "Siargao", "foreign guests without Philippine peso", "Borderless QR"),
        ("sari-sari store", "Quezon City", "neighbourhood regulars", "GCash QR"),
        ("island-hopping operator", "Coron, Palawan", "international tour groups", "Borderless QR"),
    ],
    "SEA": [
        ("small textile shop", "a heritage port city", "international tourists", "Borderless QR"),
        ("family-run guesthouse", "a coastal town", "guests booking from abroad", "payment link"),
        ("craft workshop", "an old town district", "tourists and collectors from overseas", "Borderless QR"),
        ("street food stall", "a city night market", "digital-first customers", "QR payments"),
        ("boutique dive operator", "an island destination", "foreign divers without local cash", "Borderless QR"),
    ],
}

THREADS_SYSTEM_PROMPT = """You are a brand storyteller for HitPay, a Southeast Asian payment platform.

You write short-form narratives for Meta Threads — the kind that feel human, specific, and earned. Your stories are told from HitPay's perspective ("we", "our merchants"), but they're really about the merchants: their daily friction, their workarounds, and what changes when payments stop being a problem.

VOICE:
- Warm and observational. The narrator has spent time listening to merchants.
- Specific and concrete: name cities, name the tourist home countries, name the human details (a calculator on the counter, a phone propped against the register, a notebook of hand-written totals).
- Understated. The emotional weight comes from detail, not adjectives.
- No superlatives. No marketing language. No claims. Just story.
- First person plural: "We", "our merchants", "she told us", "we had a partner in..."

STORYTELLING RULES:
- Every story needs a human detail — something physical or behavioural that anchors the merchant's world
- The problem is shown, not explained
- The tension builds through repetition: "Sometimes it worked. A lot of the time, it didn't."
- The resolution is functional and quiet — not a miracle, just: it works now
- The brand closer ("That's the kind of thing we build for.") should feel earned, not appended
- Callbacks: if you introduce a detail in Post 1, bring it back in the final post

DO NOT include: hashtags, statistics or percentages, product feature lists, emojis (except 🧵 at the end of Post 1 in multi-part threads), marketing buzzwords (seamless, empower, innovate, frictionless, cutting-edge, robust)"""


def _build_story_prompt(market: str | None, topic_hint: str | None, thread_size: int) -> str:
    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in slugs)

    market_key = market if market in _STORY_SEEDS else "SEA"
    biz, location, customers, product = random.choice(_STORY_SEEDS[market_key])

    if topic_hint:
        seed_ctx = f"Topic direction: {topic_hint}\nStill ground it in a specific merchant story."
    else:
        seed_ctx = (
            f"Story seed (use as inspiration, not verbatim):\n"
            f"- Merchant: {biz} in {location}\n"
            f"- Their customers: {customers}\n"
            f"- HitPay product that helped: {product}"
        )

    if market == "MY":
        mkt_ctx = "Market: Malaysia. Currency: ringgit (MYR). Relevant: DuitNow, FPX, Borderless QR, tourist areas in Penang/KL/Melaka/Langkawi."
    elif market == "SG":
        mkt_ctx = "Market: Singapore. Currency: SGD. Relevant: PayNow, hawker culture, tourist belts (Chinatown, Little India, Orchard)."
    elif market == "PH":
        mkt_ctx = "Market: Philippines. Currency: PHP. Relevant: GCash, QR Ph, island tourism (Palawan, Siargao, Boracay)."
    else:
        mkt_ctx = "Market: Southeast Asia broadly. Pick the most vivid and specific location from MY, SG, or PH."

    if thread_size == 1:
        fmt = (
            "Single post (no numbering): a complete micro-story. "
            "Human detail → friction → resolution → brand close. 200–450 characters."
        )
    elif thread_size == 3:
        fmt = (
            "3-part thread:\n"
            "Post 1/3 — The Scene: introduce the merchant, location, and a specific human detail that reveals the problem. End at the moment of friction. End post with 🧵\n"
            "Post 2/3 — The Tension: their workaround, the cost, the sale that didn't happen, the habit they developed just to cope.\n"
            "Post 3/3 — The Resolution: HitPay product introduced briefly and functionally. Callback to the opening human detail. End with a variation of: \"That's the kind of thing we build for.\""
        )
    else:  # 5
        fmt = (
            "5-part thread:\n"
            "Post 1/5 — The Scene: merchant, location, the telling human detail. End with 🧵\n"
            "Post 2/5 — The Problem: how widespread or frequent the friction was.\n"
            "Post 3/5 — The Breaking Point: one specific incident. A customer who left. A late night reconciling. A sale lost at the worst moment.\n"
            "Post 4/5 — The Shift: how they found HitPay. What changed. Functional, not miraculous.\n"
            "Post 5/5 — The Close: callback to the opening human detail. Brand closer: \"That's the kind of thing we build for.\""
        )

    return f"""Write a HitPay Threads story.

{seed_ctx}

{mkt_ctx}

FORMAT:
{fmt}

Each post: 200–450 characters. No hashtags. No emojis except 🧵 noted above. Warm, specific, observational tone.

LINK URL RULE:
Set link_url to https://hitpayapp.com/blog/{{slug}} using the most topically relevant slug.
If no clear match, default to: hitpay-rates

LIVE BLOG SLUGS:
{urls_list}

Return raw JSON only — no markdown fences:
{{"topic": "...", "posts": [...], "link_url": "https://hitpayapp.com/blog/..."}}"""


def _cap_post(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    cutoff = text.rfind(" ", 0, limit - 1)
    if cutoff <= 0:
        cutoff = limit - 1
    return text[:cutoff] + "…"


def generate_threads_story(
    market: str = None,
    topic_hint: str = None,
    thread_size: int = 3,
) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = _build_story_prompt(market, topic_hint, thread_size)

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=THREADS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)

    posts = data.get("posts")
    if not isinstance(posts, list) or not posts:
        raise ValueError(f"Expected posts array, got: {posts!r}")

    data["posts"] = [_cap_post(p) for p in posts]

    link_url = data.get("link_url") or _FALLBACK_URL
    if not re.match(r"^https://hitpayapp\.com/blog/[a-zA-Z0-9_\-()/]+$", link_url):
        link_url = _FALLBACK_URL
    data["link_url"] = link_url

    return data
