"""
Platform video configuration — single source of truth for format decisions.

The content strategy (agent.py) chooses which platform and content_type to use.
This module translates that choice into exact production parameters.

Usage:
    from platform_config import video_config_for
    cfg = video_config_for("tiktok")   # → {"duration": 28, "clips": 3, ...}
    cfg = video_config_for("reel")     # → {"duration": 15, "clips": 3, ...}
    cfg = video_config_for("story")    # → {"duration": 6,  "clips": 1, ...}
"""

from __future__ import annotations

# ── Platform identifiers ──────────────────────────────────────────────────────

PLATFORM_INSTAGRAM = "instagram"
PLATFORM_TIKTOK    = "tiktok"
PLATFORM_FACEBOOK  = "facebook"

CONTENT_REEL    = "reel"
CONTENT_TIKTOK  = "tiktok"
CONTENT_STORY   = "story"
CONTENT_POST    = "post"
CONTENT_CAROUSEL = "carousel"

# ── Video production config per content type ──────────────────────────────────
#
# duration_target  → total video length in seconds
# clips            → number of unique Kling clips to generate and stitch
# clip_duration    → length of each Kling clip ("5" or "10")
# aspect_ratio     → fal.ai / Kling aspect ratio string
# max_words        → max narration words (~2.2 words/sec Spanish speech rate)
# optimal_for      → optimal use case description (informational)
#
# Optimal durations based on 2025-2026 platform algorithm data:
#   Story  → 6 sec  (full retention before user taps)
#   Reel   → 15 sec (hook + value, loop incentive)
#   TikTok → 28 sec (FYP sweet spot, penalizes <6s and >60s)

_VIDEO_CONFIGS: dict[str, dict] = {
    CONTENT_STORY: {
        "duration_target": 6,
        "clips":           1,
        "clip_duration":   "5",
        "aspect_ratio":    "9:16",
        "max_words":       13,
        "optimal_for":     "Instagram/Facebook Stories — máxima retención completa",
    },
    CONTENT_REEL: {
        "duration_target": 15,
        "clips":           3,
        "clip_duration":   "5",
        "aspect_ratio":    "9:16",
        "max_words":       33,
        "optimal_for":     "Instagram/Facebook Reels — sweet spot engagement + loop",
    },
    CONTENT_TIKTOK: {
        "duration_target": 28,
        "clips":           3,
        "clip_duration":   "10",
        "aspect_ratio":    "9:16",
        "max_words":       62,
        "optimal_for":     "TikTok FYP — duración favorecida por el algoritmo",
    },
    CONTENT_POST: {
        "duration_target": 0,
        "clips":           0,
        "clip_duration":   "0",
        "aspect_ratio":    "1:1",
        "max_words":       0,
        "optimal_for":     "Imagen estática para feed",
    },
    CONTENT_CAROUSEL: {
        "duration_target": 0,
        "clips":           0,
        "clip_duration":   "0",
        "aspect_ratio":    "1:1",
        "max_words":       0,
        "optimal_for":     "Carrusel de imágenes para feed",
    },
}

# Map platform + content_type → canonical content_type key
_PLATFORM_CONTENT_MAP: dict[tuple[str, str], str] = {
    (PLATFORM_INSTAGRAM, "reel"):    CONTENT_REEL,
    (PLATFORM_INSTAGRAM, "story"):   CONTENT_STORY,
    (PLATFORM_INSTAGRAM, "post"):    CONTENT_POST,
    (PLATFORM_INSTAGRAM, "carousel"): CONTENT_CAROUSEL,
    (PLATFORM_TIKTOK,   "tiktok"):  CONTENT_TIKTOK,
    (PLATFORM_TIKTOK,   "video"):   CONTENT_TIKTOK,
    (PLATFORM_TIKTOK,   "reel"):    CONTENT_TIKTOK,
    (PLATFORM_FACEBOOK, "reel"):    CONTENT_REEL,
    (PLATFORM_FACEBOOK, "story"):   CONTENT_STORY,
    (PLATFORM_FACEBOOK, "post"):    CONTENT_POST,
}


def video_config_for(content_type: str, platform: str = "") -> dict:
    """
    Return production config for a given content_type (+ optional platform).

    Examples:
        video_config_for("tiktok")               → TikTok 28s config
        video_config_for("reel")                 → Reel 15s config
        video_config_for("reel", "tiktok")       → TikTok 28s config (platform wins)
        video_config_for("story", "instagram")   → Story 6s config
    """
    # If platform is TikTok, always return TikTok config regardless of content_type
    if platform == PLATFORM_TIKTOK:
        return dict(_VIDEO_CONFIGS[CONTENT_TIKTOK])

    # Look up by platform + content_type
    key = _PLATFORM_CONTENT_MAP.get((platform, content_type))
    if key:
        return dict(_VIDEO_CONFIGS[key])

    # Fall back to content_type alone
    cfg = _VIDEO_CONFIGS.get(content_type)
    if cfg:
        return dict(cfg)

    # Unknown → default to Reel
    return dict(_VIDEO_CONFIGS[CONTENT_REEL])


def is_video_content(content_type: str) -> bool:
    """True if this content type requires video generation."""
    cfg = _VIDEO_CONFIGS.get(content_type, {})
    return cfg.get("clips", 0) > 0


def all_platforms() -> list[str]:
    return [PLATFORM_INSTAGRAM, PLATFORM_TIKTOK, PLATFORM_FACEBOOK]


def platform_display_name(platform: str) -> str:
    return {
        PLATFORM_INSTAGRAM: "Instagram",
        PLATFORM_TIKTOK:    "TikTok",
        PLATFORM_FACEBOOK:  "Facebook",
    }.get(platform, platform.title())
