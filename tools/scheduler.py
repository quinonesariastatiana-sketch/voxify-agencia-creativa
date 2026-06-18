"""
MultiScheduler — runs one cron job per brand × platform.
Each brand uses its own Meta credentials; fal.ai is shared.

Schedule per brand (configurable in brand config):
  Instagram : Mon–Fri 9:00 AM ET
  Facebook  : Mon–Fri 10:00 AM ET
  LinkedIn  : Wednesday 8:00 AM ET → marked ready_manual
"""

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from tools.social_media import execute_social_tool

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class MultiScheduler:
    def __init__(self, db, brands: dict):
        """
        brands: dict of {brand_id: brand_config} from brands_registry.BRANDS
        """
        self.db = db
        self.brands = brands
        self.scheduler = BackgroundScheduler(timezone="America/New_York")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        for brand_id, brand in self.brands.items():
            schedule = brand.get("posting_schedule", {})
            for platform, sched_config in schedule.items():
                # Support both a single schedule dict and a list of schedule dicts
                slots = sched_config if isinstance(sched_config, list) else [sched_config]
                for idx, sched in enumerate(slots):
                    days = sched.get("days", [])
                    if not days:
                        continue
                    job_id = f"{brand_id}_{platform}" if idx == 0 else f"{brand_id}_{platform}_{idx}"
                    self.scheduler.add_job(
                        func=self._publish_next_post,
                        trigger=CronTrigger(
                            day_of_week=",".join(days),
                            hour=sched.get("hour", 9),
                            minute=sched.get("minute", 0),
                            timezone="America/New_York",
                        ),
                        args=[brand_id, platform],
                        id=job_id,
                        replace_existing=True,
                    )
                    logger.info(
                        f"Scheduler [{brand['name']}] {platform} slot {idx+1} — "
                        f"{'/'.join(days)} {sched['hour']:02d}:{sched['minute']:02d} ET"
                    )
        self.scheduler.start()
        logger.info(f"MultiScheduler activo — {len(self.brands)} marca(s).")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("MultiScheduler detenido.")

    @property
    def running(self):
        return self.scheduler.running

    # ── Cron callback ─────────────────────────────────────────────────────────

    def _publish_next_post(self, brand_id: str, platform: str):
        now_et = datetime.now(ET).strftime("%Y-%m-%dT%H:%M:%S")
        brand = self.brands.get(brand_id, {})
        logger.info(f"[{brand_id}] Scheduler disparado: {platform} — {now_et} ET")

        if platform == "linkedin":
            post = self._get_due_post(brand_id, platform)
            if post:
                self.db.mark_post_ready_manual(post[0])
                logger.info(f"[{brand_id}] LinkedIn post {post[0]} → listo manual.")
            return

        post = self._get_due_post(brand_id, platform)
        if not post:
            logger.info(f"[{brand_id}] No hay posts aprobados para {platform}.")
            return

        post_id, content_type, content, image_url, video_url = post
        creds = brand.get("credentials", {})
        result = self._execute_publish(post_id, brand_id, platform, content, image_url, video_url, creds, content_type or "")
        self._handle_result(result, post_id, brand_id, platform)

    # ── Manual trigger (testing) ──────────────────────────────────────────────

    def trigger_now(self, brand_id: str, platform: str) -> dict:
        """Force-publish the next approved post for a brand+platform, ignoring date."""
        brand = self.brands.get(brand_id)
        if not brand:
            return {"success": False, "message": f"Marca no encontrada: {brand_id}"}

        if platform == "linkedin":
            post = self.db.conn.execute(
                "SELECT id FROM scheduled_posts WHERE brand_id=? AND platform='linkedin' AND status='pending' "
                "ORDER BY scheduled_date ASC LIMIT 1",
                (brand_id,)
            ).fetchone()
            if not post:
                return {"success": False, "message": "No hay posts de LinkedIn aprobados."}
            self.db.mark_post_ready_manual(post[0])
            return {"success": True, "message": f"LinkedIn post {post[0]} marcado listo manual."}

        post = self.db.conn.execute(
            """SELECT id, content_type, content, image_url, video_url
               FROM scheduled_posts
               WHERE brand_id=? AND platform=? AND status='pending'
               ORDER BY scheduled_date ASC LIMIT 1""",
            (brand_id, platform),
        ).fetchone()

        if not post:
            return {"success": False, "message": f"No hay posts aprobados para {platform}."}

        post_id, content_type, content, image_url, video_url = post
        creds = brand.get("credentials", {})
        result = self._execute_publish(post_id, brand_id, platform, content, image_url, video_url, creds, content_type or "")
        self._handle_result(result, post_id, brand_id, platform)
        return result

    # ── Shared publish logic ──────────────────────────────────────────────────

    def _execute_publish(self, post_id: int, brand_id: str, platform: str,
                         content: str, image_url: str, video_url: str, creds: dict,
                         content_type: str = "") -> dict:
        media_url = video_url or image_url
        try:
            if platform == "instagram":
                if not media_url:
                    self.db.mark_post_skipped(post_id)
                    return {"success": False, "message": "Instagram requiere imagen o video.", "post_id": post_id}
                tool_args = {"caption": content, "image_url": media_url}
                if content_type == "instagram_story":
                    tool_args["media_type"] = "STORIES"
                elif video_url:
                    tool_args["media_type"] = "REELS"
                result_str = execute_social_tool("post_to_instagram", tool_args, creds=creds)

            elif platform == "facebook":
                result_str = execute_social_tool(
                    "post_to_facebook", {"message": content, "image_url": media_url}, creds=creds
                )
            else:
                return {"success": False, "message": f"Plataforma no soportada: {platform}", "post_id": post_id}

            result = json.loads(result_str)
            result["post_id"] = post_id
            result["external_id"] = result.get("post_id")
            return result

        except Exception as e:
            logger.error(f"[{brand_id}] Excepción publicando post {post_id}: {e}")
            return {"success": False, "message": str(e), "post_id": post_id}

    def _handle_result(self, result: dict, post_id: int, brand_id: str, platform: str):
        if result.get("success"):
            self.db.mark_post_published(post_id, result.get("external_id", ""))
            logger.info(f"[{brand_id}] ✓ Publicado {platform} post {post_id}")
        else:
            error = result.get("message") or result.get("error") or "Error desconocido"
            self.db.mark_post_failed(post_id, error)
            logger.error(f"[{brand_id}] ✗ Error {platform} post {post_id}: {error}")

    # ── Queries ───────────────────────────────────────────────────────────────

    def _get_due_post(self, brand_id: str, platform: str):
        now_et = datetime.now(ET).strftime("%Y-%m-%dT%H:%M:%S")
        return self.db.conn.execute(
            """SELECT id, content_type, content, image_url, video_url
               FROM scheduled_posts
               WHERE brand_id=? AND platform=? AND status='pending' AND scheduled_date<=?
               ORDER BY scheduled_date ASC LIMIT 1""",
            (brand_id, platform, now_et),
        ).fetchone()

    def get_upcoming(self, brand_id: str, limit: int = 10) -> list:
        return self.db.conn.execute(
            """SELECT id, platform, content_type, scheduled_date, status
               FROM scheduled_posts
               WHERE brand_id=? AND status IN ('pending','pending_approval')
               ORDER BY scheduled_date ASC LIMIT ?""",
            (brand_id, limit),
        ).fetchall()
