"""
APScheduler wrapper — runs inside Flask process, no external cron needed.
Checks every hour for approved posts and publishes them.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_publisher():
    try:
        import database as db
        import publisher

        posts = db.get_approved_pending_posts()
        if not posts:
            return
        logger.info(f"[scheduler] Publishing {len(posts)} approved post(s)")
        for post in posts:
            brand = db.get_brand(post['brand_id'])
            if not brand:
                continue
            try:
                res = publisher.publish_post(brand, post)
                if res['success']:
                    meta_id = ','.join(res['ids'].values())
                    db.update_post(post['id'], status='posted', post_id_meta=meta_id,
                                   posted_at=__import__('datetime').datetime.utcnow().isoformat())
                    logger.info(f"[scheduler] Posted {post['id']} for {brand['name']}")
                else:
                    err = '; '.join(res['errors'])
                    db.update_post(post['id'], status='failed', error_msg=err)
            except Exception as e:
                db.update_post(post['id'], status='failed', error_msg=str(e))
                logger.error(f"[scheduler] Error on post {post['id']}: {e}")
    except Exception as e:
        logger.error(f"[scheduler] Run error: {e}")


def start():
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(_run_publisher, IntervalTrigger(hours=1),
                       id='publisher', replace_existing=True)
    _scheduler.start()
    logger.info("[scheduler] Started — publishing check every hour")


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] Stopped")


def trigger_now():
    _run_publisher()


def status() -> dict:
    if not _scheduler or not _scheduler.running:
        return {'running': False, 'jobs': []}
    jobs = [{'id': j.id, 'next_run': str(j.next_run_time)}
            for j in _scheduler.get_jobs()]
    return {'running': True, 'jobs': jobs}
