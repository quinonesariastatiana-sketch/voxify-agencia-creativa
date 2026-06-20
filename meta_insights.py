"""
Meta Graph API — fetch real account metrics to ground KPI research.
Returns zero-safe dicts; never raises.
"""
import requests
import logging

GRAPH = "https://graph.facebook.com/v19.0"
logger = logging.getLogger(__name__)


def _get(endpoint: str, token: str, **params) -> dict:
    try:
        r = requests.get(
            f"{GRAPH}/{endpoint}",
            params={"access_token": token, **params},
            timeout=10,
        )
        if r.ok:
            return r.json()
        logger.warning(f"[meta] {endpoint}: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.warning(f"[meta] {endpoint}: {e}")
    return {}


def ig_baseline(token: str, account_id: str) -> dict:
    if not token or not account_id:
        return {}

    profile = _get(account_id, token,
                   fields="followers_count,media_count,name,biography")
    followers   = profile.get("followers_count", 0)
    media_count = profile.get("media_count", 0)

    media = _get(f"{account_id}/media", token,
                 fields="like_count,comments_count,media_type",
                 limit=12)
    posts = media.get("data", [])

    eng_rate = 0.0
    if posts and followers > 0:
        avg = sum(p.get("like_count", 0) + p.get("comments_count", 0)
                  for p in posts) / len(posts)
        eng_rate = round(avg / followers * 100, 2)

    content_mix = {}
    for p in posts:
        t = p.get("media_type", "IMAGE")
        content_mix[t] = content_mix.get(t, 0) + 1

    return {
        "followers":         followers,
        "media_count":       media_count,
        "engagement_rate_pct": eng_rate,
        "posts_analyzed":    len(posts),
        "content_mix":       content_mix,
    }


def fb_baseline(token: str, page_id: str) -> dict:
    if not token or not page_id:
        return {}
    info = _get(page_id, token, fields="fan_count,followers_count,name")
    return {
        "fans":      info.get("fan_count", 0),
        "followers": info.get("followers_count", 0),
    }


def brand_baseline(brand: dict) -> dict:
    """Returns real metrics: {instagram: {...}, facebook: {...}}"""
    token = brand.get("meta_access_token", "")
    ig_id = brand.get("instagram_account_id", "")
    fb_id = brand.get("facebook_page_id", "")
    out = {}
    if token and ig_id:
        out["instagram"] = ig_baseline(token, ig_id)
    if token and fb_id:
        out["facebook"] = fb_baseline(token, fb_id)
    return out
