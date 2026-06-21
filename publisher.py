"""
Meta Graph API publisher — Instagram + Facebook.
Handles all content types: post, reel, story, carousel.
Media source: image_url (photos) or video_url (reels/stories).
"""
import logging
import time
import requests

logger = logging.getLogger(__name__)

GRAPH_URL           = "https://graph.facebook.com/v19.0"
VIDEO_POLL_TIMEOUT  = 180   # seconds to wait for Instagram video processing
VIDEO_POLL_INTERVAL = 8     # seconds between status polls


def _post(path: str, params: dict) -> dict:
    resp = requests.post(f"{GRAPH_URL}/{path}", params=params, timeout=60)
    data = resp.json()
    if 'error' in data:
        msg = data['error'].get('message', str(data['error']))
        raise RuntimeError(f"Meta API: {msg}")
    return data


def _get(path: str, params: dict) -> dict:
    resp = requests.get(f"{GRAPH_URL}/{path}", params=params, timeout=30)
    data = resp.json()
    if 'error' in data:
        msg = data['error'].get('message', str(data['error']))
        raise RuntimeError(f"Meta API: {msg}")
    return data


def _wait_for_video_container(container_id: str, token: str) -> None:
    """Poll until Instagram video container is FINISHED."""
    deadline = time.time() + VIDEO_POLL_TIMEOUT
    while time.time() < deadline:
        status = _get(container_id, {'fields': 'status_code', 'access_token': token})
        code = status.get('status_code', '')
        logger.info(f"[publisher] container {container_id} status: {code}")
        if code == 'FINISHED':
            return
        if code == 'ERROR':
            raise RuntimeError(f"Video processing error: {status}")
        time.sleep(VIDEO_POLL_INTERVAL)
    raise RuntimeError(f"Video processing timed out after {VIDEO_POLL_TIMEOUT}s")


def publish_instagram(token: str, account_id: str, caption: str,
                      image_url: str = '', video_url: str = '',
                      content_type: str = 'post') -> str:
    """
    Publish to Instagram via Graph API.
    content_type: 'post' | 'reel' | 'story' | 'carousel'
    Returns the published media ID.
    """
    if not token or not account_id:
        raise ValueError("Missing Instagram credentials")

    params = {'access_token': token, 'caption': caption}
    is_video = False

    if content_type == 'reel':
        if not video_url:
            raise ValueError("Reels require a video_url")
        params['video_url'] = video_url
        params['media_type'] = 'REELS'
        is_video = True

    elif content_type == 'story':
        if video_url:
            params['video_url'] = video_url
            params['media_type'] = 'STORIES'
            is_video = True
        elif image_url:
            params['image_url'] = image_url
            params['media_type'] = 'STORIES'
        else:
            raise ValueError("Stories require image_url or video_url")

    elif content_type == 'carousel':
        if not image_url:
            raise ValueError("Carousels require an image_url")
        params['image_url'] = image_url
        params['media_type'] = 'IMAGE'

    else:  # post / default
        if video_url:
            params['video_url'] = video_url
            params['media_type'] = 'VIDEO'
            is_video = True
        elif image_url:
            params['image_url'] = image_url
            params['media_type'] = 'IMAGE'
        else:
            raise ValueError("Posts require image_url or video_url")

    # Step 1: Create media container
    container = _post(f"{account_id}/media", params)
    cid = container.get('id')
    if not cid:
        raise RuntimeError(f"No container ID returned: {container}")
    logger.info(f"[publisher] IG container created: {cid} ({content_type})")

    # Step 2: Wait for video processing if needed
    if is_video:
        _wait_for_video_container(cid, token)

    # Step 3: Publish
    result = _post(f"{account_id}/media_publish", {
        'access_token': token,
        'creation_id': cid,
    })
    media_id = result.get('id', '')
    logger.info(f"[publisher] IG published: {media_id}")
    return media_id


