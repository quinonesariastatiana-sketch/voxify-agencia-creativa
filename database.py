"""SQLite persistence layer for the content calendar and brand configs."""

import json
import sqlite3
from datetime import datetime
from config.settings import DB_PATH


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._init_schema()
        self._migrate()

    def _migrate(self):
        """Add missing columns to existing tables without losing data."""
        migrations = [
            ("scheduled_posts", "video_url",        "TEXT"),
            ("scheduled_posts", "reach",             "INTEGER"),
            ("scheduled_posts", "impressions",       "INTEGER"),
            ("scheduled_posts", "likes",             "INTEGER"),
            ("scheduled_posts", "comments",          "INTEGER"),
            ("scheduled_posts", "saves",             "INTEGER"),
            ("scheduled_posts", "shares",            "INTEGER"),
            ("scheduled_posts", "engagement_rate",   "REAL"),
            ("scheduled_posts", "voiceover_url",     "TEXT"),
            ("scheduled_posts", "music_url",         "TEXT"),
            ("scheduled_posts", "brand_id",          "TEXT DEFAULT 'voxifyhub'"),
            ("weekly_strategy", "brand_id",          "TEXT DEFAULT 'voxifyhub'"),
            ("engagement_comments", "brand_id",      "TEXT DEFAULT 'voxifyhub'"),
        ]
        for table, column, col_type in migrations:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except Exception:
                pass  # Column already exists
        self.conn.commit()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                platform         TEXT NOT NULL,
                content_type     TEXT NOT NULL,
                content          TEXT NOT NULL,
                image_url        TEXT,
                video_url        TEXT,
                scheduled_date   TEXT NOT NULL,
                status           TEXT DEFAULT 'pending_approval',
                external_post_id TEXT,
                error_message    TEXT,
                created_at       TEXT DEFAULT (datetime('now')),
                published_at     TEXT,
                reach            INTEGER,
                impressions      INTEGER,
                likes            INTEGER,
                comments         INTEGER,
                saves            INTEGER,
                shares           INTEGER,
                engagement_rate  REAL
            );

            CREATE TABLE IF NOT EXISTS agent_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT DEFAULT (datetime('now')),
                task        TEXT,
                result      TEXT
            );

            CREATE TABLE IF NOT EXISTS engagement_comments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                platform     TEXT DEFAULT 'instagram',
                comment_id   TEXT UNIQUE,
                username     TEXT,
                text         TEXT,
                media_id     TEXT,
                responded    INTEGER DEFAULT 0,
                responded_at TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS weekly_strategy (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                week_number  INTEGER,
                year         INTEGER,
                phase        INTEGER,
                theme        TEXT,
                analysis     TEXT,
                content_mix  TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trend_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT DEFAULT (datetime('now')),
                keywords    TEXT,
                data        TEXT
            );

            CREATE TABLE IF NOT EXISTS brands (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                color       TEXT DEFAULT '#635BFF',
                active      INTEGER DEFAULT 1,
                config_json TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS brand_media (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id    TEXT NOT NULL,
                filename    TEXT NOT NULL,
                url         TEXT NOT NULL,
                media_type  TEXT NOT NULL,
                title       TEXT DEFAULT '',
                description TEXT DEFAULT '',
                tags        TEXT DEFAULT '[]',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sales_leads (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id        TEXT NOT NULL,
                name            TEXT DEFAULT '',
                company         TEXT DEFAULT '',
                email           TEXT DEFAULT '',
                phone           TEXT DEFAULT '',
                linkedin_url    TEXT DEFAULT '',
                website         TEXT DEFAULT '',
                industry        TEXT DEFAULT '',
                company_size    TEXT DEFAULT '',
                job_title       TEXT DEFAULT '',
                score           INTEGER DEFAULT 0,
                stage           TEXT DEFAULT 'nuevo',
                language        TEXT DEFAULT 'es',
                hubspot_id      TEXT DEFAULT '',
                sentiment_score REAL DEFAULT 3.0,
                last_contact    TEXT,
                notes           TEXT DEFAULT '',
                source          TEXT DEFAULT 'manual',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sales_conversations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id         INTEGER NOT NULL,
                brand_id        TEXT NOT NULL,
                channel         TEXT DEFAULT 'email',
                direction       TEXT DEFAULT 'outbound',
                message         TEXT DEFAULT '',
                subject         TEXT DEFAULT '',
                sentiment_score REAL DEFAULT 3.0,
                sentiment_label TEXT DEFAULT 'neutral',
                escalated       INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sales_insights (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id    TEXT NOT NULL,
                type        TEXT DEFAULT 'general',
                content     TEXT DEFAULT '',
                data_json   TEXT DEFAULT '{}',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sales_reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id    TEXT NOT NULL,
                report_json TEXT DEFAULT '{}',
                sent_slack  INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS monthly_campaigns (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id         TEXT NOT NULL,
                month            INTEGER NOT NULL,
                year             INTEGER NOT NULL,
                product_name     TEXT DEFAULT '',
                product_desc     TEXT DEFAULT '',
                product_price    TEXT DEFAULT '',
                product_media_id INTEGER,
                promo_type       TEXT DEFAULT '',
                promo_details    TEXT DEFAULT '',
                discount_pct     TEXT DEFAULT '',
                campaign_goal    TEXT DEFAULT '',
                target_segment   TEXT DEFAULT '',
                campaign_dates   TEXT DEFAULT '',
                notes            TEXT DEFAULT '',
                suggestions_json TEXT DEFAULT '[]',
                created_at       TEXT DEFAULT (datetime('now')),
                updated_at       TEXT DEFAULT (datetime('now')),
                UNIQUE(brand_id, month, year) ON CONFLICT REPLACE
            );
        """)
        self.conn.commit()

    def save_scheduled_post(self, platform, content_type, content, scheduled_date,
                            image_url=None, video_url=None, status="pending_approval",
                            brand_id="voxifyhub"):
        self.conn.execute(
            """INSERT INTO scheduled_posts
               (platform, content_type, content, image_url, video_url, scheduled_date, status, brand_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (platform, content_type, content, image_url, video_url, scheduled_date, status, brand_id),
        )
        self.conn.commit()

    def get_posts_pending_approval(self, brand_id="voxifyhub"):
        return self.conn.execute(
            """SELECT id, platform, content_type, content, image_url, scheduled_date
               FROM scheduled_posts WHERE status = 'pending_approval' AND brand_id = ?
               ORDER BY platform, scheduled_date ASC""",
            (brand_id,)
        ).fetchall()

    def approve_post(self, post_id: int, image_url: str = None):
        if image_url:
            self.conn.execute(
                "UPDATE scheduled_posts SET status='pending', image_url=? WHERE id=?",
                (image_url, post_id),
            )
        else:
            self.conn.execute(
                "UPDATE scheduled_posts SET status='pending' WHERE id=?",
                (post_id,),
            )
        self.conn.commit()

    def mark_post_ready_manual(self, post_id: int):
        self.conn.execute(
            "UPDATE scheduled_posts SET status='ready_manual' WHERE id=?",
            (post_id,),
        )
        self.conn.commit()

    def reject_post(self, post_id: int):
        self.conn.execute(
            "UPDATE scheduled_posts SET status='rejected' WHERE id=?",
            (post_id,),
        )
        self.conn.commit()

    def get_next_pending_post(self, platform: str):
        now = datetime.utcnow().isoformat()
        return self.conn.execute(
            """SELECT id, content_type, content, image_url
               FROM scheduled_posts
               WHERE platform = ? AND status = 'pending' AND scheduled_date <= ?
               ORDER BY scheduled_date ASC LIMIT 1""",
            (platform, now),
        ).fetchone()

    def get_pending_post_now(self, platform: str):
        """Get the next approved post regardless of scheduled date (for immediate publish)."""
        return self.conn.execute(
            """SELECT id, content_type, content, image_url
               FROM scheduled_posts
               WHERE platform = ? AND status = 'pending'
               ORDER BY scheduled_date ASC LIMIT 1""",
            (platform,),
        ).fetchone()

    def mark_post_published(self, post_id: int, external_id: str):
        self.conn.execute(
            """UPDATE scheduled_posts
               SET status='published', external_post_id=?, published_at=datetime('now')
               WHERE id=?""",
            (external_id, post_id),
        )
        self.conn.commit()

    def mark_post_failed(self, post_id: int, error: str):
        self.conn.execute(
            "UPDATE scheduled_posts SET status='failed', error_message=? WHERE id=?",
            (error, post_id),
        )
        self.conn.commit()

    def mark_post_skipped(self, post_id: int):
        self.conn.execute(
            "UPDATE scheduled_posts SET status='skipped' WHERE id=?",
            (post_id,),
        )
        self.conn.commit()

    def list_posts(self, status=None, limit=20, brand_id="voxifyhub"):
        if status:
            return self.conn.execute(
                "SELECT * FROM scheduled_posts WHERE status=? AND brand_id=? ORDER BY scheduled_date DESC LIMIT ?",
                (status, brand_id, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM scheduled_posts WHERE brand_id=? ORDER BY scheduled_date DESC LIMIT ?",
            (brand_id, limit),
        ).fetchall()

    def log_session(self, task: str, result: str):
        self.conn.execute(
            "INSERT INTO agent_sessions (task, result) VALUES (?, ?)",
            (task, result),
        )
        self.conn.commit()

    def reschedule_posts(self, start_monday: str, brand_id: str = "voxifyhub") -> dict:
        """
        Redistribute all active (non-published, non-rejected) posts to slots
        starting from the given Monday. Posts are matched to slots by platform.
        Returns {"rescheduled": N, "slots_used": [...]}
        """
        from datetime import date, timedelta
        monday = date.fromisoformat(start_monday)

        # Define the 11 slots in weekly order
        slots = [
            ("instagram", f"{monday}T09:00:00"),
            ("facebook",  f"{monday}T10:00:00"),
            ("instagram", f"{monday + timedelta(1)}T09:00:00"),
            ("facebook",  f"{monday + timedelta(1)}T10:00:00"),
            ("linkedin",  f"{monday + timedelta(2)}T08:00:00"),
            ("instagram", f"{monday + timedelta(2)}T09:00:00"),
            ("facebook",  f"{monday + timedelta(2)}T10:00:00"),
            ("instagram", f"{monday + timedelta(3)}T09:00:00"),
            ("facebook",  f"{monday + timedelta(3)}T10:00:00"),
            ("instagram", f"{monday + timedelta(4)}T09:00:00"),
            ("facebook",  f"{monday + timedelta(4)}T10:00:00"),
        ]

        active_statuses = ("pending_approval", "pending", "ready_manual")
        rows = self.conn.execute(
            f"SELECT id, platform FROM scheduled_posts "
            f"WHERE status IN ({','.join('?'*len(active_statuses))}) AND brand_id=? "
            f"ORDER BY platform, scheduled_date ASC",
            (*active_statuses, brand_id),
        ).fetchall()

        # Group by platform
        by_platform: dict[str, list[int]] = {}
        for post_id, platform in rows:
            by_platform.setdefault(platform, []).append(post_id)

        # Assign slots — iterate slots in order, pick first available post for that platform
        used_slots = []
        assigned: dict[int, str] = {}
        for platform, slot_dt in slots:
            if by_platform.get(platform):
                post_id = by_platform[platform].pop(0)
                assigned[post_id] = slot_dt
                used_slots.append({"id": post_id, "platform": platform, "new_date": slot_dt})

        for post_id, new_date in assigned.items():
            self.conn.execute(
                "UPDATE scheduled_posts SET scheduled_date=? WHERE id=?",
                (new_date, post_id),
            )
        self.conn.commit()
        return {"rescheduled": len(assigned), "slots": used_slots}

    # ── Brand config CRUD ─────────────────────────────────────────────────────

    def save_brand(self, config: dict) -> None:
        """Upsert a full brand config dict."""
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT INTO brands (id, name, color, active, config_json, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, color=excluded.color,
                 config_json=excluded.config_json, updated_at=excluded.updated_at""",
            (config["id"], config["name"], config.get("color", "#635BFF"),
             json.dumps(config, ensure_ascii=False), now, now),
        )
        self.conn.commit()

    def get_brand_config(self, brand_id: str) -> dict | None:
        """Return full brand config dict or None if not found."""
        row = self.conn.execute(
            "SELECT config_json FROM brands WHERE id=?", (brand_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list_brand_configs(self) -> list[dict]:
        """Return all active brand configs as dicts."""
        rows = self.conn.execute(
            "SELECT config_json FROM brands WHERE active=1 ORDER BY name"
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete_brand(self, brand_id: str) -> None:
        self.conn.execute("DELETE FROM brands WHERE id=?", (brand_id,))
        self.conn.commit()

    def safe_patch_brand(self, brand_id: str, updates: dict) -> dict:
        """
        Update ONLY the specified keys in config_json.
        Never overwrites a key if the new value is empty/None.
        Existing data is preserved if the call that generated updates failed.
        """
        brand = self.get_brand_config(brand_id)
        if not brand:
            return {}
        changed = False
        for key, value in updates.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if isinstance(value, dict) and len(value) == 0:
                continue
            brand[key] = value
            changed = True
        if changed:
            self.save_brand(brand)
        return brand

    def has_brands_in_db(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM brands").fetchone()[0] > 0

    def get_brand_stats(self, brand_id: str) -> dict:
        """Quick stats for a brand: post counts by status + published this month."""
        stats = {}
        for status in ("pending_approval", "pending", "published", "failed"):
            stats[status] = self.conn.execute(
                "SELECT COUNT(*) FROM scheduled_posts WHERE brand_id=? AND status=?",
                (brand_id, status)
            ).fetchone()[0]
        stats["published_month"] = self.conn.execute(
            "SELECT COUNT(*) FROM scheduled_posts WHERE brand_id=? AND status='published' "
            "AND published_at >= date('now','start of month')",
            (brand_id,)
        ).fetchone()[0]
        stats["avg_engagement"] = self.conn.execute(
            "SELECT AVG(engagement_rate) FROM scheduled_posts "
            "WHERE brand_id=? AND engagement_rate IS NOT NULL AND engagement_rate > 0",
            (brand_id,)
        ).fetchone()[0] or 0
        stats["scheduled_next_7"] = self.conn.execute(
            "SELECT COUNT(*) FROM scheduled_posts WHERE brand_id=? "
            "AND status IN ('pending','pending_approval') "
            "AND scheduled_date BETWEEN date('now') AND date('now','+7 days')",
            (brand_id,)
        ).fetchone()[0]
        return stats

    # ── Media library ────────────────────────────────────────────────────────

    def save_media(self, brand_id: str, filename: str, url: str,
                   media_type: str, title: str = "", description: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO brand_media (brand_id, filename, url, media_type, title, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (brand_id, filename, url, media_type, title, description),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_media(self, brand_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, filename, url, media_type, title, description, tags, created_at "
            "FROM brand_media WHERE brand_id=? ORDER BY created_at DESC",
            (brand_id,)
        ).fetchall()
        keys = ["id", "filename", "url", "media_type", "title", "description", "tags", "created_at"]
        result = []
        for r in rows:
            d = dict(zip(keys, r))
            try:
                d["tags"] = json.loads(d["tags"] or "[]")
            except Exception:
                d["tags"] = []
            result.append(d)
        return result

    def update_media(self, media_id: int, title: str, description: str, tags: list) -> None:
        self.conn.execute(
            "UPDATE brand_media SET title=?, description=?, tags=? WHERE id=?",
            (title, description, json.dumps(tags, ensure_ascii=False), media_id),
        )
        self.conn.commit()

    def delete_media(self, media_id: int) -> str | None:
        row = self.conn.execute("SELECT url FROM brand_media WHERE id=?", (media_id,)).fetchone()
        if row:
            self.conn.execute("DELETE FROM brand_media WHERE id=?", (media_id,))
            self.conn.commit()
            return row[0]
        return None

    def get_media(self, media_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, filename, url, media_type, title, description, tags, created_at "
            "FROM brand_media WHERE id=?", (media_id,)
        ).fetchone()
        if not row:
            return None
        keys = ["id", "filename", "url", "media_type", "title", "description", "tags", "created_at"]
        d = dict(zip(keys, row))
        try:
            d["tags"] = json.loads(d["tags"] or "[]")
        except Exception:
            d["tags"] = []
        return d

    # ── Monthly campaigns ─────────────────────────────────────────────────────

    def save_campaign(self, brand_id: str, month: int, year: int, data: dict) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT INTO monthly_campaigns
               (brand_id, month, year, product_name, product_desc, product_price,
                product_media_id, promo_type, promo_details, discount_pct,
                campaign_goal, target_segment, campaign_dates, notes,
                suggestions_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (brand_id, month, year,
             data.get("product_name", ""), data.get("product_desc", ""),
             data.get("product_price", ""), data.get("product_media_id"),
             data.get("promo_type", ""), data.get("promo_details", ""),
             data.get("discount_pct", ""), data.get("campaign_goal", ""),
             data.get("target_segment", ""), data.get("campaign_dates", ""),
             data.get("notes", ""),
             json.dumps(data.get("suggestions", []), ensure_ascii=False),
             now, now),
        )
        self.conn.commit()

    def get_campaign(self, brand_id: str, month: int, year: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM monthly_campaigns WHERE brand_id=? AND month=? AND year=?",
            (brand_id, month, year)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.execute(
            "SELECT * FROM monthly_campaigns LIMIT 0").description]
        d = dict(zip(cols, row))
        try:
            d["suggestions"] = json.loads(d.get("suggestions_json") or "[]")
        except Exception:
            d["suggestions"] = []
        return d

    def get_current_campaign(self, brand_id: str) -> dict | None:
        now = datetime.utcnow()
        return self.get_campaign(brand_id, now.month, now.year)

    def save_campaign_suggestions(self, brand_id: str, month: int, year: int,
                                   suggestions: list) -> None:
        self.conn.execute(
            "UPDATE monthly_campaigns SET suggestions_json=?, updated_at=? "
            "WHERE brand_id=? AND month=? AND year=?",
            (json.dumps(suggestions, ensure_ascii=False),
             datetime.utcnow().isoformat(), brand_id, month, year),
        )
        self.conn.commit()

    # ── Sales CRM ─────────────────────────────────────────────────────────────

    def save_lead(self, brand_id: str, data: dict) -> int:
        now = datetime.utcnow().isoformat()
        if data.get("id"):
            self.conn.execute(
                """UPDATE sales_leads SET name=?,company=?,email=?,phone=?,linkedin_url=?,
                   website=?,industry=?,company_size=?,job_title=?,score=?,stage=?,language=?,
                   hubspot_id=?,sentiment_score=?,last_contact=?,notes=?,source=?,updated_at=?
                   WHERE id=? AND brand_id=?""",
                (data.get("name",""), data.get("company",""), data.get("email",""),
                 data.get("phone",""), data.get("linkedin_url",""), data.get("website",""),
                 data.get("industry",""), data.get("company_size",""), data.get("job_title",""),
                 data.get("score",0), data.get("stage","nuevo"), data.get("language","es"),
                 data.get("hubspot_id",""), data.get("sentiment_score",3.0),
                 data.get("last_contact"), data.get("notes",""), data.get("source","manual"),
                 now, data["id"], brand_id)
            )
            self.conn.commit()
            return data["id"]
        cur = self.conn.execute(
            """INSERT INTO sales_leads
               (brand_id,name,company,email,phone,linkedin_url,website,industry,
                company_size,job_title,score,stage,language,hubspot_id,sentiment_score,
                last_contact,notes,source,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (brand_id, data.get("name",""), data.get("company",""), data.get("email",""),
             data.get("phone",""), data.get("linkedin_url",""), data.get("website",""),
             data.get("industry",""), data.get("company_size",""), data.get("job_title",""),
             data.get("score",0), data.get("stage","nuevo"), data.get("language","es"),
             data.get("hubspot_id",""), data.get("sentiment_score",3.0),
             data.get("last_contact"), data.get("notes",""), data.get("source","manual"),
             now, now)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_lead(self, lead_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM sales_leads WHERE id=?", (lead_id,)).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.execute("SELECT * FROM sales_leads LIMIT 0").description]
        return dict(zip(cols, row))

    def list_leads(self, brand_id: str, stage: str = None, limit: int = 100) -> list[dict]:
        base_sql = """
            SELECT l.*, COALESCE(e.escalated_count, 0) AS escalated_count
            FROM sales_leads l
            LEFT JOIN (
                SELECT lead_id, COUNT(*) AS escalated_count
                FROM sales_conversations WHERE escalated=1
                GROUP BY lead_id
            ) e ON e.lead_id = l.id
            WHERE l.brand_id=?
        """
        if stage:
            cur = self.conn.execute(
                base_sql + " AND l.stage=? ORDER BY l.score DESC, l.updated_at DESC LIMIT ?",
                (brand_id, stage, limit)
            )
        else:
            cur = self.conn.execute(
                base_sql + " ORDER BY l.score DESC, l.updated_at DESC LIMIT ?",
                (brand_id, limit)
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def save_conversation(self, lead_id: int, brand_id: str, data: dict) -> int:
        cur = self.conn.execute(
            """INSERT INTO sales_conversations
               (lead_id,brand_id,channel,direction,message,subject,
                sentiment_score,sentiment_label,escalated)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (lead_id, brand_id, data.get("channel","email"), data.get("direction","outbound"),
             data.get("message",""), data.get("subject",""),
             data.get("sentiment_score",3.0), data.get("sentiment_label","neutral"),
             int(data.get("escalated",False)))
        )
        self.conn.execute(
            "UPDATE sales_leads SET last_contact=datetime('now'),updated_at=datetime('now') WHERE id=?",
            (lead_id,)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_conversations(self, lead_id: int) -> list[dict]:
        cols_q = self.conn.execute("SELECT * FROM sales_conversations LIMIT 0")
        cols = [d[0] for d in cols_q.description]
        rows = self.conn.execute(
            "SELECT * FROM sales_conversations WHERE lead_id=? ORDER BY created_at ASC",
            (lead_id,)
        ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def save_insight(self, brand_id: str, insight_type: str, content: str, data: dict = None) -> None:
        self.conn.execute(
            "INSERT INTO sales_insights (brand_id,type,content,data_json) VALUES (?,?,?,?)",
            (brand_id, insight_type, content, json.dumps(data or {}, ensure_ascii=False))
        )
        self.conn.commit()

    def get_insights(self, brand_id: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,type,content,data_json,created_at FROM sales_insights "
            "WHERE brand_id=? ORDER BY created_at DESC LIMIT ?",
            (brand_id, limit)
        ).fetchall()
        result = []
        for r in rows:
            d = {"id": r[0], "type": r[1], "content": r[2], "created_at": r[4]}
            try:
                d["data"] = json.loads(r[3] or "{}")
            except Exception:
                d["data"] = {}
            result.append(d)
        return result

    def save_report(self, brand_id: str, report: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO sales_reports (brand_id,report_json) VALUES (?,?)",
            (brand_id, json.dumps(report, ensure_ascii=False))
        )
        self.conn.commit()
        return cur.lastrowid

    def get_reports(self, brand_id: str, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,report_json,sent_slack,created_at FROM sales_reports "
            "WHERE brand_id=? ORDER BY created_at DESC LIMIT ?",
            (brand_id, limit)
        ).fetchall()
        result = []
        for r in rows:
            try:
                report = json.loads(r[1] or "{}")
            except Exception:
                report = {}
            result.append({"id": r[0], "report": report, "sent_slack": bool(r[2]), "created_at": r[3]})
        return result

    def get_sales_stats(self, brand_id: str) -> dict:
        stages = ["nuevo","contactado","interesado","propuesta","negociacion","cerrado"]
        stats = {"by_stage": {}, "total": 0, "avg_score": 0, "escalations_pending": 0}
        for stage in stages:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM sales_leads WHERE brand_id=? AND stage=?",
                (brand_id, stage)
            ).fetchone()[0]
            stats["by_stage"][stage] = count
            stats["total"] += count
        avg = self.conn.execute(
            "SELECT AVG(score) FROM sales_leads WHERE brand_id=? AND stage != 'cerrado'",
            (brand_id,)
        ).fetchone()[0]
        stats["avg_score"] = round(avg or 0, 1)
        stats["escalations_pending"] = self.conn.execute(
            "SELECT COUNT(*) FROM sales_conversations WHERE brand_id=? AND escalated=1 "
            "AND created_at >= date('now','-7 days')",
            (brand_id,)
        ).fetchone()[0]
        stats["closed_this_month"] = self.conn.execute(
            "SELECT COUNT(*) FROM sales_leads WHERE brand_id=? AND stage='cerrado' "
            "AND updated_at >= date('now','start of month')",
            (brand_id,)
        ).fetchone()[0]
        return stats

    def close(self):
        self.conn.close()
