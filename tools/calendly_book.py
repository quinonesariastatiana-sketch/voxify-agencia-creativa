"""Calendly integration — scheduling links and event management."""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)
BASE = "https://api.calendly.com"


def _token() -> str:
    return settings.CALENDLY_API_TOKEN


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def _ok() -> bool:
    return bool(_token())


def get_scheduling_link(event_type_uri: str = "", name: str = "", email: str = "") -> dict:
    """
    Generate a one-off scheduling link for a specific prospect.
    Uses CALENDLY_EVENT_URI from settings as default. Falls back to CALENDLY_BOOKING_URL.
    """
    event_uri  = event_type_uri or settings.CALENDLY_EVENT_URI
    booking_url = settings.CALENDLY_BOOKING_URL

    if not _ok() or not event_uri:
        return {"url": booking_url, "generic": True}

    try:
        payload = {
            "max_event_count": 1,
            "owner": event_uri,
            "owner_type": "EventType",
        }
        r = requests.post(
            f"{BASE}/scheduling_links",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        data = r.json()
        if r.status_code in (200, 201):
            url = data.get("resource", {}).get("booking_url", booking_url)
            return {"url": url, "generic": False}
        logger.warning(f"[calendly] Error generando one-off link: {data.get('message','')}")
        return {"url": booking_url, "generic": True, "error": data.get("message", "")}
    except Exception as e:
        logger.warning(f"[calendly] Error: {e}")
        return {"url": booking_url, "generic": True}


def get_event_types() -> list[dict]:
    if not _ok():
        return []
    try:
        me = requests.get(f"{BASE}/users/me", headers=_headers(), timeout=10).json()
        user_uri = me.get("resource", {}).get("uri", "")
        if not user_uri:
            return []
        r = requests.get(
            f"{BASE}/event_types",
            headers=_headers(),
            params={"user": user_uri, "active": True},
            timeout=15,
        )
        return r.json().get("collection", [])
    except Exception as e:
        logger.warning(f"[calendly] Error obteniendo event types: {e}")
        return []


def get_scheduled_events(count: int = 10) -> list[dict]:
    if not _ok():
        return []
    try:
        me = requests.get(f"{BASE}/users/me", headers=_headers(), timeout=10).json()
        user_uri = me.get("resource", {}).get("uri", "")
        if not user_uri:
            return []
        r = requests.get(
            f"{BASE}/scheduled_events",
            headers=_headers(),
            params={"user": user_uri, "status": "active", "count": count,
                    "sort": "start_time:desc"},
            timeout=15,
        )
        return r.json().get("collection", [])
    except Exception as e:
        logger.warning(f"[calendly] Error obteniendo eventos: {e}")
        return []


def is_configured() -> bool:
    return _ok() or bool(settings.CALENDLY_BOOKING_URL)
