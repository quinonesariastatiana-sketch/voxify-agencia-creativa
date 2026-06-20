"""
Media generation tools for VoxifyHub.
- Images: fal.ai FLUX Schnell (realistic photos)
- Videos: fal.ai Kling 1.6 image-to-video
- Voiceover: fal.ai PlayAI TTS (native Spanish)
- Music: fal.ai Stable Audio (VoxifyHub brand sound)
- Mix: moviepy (video + voiceover + background music)

Single FAL_API_KEY covers everything.
"""

import json
import time
import logging
import os
import tempfile
import requests

logger = logging.getLogger(__name__)

IMAGE_SIZES = {
    "instagram_post":  "square_hd",       # 1080x1080
    "instagram_story": "portrait_4_3",    # 1080x1350
    "facebook_post":   "landscape_4_3",   # 1200x900
    "linkedin_post":   "landscape_16_9",  # 1200x675
}

VIDEO_MODELS = {
    "kling": "fal-ai/kling-video/v1.6/standard/image-to-video",
    "luma":  "fal-ai/luma-dream-machine/image-to-video",
    "ltx":   "fal-ai/ltx-video/image-to-video",
}
DEFAULT_VIDEO_MODEL = "kling"

TEXT_TO_VIDEO_MODELS = {
    "kling": "fal-ai/kling-video/v1.6/standard/text-to-video",
    "wan":   "fal-ai/wan/t2v-1.3",
    "ltx":   "fal-ai/ltx-video",
}
DEFAULT_T2V_MODEL = "kling"

# VoxifyHub brand sound identity
VOXIFY_SOUND_IDENTITY = {
    "music_prompt": (
        "upbeat Latin soul instrumental, warm acoustic guitar melody, light marimba and percussion, "
        "professional optimistic energy, small business celebration vibe, "
        "30 seconds, no lyrics, smooth fade in and fade out, high quality studio recording"
    ),
    "voice_style": "Valentina(Spanish(Latin America))",  # PlayAI native Spanish voice
    "music_volume": 0.12,   # background — subtle
    "voice_volume": 1.0,
    "music_duration_seconds": 32,
}


def _fal_client():
    from config.settings import FAL_API_KEY
    os.environ["FAL_KEY"] = FAL_API_KEY
    import fal_client
    return fal_client


def _download_to_temp(url: str, suffix: str) -> str:
    """Download a URL to a temp file. Returns local path."""
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(r.content)
    tmp.close()
    return tmp.name


# ── Image generation ──────────────────────────────────────────────────────

def generate_image(prompt: str, platform_format: str = "instagram_post") -> dict:
    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return {"error": "FAL_API_KEY no configurado."}

    full_prompt = (
        f"{prompt}. "
        "Professional lifestyle photography, natural lighting, authentic real people, "
        "warm tones, editorial magazine quality. No text overlays, no graphics, no logos."
    )
    try:
        fal = _fal_client()
        result = fal.run(
            "fal-ai/flux/schnell",
            arguments={
                "prompt": full_prompt,
                "image_size": IMAGE_SIZES.get(platform_format, "square_hd"),
                "num_inference_steps": 4,
                "num_images": 1,
                "enable_safety_checker": True,
            },
        )
        url = result["images"][0]["url"]
        logger.info(f"Imagen generada: {url}")
        return {"success": True, "image_url": url}
    except Exception as e:
        logger.error(f"Error generando imagen: {e}")
        return {"error": str(e)}


# ── Text-to-video generation ──────────────────────────────────────────────────

