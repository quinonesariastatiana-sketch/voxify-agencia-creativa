"""
Voxify Agencia Creativa — Flask server.
Multi-brand content management for social media.
"""
import os
import logging
from datetime import datetime

from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s'
)
logger = logging.getLogger(__name__)

import database as db
import agent
import publisher
import scheduler as sched
import meta_insights

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'voxify-secret-2026')

# ── Init ─────────────────────────────────────────────────────────────────────
db.init_db()
sched.start()

# ── Health ────────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    brands         = db.get_all_brands()
    pending_posts  = db.get_posts(status='pending', limit=20)
    approved_posts = db.get_posts(status='approved', limit=10)
    posted_today   = [p for p in db.get_posts(status='posted', limit=50)
                      if p.get('posted_at', '').startswith(datetime.utcnow().strftime('%Y-%m-%d'))]
    return render_template('index.html',
                           brands=brands,
                           pending_posts=pending_posts,
                           approved_posts=approved_posts,
                           posted_today=posted_today,
                           scheduler=sched.status())


@app.route('/brands')
def brands_page():
    brands = db.get_all_brands()
    return render_template('brands.html', brands=brands)


@app.route('/content')
def content_page():
    brands = db.get_all_brands()
    posts  = db.get_posts(limit=100)
    return render_template('content.html', brands=brands, posts=posts)


# ── API: Brands ───────────────────────────────────────────────────────────────

@app.route('/api/brands', methods=['GET'])
def api_list_brands():
    return jsonify(db.get_all_brands())


@app.route('/api/brands', methods=['POST'])
def api_create_brand():
    data     = request.get_json(force=True) or {}
    brand_id = data.get('brand_id', '').strip().lower().replace(' ', '_')
    name     = data.get('name', '').strip()

    if not brand_id or not name:
        return jsonify({'success': False, 'error': 'brand_id and name are required'}), 400
    if db.get_brand(brand_id):
        return jsonify({'success': False, 'error': f'Brand "{brand_id}" already exists'}), 409

    brand = db.create_brand(
        brand_id, name,
        tagline              = data.get('tagline', ''),
        description          = data.get('description', ''),
        industry             = data.get('industry', ''),
        geography            = data.get('geography', 'United States'),
        website_url          = data.get('website_url', ''),
        instagram_handle     = data.get('instagram_handle', ''),
        color                = data.get('color', '#635BFF'),
        meta_access_token    = data.get('meta_access_token', ''),
        instagram_account_id = data.get('instagram_account_id', ''),
        facebook_page_id     = data.get('facebook_page_id', ''),
        mission              = data.get('mission', ''),
    )
    return jsonify({'success': True, 'id': brand_id, 'brand': brand}), 201


@app.route('/api/brands/<brand_id>', methods=['GET'])
def api_get_brand(brand_id):
    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(brand)


@app.route('/api/brands/<brand_id>', methods=['PUT', 'PATCH'])
def api_update_brand(brand_id):
    data  = request.get_json(force=True) or {}
    brand = db.safe_patch_brand(brand_id, data)
    if not brand:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True, 'brand': brand})


@app.route('/api/brands/<brand_id>', methods=['DELETE'])
def api_delete_brand(brand_id):
    db.delete_brand(brand_id)
    return jsonify({'success': True})


# ── API: Research ─────────────────────────────────────────────────────────────

@app.route('/api/research/<brand_id>', methods=['POST'])
def api_research(brand_id):
    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    data = request.get_json(force=True) or {}
    modules = data.pop('modules', None)
    for k, v in data.items():
        if v and k not in ('id',):
            brand[k] = v

    result = agent.research_brand(brand, modules=modules)

    if result.get('research'):
        updated = db.safe_patch_brand(brand_id, result['research'])
        result['brand'] = updated

    return jsonify(result)


