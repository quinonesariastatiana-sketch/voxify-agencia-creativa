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
    db.update_post(post_id, status='rejected')
    return jsonify({'success': True})


@app.route('/api/posts/<int:post_id>/publish', methods=['POST'])
def api_publish_post(post_id):
    post = db.get_post(post_id)
    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    brand = db.get_brand(post['brand_id'])
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    result = publisher.publish_post(brand, post)
    if result['success']:
        meta_id = ','.join(result['ids'].values())
        db.update_post(post_id, status='posted', post_id_meta=meta_id,
                       posted_at=datetime.utcnow().isoformat())
    else:
        db.update_post(post_id, status='failed',
                       error_msg='; '.join(result['errors']))
    return jsonify(result)


@app.route('/api/posts/<int:post_id>/generate-media', methods=['POST'])
def api_generate_post_media(post_id):
    import json as _json
    post = db.get_post(post_id)
    if not post:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    brand = db.get_brand(post['brand_id'])
    if not brand:
        return jsonify({'success': False, 'error': 'Brand not found'}), 404

    from config.settings import IMAGES_ENABLED
    if not IMAGES_ENABLED:
        return jsonify({'success': False, 'error': 'FAL_API_KEY no configurado'}), 400

    # Build item compatible with agent prompt helpers
    extra = {}
    try:
        extra = _json.loads(post.get('extra_json') or '{}')
    except Exception:
        pass

    item = {
        'content_type': post.get('content_type', 'post'),
        'platform':     post.get('platform', 'instagram'),
        'topic':        extra.get('topic', post.get('caption', '')[:60]),
        'caption':      post.get('caption', ''),
    }

    content_type = item['content_type']
    try:
        if content_type in ('reel', 'story'):
            from tools.media_generator import generate_video_from_text
            prompt = agent._make_video_prompt(item, brand)
            result = generate_video_from_text(prompt, aspect_ratio="9:16", duration=5)
            if result.get('video_url'):
                db.update_post(post_id, video_url=result['video_url'])
                return jsonify({'success': True, 'video_url': result['video_url']})
        else:
            from tools.media_generator import generate_image
            prompt = agent._make_image_prompt(item, brand)
            fmt    = agent._image_format_for_item(item)
            result = generate_image(prompt, fmt)
            if result.get('image_url'):
                db.update_post(post_id, image_url=result['image_url'])
                return jsonify({'success': True, 'image_url': result['image_url']})
        return jsonify({'success': False, 'error': result.get('error', 'Sin URL en respuesta')}), 500
    except Exception as e:
        import traceback as _tb
        return jsonify({'success': False, 'error': str(e), 'trace': _tb.format_exc()[-1000:]}), 500


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

    if data.get('generate_images') and result.get('grid'):
        result['grid'] = agent.generate_grid_images(result['grid'], brand)

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

    return jsonify({'success': True, 'saved_ids': saved_ids, 'total': len(saved_ids)})


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


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Voxify Agencia on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
