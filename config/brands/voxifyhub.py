"""VoxifyHub brand configuration."""
import os
from config.brand import BRAND_SYSTEM_PROMPT
from config.brand import POSTING_SCHEDULE
from strategy.plan_90days import ESTRATEGIA_90_DIAS, MONTHLY_TARGETS

BRAND_CONFIG = {
    "id": "voxifyhub",
    "name": "VoxifyHub",
    "tagline": "Answer smarter. Grow faster.",
    "color": "#635BFF",       # primary UI accent for this brand
    "text_color": "#FFFFFF",

    # ── Social media credentials ──────────────────────────────────────────
    # Brand-specific vars take priority; fall back to legacy generic vars.
    "credentials": {
        "meta_access_token":               os.getenv("VOXIFYHUB_META_ACCESS_TOKEN",    os.getenv("META_ACCESS_TOKEN", "")),
        "instagram_business_account_id":   os.getenv("VOXIFYHUB_IG_ID",               os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")),
        "facebook_page_id":                os.getenv("VOXIFYHUB_FB_PAGE_ID",          os.getenv("FACEBOOK_PAGE_ID", "")),
        "facebook_page_access_token":      os.getenv("VOXIFYHUB_FB_PAGE_TOKEN",       os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")),
        "linkedin_access_token":           os.getenv("VOXIFYHUB_LINKEDIN_TOKEN",      os.getenv("LINKEDIN_ACCESS_TOKEN", "")),
        "linkedin_organization_id":        os.getenv("VOXIFYHUB_LINKEDIN_ORG_ID",     os.getenv("LINKEDIN_ORGANIZATION_ID", "")),
    },

    # ── Posting schedule (ET) ─────────────────────────────────────────────
    "posting_schedule": POSTING_SCHEDULE,

    # ── Agent prompts ─────────────────────────────────────────────────────
    "system_prompt": BRAND_SYSTEM_PROMPT,
    "strategy_90days": ESTRATEGIA_90_DIAS,
    "monthly_targets": MONTHLY_TARGETS,
}