@app.route('/api/insights/<brand_id>', methods=['GET'])
def api_insights(brand_id):
    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'error': 'Not found'}), 404
    baseline = meta_insights.brand_baseline(brand)
    return jsonify({'success': True, 'baseline': baseline})


# ── API: Content Generation ───────────────────────────────────────────────────

@app.route('/api/generate/<brand_id>', methods=['POST'])
def api_generate(brand_id):
    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    data     = request.get_json(force=True) or {}
    platform = data.get('platform', 'instagram')
    topic    = data.get('topic', '')
    save     = data.get('save', True)

    post_data = agent.generate_post(brand, platform, topic)
    if not post_data.get('caption'):
        return jsonify({'success': False, 'error': 'Generation failed'}), 500

    post_id = None
    if save:
        post_id = db.create_post(brand_id, post_data['caption'], platform=platform)

    return jsonify({'success': True, 'post': post_data, 'post_id': post_id})


# ── API: Posts ────────────────────────────────────────────────────────────────

@app.route('/api/posts', methods=['GET'])
def api_list_posts():
    brand_id = request.args.get('brand_id')
    status   = request.args.get('status')
    limit    = int(request.args.get('limit', 100))
    return jsonify(db.get_posts(brand_id, status, limit))


@app.route('/api/posts/<int:post_id>/approve', methods=['POST'])
def api_approve_post(post_id):
    db.update_post(post_id, status='approved')
    return jsonify({'success': True})


@app.route('/api/posts/<int:post_id>/reject', methods=['POST'])
def api_reject_post(post_id):
    import json as _json
    data = request.get_json(force=True) or {}
    what = data.get('what', '')   # 'copy' | 'image' | 'both'
    note = data.get('note', '').strip()
    updates = {'status': 'rejected'}
    if what or note:
        post = db.get_post(post_id)
        extra = {}
        try:
            extra = _json.loads(post.get('extra_json') or '{}')
        except Exception:
            pass
        if what:
            extra['feedback_type'] = what
        if note:
            extra['feedback_note'] = note
        updates['extra_json'] = _json.dumps(extra)
    db.update_post(post_id, **updates)
    return jsonify({'success': True})


def _do_publish_post(post_id: int, post: dict, brand: dict):
    """Publish one post in a background thread — updates DB when done."""
    try:
        result = publisher.publish_post(brand, post)
        if result['success']:
            meta_id = ','.join(result['ids'].values())
            db.update_post(post_id, status='posted', post_id_meta=meta_id,
                           posted_at=datetime.utcnow().isoformat(), error_msg='')
            logger.info(f"[publish] post {post_id} → posted ({meta_id})")
        else:
            err = '; '.join(result['errors'])
            db.update_post(post_id, status='failed', error_msg=err)
            logger.error(f"[publish] post {post_id} failed: {err}")
    except Exception as e:
        db.update_post(post_id, status='failed', error_msg=str(e))
        logger.error(f"[publish] post {post_id} exception: {e}")


