"""Social media API integrations: Instagram, Facebook, LinkedIn."""

import os
import time
import requests
import json
import logging
from pathlib import Path
from config import settings

logger = logging.getLogger(__name__)
GRAPH_API = "https://graph.facebook.com/v19.0"

# Project root (parent of this file's directory)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ensure_public_url(url: str) -> str:
    """
    If the URL is a localhost/127.0.0.1 address (not reachable by Meta),
    upload the file to fal.ai storage and return the public URL instead.
    """
    if not url:
        return url
    if not ("localhost" in url or "127.0.0.1" in url):
        return url  # already public

    try:
        import fal_client
        # fal_client expects FAL_KEY; map from FAL_API_KEY if needed
        if not os.environ.get("FAL_KEY") and os.environ.get("FAL_API_KEY"):
            os.environ["FAL_KEY"] = os.environ["FAL_API_KEY"]
        # Extract the path component after the host:port
        from urllib.parse import urlparse
        parsed = urlparse(url)
        rel_path = parsed.path.lstrip("/")  # e.g. "static/uploads/media/..."
        local_path = _PROJECT_ROOT / rel_path

        if not local_path.exists():
            logger.warning(f"[upload] Archivo local no encontrado: {local_path}")
            return url

        # Determine MIME type
        suffix = local_path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
            ".gif": "image/gif", ".mp4": "video/mp4",
        }.get(suffix, "application/octet-stream")

        logger.info(f"[upload] Subiendo imagen local a fal.ai: {local_path.name}")
        public_url = fal_client.upload_file(local_path)
        logger.info(f"[upload] URL pública obtenida: {public_url}")
        return public_url

    except Exception as e:
        logger.error(f"[upload] Error subiendo a fal.ai: {e}")
        return url  # fallback: try original URL anyway


# ── Instagram (Meta Graph API) ─────────────────────────────────────────────

def instagram_create_text_post(caption: str) -> dict:
    """
    Publish a text-only post to Instagram Business account.
    For photo/video posts, an image_url is required — handled by instagram_create_media_post.
    """
    # Instagram requires media; for text we use a blank-image workaround or just log warning.
    return {
        "error": "Instagram requires an image or video. Use instagram_create_media_post with an image_url."
    }


def _wait_for_container(creation_id: str, token: str, max_wait: int = 90) -> tuple[bool, str]:
    """
    Poll the Instagram container status until FINISHED or ERROR.
    Returns (ready: bool, error_message: str).
    Meta requires this before calling media_publish — skipping it causes
    the 'Media ID is not available' error.
    """
    for attempt in range(max_wait // 5):
        resp = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=15,
        ).json()
        status_code = resp.get("status_code", "")
        logger.info(f"[instagram] container {creation_id} status: {status_code} (intento {attempt+1})")
        if status_code == "FINISHED":
            return True, ""
        if status_code in ("ERROR", "EXPIRED"):
            return False, f"Meta rechazó la imagen: {resp.get('status', status_code)}"
        time.sleep(5)
    return False, "Timeout: Instagram tardó más de 90s en procesar la imagen."


