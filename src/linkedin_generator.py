import json
import random
import re

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.generator import _messages_create_with_retry
from src.thought_leadership import _fetch_live_blog_slugs, _WRITING_STYLE_RULES

_FALLBACK_URL = "https://hitpayapp.com/blog/hitpay-rates"
_SME_FALLBACK_URL = "https://smegrowthhub.com/blog"

_LINKEDIN_TOPICS: dict[str, list[str]] = {
    "SG": [
        "Why PayNow works for Singapore SMEs",
        "The real cost of card payment fees for hawker businesses",
        "How Singapore merchants accept WeChat Pay and Alipay from tourists",
        "Payment link vs QR code: which is right for your Singapore business?",
        "Why small Singapore businesses are switching to HitPay",
        "Managing multi-currency payments as a Singapore e-commerce business",
        "How to get MAS-licensed payment processing for your business",
    ],
    "MY": [
        "DuitNow vs FPX: which works better for Malaysian SMEs?",
        "How Malaysian merchants are accepting payments from international tourists",
        "The cost of payment processing for Malaysian small businesses",
        "Why Malaysian e-commerce sellers switch from marketplace to own store",
        "How to accept payments as a Malaysian home-based business",
        "Borderless QR: how Penang businesses serve Japanese and Chinese tourists",
    ],
    "PH": [
        "GCash vs QR Ph: what Philippine businesses need to know",
        "How Philippine SMEs accept payments from foreign tourists",
        "The hidden cost of cash for Filipino sari-sari stores",
        "How to get started with digital payments for your Philippine business",
        "QR payment adoption in the Philippines: what merchants are saying",
    ],
    "SEA": [
        "Why payment method diversity matters for Southeast Asian SMEs",
        "How small businesses in SEA are competing on checkout experience",
        "The case for accepting tourist payments in Southeast Asia",
        "What payment infrastructure actually costs a growing SEA business",
        "How multi-market businesses manage payments across SG, MY, and PH",
    ],
}

LINKEDIN_SYSTEM_PROMPT = """You are a content strategist for HitPay, a Southeast Asian payment platform trusted by 30,000+ businesses.

You write LinkedIn posts for HitPay's business audience: SME owners, finance managers, operations leads, and entrepreneurs in Singapore, Malaysia, and the Philippines. These are people who deal with payment friction every day and respect content that is specific, credible, and useful.

VOICE:
- Professional but warm. Like a trusted industry peer, not a brand account.
- Specific and evidence-grounded: use real market details, specific friction scenarios, concrete numbers where available.
- Insight-first: open with a counterintuitive observation, a specific tension, or a fact that reframes how the reader sees the problem.
- No buzzwords: never use "seamless", "empower", "innovate", "frictionless", "cutting-edge", "robust", "game-changer".
- First person plural occasionally ("We've seen this with merchants…") but mostly third person observation.

FORMAT:
- Single post. No thread separators.
- 900–1,400 characters. Long enough to develop an idea; short enough to read in under 90 seconds.
- Structure: Hook (1-2 lines) → Specific insight or tension (2-3 lines) → What it means for the business owner (2-3 lines) → Quiet CTA linking to a relevant blog post.
- 2–3 relevant hashtags at the very end (e.g. #PayNow #SME #Singapore). No more.
- No emojis except one optional at the very start of the hook line.

CONTENT RULES:
- Ground every post in a specific market: SG, MY, or PH — never generic "businesses everywhere"
- Reference real payment methods: PayNow, DuitNow, FPX, GCash, QR Ph, Borderless QR
- The CTA link must be a real HitPay blog post (provided in slug list). Never invent slugs.
- Don't enumerate feature lists. Tell a story through one specific scenario."""