@app.route('/api/posts/<int:post_id>/publish', methods=['POST'])
def api_publish_post(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    brand = db.get_brand(post['brand_id'])
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    # Mark as publishing immediately so the UI stops showing the button
    db.update_post(post_id, status='publishing')

    import threading
    t = threading.Thread(target=_do_publish_post, args=(post_id, post, brand), daemon=True)
    t.start()
    return jsonify({'success': True, 'queued': True})


@app.route('/api/posts/<int:post_id>/status', methods=['GET'])
def api_post_status(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({'success': False}), 404
    return jsonify({'status': post.get('status'), 'error_msg': post.get('error_msg', '')})


def _do_generate_post_media(post_id: int, post: dict, brand: dict, direction: str = ''):
    """Core media generation logic for one post. Safe to call in a background thread."""
    import openmontage_bridge as bridge

    content_type = post.get('content_type', 'post')
    caption      = post.get('caption', '')
    if direction:
        caption = f"{caption}\n[Visual direction: {direction}]"
    try:
        if content_type in ('reel', 'story'):
            # Use full bridge pipeline for video content
            platform = post.get('platform', 'instagram')
            job_id   = bridge.start_reel_job(brand, post_id, caption,
                                             content_type, platform)
            logger.info(f"[media] video job {job_id} queued → post {post_id}")
            return {'success': True, 'job_id': job_id}
        else:
            # Posts and carousels: FLUX Pro image via bridge
            result = bridge.generate_image(brand, content_type, caption)
            if result.get('success'):
                db.update_post(post_id, image_url=result['image_url'])
                logger.info(f"[media] image OK → post {post_id} {result['image_url'][:60]}")
                return {'success': True, 'image_url': result['image_url']}
            logger.error(f"[media] image failed post {post_id}: {result.get('error')}")
            return {'success': False, 'error': result.get('error', 'Sin URL')}
    except Exception as e:
        logger.error(f"[media] post {post_id}: {e}")
        return {'success': False, 'error': str(e)}


def _generate_media_background(post_ids: list, brand: dict):
    """
    Background thread: generate media for multiple posts in parallel.
    Uses one batch Haiku call for visual prompts, then fal.ai in a thread pool.
    """
    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return
    from concurrent.futures import ThreadPoolExecutor, as_completed

    posts = [db.get_post(pid) for pid in post_ids]
    posts = [(pid, p) for pid, p in zip(post_ids, posts) if p]
    if not posts:
        return

    # One Haiku call for all visual prompts (reads captions, returns unique scenes)
    grid_items = [{'caption': p.get('caption', ''), 'content_type': p.get('content_type', 'post')}
                  for _, p in posts]
    visual_scenes: dict = {}
    try:
        visual_scenes = agent._batch_visual_prompts(grid_items, brand)
    except Exception as e:
        logger.warning(f"[media-bg] batch visual prompts: {e}")

    geo = brand.get('geography', 'United States')

    def _gen(idx, post_id, post):
        content_type = post.get('content_type', 'post')
        scene = visual_scenes.get(idx) or agent._scene_base(brand)
        try:
            if content_type in ('reel', 'story'):
                from tools.media_generator import generate_video_from_text
                motion = ("smooth vertical pan, warm golden hour lighting"
                          if content_type == 'story'
                          else "dynamic camera movement, energetic viral social media")
                result = generate_video_from_text(
                    f"{scene}, {geo}, {motion}, 9:16 vertical, cinematic, no text",
                    aspect_ratio="9:16", duration=5
                )
                if result.get('video_url'):
                    db.update_post(post_id, video_url=result['video_url'])
                    logger.info(f"[media-bg] video OK → post {post_id}")
            else:
                from tools.media_generator import generate_image
                framing = ("editorial clean composition, professional"
                           if content_type == 'carousel'
                           else "editorial lifestyle photo, magazine quality")
                fmt = agent._image_format_for_item({'content_type': content_type,
                                                    'platform': post.get('platform', 'instagram')})
                result = generate_image(f"{scene}, {geo}, {framing}", fmt)
                if result.get('image_url'):
                    db.update_post(post_id, image_url=result['image_url'])
                    logger.info(f"[media-bg] image OK → post {post_id}")
        except Exception as e:
            logger.error(f"[media-bg] post {post_id}: {e}")

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_gen, i, pid, p): pid for i, (pid, p) in enumerate(posts)}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception:
                pass

    logger.info(f"[media-bg] done — {len(posts)} posts processed")