def instagram_create_media_post(caption: str, image_url: str, media_type: str = "IMAGE",
                                creds: dict = None) -> dict:
    """Publish a photo or Reel to Instagram Business."""
    c = creds or {}
    token = c.get("meta_access_token") or settings.META_ACCESS_TOKEN
    ig_id  = c.get("instagram_business_account_id") or settings.INSTAGRAM_BUSINESS_ACCOUNT_ID

    if not token:
        return {"error": "No hay Meta Access Token configurado. Ve a /brands → pestaña Credenciales."}
    if not ig_id:
        return {"error": "No hay Instagram Business Account ID configurado. Ve a /brands → pestaña Credenciales."}

    # If image is on localhost, upload to fal.ai to get a public URL
    image_url = _ensure_public_url(image_url)

    # Verify image is still accessible before sending to Meta
    try:
        head = requests.head(image_url, timeout=10, allow_redirects=True)
        if head.status_code >= 400:
            return {
                "error": (
                    f"La URL de imagen ya no está disponible (HTTP {head.status_code}). "
                    "Las URLs de fal.ai expiran en ~1h. Regenera la imagen."
                )
            }
    except Exception as e:
        logger.warning(f"[instagram] No se pudo verificar URL de imagen: {e}")

    # Step 1: Create media container
    params = {"access_token": token}
    if media_type == "REELS":
        params["media_type"] = "REELS"
        params["video_url"] = image_url
        params["caption"] = caption
    elif media_type == "STORIES":
        params["media_type"] = "STORIES"
        params["image_url"] = image_url
        # Stories don't support captions — skip it
    else:
        params["image_url"] = image_url
        params["caption"] = caption

    container_resp = requests.post(
        f"{GRAPH_API}/{ig_id}/media",
        params=params,
        timeout=30,
    )
    container_data = container_resp.json()
    if "error" in container_data:
        return {"error": container_data["error"].get("message", str(container_data["error"]))}

    creation_id = container_data.get("id")
    logger.info(f"[instagram] Contenedor creado: {creation_id}")

    # Step 2: Wait for Meta to process the media (required — skipping this causes the error)
    ready, err = _wait_for_container(creation_id, token)
    if not ready:
        return {"error": err}

    # Step 3: Publish
    publish_resp = requests.post(
        f"{GRAPH_API}/{ig_id}/media_publish",
        params={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    result = publish_resp.json()
    if "error" in result:
        return {"error": result["error"].get("message", str(result["error"]))}

    return {"success": True, "post_id": result.get("id"), "platform": "instagram"}


# ── Facebook (Meta Graph API) ──────────────────────────────────────────────

def _get_page_access_token(user_token: str, page_id: str) -> str:
    """
    Get the Page Access Token for a Facebook Page.
    Uses /{page_id}?fields=access_token — works for both regular users and System Users.
    /me/accounts does NOT work for Business Manager System Users.
    """
    try:
        resp = requests.get(
            f"{GRAPH_API}/{page_id}",
            params={"fields": "access_token,name", "access_token": user_token},
            timeout=10,
        )
        data = resp.json()
        logger.info(f"[facebook] Page token exchange: {json.dumps({k: v for k, v in data.items() if k != 'access_token'})}")

        page_token = data.get("access_token")
        if page_token:
            logger.info(f"[facebook] Page Token obtenido para '{data.get('name')}'")
            return page_token

        logger.error(f"[facebook] No se obtuvo page token: {data.get('error', data)}")
    except Exception as e:
        logger.error(f"[facebook] Excepción obteniendo Page Token: {e}")
    return user_token


def facebook_create_post(message: str, image_url: str = None, creds: dict = None) -> dict:
    """
    Publish a post to the Facebook Page.
    With image: uploads photo unpublished first, then attaches to feed post.
    Without image: posts directly to /feed.
    """
    c = creds or {}
    user_token = c.get("meta_access_token") or settings.META_ACCESS_TOKEN
    page_id    = c.get("facebook_page_id") or settings.FACEBOOK_PAGE_ID

    if not user_token:
        return {"error": "No hay Meta Access Token configurado. Ve a /brands → pestaña Credenciales."}
    if not page_id:
        return {"error": "No hay Facebook Page ID configurado. Ve a /brands → pestaña Credenciales."}

    explicit_page_token = c.get("facebook_page_access_token") or settings.FACEBOOK_PAGE_ACCESS_TOKEN
    if explicit_page_token:
        token = explicit_page_token
        logger.info("[facebook] Usando Page Token explícito de brand config / .env")
    else:
        token = _get_page_access_token(user_token, page_id)

    # If image is on localhost, upload to fal.ai to get a public URL
    if image_url:
        image_url = _ensure_public_url(image_url)

    if image_url:
        # Publicar foto directamente con caption (1 solo paso — compatible con páginas nuevas/en verificación)
        photo_resp = requests.post(
            f"{GRAPH_API}/{page_id}/photos",
            params={
                "url": image_url,
                "caption": message,
                "access_token": token,
            },
            timeout=30,
        )
        photo_data = photo_resp.json()
        logger.info(f"[facebook] upload photo response: {photo_data}")

        if "error" in photo_data:
            err_code = photo_data["error"].get("code")
            err_msg  = photo_data["error"].get("message", str(photo_data["error"]))
            # Si falla la foto, publicar solo texto como fallback
            if err_code in (200, 10, 190):
                logger.warning(f"[facebook] Sin permiso para foto ({err_code}), publicando solo texto")
                return _facebook_text_only(page_id, token, message)
            return {"error": f"Facebook foto: {err_msg}"}

        return {"success": True, "post_id": photo_data.get("post_id") or photo_data.get("id"), "platform": "facebook"}

    else:
        # Text-only post
        resp = requests.post(
            f"{GRAPH_API}/{page_id}/feed",
            params={"message": message, "access_token": token},
            timeout=30,
        )
        result = resp.json()
        if "error" in result:
            return {"error": result["error"].get("message", str(result["error"]))}
        return {"success": True, "post_id": result.get("id"), "platform": "facebook"}


def _facebook_text_only(page_id: str, token: str, message: str) -> dict:
    """Fallback: publicar solo texto al feed cuando la foto falla."""
    resp = requests.post(
        f"{GRAPH_API}/{page_id}/feed",
        params={"message": message, "access_token": token},
        timeout=30,
    )
    result = resp.json()
    if "error" in result:
        return {"error": result["error"].get("message", str(result["error"]))}
    return {"success": True, "post_id": result.get("id"), "platform": "facebook", "note": "publicado sin foto (fallback texto)"}


# ── LinkedIn ───────────────────────────────────────────────────────────────

def linkedin_create_post(text: str) -> dict:
    """Publish an organization post to LinkedIn."""
    token = settings.LINKEDIN_ACCESS_TOKEN
    org_id = settings.LINKEDIN_ORGANIZATION_ID

    if not token or not org_id:
        return {"error": "LINKEDIN_ACCESS_TOKEN o LINKEDIN_ORGANIZATION_ID no configurados en .env"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    payload = {
        "author": f"urn:li:organization:{org_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    resp = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers=headers,
        data=json.dumps(payload),
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        return {"error": f"LinkedIn error {resp.status_code}: {resp.text}"}

    result = resp.json()
    return {"success": True, "post_id": result.get("id"), "platform": "linkedin"}


# ── Tool definitions for the agent ────────────────────────────────────────

SOCIAL_TOOLS = [
    {
        "name": "post_to_instagram",
        "description": (
            "Publica una foto con caption en Instagram Business (@voxifyhub). "
            "Requiere una URL pública de imagen. Retorna el ID del post o un error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "caption": {
                    "type": "string",
                    "description": "Texto del post incluyendo hashtags (máx 2200 caracteres).",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL pública de la imagen a publicar.",
                },
            },
            "required": ["caption", "image_url"],
        },
    },
    {
        "name": "post_to_facebook",
        "description": (
            "Publica un post en la página de Facebook de VoxifyHub. "
            "Puede ser solo texto o texto con imagen (opcional)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Texto del post (máx 63,206 caracteres).",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL pública de imagen (opcional).",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "post_to_linkedin",
        "description": (
            "Publica un post en la página de LinkedIn de VoxifyHub. "
            "Ideal para contenido profesional y thought leadership."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Texto del post (máx 3000 caracteres para mayor alcance).",
                },
            },
            "required": ["text"],
        },
    },
]


def execute_social_tool(tool_name: str, tool_input: dict, creds: dict = None) -> str:
    """Route tool calls from the agent to the right API function."""
    if tool_name == "post_to_instagram":
        result = instagram_create_media_post(
            caption=tool_input["caption"],
            image_url=tool_input["image_url"],
            media_type=tool_input.get("media_type", "IMAGE"),
            creds=creds,
        )
    elif tool_name == "post_to_facebook":
        result = facebook_create_post(
            message=tool_input["message"],
            image_url=tool_input.get("image_url"),
            creds=creds,
        )
    elif tool_name == "post_to_linkedin":
        result = linkedin_create_post(text=tool_input["text"])
    else:
        result = {"error": f"Herramienta desconocida: {tool_name}"}

    return json.dumps(result, ensure_ascii=False)