SME_LINKEDIN_SYSTEM_PROMPT = """You are a content strategist for SME Growth Hub, an independent editorial resource for small business operators across Southeast Asia.

You write LinkedIn posts for a professional audience: business owners, freelancers, finance leads, and entrepreneurs who want practical, credible insight — not brand content.

VOICE:
- Peer-to-peer tone. Like advice from a consultant who has seen a lot of small businesses.
- Specific and grounded. Name real cities, real regulatory bodies (CPF, EPF, BIR, SST), real tools.
- Insight-led: open with something that reframes the reader's understanding of a problem they already have.
- No brand promotion. Don't mention HitPay unless the post is directly about payment methods.
- No buzzwords, no superlatives, no marketing language.

FORMAT:
- Single post. 900–1,400 characters.
- Structure: Reframe hook → Specific evidence or scenario → What it means practically → Quiet CTA.
- 2–3 relevant hashtags at the end. No emojis except one optional opener.

CONTENT RULES:
- Topics: cash flow, invoicing, payroll, hiring, accounting, payment processing, e-commerce setup, business registration
- Always ground in a specific SEA market with local context
- CTA link must be a real blog post slug from the provided list."""


def _build_linkedin_prompt(market: str | None, topic_hint: str | None, brand: str) -> str:
    from src.brand_config import get_brand_config
    bc = get_brand_config(brand)

    slugs = _fetch_live_blog_slugs()
    if not slugs and brand == "hitpay":
        slugs = ["hitpay-rates", "paynow-singapore", "duitnow-malaysia", "gcash-philippines"]
    urls_list = "\n".join(f"  {s}" for s in (slugs or []))

    market_key = market if market in _LINKEDIN_TOPICS else "SEA"

    if topic_hint:
        topic_ctx = f"Topic: {topic_hint}"
    else:
        topic_ctx = f"Topic: {random.choice(_LINKEDIN_TOPICS[market_key])}"

    if market == "MY":
        mkt_ctx = (
            "Market: Malaysia. Currency: MYR. "
            "Reference: DuitNow (1.2%), FPX (1.8% + RM0.40), BNM-approved, Penang/KL/Melaka/Langkawi merchant contexts."
        )
    elif market == "SG":
        mkt_ctx = (
            "Market: Singapore. Currency: SGD. "
            "Reference: PayNow (0.65% + S$0.30), MAS-licensed, hawker culture, Chinatown/Little India/Orchard tourist contexts."
        )
    elif market == "PH":
        mkt_ctx = (
            "Market: Philippines. Currency: PHP. "
            "Reference: GCash (2.3%), QR Ph (1.0% / ₱20 min), BSP OPS licence, Palawan/Siargao/Boracay tourist contexts."
        )
    else:
        mkt_ctx = (
            "Market: Southeast Asia broadly. "
            "Pick the most specific, credible context from SG, MY, or PH."
        )

    if brand == "smegrowthhub":
        fallback = _SME_FALLBACK_URL
        link_rule = (
            f"Set link_url to {bc.blog_base_url}/{{slug}} using a slug that matches the topic.\n"
            f"If no clear match, use: {bc.blog_base_url}"
        )
        link_example = bc.blog_base_url
    else:
        fallback = _FALLBACK_URL
        link_rule = (
            "Set link_url to https://hitpayapp.com/blog/{slug} using the most topically relevant slug from the list below.\n"
            "If no clear match, use: hitpay-rates"
        )
        link_example = "https://hitpayapp.com/blog/hitpay-rates"

    return f"""Write a HitPay LinkedIn post.

{topic_ctx}

{mkt_ctx}

FORMAT:
- Single post, 900–1,400 characters
- Hook (1-2 lines, insight-first) → Specific scenario or evidence (2-3 lines) → Practical implication (2-3 lines) → Quiet CTA with blog link
- End with 2–3 relevant hashtags

LINK RULE:
{link_rule}

LIVE BLOG SLUGS (use one of these — do not invent slugs):
{urls_list}

Return raw JSON only — no markdown fences:
{{"topic": "...", "content": "...", "link_url": "{link_example}"}}"""