@app.route('/api/posts/<int:post_id>/generate-media', methods=['POST'])
def api_generate_post_media(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    brand = db.get_brand(post['brand_id'])
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return jsonify({'success': False, 'error': 'FAL_API_KEY no configurado'}), 400

    req_data = request.get_json(force=True) or {}
    direction = req_data.get('direction', '').strip()

    # Always run in background — response is immediate, Railway does the work
    import threading
    t = threading.Thread(
        target=_do_generate_post_media,
        args=(post_id, post, brand, direction),
        daemon=True,
    )
    t.start()
    return jsonify({'success': True, 'queued': True})


@app.route('/api/posts/<int:post_id>', methods=['PATCH'])
def api_update_post(post_id):
    data = request.get_json(force=True) or {}
    updates = {}
    if data.get('caption'):
        updates['caption'] = data['caption']
    if data.get('status') in ('pending', 'approved', 'rejected'):
        updates['status'] = data['status']
        updates['error_msg'] = ''        # clear error on status reset
    if not updates:
        return jsonify({'success': False, 'error': 'Nada que actualizar'}), 400
    db.update_post(post_id, **updates)
    return jsonify({'success': True})


@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def api_delete_post(post_id):
    db.update_post(post_id, status='deleted')
    return jsonify({'success': True})


# ── API: Scheduler ────────────────────────────────────────────────────────────

@app.route('/api/scheduler/status', methods=['GET'])
def api_scheduler_status():
    return jsonify(sched.status())


@app.route('/api/scheduler/trigger', methods=['POST'])
def api_scheduler_trigger():
    sched.trigger_now()
    return jsonify({'success': True, 'message': 'Publisher triggered'})


# ── API: Seed ─────────────────────────────────────────────────────────────────

@app.route('/api/seed', methods=['POST'])
def api_seed():
    import traceback as _tb
    results = {}
    try:
        vox_token = os.environ.get('META_ACCESS_TOKEN_VOXIFY', '')
        vox_ig    = os.environ.get('INSTAGRAM_BUSINESS_ACCOUNT_ID_VOXIFY', '17841478805587018')
        vox_fb    = os.environ.get('FACEBOOK_PAGE_ID_VOXIFY', '860119253859919')

        if not db.get_brand('voxifyhub'):
            db.create_brand('voxifyhub', 'VoxifyHub',
                            tagline              = 'Answer smarter. Grow faster.',
                            description          = 'Plataforma de gestión de redes sociales con IA para agencias creativas y marcas multi-canal.',
                            industry             = 'SaaS / Marketing Technology',
                            geography            = 'United States',
                            website_url          = 'https://www.voxifyhub.com',
                            instagram_handle     = '@voxifyhub',
                            color                = '#635BFF',
                            meta_access_token    = vox_token,
                            instagram_account_id = vox_ig,
                            facebook_page_id     = vox_fb)
            results['voxifyhub'] = 'created'
        else:
            results['voxifyhub'] = 'already_exists'

        aroma_token = os.environ.get('META_ACCESS_TOKEN_AROMA',
                       os.environ.get('META_ACCESS_TOKEN', ''))
        aroma_ig    = os.environ.get('INSTAGRAM_BUSINESS_ACCOUNT_ID_AROMA', '17841430977157582')
        aroma_fb    = os.environ.get('FACEBOOK_PAGE_ID_AROMA', '1070241312848461')

        if not db.get_brand('aromabeans'):
            db.create_brand('aromabeans', 'Aroma Beans',
                            tagline              = 'El café colombiano que conquista Miami.',
                            description          = 'Café colombiano de especialidad para la comunidad latina en Miami y el sur de Florida.',
                            industry             = 'Café / Alimentos y Bebidas',
                            geography            = 'Miami, Florida, USA',
                            instagram_handle     = '@aromabeanscol',
                            color                = '#8B4513',
                            meta_access_token    = aroma_token,
                            instagram_account_id = aroma_ig,
                            facebook_page_id     = aroma_fb)
            results['aromabeans'] = 'created'
        else:
            results['aromabeans'] = 'already_exists'

        vox = db.get_brand('voxifyhub')
        if vox:
            research = agent.research_brand(vox)
            if research.get('research'):
                db.safe_patch_brand('voxifyhub', research['research'])
            results['voxifyhub_research'] = {
                'success':       research.get('success'),
                'fields_filled': research.get('fields_filled', 0),
                'errors':        research.get('errors', []),
            }

        post_id = db.create_post(
            'voxifyhub',
            "🚀 VoxifyHub transforma la gestión de contenido para agencias creativas.\n\n"
            "Con IA avanzada, publica más contenido de calidad en menos tiempo. "
            "¿Lista para escalar tu presencia digital?\n\n"
            "#VoxifyHub #MarketingDigital #AgenciaCreativa #IA #RedesSociales",
            platform='instagram',
        )
        results['test_post_id'] = post_id
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e),
                        'trace': _tb.format_exc()[-2000:]}), 500


