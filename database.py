"""
SQLite wrapper — Voxify Agencia Creativa.
JSON list/object fields auto-serialized.
safe_patch_brand() never wipes existing data with empty values.
"""
import sqlite3
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "voxify.db"))

_LIST_FIELDS = frozenset({"competitors", "differentiators", "hashtags",
                           "kpi_30_days", "kpi_60_days", "kpi_90_days", "brand_values"})
_OBJ_FIELDS  = frozenset({"strategy_phases", "voice"})


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_REQUIRED_BRAND_COLS = frozenset({
    'id', 'name', 'tagline', 'description', 'industry', 'geography',
    'website_url', 'logo_url', 'instagram_handle', 'color',
    'meta_access_token', 'instagram_account_id', 'facebook_page_id',
    'competitors', 'differentiators', 'audience_profile', 'brand_tone',
    'unique_value_proposition', 'hashtags', 'kpi_30_days', 'kpi_60_days',
    'kpi_90_days', 'strategy_phases', 'mission', 'brand_values', 'voice',
    'positioning', 'last_research', 'active', 'created_at', 'updated_at',
})

_BRANDS_DDL = """
CREATE TABLE brands (
    id                       TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    tagline                  TEXT DEFAULT '',
    description              TEXT DEFAULT '',
    industry                 TEXT DEFAULT '',
    geography                TEXT DEFAULT 'United States',
    website_url              TEXT DEFAULT '',
    logo_url                 TEXT DEFAULT '',
    instagram_handle         TEXT DEFAULT '',
    color                    TEXT DEFAULT '#635BFF',
    meta_access_token        TEXT DEFAULT '',
    instagram_account_id     TEXT DEFAULT '',
    facebook_page_id         TEXT DEFAULT '',
    competitors              TEXT DEFAULT '[]',
    differentiators          TEXT DEFAULT '[]',
    audience_profile         TEXT DEFAULT '',
    brand_tone               TEXT DEFAULT '',
    unique_value_proposition TEXT DEFAULT '',
    hashtags                 TEXT DEFAULT '[]',
    kpi_30_days              TEXT DEFAULT '[]',
    kpi_60_days              TEXT DEFAULT '[]',
    kpi_90_days              TEXT DEFAULT '[]',
    strategy_phases          TEXT DEFAULT '{}',
    mission                  TEXT DEFAULT '',
    brand_values             TEXT DEFAULT '[]',
    voice                    TEXT DEFAULT '{}',
    positioning              TEXT DEFAULT '',
    last_research            TEXT,
    active                   INTEGER DEFAULT 1,
    created_at               TEXT DEFAULT (datetime('now')),
    updated_at               TEXT DEFAULT (datetime('now'))
);
"""


_REQUIRED_POST_COLS = frozenset({
    'id', 'brand_id', 'caption', 'image_url', 'video_url', 'platform',
    'status', 'scheduled_for', 'posted_at', 'post_id_meta', 'error_msg',
    'created_at', 'content_type', 'suggested_day', 'suggested_time', 'extra_json',
})

_POSTS_DDL = """
CREATE TABLE scheduled_posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id       TEXT NOT NULL,
    caption        TEXT NOT NULL,
    image_url      TEXT DEFAULT '',
    video_url      TEXT DEFAULT '',
    platform       TEXT DEFAULT 'instagram',
    status         TEXT DEFAULT 'pending',
    scheduled_for  TEXT,
    posted_at      TEXT,
    post_id_meta   TEXT DEFAULT '',
    error_msg      TEXT DEFAULT '',
    content_type   TEXT DEFAULT 'post',
    suggested_day  TEXT DEFAULT '',
    suggested_time TEXT DEFAULT '',
    extra_json     TEXT DEFAULT '{}',
    created_at     TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (brand_id) REFERENCES brands(id)
);
"""


