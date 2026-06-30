from dataclasses import dataclass

from config import (
    TYPEFULLY_SOCIAL_SET_ID,
    TYPEFULLY_THREADS_SOCIAL_SET_ID,
    TYPEFULLY_SME_SOCIAL_SET_ID,
    TYPEFULLY_SME_THREADS_SOCIAL_SET_ID,
    TYPEFULLY_LINKEDIN_SOCIAL_SET_ID,
    TYPEFULLY_SME_LINKEDIN_SOCIAL_SET_ID,
    SME_BLOG_BASE_URL,
)


@dataclass
class BrandConfig:
    key: str
    name: str
    docs_file: str
    blog_links_file: str
    blog_base_url: str
    sitemap_url: str | None
    typefully_social_set_id: str | None
    typefully_threads_social_set_id: str | None
    typefully_linkedin_social_set_id: str | None = None


HITPAY = BrandConfig(
    key="hitpay",
    name="HitPay",
    docs_file="hitpay_docs.md",
    blog_links_file="blog_links.yaml",
    blog_base_url="https://hitpayapp.com/blog",
    sitemap_url="https://hitpayapp.com/sitemap_en.xml",
    typefully_social_set_id=TYPEFULLY_SOCIAL_SET_ID or None,
    typefully_threads_social_set_id=TYPEFULLY_THREADS_SOCIAL_SET_ID or None,
    typefully_linkedin_social_set_id=TYPEFULLY_LINKEDIN_SOCIAL_SET_ID or None,
)

SME_GROWTH_HUB = BrandConfig(
    key="smegrowthhub",
    name="SME Growth Hub",
    docs_file="sme_growth_hub_docs.md",
    blog_links_file="sme_blog_links.yaml",
    blog_base_url=SME_BLOG_BASE_URL,
    sitemap_url=None,
    typefully_social_set_id=TYPEFULLY_SME_SOCIAL_SET_ID or None,
    typefully_threads_social_set_id=TYPEFULLY_SME_THREADS_SOCIAL_SET_ID or None,
    typefully_linkedin_social_set_id=TYPEFULLY_SME_LINKEDIN_SOCIAL_SET_ID or None,
)

_REGISTRY: dict[str, BrandConfig] = {
    "hitpay": HITPAY,
    "smegrowthhub": SME_GROWTH_HUB,
}


def get_brand_config(brand: str) -> BrandConfig:
    if brand not in _REGISTRY:
        raise ValueError(f"Unknown brand: {brand!r}. Must be one of: {list(_REGISTRY.keys())}")
    return _REGISTRY[brand]