# ── API: Content Generate (genera + guarda 7 posts en DB) ────────────────────

@app.route('/api/content/generate/<brand_id>', methods=['POST'])
def api_content_generate(brand_id):
    import json as _json
    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    data = request.get_json(force=True) or {}
    config = {
        'weeks':          int(data.get('weeks', 1)),
        'post_count':     int(data.get('post_count', 3)),
        'reel_count':     int(data.get('reel_count', 2)),
        'story_count':    int(data.get('story_count', 1)),
        'carousel_count': int(data.get('carousel_count', 1)),
        'platforms':      data.get('platforms', ['instagram']),
        'topic':          data.get('topic', ''),
    }

    result = agent.generate_grid(brand, **config)
    grid   = result.get('grid', [])
    if not grid:
        return jsonify({'success': False, 'error': 'Grid generation failed', 'detail': result}), 500

    saved_ids = []
    for item in grid:
        extra = {k: v for k, v in item.items()
                 if k not in ('caption', 'image_url', 'video_url', 'platform',
                              'content_type', 'suggested_day', 'suggested_time',
                              'hashtags', 'scheduled_for')}
        post_id = db.create_post(
            brand_id,
            item.get('caption', ''),
            image_url      = item.get('image_url', ''),
            video_url      = item.get('video_url', ''),
            platform       = item.get('platform', 'instagram'),
            scheduled_for  = item.get('scheduled_for'),
            content_type   = item.get('content_type', 'post'),
            suggested_day  = item.get('day', ''),
            suggested_time = item.get('time', ''),
            extra_json     = _json.dumps(extra),
        )
        saved_ids.append(post_id)

    posts = [db.get_post(pid) for pid in saved_ids if pid]
    pending = [p for p in posts if p and p.get('status') == 'pending']

    return jsonify({
        'success':   True,
        'generated': len(grid),
        'saved':     len(saved_ids),
        'pending':   len(pending),
        'post_ids':  saved_ids,
    })


# ── API: Content Grid ─────────────────────────────────────────────────────────

@app.route('/api/generate-grid/<brand_id>', methods=['POST'])
def api_generate_grid(brand_id):
    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    data     = request.get_json(force=True) or {}
    weeks    = int(data.get('weeks', 1))
    platforms = data.get('platforms', ['instagram'])
    config   = {
        'weeks':          weeks,
        'post_count':     int(data.get('post_count', 3)),
        'reel_count':     int(data.get('reel_count', 2)),
        'story_count':    int(data.get('story_count', 5)),
        'carousel_count': int(data.get('carousel_count', 1)),
        'platforms':      platforms,
        'topic':          data.get('topic', ''),
    }

    result = agent.generate_grid(brand, **config)

    if data.get('save') and result.get('grid'):
        import json as _json
        saved_ids = []
        for item in result['grid']:
            extra = {k: v for k, v in item.items()
                     if k not in ('caption', 'image_url', 'video_url', 'platform',
                                  'content_type', 'suggested_day', 'suggested_time',
                                  'hashtags', 'scheduled_for')}
            post_id = db.create_post(
                brand_id,
                item.get('caption', ''),
                image_url      = item.get('image_url', ''),
                video_url      = item.get('video_url', ''),
                platform       = item.get('platform', 'instagram'),
                scheduled_for  = item.get('scheduled_for'),
                content_type   = item.get('content_type', 'post'),
                suggested_day  = item.get('day', ''),
                suggested_time = item.get('time', ''),
                extra_json     = _json.dumps(extra),
            )
            saved_ids.append(post_id)
        result['saved_ids'] = saved_ids

    return jsonify(result)