def _build_sme_linkedin_prompt(market: str | None, topic_hint: str | None) -> str:
    from src.brand_config import get_brand_config
    bc = get_brand_config("smegrowthhub")

    if topic_hint:
        topic_ctx = f"Topic: {topic_hint}"
    else:
        sme_topics = [
            "The real cost of waiting 60 days on an invoice",
            "Why more SEA small businesses are moving off marketplaces",
            "What most small business owners get wrong about cash flow",
            "Hiring your first employee in Singapore: what people don't tell you",
            "When to register for GST (and when it hurts to wait)",
        ]
        topic_ctx = f"Topic: {random.choice(sme_topics)}"

    if market == "MY":
        mkt_ctx = "Market: Malaysia. Reference: EPF, SST, real Malaysian cities (Bangsar, PJ, Penang, JB)."
    elif market == "SG":
        mkt_ctx = "Market: Singapore. Reference: CPF, GST, real SG neighbourhoods (Tanjong Pagar, Tiong Bahru, Jurong)."
    elif market == "PH":
        mkt_ctx = "Market: Philippines. Reference: BIR, DTI, real PH cities (BGC, Makati, Cebu, Davao)."
    else:
        mkt_ctx = "Market: Southeast Asia. Pick the most specific and credible context from SG, MY, or PH."

    return f"""Write an SME Growth Hub LinkedIn post.

{topic_ctx}

{mkt_ctx}

FORMAT:
- Single post, 900–1,400 characters
- Hook (insight that reframes the problem) → Specific scenario → Practical implication → Quiet CTA
- End with 2–3 relevant hashtags
- Do not mention HitPay unless the topic is specifically about payment methods

LINK RULE:
Set link_url to {bc.blog_base_url} (no specific slug needed).

Return raw JSON only — no markdown fences:
{{"topic": "...", "content": "...", "link_url": "{bc.blog_base_url}"}}"""


def _cap_post(text: str, limit: int = 1500) -> str:
    if len(text) <= limit:
        return text
    cutoff = text.rfind(" ", 0, limit - 1)
    if cutoff <= 0:
        cutoff = limit - 1
    return text[:cutoff] + "…"


def generate_linkedin_post(
    market: str = None,
    topic_hint: str = None,
    brand: str = "hitpay",
) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if brand == "smegrowthhub":
        system = SME_LINKEDIN_SYSTEM_PROMPT
        prompt = _build_sme_linkedin_prompt(market, topic_hint)
        fallback = _SME_FALLBACK_URL
        url_pattern = None
    else:
        system = LINKEDIN_SYSTEM_PROMPT
        prompt = _build_linkedin_prompt(market, topic_hint, brand)
        fallback = _FALLBACK_URL
        url_pattern = r"^https://hitpayapp\.com/blog/[a-zA-Z0-9_\-()/]+$"

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=1200,
        system=system + "\n\n" + _WRITING_STYLE_RULES,
        messages=[{"role": "user", "content": prompt}],
        metadata={"user_id": "linkedin-generation"}
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)

    content = data.get("content", "")
    if not content:
        raise ValueError(f"Expected content string, got: {content!r}")

    data["content"] = _cap_post(content)

    link_url = data.get("link_url") or fallback
    if url_pattern:
        if not re.match(url_pattern, link_url):
            link_url = fallback
        else:
            from src.thought_leadership import _is_valid_blog_url
            if not _is_valid_blog_url(link_url):
                link_url = fallback
    data["link_url"] = link_url

    return data


def generate_linkedin_from_changelog(changelog_text: str, brand: str = "hitpay") -> dict:
    """Generate a LinkedIn post summarising a product changelog entry."""
    from src.brand_config import get_brand_config
    bc = get_brand_config(brand)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    slugs = _fetch_live_blog_slugs()
    urls_list = "\n".join(f"  {s}" for s in (slugs or []))
    fallback = _FALLBACK_URL if brand == "hitpay" else _SME_FALLBACK_URL

    prompt = f"""Write a LinkedIn post about this product update.

CHANGELOG:
{changelog_text}

FORMAT:
- Single post, 700–1,200 characters
- Open with what changed and why it matters to business owners
- Be specific: mention the feature name and the pain it solves
- End with a quiet CTA pointing to a relevant blog post
- 2–3 hashtags at the end

LINK RULE:
Set link_url to {bc.blog_base_url}/{{slug}} using the most relevant slug.
If no clear match, use: {fallback}

LIVE BLOG SLUGS:
{urls_list}

Return raw JSON only:
{{"topic": "...", "content": "...", "link_url": "..."}}"""

    system = LINKEDIN_SYSTEM_PROMPT if brand == "hitpay" else SME_LINKEDIN_SYSTEM_PROMPT

    response = _messages_create_with_retry(
        client,
        model=CLAUDE_MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        metadata={"user_id": "linkedin-changelog"}
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    data["content"] = _cap_post(data.get("content", ""))
    data.setdefault("link_url", fallback)
    return data