def generate_video_from_text(prompt: str, aspect_ratio: str = "9:16",
                              duration: int = 5,
                              model: str = DEFAULT_T2V_MODEL) -> dict:
    """Generate video directly from a text prompt (no source image needed)."""
    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return {"error": "FAL_API_KEY no configurado."}

    model_id = TEXT_TO_VIDEO_MODELS.get(model, TEXT_TO_VIDEO_MODELS["kling"])
    try:
        fal = _fal_client()
        if model == "kling":
            args = {"prompt": prompt, "duration": str(duration), "aspect_ratio": aspect_ratio}
        elif model == "wan":
            args = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        else:  # ltx
            args = {"prompt": prompt, "aspect_ratio": aspect_ratio}

        logger.info(f"Generando video T2V con {model} ({model_id})...")
        result = fal.run(model_id, arguments=args)
        video_url = (
            result.get("video", {}).get("url")
            or result.get("video_url")
            or (result.get("videos") or [{}])[0].get("url")
        )
        if not video_url:
            raise ValueError(f"No video URL en respuesta: {result}")
        logger.info(f"Video T2V generado: {video_url}")
        return {"success": True, "video_url": video_url, "model": model}

    except Exception as e:
        logger.error(f"Error T2V con {model}: {e}")
        if model == "kling":
            logger.info("Fallback T2V → wan...")
            return generate_video_from_text(prompt, aspect_ratio, duration, model="wan")
        if model == "wan":
            logger.info("Fallback T2V → ltx...")
            return generate_video_from_text(prompt, aspect_ratio, duration, model="ltx")
        return {"error": str(e)}


# ── Video generation (image-to-video) ────────────────────────────────────────

def generate_video(image_url: str, motion_prompt: str,
                   duration: int = 5, model: str = DEFAULT_VIDEO_MODEL) -> dict:
    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return {"error": "FAL_API_KEY no configurado."}

    model_id = VIDEO_MODELS.get(model, VIDEO_MODELS["kling"])
    try:
        fal = _fal_client()
        if model == "kling":
            args = {"image_url": image_url, "prompt": motion_prompt,
                    "duration": str(duration), "aspect_ratio": "9:16"}
        elif model == "luma":
            args = {"image_url": image_url, "prompt": motion_prompt,
                    "duration": f"{duration}s", "aspect_ratio": "9:16"}
        else:
            args = {"image_url": image_url, "prompt": motion_prompt}

        logger.info(f"Generando video con {model}...")
        result = fal.run(model_id, arguments=args)
        video_url = (
            result.get("video", {}).get("url")
            or result.get("video_url")
            or (result.get("videos") or [{}])[0].get("url")
        )
        if not video_url:
            raise ValueError(f"No se encontró URL de video: {result}")
        logger.info(f"Video generado: {video_url}")
        return {"success": True, "video_url": video_url, "model": model}

    except Exception as e:
        logger.error(f"Error con {model}: {e}")
        if model != "ltx":
            logger.info("Fallback a LTX...")
            return generate_video(image_url, motion_prompt, duration, model="ltx")
        return {"error": str(e)}


# ── Voiceover generation — fal.ai PlayAI TTS (Spanish) ───────────────────

def generate_voiceover(script: str, voice: str = None) -> dict:
    """Generate Spanish voiceover audio using PlayAI TTS via fal.ai."""
    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return {"error": "FAL_API_KEY no configurado."}

    selected_voice = voice or VOXIFY_SOUND_IDENTITY["voice_style"]
    try:
        fal = _fal_client()
        result = fal.run(
            "fal-ai/playai-tts",
            arguments={
                "input": script,
                "voice": selected_voice,
                "output_format": "mp3",
            },
        )
        audio_url = result.get("audio", {}).get("url") or result.get("audio_url")
        if not audio_url:
            raise ValueError(f"No se encontró URL de audio: {result}")
        logger.info(f"Voiceover generado: {audio_url}")
        return {"success": True, "voiceover_url": audio_url, "voice": selected_voice}
    except Exception as e:
        logger.error(f"Error generando voiceover: {e}")
        return {"error": str(e)}


# ── Background music — fal.ai Stable Audio ────────────────────────────────

