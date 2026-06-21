"""
OpenMontage Bridge — direct tool integration for Voxify Agent.

Full Reel pipeline:
  FLUX Pro image → Kling v3 video → ElevenLabs narration
  → SRT subtitles → Stable Audio music → FFmpeg compose → final MP4

All steps are individually resilient: if voice/music/subtitles fail,
the video still completes without them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

from platform_config import video_config_for

# ── OpenMontage path ──────────────────────────────────────────────────────────

_BRIDGE_DIR = Path(__file__).parent
_OM_PATH    = str(_BRIDGE_DIR / "openmontage")

if _OM_PATH not in sys.path:
    sys.path.insert(0, _OM_PATH)


def _sync_fal_env():
    fal_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")
    fal_api = os.environ.get("FAL_API_KEY")
    if fal_api and not fal_key:
        os.environ["FAL_KEY"] = fal_api
    elif fal_key and not os.environ.get("FAL_API_KEY"):
        os.environ["FAL_API_KEY"] = fal_key

_sync_fal_env()

# ── Storage ───────────────────────────────────────────────────────────────────

def _storage_dir(subdir: str) -> Path:
    base = Path(os.environ.get("DATA_DIR", "/data" if os.path.exists("/data") else str(_BRIDGE_DIR)))
    d = base / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d

# ── Job registry ──────────────────────────────────────────────────────────────

_jobs: dict = {}
_jobs_lock = threading.Lock()


def get_job(job_id: str) -> dict:
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


def _set_job(job_id: str, **kwargs):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(kwargs)

# ── Prompt builders ───────────────────────────────────────────────────────────

def _image_prompt(brand: dict, content_type: str, caption: str = "") -> str:
    industry  = brand.get("industry", "business")
    geography = brand.get("geography", "United States")
    color     = brand.get("color", "#635BFF")

    base_style = (
        "Cinematic vertical 9:16 photograph, editorial quality, "
        "professional lifestyle photography, no text overlays, no logos. "
        f"Location: {geography}. Brand color accent: {color}."
    )
    il = industry.lower()
    if "saas" in il or "tech" in il or "software" in il:
        subject = (
            "Young Latino tech professional working on a sleek laptop in a modern coworking space, "
            "looking inspired and confident, warm ambient lighting, bokeh background."
        )
    elif "café" in il or "coffee" in il or "food" in il:
        subject = (
            "Artisan barista pouring latte art in an upscale coffee shop, "
            "golden hour warm light, shallow depth of field, rich tones."
        )
    elif "fashion" in il or "moda" in il:
        subject = (
            "Elegant woman wearing curated luxury outfit in a high-end boutique, "
            "editorial fashion lighting, sophisticated composition."
        )
    else:
        subject = (
            f"Professional in {industry} industry, confident and engaging, "
            "modern workspace, authentic candid moment."
        )

    hint = f" Scene concept: {caption[:120]}." if caption else ""
    return f"{subject} {base_style} Vertical frame 9:16 for mobile.{hint}"


def _motion_prompt(brand: dict, content_type: str) -> str:
    il = brand.get("industry", "").lower()
    if "saas" in il or "tech" in il:
        return (
            "Slow cinematic push-in, subtle parallax depth, soft focus pull, "
            "dynamic modern energy, professional confidence, viral social media quality. "
            "No text. No logos. Photorealistic. 9:16 vertical."
        )
    if "café" in il or "coffee" in il or "food" in il:
        return (
            "Gentle dolly forward, warm steam rising, slow-motion pour, "
            "golden light flicker, sensory and inviting. "
            "No text. No logos. Photorealistic. 9:16 vertical."
        )
    return (
        "Cinematic slow zoom in, atmospheric depth, elegant premium motion, "
        "social media viral quality. No text. No logos. 9:16 vertical."
    )

# ── Step 1: FLUX Pro image ────────────────────────────────────────────────────

def generate_image(brand: dict, content_type: str = "reel",
                   caption: str = "", custom_prompt: str = "") -> dict:
    try:
        from tools.graphics.flux_image import FluxImage
    except ImportError as e:
        return {"success": False, "error": f"FluxImage import failed: {e}"}

    prompt   = custom_prompt or _image_prompt(brand, content_type, caption)
    img_dir  = _storage_dir("images")
    img_name = f"{brand.get('id','brand')}_{uuid.uuid4().hex[:8]}.png"
    img_path = str(img_dir / img_name)

    result = FluxImage().execute({
        "prompt":               prompt,
        "model":                "flux-pro/v1.1",
        "width":                1080,
        "height":               1920,
        "num_inference_steps":  28,
        "guidance_scale":       3.5,
        "output_path":          img_path,
    })
    if not result.success:
        return {"success": False, "error": result.error}

    return {"success": True, "image_path": img_path,
            "image_url": f"/media/images/{img_name}",
            "prompt": prompt, "cost_usd": result.cost_usd}

# ── Step 2: Kling v3 video ────────────────────────────────────────────────────

def _upload_to_fal(local_path: str) -> str | None:
    fal_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not fal_key:
        return None
    try:
        import fal_client
        url = fal_client.upload_file(local_path)
        return url
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"[bridge] fal_client upload failed: {e}")

    import requests
    try:
        with open(local_path, "rb") as f:
            resp = requests.post(
                "https://fal.run/files",
                headers={"Authorization": f"Key {fal_key}"},
                files={"file": (Path(local_path).name, f, "image/png")},
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("url") or data.get("file_url")
    except Exception as e:
        logger.error(f"[bridge] CDN upload failed: {e}")
        return None


def generate_video(brand: dict, image_path: str, content_type: str = "reel",
                   caption: str = "", duration: int = 5) -> dict:
    try:
        from tools.video.kling_video import KlingVideo
    except ImportError as e:
        return {"success": False, "error": f"KlingVideo import failed: {e}"}

    image_url = _upload_to_fal(image_path)
    if not image_url:
        return {"success": False, "error": "Image CDN upload failed"}

    vid_dir  = _storage_dir("videos")
    vid_name = f"{brand.get('id','brand')}_{uuid.uuid4().hex[:8]}.mp4"
    vid_path = str(vid_dir / vid_name)

    result = KlingVideo().execute({
        "prompt":        _motion_prompt(brand, content_type),
        "operation":     "image_to_video",
        "model_variant": "v3/standard",
        "aspect_ratio":  "9:16",
        "duration":      str(duration),
        "image_url":     image_url,
        "output_path":   vid_path,
    })
    if not result.success:
        return {"success": False, "error": result.error}

    return {"success": True, "video_path": vid_path,
            "video_url": f"/media/videos/{vid_name}",
            "cost_usd": result.cost_usd}

# ── Step 3: Narration script (Claude Haiku) ───────────────────────────────────

def _generate_narration_script(caption: str, duration: int = 5) -> str:
    # Spanish speech rate ~2.2 words/sec for natural, relaxed narration
    max_words = int(duration * 2.2)
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    f"Convierte este texto de Instagram en narración de voz en español latinoamericano "
                    f"para un Reel de {duration} segundos.\n"
                    f"MÁXIMO {max_words} palabras. Velocidad de lectura natural (no demasiado rápido).\n"
                    "Sin hashtags, emojis, signos de exclamación exagerados ni comillas.\n"
                    "Tono cálido, directo y profesional. Primera persona o llamada a la acción concreta.\n"
                    "Español neutro latinoamericano, no castellano de España.\n"
                    "RESPONDE ÚNICAMENTE el texto de narración, sin explicaciones.\n\n"
                    f"Texto: {caption[:400]}"
                ),
            }]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning(f"[bridge] Narration script generation failed: {e}")
        # Fallback: clean the caption
        clean = re.sub(r'#\w+', '', caption)
        clean = re.sub(r'[^\w\s.,¿?!]', '', clean)
        words = clean.split()[:max_words]
        return ' '.join(words)

# ── Step 4: ElevenLabs voice narration ───────────────────────────────────────

def generate_elevenlabs_voice(script: str, brand_id: str = "") -> dict:
    """
    Generate Spanish narration using ElevenLabs eleven_multilingual_v2.
    Requires ELEVENLABS_API_KEY env var.
    Voice can be customized via ELEVENLABS_VOICE_ID (default: Rachel).
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return {"success": False, "error": "ELEVENLABS_API_KEY not set"}
    if not script or not script.strip():
        return {"success": False, "error": "Empty narration script"}

    # Bella (hpp4J3VqNfWAUOO0d1Us) — Professional, Bright, Warm — ideal for Spanish LatAm brand narration
    # eleven_multilingual_v2 model makes any voice speak natural Spanish
    # User can override with ELEVENLABS_VOICE_ID env var
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "hpp4J3VqNfWAUOO0d1Us")

    import requests
    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key":   api_key,
                "Content-Type": "application/json",
                "Accept":       "audio/mpeg",
            },
            json={
                "text":     script,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability":        0.5,
                    "similarity_boost": 0.8,
                    "style":            0.3,
                    "use_speaker_boost": True,
                },
            },
            timeout=45,
        )
        resp.raise_for_status()
    except Exception as e:
        return {"success": False, "error": f"ElevenLabs API error: {e}"}

    audio_dir  = _storage_dir("audio")
    audio_name = f"{brand_id}_{uuid.uuid4().hex[:8]}_narration.mp3"
    audio_path = str(audio_dir / audio_name)

    with open(audio_path, "wb") as f:
        f.write(resp.content)

    logger.info(f"[bridge] Narration generated → {audio_path} ({len(script)} chars)")
    return {"success": True, "audio_path": audio_path, "script": script,
            "audio_url": f"/media/audio/{audio_name}"}