@app.route('/api/posts/bulk', methods=['POST'])
def api_bulk_save_posts():
    import json as _json
    data     = request.get_json(force=True) or {}
    brand_id = data.get('brand_id', '')
    items    = data.get('items', [])

    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    saved_ids = []
    for item in items:
        extra = {k: v for k, v in item.items()
                 if k not in ('caption', 'image_url', 'video_url', 'platform',
                              'content_type', 'day', 'time', 'hashtags', 'scheduled_for')}
        post_id = db.create_post(
            brand_id,
            item.get('caption', ''),
            image_url      = item.get('image_url', ''),
            video_url      = item.get('video_url', ''),
            platform       = item.get('platform', 'instagram'),
            scheduled_for  = item.get('scheduled_for'),
            content_type   = item.get('content_type', 'post'),
            suggested_day  = item.get('day', ''),
            suggested_time = item.get('time', ''),
            extra_json     = _json.dumps(extra),
        )
        saved_ids.append(post_id)

    # If generate_media=True, spawn background thread — response is immediate
    media_generating = False
    if data.get('generate_media') and saved_ids:
        from config.settings import IMAGES_ENABLED
        if IMAGES_ENABLED:
            import threading
            t = threading.Thread(
                target=_generate_media_background,
                args=(saved_ids, brand),
                daemon=True,
            )
            t.start()
            media_generating = True

    return jsonify({'success': True, 'saved_ids': saved_ids,
                    'total': len(saved_ids), 'media_generating': media_generating})


# ── API: Schedule Config ───────────────────────────────────────────────────────

@app.route('/api/schedule/<brand_id>', methods=['GET'])
def api_get_schedule(brand_id):
    return jsonify(db.get_schedule(brand_id))


@app.route('/api/schedule/<brand_id>', methods=['POST'])
def api_save_schedule(brand_id):
    configs = request.get_json(force=True) or []
    if not isinstance(configs, list):
        configs = [configs]
    db.save_schedule(brand_id, configs)
    return jsonify({'success': True, 'schedule': db.get_schedule(brand_id)})


# ── API: Video Generation (OpenMontage Bridge) ───────────────────────────────

@app.route('/api/video/generate/<brand_id>', methods=['POST'])
def api_video_generate(brand_id):
    """
    Generate a professional Reel/TikTok/Story using OpenMontage (FLUX Pro + Kling v3).
    Runs in background thread — returns job_id immediately.

    Format is decided by platform_config based on platform + content_type:
      platform=instagram, content_type=reel   → 15 sec, 3 clips × 5s
      platform=instagram, content_type=story  → 6 sec,  1 clip  × 5s
      platform=tiktok,    content_type=tiktok → 28 sec, 3 clips × 10s

    Body params:
      post_id       int    (optional) — attach video to existing post
      caption       str    (optional) — used to inform visual/narration prompts
      content_type  str    reel|story|tiktok (default: reel)
      platform      str    instagram|tiktok|facebook (default: instagram)
      custom_prompt str    (optional) — override auto-generated visual prompt
    """
    import openmontage_bridge as bridge

    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    data         = request.get_json(force=True) or {}
    post_id      = data.get('post_id')
    caption      = data.get('caption', '')
    content_type = data.get('content_type', 'reel')
    platform     = data.get('platform', 'instagram')
    custom_p     = data.get('custom_prompt', '')

    if post_id:
        post = db.get_post(int(post_id))
        if not post:
            return jsonify({'success': False, 'error': 'Post not found'}), 404
        caption      = caption or post.get('caption', '')
        content_type = content_type or post.get('content_type', 'reel')
        platform     = platform     or post.get('platform', 'instagram')

    job_id = bridge.start_reel_job(
        brand        = brand,
        post_id      = int(post_id) if post_id else None,
        caption      = caption,
        content_type = content_type,
        platform     = platform,
        custom_prompt= custom_p,
    )
    return jsonify({'success': True, 'job_id': job_id,
                    'status': 'queued', 'platform': platform,
                    'content_type': content_type})