def generate_background_music(mood: str = "brand", duration: int = 32) -> dict:
    """Generate brand background music using Stable Audio via fal.ai."""
    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return {"error": "FAL_API_KEY no configurado."}

    music_prompts = {
        "brand":      VOXIFY_SOUND_IDENTITY["music_prompt"],
        "energetic":  "energetic Latin pop instrumental, fast tempo, electric guitar, drums, 30s, no lyrics",
        "emotional":  "gentle emotional Latin ballad, acoustic guitar, soft piano, warm, 30s, no lyrics",
        "celebratory": "festive Latin celebration music, brass, percussion, joyful, 30s, no lyrics",
    }
    prompt = music_prompts.get(mood, music_prompts["brand"])

    try:
        fal = _fal_client()
        result = fal.run(
            "fal-ai/stable-audio",
            arguments={
                "prompt": prompt,
                "seconds_total": duration,
                "steps": 100,
            },
        )
        music_url = result.get("audio_file", {}).get("url") or result.get("audio_url")
        if not music_url:
            raise ValueError(f"No se encontró URL de música: {result}")
        logger.info(f"Música generada ({mood}): {music_url}")
        return {"success": True, "music_url": music_url, "mood": mood}
    except Exception as e:
        logger.error(f"Error generando música: {e}")
        return {"error": str(e)}


# ── Audio mixing — moviepy ────────────────────────────────────────────────

def mix_video_audio(video_url: str, voiceover_url: str = None,
                    music_url: str = None) -> dict:
    """
    Mix a video with voiceover and/or background music using moviepy.
    Uploads the result back to fal.ai CDN and returns the new URL.
    """
    try:
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
    except ImportError:
        return {"error": "moviepy no instalado. Ejecuta: pip install moviepy imageio-ffmpeg"}

    if not voiceover_url and not music_url:
        return {"error": "Se requiere al menos voiceover_url o music_url."}

    tmp_files = []
    try:
        # Download all media
        video_path = _download_to_temp(video_url, ".mp4")
        tmp_files.append(video_path)

        video = VideoFileClip(video_path)
        audio_tracks = []

        if voiceover_url:
            vo_path = _download_to_temp(voiceover_url, ".mp3")
            tmp_files.append(vo_path)
            vo_clip = AudioFileClip(vo_path).set_duration(video.duration)
            vo_clip = vo_clip.volumex(VOXIFY_SOUND_IDENTITY["voice_volume"])
            audio_tracks.append(vo_clip)

        if music_url:
            music_path = _download_to_temp(music_url, ".mp3")
            tmp_files.append(music_path)
            music_clip = AudioFileClip(music_path).set_duration(video.duration)
            music_clip = music_clip.volumex(VOXIFY_SOUND_IDENTITY["music_volume"])
            audio_tracks.append(music_clip)

        composite = CompositeAudioClip(audio_tracks)
        final_video = video.set_audio(composite)

        output_path = tempfile.mktemp(suffix="_voxify.mp4")
        tmp_files.append(output_path)
        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )
        video.close()
        final_video.close()

        # Upload mixed video back to fal.ai CDN
        fal = _fal_client()
        with open(output_path, "rb") as f:
            upload_url = fal.upload(f, content_type="video/mp4")

        logger.info(f"Video mezclado subido: {upload_url}")
        return {"success": True, "video_url": upload_url}

    except Exception as e:
        logger.error(f"Error mezclando video: {e}")
        return {"error": str(e)}
    finally:
        for path in tmp_files:
            try:
                os.unlink(path)
            except Exception:
                pass


# ── Tool definitions for the agent ────────────────────────────────────────