def publish_facebook(token: str, page_id: str, caption: str,
                     image_url: str = '', video_url: str = '',
                     content_type: str = 'post') -> str:
    """Publish to Facebook Page. Returns the post/video ID."""
    if not token or not page_id:
        raise ValueError("Missing Facebook credentials")

    if video_url:
        result = _post(f"{page_id}/videos", {
            'access_token': token,
            'file_url':    video_url,
            'description': caption,
        })
        return result.get('id', '')

    if image_url:
        result = _post(f"{page_id}/photos", {
            'access_token': token,
            'url':     image_url,
            'message': caption,
        })
        return result.get('id', result.get('post_id', ''))

    # Text-only
    result = _post(f"{page_id}/feed", {
        'access_token': token,
        'message': caption,
    })
    return result.get('id', '')


def publish_tiktok(access_token: str, video_url: str, caption: str) -> str:
    """
    Publish a video to TikTok via Content Posting API (PULL_FROM_URL).
    video_url must be publicly accessible (e.g. Railway media endpoint).
    Returns the TikTok publish_id on success.

    Requires: TikTok for Business developer app with video.publish scope.
    Set tiktok_access_token on the brand when the user authorizes the app.
    """
    if not access_token:
        raise ValueError("Missing TikTok access token")
    if not video_url:
        raise ValueError("TikTok requires a video_url")

    TIKTOK_API = "https://open.tiktokapis.com/v2"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }

    # Step 1: Initialize post
    init_resp = requests.post(
        f"{TIKTOK_API}/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {
                "title":                    caption[:2200],
                "privacy_level":            "PUBLIC_TO_EVERYONE",
                "disable_duet":             False,
                "disable_comment":          False,
                "disable_stitch":           False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source":    "PULL_FROM_URL",
                "video_url": video_url,
            },
        },
        timeout=30,
    )
    init_resp.raise_for_status()
    data       = init_resp.json()
    publish_id = data.get("data", {}).get("publish_id", "")
    if not publish_id:
        raise RuntimeError(f"TikTok init failed: {data}")

    logger.info(f"[publisher] TikTok publish_id: {publish_id}")

    # Step 2: Poll for completion (up to 60 seconds)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(4)
        status_resp = requests.post(
            f"{TIKTOK_API}/post/publish/status/fetch/",
            headers=headers,
            json={"publish_id": publish_id},
            timeout=15,
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status      = status_data.get("data", {}).get("status", "")
        logger.info(f"[publisher] TikTok status: {status}")
        if status == "PUBLISH_COMPLETE":
            return publish_id
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"TikTok publish {status}: {status_data}")

    logger.warning(f"[publisher] TikTok publish_id {publish_id} still processing — returning ID")
    return publish_id


def publish_post(brand: dict, post: dict) -> dict:
    token        = brand.get('meta_access_token', '')
    ig_acct      = brand.get('instagram_account_id', '')
    fb_page      = brand.get('facebook_page_id', '')
    tiktok_token = brand.get('tiktok_access_token', '')
    caption      = post.get('caption', '')
    img_url      = post.get('image_url', '')
    vid_url      = post.get('video_url', '')
    platform     = post.get('platform', 'instagram')
    content_type = post.get('content_type', 'post')

    result = {'success': False, 'ids': {}, 'errors': []}

    if platform in ('instagram', 'both') and token and ig_acct:
        try:
            ig_id = publish_instagram(token, ig_acct, caption,
                                      img_url, vid_url, content_type)
            result['ids']['instagram'] = ig_id
        except Exception as e:
            result['errors'].append(f"Instagram: {e}")
            logger.error(f"[publisher] Instagram failed: {e}")

    if platform in ('facebook', 'both') and token and fb_page:
        try:
            fb_id = publish_facebook(token, fb_page, caption,
                                     img_url, vid_url, content_type)
            result['ids']['facebook'] = fb_id
        except Exception as e:
            result['errors'].append(f"Facebook: {e}")
            logger.error(f"[publisher] Facebook failed: {e}")

    if platform == 'tiktok' and tiktok_token and vid_url:
        try:
            # Build absolute URL if relative path was stored
            base_url = "https://server-production-f212.up.railway.app"
            full_vid  = vid_url if vid_url.startswith("http") else f"{base_url}{vid_url}"
            tk_id = publish_tiktok(tiktok_token, full_vid, caption)
            result['ids']['tiktok'] = tk_id
        except Exception as e:
            result['errors'].append(f"TikTok: {e}")
            logger.error(f"[publisher] TikTok failed: {e}")

    result['success'] = bool(result['ids'])
    return result