def _check_and_fix_schema():
    """Drop and recreate tables that are missing required columns."""
    with _conn() as c:
        brand_cols = {r[1] for r in c.execute("PRAGMA table_info(brands)").fetchall()}
        if brand_cols and not _REQUIRED_BRAND_COLS.issubset(brand_cols):
            c.executescript(f"DROP TABLE IF EXISTS brands; {_BRANDS_DDL}")

        post_cols = {r[1] for r in c.execute("PRAGMA table_info(scheduled_posts)").fetchall()}
        if post_cols and not _REQUIRED_POST_COLS.issubset(post_cols):
            c.executescript(f"DROP TABLE IF EXISTS scheduled_posts; {_POSTS_DDL}")


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS brands (
            id                       TEXT PRIMARY KEY,
            name                     TEXT NOT NULL,
            tagline                  TEXT DEFAULT '',
            description              TEXT DEFAULT '',
            industry                 TEXT DEFAULT '',
            geography                TEXT DEFAULT 'United States',
            website_url              TEXT DEFAULT '',
            logo_url                 TEXT DEFAULT '',
            instagram_handle         TEXT DEFAULT '',
            color                    TEXT DEFAULT '#635BFF',
            meta_access_token        TEXT DEFAULT '',
            instagram_account_id     TEXT DEFAULT '',
            facebook_page_id         TEXT DEFAULT '',
            competitors              TEXT DEFAULT '[]',
            differentiators          TEXT DEFAULT '[]',
            audience_profile         TEXT DEFAULT '',
            brand_tone               TEXT DEFAULT '',
            unique_value_proposition TEXT DEFAULT '',
            hashtags                 TEXT DEFAULT '[]',
            kpi_30_days              TEXT DEFAULT '[]',
            kpi_60_days              TEXT DEFAULT '[]',
            kpi_90_days              TEXT DEFAULT '[]',
            strategy_phases          TEXT DEFAULT '{}',
            mission                  TEXT DEFAULT '',
            brand_values             TEXT DEFAULT '[]',
            voice                    TEXT DEFAULT '{}',
            positioning              TEXT DEFAULT '',
            last_research            TEXT,
            active                   INTEGER DEFAULT 1,
            created_at               TEXT DEFAULT (datetime('now')),
            updated_at               TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id      TEXT NOT NULL,
            caption       TEXT NOT NULL,
            image_url     TEXT DEFAULT '',
            video_url     TEXT DEFAULT '',
            platform      TEXT DEFAULT 'instagram',
            status        TEXT DEFAULT 'pending',
            scheduled_for TEXT,
            posted_at     TEXT,
            post_id_meta  TEXT DEFAULT '',
            error_msg     TEXT DEFAULT '',
            created_at    TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (brand_id) REFERENCES brands(id)
        );

        CREATE TABLE IF NOT EXISTS weekly_strategy (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id        TEXT NOT NULL,
            week_start      TEXT NOT NULL,
            strategy_json   TEXT DEFAULT '{}',
            posts_generated INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (brand_id) REFERENCES brands(id)
        );

        CREATE TABLE IF NOT EXISTS trends_cache (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id   TEXT DEFAULT '',
            topic      TEXT NOT NULL,
            data       TEXT DEFAULT '{}',
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS brand_schedule (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id     TEXT NOT NULL,
            platform     TEXT DEFAULT 'instagram',
            days_of_week TEXT DEFAULT '[1,3,5]',
            time_of_day  TEXT DEFAULT '10:00',
            active       INTEGER DEFAULT 1,
            updated_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(brand_id, platform),
            FOREIGN KEY (brand_id) REFERENCES brands(id)
        );
        """)
    _check_and_fix_schema()


def _load(row: dict) -> dict:
    for f in _LIST_FIELDS:
        if f in row:
            try:
                v = json.loads(row[f]) if row[f] else []
                row[f] = v if isinstance(v, list) else []
            except Exception:
                row[f] = []
    for f in _OBJ_FIELDS:
        if f in row:
            try:
                v = json.loads(row[f]) if row[f] else {}
                row[f] = v if isinstance(v, dict) else {}
            except Exception:
                row[f] = {}
    return row


def _dump(brand: dict) -> dict:
    b = dict(brand)
    for f in _LIST_FIELDS | _OBJ_FIELDS:
        if f in b and not isinstance(b[f], str):
            default = [] if f in _LIST_FIELDS else {}
            b[f] = json.dumps(b[f] if b[f] is not None else default)
    return b


# ── Brands ────────────────────────────────────────────────────────────────────

def get_all_brands() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM brands WHERE active=1 ORDER BY name").fetchall()
    return [_load(dict(r)) for r in rows]


def get_brand(brand_id: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
    return _load(dict(row)) if row else None


def save_brand(brand: dict):
    b = _dump(brand)
    b.setdefault('active', 1)
    b['updated_at'] = datetime.utcnow().isoformat()
    cols   = ', '.join(b.keys())
    phs    = ', '.join('?' for _ in b)
    upsert = ', '.join(f"{k}=excluded.{k}" for k in b if k != 'id')
    with _conn() as c:
        c.execute(
            f"INSERT INTO brands ({cols}) VALUES ({phs}) ON CONFLICT(id) DO UPDATE SET {upsert}",
            list(b.values())
        )


def create_brand(brand_id: str, name: str, **kw) -> dict:
    brand = {
        'id': brand_id, 'name': name,
        'tagline':               kw.get('tagline', ''),
        'description':           kw.get('description', ''),
        'industry':              kw.get('industry', ''),
        'geography':             kw.get('geography', 'United States'),
        'website_url':           kw.get('website_url', ''),
        'logo_url':              kw.get('logo_url', ''),
        'instagram_handle':      kw.get('instagram_handle', ''),
        'color':                 kw.get('color', '#635BFF'),
        'meta_access_token':     kw.get('meta_access_token', ''),
        'instagram_account_id':  kw.get('instagram_account_id', ''),
        'facebook_page_id':      kw.get('facebook_page_id', ''),
        'mission':               kw.get('mission', ''),
        'positioning':           kw.get('positioning', ''),
        'competitors': [], 'differentiators': [], 'hashtags': [],
        'kpi_30_days': [], 'kpi_60_days':     [], 'kpi_90_days': [],
        'strategy_phases': {}, 'brand_values': [], 'voice': {},
        'audience_profile': '', 'brand_tone': '', 'unique_value_proposition': '',
        'active': 1,
    }
    save_brand(brand)
    return get_brand(brand_id)


def safe_patch_brand(brand_id: str, updates: dict):
    brand = get_brand(brand_id)
    if not brand:
        return None
    changed = False
    for k, v in updates.items():
        if k == 'id':
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, dict)) and not v:
            continue
        brand[k] = v
        changed = True
    if changed:
        save_brand(brand)
    return get_brand(brand_id)


def delete_brand(brand_id: str):
    with _conn() as c:
        c.execute("UPDATE brands SET active=0 WHERE id=?", (brand_id,))


# ── Posts ─────────────────────────────────────────────────────────────────────

def create_post(brand_id: str, caption: str, image_url: str = '',
                platform: str = 'instagram', scheduled_for: str = None,
                content_type: str = 'post', suggested_day: str = '',
                suggested_time: str = '', extra_json: str = '{}') -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO scheduled_posts "
            "(brand_id, caption, image_url, platform, scheduled_for, "
            " content_type, suggested_day, suggested_time, extra_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (brand_id, caption, image_url, platform, scheduled_for,
             content_type, suggested_day, suggested_time, extra_json)
        )
    return cur.lastrowid


def get_posts(brand_id: str = None, status: str = None, limit: int = 200) -> list:
    q = ("SELECT sp.*, b.name AS brand_name, b.color AS brand_color "
         "FROM scheduled_posts sp LEFT JOIN brands b ON sp.brand_id=b.id WHERE 1=1")
    p = []
    if brand_id: q += " AND sp.brand_id=?"; p.append(brand_id)
    if status:   q += " AND sp.status=?";   p.append(status)
    q += f" ORDER BY sp.created_at DESC LIMIT {int(limit)}"
    with _conn() as c:
        rows = c.execute(q, p).fetchall()
    return [dict(r) for r in rows]


def get_post(post_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM scheduled_posts WHERE id=?", (post_id,)).fetchone()
    return dict(row) if row else None


def update_post(post_id: int, **kw):
    if not kw:
        return
    set_clause = ', '.join(f"{k}=?" for k in kw)
    with _conn() as c:
        c.execute(f"UPDATE scheduled_posts SET {set_clause} WHERE id=?",
                  list(kw.values()) + [post_id])


def get_approved_pending_posts() -> list:
    with _conn() as c:
        rows = c.execute("""
            SELECT sp.*, b.meta_access_token, b.instagram_account_id,
                   b.facebook_page_id, b.name AS brand_name
            FROM scheduled_posts sp
            JOIN brands b ON sp.brand_id=b.id
            WHERE sp.status='approved'
              AND (sp.scheduled_for IS NULL OR sp.scheduled_for <= datetime('now'))
        """).fetchall()
    return [dict(r) for r in rows]


# ── Schedule config ───────────────────────────────────────────────────────────

def get_schedule(brand_id: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM brand_schedule WHERE brand_id=? AND active=1",
            (brand_id,)
        ).fetchall()
    result = []
    for r in [dict(row) for row in rows]:
        try:
            r['days_of_week'] = json.loads(r.get('days_of_week', '[]'))
        except Exception:
            r['days_of_week'] = []
        result.append(r)
    return result


def save_schedule(brand_id: str, configs: list):
    with _conn() as c:
        for cfg in configs:
            platform = cfg.get('platform', 'instagram')
            c.execute("""
                INSERT INTO brand_schedule
                    (brand_id, platform, days_of_week, time_of_day, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(brand_id, platform) DO UPDATE SET
                    days_of_week = excluded.days_of_week,
                    time_of_day  = excluded.time_of_day,
                    updated_at   = excluded.updated_at
            """, (brand_id, platform,
                  json.dumps(cfg.get('days_of_week', [])),
                  cfg.get('time_of_day', '10:00')))