MEDIA_TOOLS = [
    {
        "name": "generate_post_image",
        "description": (
            "Genera una imagen fotorrealista para un post usando FLUX via fal.ai. "
            "Personas reales en situaciones de negocio latino: restaurante, peluquería, "
            "contractor, realtor, spa, clínica. Devuelve image_url pública."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Descripción EN INGLÉS de la escena. Incluye tipo de negocio, persona, "
                        "acción, ambiente, iluminación. Ejemplo: 'Latina restaurant owner checking "
                        "phone with multiple WhatsApp messages, warm kitchen lighting, candid moment'"
                    ),
                },
                "platform_format": {
                    "type": "string",
                    "enum": ["instagram_post", "instagram_story", "facebook_post", "linkedin_post"],
                },
            },
            "required": ["prompt", "platform_format"],
        },
    },
    {
        "name": "generate_reel_video",
        "description": (
            "Genera un video vertical 9:16 para Instagram Reels via fal.ai Kling 1.6. "
            "Toma la imagen de generate_post_image y le agrega movimiento cinematográfico. "
            "Para audio (música y voiceover), usa después mix_reel_audio. "
            "Devuelve video_url pública (sin audio)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_url": {"type": "string"},
                "motion_prompt": {
                    "type": "string",
                    "description": "Descripción EN INGLÉS del movimiento visual. Sin mencionar audio ni voz.",
                },
                "duration": {"type": "integer", "enum": [5, 10], "default": 5},
                "model": {"type": "string", "enum": ["kling", "luma", "ltx"], "default": "kling"},
            },
            "required": ["image_url", "motion_prompt"],
        },
    },
    {
        "name": "generate_voiceover",
        "description": (
            "Genera un audio de voz en off en español usando PlayAI TTS via fal.ai. "
            "Usa la voz de marca de VoxifyHub (Valentina, español latinoamericano, cálida y profesional). "
            "Úsalo en Reels donde el mensaje necesita ser narrado, no en todos los posts. "
            "Devuelve voiceover_url (mp3)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": (
                        "Texto en español para narrar. Máximo 40 segundos de lectura (~100 palabras). "
                        "Voz cálida y directa. Ejemplo: '¿Cuántos mensajes sin responder tienes ahora mismo? "
                        "VoxifyHub responde por ti, automáticamente, en segundos. Enfócate en tu negocio.'"
                    ),
                },
                "voice": {
                    "type": "string",
                    "description": "Voz opcional. Por defecto usa la voz de marca Valentina (español).",
                },
            },
            "required": ["script"],
        },
    },
    {
        "name": "generate_background_music",
        "description": (
            "Genera música de fondo instrumental con la identidad sonora de VoxifyHub "
            "usando Stable Audio via fal.ai. Ritmo latino-soul profesional y cálido. "
            "Úsala en todos los Reels. Devuelve music_url (mp3)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["brand", "energetic", "emotional", "celebratory"],
                    "description": (
                        "brand = identidad VoxifyHub (guitarra acústica latina, profesional). "
                        "energetic = pop latino rápido. emotional = balada suave. "
                        "celebratory = festivo con bronces."
                    ),
                    "default": "brand",
                },
                "duration": {
                    "type": "integer",
                    "description": "Duración en segundos (default 32).",
                    "default": 32,
                },
            },
            "required": [],
        },
    },
    {
        "name": "mix_reel_audio",
        "description": (
            "Mezcla un video Reel con voiceover y/o música de fondo usando moviepy. "
            "La voz va al 100% de volumen; la música de fondo al 12% (sutil). "
            "Sube el video mezclado a fal.ai CDN y devuelve la nueva video_url con audio. "
            "SIEMPRE llama esto después de generate_reel_video + generate_voiceover + generate_background_music."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "video_url": {"type": "string", "description": "URL del video sin audio (de generate_reel_video)."},
                "voiceover_url": {"type": "string", "description": "URL del audio de voz (de generate_voiceover). Opcional."},
                "music_url": {"type": "string", "description": "URL de la música (de generate_background_music). Opcional."},
            },
            "required": ["video_url"],
        },
    },
]


def execute_media_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "generate_post_image":
        result = generate_image(
            prompt=tool_input["prompt"],
            platform_format=tool_input.get("platform_format", "instagram_post"),
        )
    elif tool_name == "generate_reel_video":
        result = generate_video(
            image_url=tool_input["image_url"],
            motion_prompt=tool_input["motion_prompt"],
            duration=tool_input.get("duration", 5),
            model=tool_input.get("model", DEFAULT_VIDEO_MODEL),
        )
    elif tool_name == "generate_voiceover":
        result = generate_voiceover(
            script=tool_input["script"],
            voice=tool_input.get("voice"),
        )
    elif tool_name == "generate_background_music":
        result = generate_background_music(
            mood=tool_input.get("mood", "brand"),
            duration=tool_input.get("duration", 32),
        )
    elif tool_name == "mix_reel_audio":
        result = mix_video_audio(
            video_url=tool_input["video_url"],
            voiceover_url=tool_input.get("voiceover_url"),
            music_url=tool_input.get("music_url"),
        )
    else:
        result = {"error": f"Herramienta de medios desconocida: {tool_name}"}

    return json.dumps(result, ensure_ascii=False)