# ── Step 5: Subtitle SRT ──────────────────────────────────────────────────────

def _audio_duration_ffprobe(audio_path: str) -> float:
    """Get MP3 duration via ffprobe. Returns seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a", audio_path],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            return float(streams[0].get("duration", 0))
    except Exception as e:
        logger.warning(f"[bridge] ffprobe duration failed: {e}")
    # Fallback estimate: ~130 words/minute
    return 0.0


def generate_subtitles_srt(script: str, video_duration: float,
                            audio_path: str | None = None) -> str | None:
    """
    Generate a .srt file from the narration script.
    Timing is derived from actual audio duration (ffprobe) or estimated.
    Returns path to .srt file, or None on failure.
    """
    if not script:
        return None

    audio_dur = 0.0
    if audio_path and os.path.exists(audio_path):
        audio_dur = _audio_duration_ffprobe(audio_path)

    # Use audio duration if available; otherwise estimate from word count
    if audio_dur < 0.5:
        word_count = len(script.split())
        audio_dur  = word_count / 2.5  # conservative 2.5 words/sec for Spanish

    # Clamp to video duration
    total_dur = min(audio_dur, video_duration)

    words      = script.split()
    chunk_size = 4  # words per subtitle card — feels natural on mobile
    chunks     = [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]

    def srt_ts(secs: float) -> str:
        h  = int(secs // 3600)
        m  = int((secs % 3600) // 60)
        s  = secs % 60
        ms = int((s - int(s)) * 1000)
        return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"

    lines: list[str] = []
    t     = 0.0
    step  = total_dur / len(chunks) if chunks else total_dur

    for i, chunk in enumerate(chunks):
        end_t = min(t + step, total_dur - 0.05)
        lines.append(str(i + 1))
        lines.append(f"{srt_ts(t)} --> {srt_ts(end_t)}")
        lines.append(" ".join(chunk))
        lines.append("")
        t = end_t + 0.05
        if t >= total_dur:
            break

    tmp_dir  = _storage_dir("tmp")
    srt_path = str(tmp_dir / f"{uuid.uuid4().hex[:8]}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return srt_path

# ── Step 6: Background music ──────────────────────────────────────────────────

def _get_background_music(brand: dict, duration: int = 10) -> str | None:
    """
    Resolve background music track. Priority:
    1. openmontage/music_library/ (user drops files here)
    2. Already cached for this brand in /data/audio/
    3. Generate via fal.ai Stable Audio
    """
    # 1. music_library/ (user-provided royalty-free tracks)
    music_lib = _BRIDGE_DIR / "openmontage" / "music_library"
    if music_lib.exists():
        for ext in ("*.mp3", "*.wav", "*.m4a"):
            tracks = list(music_lib.glob(ext))
            if tracks:
                logger.info(f"[bridge] Using music_library track: {tracks[0].name}")
                return str(tracks[0])

    # 2. Cached brand music
    audio_dir = _storage_dir("audio")
    brand_id  = brand.get("id", "brand")
    cached    = sorted(audio_dir.glob(f"music_{brand_id}*.mp3"))
    if cached:
        logger.info(f"[bridge] Using cached music: {cached[-1].name}")
        return str(cached[-1])

    # 3. Generate via fal.ai Stable Audio
    fal_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not fal_key:
        return None

    il = brand.get("industry", "").lower()
    if "café" in il or "coffee" in il or "food" in il:
        prompt = (
            "warm Latin acoustic guitar ambient, cozy coffee shop atmosphere, "
            "light bossa nova percussion, 35 seconds, no lyrics, fade in and out"
        )
    elif "fashion" in il or "moda" in il:
        prompt = (
            "elegant ambient electronic, luxury fashion show mood, "
            "cinematic strings, 35 seconds, no lyrics, fade in and out"
        )
    else:
        prompt = (
            "upbeat modern ambient, professional startup energy, "
            "light electronic beats, warm synths, 35 seconds, no lyrics, fade in and out"
        )

    import requests
    try:
        logger.info("[bridge] Generating background music via Stable Audio...")
        resp = requests.post(
            "https://fal.run/fal-ai/stable-audio",
            headers={"Authorization": f"Key {fal_key}",
                     "Content-Type": "application/json"},
            json={"prompt": prompt, "seconds_total": 35, "steps": 50},
            timeout=120,
        )
        resp.raise_for_status()
        data      = resp.json()
        music_url = (data.get("audio_file") or {}).get("url") or data.get("audio_url")
        if not music_url:
            return None

        music_resp = requests.get(music_url, timeout=60)
        music_resp.raise_for_status()
        music_name = f"music_{brand_id}_{uuid.uuid4().hex[:6]}.mp3"
        music_path = str(audio_dir / music_name)
        with open(music_path, "wb") as f:
            f.write(music_resp.content)

        logger.info(f"[bridge] Music generated → {music_path}")
        return music_path
    except Exception as e:
        logger.warning(f"[bridge] Music generation failed: {e}")
        return None

# ── Step 7: FFmpeg compose ────────────────────────────────────────────────────

def _ffmpeg_compose(
    video_path: str,
    narration_path: str | None,
    music_path: str | None,
    srt_path: str | None,
    output_path: str,
) -> dict:
    """
    Compose final Reel with FFmpeg:
      - Narration at 100% volume
      - Background music at 12% volume
      - Subtitles burned in (white + black outline, bottom center)
    Falls back gracefully if subtitles filter is unavailable.
    """
    # -stream_loop -1 loops the video clip infinitely so -shortest can use
    # the narration duration instead of the (shorter) Kling clip duration.
    inputs        : list[str] = ["-stream_loop", "-1", "-i", video_path]
    filter_parts  : list[str] = []
    audio_labels  : list[str] = []
    audio_idx     = 1

    if narration_path and os.path.exists(narration_path):
        inputs += ["-i", narration_path]
        filter_parts.append(f"[{audio_idx}:a]volume=1.0[vo]")
        audio_labels.append("[vo]")
        audio_idx += 1

    if music_path and os.path.exists(music_path):
        inputs += ["-i", music_path]
        filter_parts.append(f"[{audio_idx}:a]volume=0.12[bg]")
        audio_labels.append("[bg]")
        audio_idx += 1

    # Build audio mix
    audio_map: str | None = None
    if len(audio_labels) == 2:
        filter_parts.append(
            f"{audio_labels[0]}{audio_labels[1]}"
            "amix=inputs=2:duration=first:dropout_transition=1[audio]"
        )
        audio_map = "[audio]"
    elif len(audio_labels) == 1:
        # Rename single stream
        filter_parts.append(f"{audio_labels[0]}acopy[audio]")
        audio_map = "[audio]"

    # Subtitle filter string (libass via subtitles= filter)
    sub_style = (
        "FontSize=22,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,Bold=1,Outline=2,"
        "Alignment=2,MarginV=80"
    )

    def _build_cmd(with_subs: bool) -> list[str]:
        cmd = ["ffmpeg", "-y"] + inputs
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += ["-map", "0:v"]
        if audio_map:
            cmd += ["-map", audio_map]
        if with_subs and srt_path and os.path.exists(srt_path):
            # Escape path for FFmpeg filter syntax
            safe_srt = srt_path.replace("\\", "/")
            if ":" in safe_srt:
                safe_srt = safe_srt.replace(":", "\\:")
            cmd += ["-vf", f"subtitles={safe_srt}:force_style='{sub_style}'"]
        cmd += ["-c:v", "libx264", "-c:a", "aac", "-crf", "22", "-shortest", output_path]
        return cmd

    def _run(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    # Try with subtitles first
    result = _run(_build_cmd(with_subs=True))
    if result.returncode != 0 and srt_path:
        logger.warning("[bridge] Subtitles filter failed, retrying without subs")
        result = _run(_build_cmd(with_subs=False))

    if result.returncode != 0:
        return {"success": False,
                "error": f"FFmpeg failed: {result.stderr[-600:]}"}

    logger.info(f"[bridge] FFmpeg compose done → {output_path}")
    return {"success": True, "output_path": output_path}

# ── Full pipeline job ─────────────────────────────────────────────────────────

def _generate_multi_clip(brand: dict, caption: str, content_type: str,
                          cfg: dict, custom_prompt: str) -> tuple[str | None, float]:
    """
    Generate N Kling clips from N different FLUX images, stitch with FFmpeg.
    Returns (stitched_video_path, total_cost_usd).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    n_clips      = cfg["clips"]
    clip_dur     = cfg["clip_duration"]
    total_cost   = 0.0

    # Scene variation prompts so each clip looks different
    scene_hints = [
        custom_prompt or "",
        "close-up detail shot, shallow depth of field",
        "wide establishing shot, environmental context",
        "medium shot, action moment, dynamic energy",
        "overhead bird's eye view, geometric composition",
        "golden hour lighting, warm cinematic glow",
    ]

    def _gen_one(i: int) -> tuple[int, dict, dict]:
        hint     = scene_hints[i % len(scene_hints)]
        combined = f"{custom_prompt} {hint}".strip() if (i > 0 or custom_prompt) else ""
        img = generate_image(brand, content_type, caption, combined)
        if not img.get("success"):
            return i, img, {}
        vid = generate_video(brand, img["image_path"], content_type, caption,
                             int(clip_dur))
        return i, img, vid

    clips_ordered: list[str] = []
    with ThreadPoolExecutor(max_workers=min(n_clips, 3)) as ex:
        futures = {ex.submit(_gen_one, i): i for i in range(n_clips)}
        results: dict[int, tuple[dict, dict]] = {}
        for fut in as_completed(futures):
            i, img, vid = fut.result()
            results[i] = (img, vid)
            total_cost += (img.get("cost_usd") or 0) + (vid.get("cost_usd") or 0)

    # Keep original order
    for i in range(n_clips):
        img, vid = results.get(i, ({}, {}))
        if vid.get("success"):
            clips_ordered.append(vid["video_path"])
        elif img.get("success"):
            logger.warning(f"[bridge] Clip {i} video failed, skipping")

    if not clips_ordered:
        return None, total_cost

    if len(clips_ordered) == 1:
        return clips_ordered[0], total_cost

    # Stitch clips with FFmpeg concat
    tmp_dir   = _storage_dir("tmp")
    list_file = str(tmp_dir / f"concat_{uuid.uuid4().hex[:8]}.txt")
    with open(list_file, "w") as f:
        for p in clips_ordered:
            f.write(f"file '{p}'\n")

    vid_dir     = _storage_dir("videos")
    stitched    = str(vid_dir / f"{brand.get('id','brand')}_{uuid.uuid4().hex[:8]}_stitched.mp4")
    stitch_cmd  = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                   "-i", list_file, "-c:v", "libx264", "-c:a", "aac", stitched]
    r = subprocess.run(stitch_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        logger.error(f"[bridge] Stitch failed: {r.stderr[-300:]}")
        return clips_ordered[0], total_cost  # fallback to first clip

    logger.info(f"[bridge] {len(clips_ordered)} clips stitched → {stitched}")
    return stitched, total_cost


def _run_reel_job(job_id: str, brand: dict, post_id: int | None,
                  caption: str, content_type: str, platform: str,
                  custom_prompt: str):
    """
    Full Reel/TikTok/Story pipeline (background thread).

    Format is decided by platform_config based on content_type + platform:
      story   → 6 sec,  1 clip
      reel    → 15 sec, 3 clips × 5s
      tiktok  → 28 sec, 3 clips × 10s

    Steps:
      1. platform_config   → determine duration, clips, aspect ratio
      2. Multi-clip FLUX+Kling (parallel)
      3. FFmpeg stitch clips
      4. Claude Haiku narration script
      5. ElevenLabs voice
      6. SRT subtitles
      7. Stable Audio background music
      8. FFmpeg compose → final MP4
      9. DB update
    Steps 4-7 are optional — failure skips gracefully.
    """
    started    = time.time()
    brand_id   = brand.get("id", "brand")
    total_cost = 0.0

    # ── Step 1: Format from strategy ──────────────────────────────────────
    cfg = video_config_for(content_type, platform)
    _set_job(job_id,
             format_cfg=cfg,
             platform=platform,
             content_type=content_type)
    logger.info(
        f"[bridge] Job {job_id} | {platform}/{content_type} → "
        f"{cfg['duration_target']}s, {cfg['clips']}×{cfg['clip_duration']}s clips"
    )

    # ── Step 2+3: Multi-clip generation ───────────────────────────────────
    _set_job(job_id, status="generating_clips",
             clips_total=cfg["clips"])

    video_path, clip_cost = _generate_multi_clip(
        brand, caption, content_type, cfg, custom_prompt
    )
    total_cost += clip_cost

    if not video_path:
        _set_job(job_id, status="failed", error="All clip generations failed")
        return

    first_clip_url = f"/media/videos/{Path(video_path).name}"
    _set_job(job_id, raw_video_url=first_clip_url)

    duration_target = cfg["duration_target"]

    # ── Step 4: Narration script ───────────────────────────────────────────
    _set_job(job_id, status="generating_narration")
    narration_script = ""
    if caption:
        narration_script = _generate_narration_script(caption, duration_target)
        logger.info(f"[bridge] Narration: {narration_script!r}")

    # ── Step 5: ElevenLabs voice ───────────────────────────────────────────
    narration_path: str | None = None
    if narration_script and os.environ.get("ELEVENLABS_API_KEY"):
        voice = generate_elevenlabs_voice(narration_script, brand_id)
        if voice.get("success"):
            narration_path = voice["audio_path"]
            _set_job(job_id,
                     narration_url=voice.get("audio_url"),
                     narration_script=narration_script)
        else:
            logger.warning(f"[bridge] ElevenLabs skipped: {voice.get('error')}")

    # ── Step 6: SRT subtitles ──────────────────────────────────────────────
    srt_path: str | None = None
    if narration_script:
        srt_path = generate_subtitles_srt(
            narration_script, duration_target, narration_path
        )

    # ── Step 7: Background music ───────────────────────────────────────────
    _set_job(job_id, status="generating_music")
    music_path = _get_background_music(brand, duration_target)

    # ── Step 8: FFmpeg compose ─────────────────────────────────────────────
    _set_job(job_id, status="composing")
    has_extras = narration_path or music_path or srt_path

    if has_extras:
        vid_dir    = _storage_dir("videos")
        final_name = f"{brand_id}_{uuid.uuid4().hex[:8]}_final.mp4"
        final_path = str(vid_dir / final_name)
        compose    = _ffmpeg_compose(video_path, narration_path, music_path,
                                     srt_path, final_path)
        if compose.get("success"):
            final_video_url = f"/media/videos/{final_name}"
        else:
            logger.warning(f"[bridge] Compose failed: {compose.get('error')} — raw video")
            final_video_url = first_clip_url
    else:
        final_video_url = first_clip_url

    # ── Step 9: DB update ──────────────────────────────────────────────────
    if post_id:
        try:
            import database as db
            db.update_post(post_id, video_url=final_video_url)
        except Exception as e:
            logger.warning(f"[bridge] DB update failed: {e}")

    elapsed = round(time.time() - started, 1)
    _set_job(job_id,
             status="completed",
             video_url=final_video_url,
             has_voice=bool(narration_path),
             has_subtitles=bool(srt_path),
             has_music=bool(music_path),
             cost_usd=round(total_cost, 4),
             duration_s=elapsed,
             clips_generated=cfg["clips"])

    logger.info(
        f"[bridge] Job {job_id} done {elapsed}s | {cfg['clips']} clips | "
        f"voice={bool(narration_path)} subs={bool(srt_path)} "
        f"music={bool(music_path)} cost=${total_cost:.3f}"
    )


def start_reel_job(brand: dict, post_id: int | None = None,
                   caption: str = "", content_type: str = "reel",
                   platform: str = "instagram", custom_prompt: str = "") -> str:
    """
    Launch a background Reel/TikTok/Story generation job. Returns job_id.

    platform + content_type → platform_config → duration, clips, aspect_ratio
    """
    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", brand_id=brand.get("id"),
             post_id=post_id, platform=platform, content_type=content_type)

    t = threading.Thread(
        target=_run_reel_job,
        args=(job_id, brand, post_id, caption, content_type, platform, custom_prompt),
        daemon=True,
    )
    t.start()
    logger.info(
        f"[bridge] Job {job_id} started | brand={brand.get('id')} "
        f"platform={platform} type={content_type}"
    )
    return job_id
