"""Load and query the competitor research database."""

import json
from pathlib import Path

COMPETITORS_DIR = Path(__file__).parent.parent / "competitors"


def get_competitor(key: str) -> dict | None:
    """Load a single competitor profile."""
    path = COMPETITORS_DIR / f"{key}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_all_competitors() -> dict:
    """Load all competitor profiles keyed by ID."""
    result = {}
    for path in COMPETITORS_DIR.glob("*.json"):
        if path.stem == "_index":
            continue
        with open(path, "r", encoding="utf-8") as f:
            result[path.stem] = json.load(f)
    return result


def get_index() -> dict:
    """Load the summary index."""
    index_path = COMPETITORS_DIR / "_index.json"
    if not index_path.exists():
        return {}
    with open(index_path, "r") as f:
        return json.load(f)



# Clean known market names — scraper can pull in junk like "135+ currencies"
KNOWN_MARKETS = {
    "singapore", "malaysia", "philippines", "indonesia", "thailand",
    "vietnam", "hong kong", "australia", "global", "southeast asia",
    "united states", "uk", "europe", "japan", "india", "china",
}

def _clean_markets(raw_markets: list) -> list[str]:
    """Filter markets_served to only real geographic entries."""
    result = []
    for m in raw_markets:
        m_lower = m.lower().strip()
        if any(km in m_lower for km in KNOWN_MARKETS):
            result.append(m_lower)
    return result


def get_relevant_competitors(keyword: str, market: str = None) -> list[dict]:
    """Return competitor profiles most relevant to a given keyword and market."""
    all_comps = get_all_competitors()
    if not all_comps:
        return []

    keyword_lower = keyword.lower()
    keyword_words = [w for w in keyword_lower.split() if len(w) >= 4]

    # Detect market signals from the keyword itself
    market_signals = {
        "singapore": ["singapore", "paynow", "grabpay", "shopeepay", "nets"],
        "malaysia": ["malaysia", "duitnow", "fpx", "touchngo", "touch n go", "boost"],
        "philippines": ["philippines", "gcash", "qr ph", "qrph", "instapay",
                        "pesonet", "paymongo", "xendit", "maya", "bsp"],
        "southeast asia": ["southeast asia", "sea", "asean"],
        "global": ["global", "international", "worldwide"],
    }

    detected_markets = set()
    for mkt, signals in market_signals.items():
        if any(sig in keyword_lower for sig in signals):
            detected_markets.add(mkt)
    if market:
        detected_markets.add(market.lower())

    scored = []
    for key, profile in all_comps.items():
        score = 0
        raw_markets = profile.get("markets_served", [])
        clean_markets = _clean_markets(raw_markets)

        # Is this a market specialist (few markets) or global player?
        is_specialist = len(clean_markets) <= 3 and "global" not in clean_markets

        # Market match scoring
        for dm in detected_markets:
            if any(dm in m for m in clean_markets):
                # Specialists get bigger boost when their market is queried
                score += 6 if is_specialist else 3

        # Global/SEA is broadly relevant (small bonus)
        if any(m in ["global", "southeast asia"] for m in clean_markets):
            score += 1

        # Keyword word match across content fields (excluding polluted markets)
        all_text = " ".join([
            " ".join(profile.get("features", [])),
            " ".join(profile.get("unique_selling_points", [])),
            profile.get("positioning") or "",
            " ".join(profile.get("target_segment", [])),
        ]).lower()

        for word in keyword_words:
            if word in all_text:
                score += 1

        # If no market signal detected, include everyone with at least baseline score
        if not detected_markets:
            score += 2

        if score > 0:
            scored.append((score, profile))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:5]]  # Return top 5 most relevant


def format_for_prompt(competitors: list[dict]) -> str:
    """Format competitor data for injection into the blog generation prompt."""
    if not competitors:
        return ""

    lines = ["## Competitor Research Data\n"]
    lines.append("Use this data to write accurate comparison content. Do not fabricate competitor facts.\n")

    for comp in competitors:
        lines.append(f"### {comp['name']} ({comp.get('base_url', '')})")
        lines.append(f"*Last updated: {comp.get('last_updated', 'unknown')}*\n")

        if comp.get("positioning"):
            lines.append(f"**Positioning:** {comp['positioning']}")

        if comp.get("target_segment"):
            lines.append(f"**Target segment:** {', '.join(comp['target_segment'])}")

        if comp.get("markets_served"):
            lines.append(f"**Markets:** {', '.join(comp['markets_served'])}")

        pricing = comp.get("pricing", {})
        if pricing:
            lines.append("**Pricing:**")
            if pricing.get("monthly_fee"):
                lines.append(f"  - Monthly fee: {pricing['monthly_fee']}")
            if pricing.get("setup_fee"):
                lines.append(f"  - Setup fee: {pricing['setup_fee']}")
            if pricing.get("pricing_model"):
                lines.append(f"  - Model: {pricing['pricing_model']}")
            tf = pricing.get("transaction_fees", {})
            if tf:
                if tf.get("cards"):
                    lines.append(f"  - Card fee: {tf['cards']}")
                if tf.get("notes"):
                    lines.append(f"  - Note: {tf['notes']}")

        pm = comp.get("payment_methods", {})
        if pm:
            lines.append("**Payment methods:**")
            for market, methods in pm.items():
                if methods:
                    lines.append(f"  - {market.title()}: {', '.join(methods)}")

        if comp.get("features"):
            lines.append(f"**Key features:** {', '.join(comp['features'][:10])}")

        if comp.get("unique_selling_points"):
            lines.append(f"**Differentiators:** {', '.join(comp['unique_selling_points'][:5])}")

        if comp.get("payout_speed"):
            lines.append(f"**Payout speed:** {comp['payout_speed']}")

        lines.append("")

    return "\n".join(lines)
