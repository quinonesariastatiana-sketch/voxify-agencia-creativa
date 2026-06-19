"""
Meta Graph API publisher — Instagram + Facebook.
Each brand carries its own token and account IDs.
"""
import logging
import requests

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v19.0"


def _post(path: str, params: dict) -> dict:
    resp = requests.post(f"{GRAPH_URL}/{path}", params=params, timeout=30)
    data = resp.json()
    if 'error' in data:
        msg = data['error'].get('message', str(data['error']))
        raise RuntimeError(f"Meta API: {msg}")
    return data


def publish_instagram(token: str, account_id: str, caption: str, image_url: str = '') -> str:
    if not token or not account_id:
        raise ValueError("Missing Instagram credentials")
    container_params = {'access_token': token, 'caption': caption}
    if image_url:
        container_params['image_url'] = image_url
        container_params['media_type'] = 'IMAGE'
    else:
        raise ValueError("Instagram requires an image_url")

    container = _post(f"{account_id}/media", container_params)
    cid = container.get('id')
    if not cid:
        raise RuntimeError(f"No container ID: {container}")

    result = _post(f"{account_id}/media_publish", {
        'access_token': token,
        'creation_id': cid,
    })
    return result.get('id', '')


def publish_facebook(token: str, page_id: str, caption: str, image_url: str = '') -> str:
    if not token or not page_id:
        raise ValueError("Missing Facebook credentials")
    params = {'access_token': token, 'message': caption}
    if image_url:
        params['url'] = image_url
        result = _post(f"{page_id}/photos", params)
    else:
        result = _post(f"{page_id}/feed", params)
    return result.get('id', result.get('post_id', ''))


def publish_post(brand: dict, post: dict) -> dict:
    token    = brand.get('meta_access_token', '')
    ig_acct  = brand.get('instagram_account_id', '')
    fb_page  = brand.get('facebook_page_id', '')
    caption  = post.get('caption', '')
    img_url  = post.get('image_url', '')
    platform = post.get('platform', 'instagram')

    result = {'success': False, 'ids': {}, 'errors': []}

    if platform in ('instagram', 'both') and token and ig_acct:
        try:
            ig_id = publish_instagram(token, ig_acct, caption, img_url)
            result['ids']['instagram'] = ig_id
        except Exception as e:
            result['errors'].append(f"Instagram: {e}")
            logger.error(f"[publisher] Instagram failed: {e}")

    if platform in ('facebook', 'both') and token and fb_page:
        try:
            fb_id = publish_facebook(token, fb_page, caption, img_url)
            result['ids']['facebook'] = fb_id
        except Exception as e:
            result['errors'].append(f"Facebook: {e}")
            logger.error(f"[publisher] Facebook failed: {e}")

    result['success'] = bool(result['ids'])
    return result