@app.route('/api/video/status/<job_id>', methods=['GET'])
def api_video_status(job_id):
    """Poll the status of a background video generation job."""
    import openmontage_bridge as bridge
    job = bridge.get_job(job_id)
    if not job:
        return jsonify({'success': False, 'error': 'Job not found'}), 404
    return jsonify({'success': True, **job})


@app.route('/api/image/generate/<brand_id>', methods=['POST'])
def api_image_generate(brand_id):
    """
    Generate a FLUX Pro image for a post or carousel using OpenMontage bridge.
    Synchronous — waits for the image and updates the post DB.

    Body params:
      post_id       int    (optional) — update this post with the generated image_url
      caption       str    (optional) — used to inform visual prompt
      content_type  str    post|carousel (default: post)
      custom_prompt str    (optional) — override auto-generated visual prompt
    """
    import openmontage_bridge as bridge

    brand = db.get_brand(brand_id)
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    data         = request.get_json(force=True) or {}
    post_id      = data.get('post_id')
    caption      = data.get('caption', '')
    content_type = data.get('content_type', 'post')
    custom_p     = data.get('custom_prompt', '')

    if post_id:
        post = db.get_post(int(post_id))
        if not post:
            return jsonify({'success': False, 'error': 'Post not found'}), 404
        caption      = caption or post.get('caption', '')
        content_type = content_type or post.get('content_type', 'post')

    result = bridge.generate_image(brand, content_type, caption, custom_p)
    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('error')}), 500

    if post_id:
        db.update_post(int(post_id), image_url=result['image_url'])

    return jsonify({'success': True,
                    'image_url': result['image_url'],
                    'post_id': post_id})


# ── Media files (videos/images generated by OpenMontage Bridge) ──────────────

@app.route('/media/videos/<path:filename>')
def media_video(filename):
    from flask import send_from_directory
    import openmontage_bridge as bridge
    vid_dir = bridge._storage_dir("videos")
    return send_from_directory(str(vid_dir), filename)


@app.route('/media/images/<path:filename>')
def media_image(filename):
    from flask import send_from_directory
    import openmontage_bridge as bridge
    img_dir = bridge._storage_dir("images")
    return send_from_directory(str(img_dir), filename)


@app.route('/media/audio/<path:filename>')
def media_audio(filename):
    from flask import send_from_directory
    import openmontage_bridge as bridge
    audio_dir = bridge._storage_dir("audio")
    return send_from_directory(str(audio_dir), filename)


# ── Voxify Stats (para Zeus bot en Railway) ───────────────────────────────────

@app.route('/voxify-stats', methods=['GET'])
def api_voxify_stats_get():
    snap = db.get_latest_stats_snapshot()
    if not snap:
        return jsonify({
            'fecha': datetime.utcnow().date().isoformat(),
            'total_prospectos': 0,
            'calificados': 0,
            'nuevos': 0,
            'contactados': 0,
            'google_calls_hoy': 0,
            'google_costo_total': 0.0,
        })
    snap.pop('raw_json', None)
    return jsonify(snap)


@app.route('/voxify-stats', methods=['POST'])
def api_voxify_stats_post():
    data = request.get_json(force=True) or {}
    db.save_stats_snapshot(data)
    return jsonify({'success': True})


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Voxify Agencia on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
