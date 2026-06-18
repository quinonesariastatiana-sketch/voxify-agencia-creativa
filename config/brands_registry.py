"""
Brand registry — loads brand configs from SQLite (source of truth).
Python config files under config/brands/ are used only for initial seeding.

To add a brand: use the /brands panel UI, or save_brand() + reload_from_db().
"""
from config.brands.voxifyhub import BRAND_CONFIG as _voxifyhub

# ── Python-file seed configs (used only when DB is empty) ─────────────────
_SEED_CONFIGS = [_voxifyhub]
# To add a new brand seed: from config.brands.my_brand import BRAND_CONFIG as _mb; _SEED_CONFIGS.append(_mb)

# ── In-memory registry (populated at startup from DB) ─────────────────────
BRANDS: dict[str, dict] = {b["id"]: b for b in _SEED_CONFIGS}
DEFAULT_BRAND_ID: str = _SEED_CONFIGS[0]["id"]


def get_brand(brand_id: str) -> dict:
    if brand_id not in BRANDS:
        raise ValueError(f"Marca '{brand_id}' no encontrada. Disponibles: {list(BRANDS.keys())}")
    return BRANDS[brand_id]


def list_brands() -> list[dict]:
    return [
        {"id": b["id"], "name": b["name"], "tagline": b.get("tagline", ""),
         "color": b.get("color", "#635BFF")}
        for b in BRANDS.values()
    ]


def reload_from_db(db) -> None:
    """
    Reload BRANDS dict from the brands DB table.
    Called at startup (after seeding) and after every brand save/delete.
    Thread-safe in CPython: dict.clear() + dict.update() under GIL.
    """
    global DEFAULT_BRAND_ID
    configs = db.list_brand_configs()
    if not configs:
        configs = _SEED_CONFIGS
    new_brands = {b["id"]: b for b in configs}
    BRANDS.clear()
    BRANDS.update(new_brands)
    if BRANDS:
        DEFAULT_BRAND_ID = next(iter(BRANDS))


def seed_defaults_if_empty(db) -> None:
    """Seed DB with Python-config brands if the brands table is empty."""
    if not db.has_brands_in_db():
        for cfg in _SEED_CONFIGS:
            # Ensure all required agent keys are present
            _normalize_config(cfg)
            db.save_brand(cfg)


def _normalize_config(cfg: dict) -> None:
    """Add default keys expected by the agent if missing from a brand config."""
    cfg.setdefault("industry", "")
    cfg.setdefault("geography", "")
    cfg.setdefault("description", "")
    cfg.setdefault("mission", "")
    cfg.setdefault("values", [])
    cfg.setdefault("hashtags", [])
    cfg.setdefault("audience", {"personas": [], "language": "es", "channels": [], "geography": ""})
    cfg.setdefault("voice", {"adjectives": [], "avoid": "", "examples_good": "", "examples_bad": "", "formality": 0.4, "emoji_use": "moderado"})
    cfg.setdefault("positioning", {"usp": "", "competitors": [], "differentiators": []})
    cfg.setdefault("content_lines", [])
    cfg.setdefault("goals", {
        "30": {"instagram_followers": 0, "instagram_engagement_rate": 0, "facebook_reach": 0, "leads": 0, "clients": 0, "revenue_usd": 0},
        "60": {"instagram_followers": 0, "instagram_engagement_rate": 0, "facebook_reach": 0, "leads": 0, "clients": 0, "revenue_usd": 0},
        "90": {"instagram_followers": 0, "instagram_engagement_rate": 0, "facebook_reach": 0, "leads": 0, "clients": 0, "revenue_usd": 0},
    })
