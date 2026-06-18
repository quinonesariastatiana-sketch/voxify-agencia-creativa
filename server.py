"""
VoxifyHub Review Server — interfaz web para aprobar y publicar posts.
Corre con: python server.py
Abre en: http://localhost:5000
"""

import anthropic
import json
import os
import webbrowser
import threading
import time
import atexit
import requests
from pathlib import Path
from flask import Flask, jsonify, request, render_template, send_from_directory

from config.settings import validate_config, ANTHROPIC_API_KEY, AGENT_MODEL
from config.brands_registry import (
    BRANDS, DEFAULT_BRAND_ID, list_brands,
    reload_from_db, seed_defaults_if_empty,
)
from database import Database
from agent import VoxifyCreativeDirector
from tools.scheduler import MultiScheduler

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB per request
db = Database()

# Seed Python configs into DB on first run, then load all brands from DB
seed_defaults_if_empty(db)
reload_from_db(db)

scheduler = MultiScheduler(db, BRANDS)

# Agent instances cached per brand
_agents: dict[str, VoxifyCreativeDirector] = {}

def get_agent(brand_id: str) -> VoxifyCreativeDirector:
    if brand_id not in _agents:
        _agents[brand_id] = VoxifyCreativeDirector(db, brand_id)
    return _agents[brand_id]



def brand_id_from_request() -> str:
    bid = request.args.get("brand")
    if not bid and request.is_json:
        bid = (request.get_json(silent=True) or {}).get("brand")
    return bid or DEFAULT_BRAND_ID

# ── Generation state (shared across requests) ─────────────────────────────
generation_state = {
    "running": False,
    "step": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
}
state_lock = threading.Lock()

STATUS_LABELS = {
    "pending_approval": "Pendiente de aprobación",
    "pending":          "Aprobado",
    "published":        "Publicado",
    "ready_manual":     "Listo para subir manualmente",
    "rejected":         "Rechazado",
    "failed":           "Error al publicar",
    "skipped":          "Omitido",
}


def post_to_dict(row):
    keys = ["id", "platform", "content_type", "content", "image_url", "scheduled_date",
            "status", "external_post_id", "error_message", "created_at", "published_at",
            "video_url", "reach", "impressions", "likes", "comments", "saves", "shares",
            "engagement_rate", "voiceover_url", "music_url"]
    d = dict(zip(keys, row))
    d["status_label"] = STATUS_LABELS.get(d["status"], d["status"])
    return d


# ── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("home.html")


@app.route("/creative")
def creative_page():
    return render_template("review.html")


@app.route("/brand/new")
def brand_new():
    return render_template("brand_setup.html")


@app.route("/brand/<brand_id>")
def brand_edit(brand_id):
    return render_template("brand_setup.html")


@app.route("/brands")
def brands_page():
    return render_template("brands.html")


@app.route("/api/brands/<brand_id>/research", methods=["POST"])
def research_brand_route(brand_id):
    from tools.brand_researcher import research_brand, apply_research_to_brand
    data = request.get_json(force=True) or {}
    brand_data = data.get("brand_data", {})
    save_to_brand = data.get("save", False)

    result = research_brand(brand_data)
    if not result.get("success"):
        return jsonify(result), 500

    if save_to_brand and brand_id != "preview":
        brand = db.get_brand_config(brand_id)
        if brand:
            updated = apply_research_to_brand(brand, result["research"])
            db.save_brand(updated)
            reload_from_db(db)

    return jsonify(result)


# ── Brand CRUD ────────────────────────────────────────────────────────────

@app.route("/api/brands")
def get_brands():
    # Always read from DB so hot-seeded brands are visible without restart
    configs = db.list_brand_configs()
    return jsonify([
        {"id": c["id"], "name": c["name"],
         "tagline": c.get("tagline", ""), "color": c.get("color", "#635BFF")}
        for c in configs
    ])


@app.route("/api/brands/<brand_id>")
def get_brand_full(brand_id):
    config = db.get_brand_config(brand_id)
    if not config:
        return jsonify({"error": "Marca no encontrada"}), 404
    stats = db.get_brand_stats(brand_id)
    return jsonify({"config": config, "stats": stats})


@app.route("/api/brands", methods=["POST"])
def create_or_update_brand():
    config = request.json
    if not config or not config.get("id") or not config.get("name"):
        return jsonify({"error": "id y name son obligatorios"}), 400

    # Ensure monthly_targets matches goals 30/60/90
    goals = config.get("goals", {})
    config["monthly_targets"] = {
        1: goals.get("30", {}),
        2: goals.get("60", {}),
        3: goals.get("90", {}),
    }

    db.save_brand(config)
    reload_from_db(db)

    # Rebuild scheduler jobs for this brand (supports single dict or list of slots)
    sched = config.get("posting_schedule", {})
    for platform, sched_config in sched.items():
        slots = sched_config if isinstance(sched_config, list) else [sched_config]
        for idx, s in enumerate(slots):
            days = s.get("days", [])
            if not days:
                continue
            try:
                from apscheduler.triggers.cron import CronTrigger
                job_id = f"{config['id']}_{platform}" if idx == 0 else f"{config['id']}_{platform}_{idx}"
                scheduler.scheduler.add_job(
                    func=scheduler._publish_next_post,
                    trigger=CronTrigger(
                        day_of_week=",".join(days),
                        hour=s.get("hour", 9), minute=s.get("minute", 0),
                        timezone="America/New_York",
                    ),
                    args=[config["id"], platform],
                    id=job_id,
                    replace_existing=True,
                )
            except Exception:
                pass

    # Clear cached agent for this brand
    _agents.pop(config["id"], None)

    return jsonify({"success": True, "id": config["id"]})


@app.route("/api/brands/<brand_id>", methods=["DELETE"])
def delete_brand(brand_id):
    if brand_id == DEFAULT_BRAND_ID and len(BRANDS) == 1:
        return jsonify({"error": "No puedes eliminar la única marca activa"}), 400
    db.delete_brand(brand_id)
    reload_from_db(db)
    _agents.pop(brand_id, None)
    # Remove scheduler jobs for this brand
    for platform in ("instagram", "facebook", "linkedin"):
        try:
            scheduler.scheduler.remove_job(f"{brand_id}_{platform}")
        except Exception:
            pass
    return jsonify({"success": True})


UPLOAD_LOGOS   = Path(__file__).parent / "static" / "uploads" / "logos"
UPLOAD_MANUALS = Path(__file__).parent / "static" / "uploads" / "manuals"
UPLOAD_MEDIA   = Path(__file__).parent / "static" / "uploads" / "media"
UPLOAD_LOGOS.mkdir(parents=True, exist_ok=True)
UPLOAD_MANUALS.mkdir(parents=True, exist_ok=True)
UPLOAD_MEDIA.mkdir(parents=True, exist_ok=True)

ALLOWED_IMG   = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
ALLOWED_VIDEO = {".mp4", ".mov", ".webm", ".avi"}
ALLOWED_MEDIA = ALLOWED_IMG | ALLOWED_VIDEO
ALLOWED_PDF   = {".pdf", ".txt", ".md"}


@app.route("/static/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(Path(__file__).parent / "static" / "uploads", filename)


@app.route("/api/brands/<brand_id>/upload-logo", methods=["POST"])
def upload_logo(brand_id):
    if "file" not in request.files:
        return jsonify({"error": "No se envió archivo"}), 400
    f = request.files["file"]
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_IMG:
        return jsonify({"error": f"Formato no permitido: {ext}"}), 400
    dest = UPLOAD_LOGOS / f"{brand_id}{ext}"
    f.save(dest)
    url = f"/static/uploads/logos/{brand_id}{ext}"
    # Persist URL in brand config
    brand = db.get_brand_config(brand_id)
    if brand:
        brand["logo_url"] = url
        db.save_brand(brand)
        reload_from_db(db)
        _agents.pop(brand_id, None)
    return jsonify({"success": True, "url": url})


@app.route("/api/brands/<brand_id>/upload-manual", methods=["POST"])
def upload_manual(brand_id):
    if "file" not in request.files:
        return jsonify({"error": "No se envió archivo"}), 400
    f = request.files["file"]
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_PDF:
        return jsonify({"error": f"Formato no permitido: {ext}"}), 400
    dest = UPLOAD_MANUALS / f"{brand_id}{ext}"
    f.save(dest)
    # Extract text preview
    text = ""
    try:
        if ext == ".pdf":
            import PyPDF2
            reader = PyPDF2.PdfReader(str(dest))
            pages = [reader.pages[i].extract_text() or "" for i in range(min(10, len(reader.pages)))]
            text = "\n".join(pages)
        else:
            text = dest.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        text = f"[No se pudo extraer texto: {e}]"
    # Persist path in brand config
    brand = db.get_brand_config(brand_id)
    if brand:
        brand["manual_path"] = str(dest)
        brand["manual_text_preview"] = text[:8000]
        db.save_brand(brand)
        reload_from_db(db)
        _agents.pop(brand_id, None)
    return jsonify({"success": True, "text_preview": text[:500], "chars": len(text)})


@app.route("/api/brands/<brand_id>/analyze", methods=["POST"])
def analyze_brand(brand_id):
    """Use Claude to read website + social pages + manual and extract brand insights."""
    import anthropic as _anthropic
    from config.settings import ANTHROPIC_API_KEY, AGENT_MODEL

    data = request.json or {}
    website_url   = data.get("website_url", "").strip()
    social_urls   = data.get("social_urls", {})
    manual_text   = data.get("manual_text", "")
    brand_name    = data.get("brand_name", brand_id)

    # Gather raw content from each source
    sources = []

    if website_url:
        try:
            from bs4 import BeautifulSoup
            resp = requests.get(website_url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            web_text = " ".join(soup.get_text(separator=" ").split())[:6000]
            sources.append(f"== SITIO WEB ({website_url}) ==\n{web_text}")
        except Exception as e:
            sources.append(f"== SITIO WEB ==\n[No se pudo acceder: {e}]")

    for platform, url in social_urls.items():
        if url and url.strip():
            sources.append(f"== {platform.upper()} ==\nURL: {url.strip()}")

    if manual_text:
        sources.append(f"== MANUAL / GUIDELINES DE MARCA ==\n{manual_text[:6000]}")

    # Also include any stored manual
    brand = db.get_brand_config(brand_id) or {}
    stored_manual = brand.get("manual_text_preview", "")
    if stored_manual and not manual_text:
        sources.append(f"== MANUAL DE MARCA (cargado) ==\n{stored_manual[:5000]}")

    if not sources:
        return jsonify({"error": "Proporciona al menos la URL del sitio web o un manual de marca"}), 400

    context = "\n\n".join(sources)

    prompt = f"""Analiza los siguientes recursos de la marca "{brand_name}" y extrae toda la información relevante.

RECURSOS DISPONIBLES:
{context}

TAREA: Devuelve ÚNICAMENTE un JSON válido con esta estructura (sin texto antes ni después del JSON):
{{
  "name": "nombre oficial de la marca",
  "tagline": "slogan o tagline principal",
  "description": "descripción clara de qué hace la marca y a quién sirve (2-3 oraciones)",
  "mission": "misión o propósito de la marca",
  "industry": "industria o sector",
  "geography": "ubicación geográfica o mercado objetivo",
  "values": ["valor1", "valor2", "valor3"],
  "hashtags": ["#hashtag1", "#hashtag2"],
  "voice": {{
    "adjectives": ["adjetivo1", "adjetivo2", "adjetivo3"],
    "avoid": "qué NO hacer en comunicación: palabras prohibidas, tono a evitar",
    "formality": 0.4,
    "emoji_use": "ninguno|moderado|frecuente"
  }},
  "positioning": {{
    "usp": "propuesta única de valor — qué hace diferente a esta marca de todas las demás",
    "competitors": [
      {{"name": "competidor", "weakness": "su debilidad principal"}}
    ],
    "differentiators": ["diferenciador1", "diferenciador2"]
  }},
  "audience": {{
    "personas": [
      {{"name": "nombre del perfil", "age": "rango de edad", "occupation": "ocupación", "pain": "problema principal", "goal": "qué busca"}}
    ],
    "language": "es|en|both",
    "channels": ["instagram", "facebook"],
    "geography": "descripción del público por ubicación"
  }},
  "content_lines": [
    {{"name": "nombre del pilar", "percentage": 0.30, "description": "qué cubre este pilar"}}
  ],
  "insights_summary": "resumen de 3-5 puntos clave que aprendiste sobre esta marca para el agente creativo"
}}

Extrae la información real de los recursos. Si algo no está disponible, usa valores razonables basados en el contexto de la marca."""

    try:
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Extract JSON if wrapped in markdown fences
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        return jsonify({"success": True, "insights": result})
    except json.JSONDecodeError as e:
        return jsonify({"success": False, "error": f"JSON inválido: {e}", "raw": raw[:500]}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Media library ────────────────────────────────────────────────────────────

@app.route("/api/brands/<brand_id>/media", methods=["GET"])
def list_media(brand_id):
    return jsonify(db.list_media(brand_id))


@app.route("/api/brands/<brand_id>/media", methods=["POST"])
def upload_media(brand_id):
    if "files" not in request.files and "file" not in request.files:
        return jsonify({"error": "No se enviaron archivos"}), 400
    files = request.files.getlist("files") or [request.files.get("file")]
    brand_dir = UPLOAD_MEDIA / brand_id
    brand_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_MEDIA:
            continue
        # Unique filename: timestamp + original name
        import uuid
        safe_name = f"{uuid.uuid4().hex[:8]}_{Path(f.filename).stem[:30]}{ext}"
        dest = brand_dir / safe_name
        f.save(dest)
        url = f"/static/uploads/media/{brand_id}/{safe_name}"
        media_type = "video" if ext in ALLOWED_VIDEO else "image"
        title = Path(f.filename).stem.replace("_", " ").replace("-", " ")
        media_id = db.save_media(brand_id, safe_name, url, media_type, title)
        saved.append({"id": media_id, "url": url, "media_type": media_type,
                      "filename": safe_name, "title": title})
    return jsonify({"success": True, "saved": saved})


@app.route("/api/brands/<brand_id>/media/<int:media_id>", methods=["PUT"])
def update_media(brand_id, media_id):
    data = request.json or {}
    db.update_media(media_id, data.get("title", ""),
                    data.get("description", ""), data.get("tags", []))
    return jsonify({"success": True})


@app.route("/api/brands/<brand_id>/media/<int:media_id>", methods=["DELETE"])
def delete_media(brand_id, media_id):
    url = db.delete_media(media_id)
    if url:
        # Remove file from disk
        file_path = Path(__file__).parent / url.lstrip("/")
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
    return jsonify({"success": True})


# ── Monthly campaigns ─────────────────────────────────────────────────────────

@app.route("/api/brands/<brand_id>/campaign", methods=["GET"])
def get_campaign(brand_id):
    from datetime import datetime as _dt
    month = int(request.args.get("month", _dt.utcnow().month))
    year  = int(request.args.get("year",  _dt.utcnow().year))
    camp  = db.get_campaign(brand_id, month, year)
    return jsonify(camp or {})


@app.route("/api/brands/<brand_id>/campaign", methods=["POST"])
def save_campaign(brand_id):
    from datetime import datetime as _dt
    data  = request.json or {}
    month = int(data.get("month", _dt.utcnow().month))
    year  = int(data.get("year",  _dt.utcnow().year))
    db.save_campaign(brand_id, month, year, data)
    return jsonify({"success": True})


@app.route("/api/brands/<brand_id>/campaign/evaluate", methods=["POST"])
def evaluate_campaign(brand_id):
    """Claude evaluates the monthly campaign and returns structured improvement suggestions."""
    import anthropic as _anthropic
    from config.settings import ANTHROPIC_API_KEY, AGENT_MODEL
    from datetime import datetime as _dt

    data  = request.json or {}
    month = int(data.get("month", _dt.utcnow().month))
    year  = int(data.get("year",  _dt.utcnow().year))

    brand  = db.get_brand_config(brand_id)
    camp   = db.get_campaign(brand_id, month, year) or data
    media  = db.list_media(brand_id)

    if not brand:
        return jsonify({"error": "Marca no encontrada"}), 404

    month_name = _dt(year, month, 1).strftime("%B %Y")
    media_summary = f"{len([m for m in media if m['media_type']=='image'])} imágenes, " \
                    f"{len([m for m in media if m['media_type']=='video'])} videos en biblioteca"

    prompt = f"""Eres un estratega de marketing digital experto en e-commerce y redes sociales.
Analiza la siguiente campaña mensual y devuelve sugerencias de mejora concretas.

MARCA: {brand.get('name')} — {brand.get('tagline','')}
INDUSTRIA: {brand.get('industry','')}
AUDIENCIA PRINCIPAL: {brand.get('geography','')}
PROPUESTA ÚNICA: {brand.get('positioning',{}).get('usp','')}
RECURSOS VISUALES: {media_summary}

CAMPAÑA DEL MES — {month_name}:
- Producto/Servicio a promocionar: {camp.get('product_name','')}
- Descripción: {camp.get('product_desc','')}
- Precio: {camp.get('product_price','')}
- Tipo de promoción: {camp.get('promo_type','')}
- Detalles del descuento/oferta: {camp.get('promo_details','')}
- Descuento: {camp.get('discount_pct','')}%
- Meta de la campaña: {camp.get('campaign_goal','')}
- Segmento objetivo: {camp.get('target_segment','')}
- Fechas: {camp.get('campaign_dates','')}
- Notas adicionales: {camp.get('notes','')}

OBJETIVOS DEL MES: {json.dumps(brand.get('goals',{}).get('30',{}), ensure_ascii=False)}

Evalúa la campaña considerando:
1. Coherencia con la propuesta de valor de la marca
2. Atractivo y claridad de la oferta
3. Potencial de conversión dado el segmento
4. Riesgos (canibalización de precio, expectativas, percepción de marca)
5. Oportunidades de amplificación

Devuelve ÚNICAMENTE un JSON con esta estructura (sin texto antes ni después):
{{
  "campaign_score": 7.5,
  "score_rationale": "Explicación del puntaje en 2 oraciones",
  "revenue_estimate": "Estimado de impacto en ventas: $X - $Y extra este mes",
  "reach_estimate": "Estimado de alcance adicional: X-Y personas",
  "conversion_estimate": "Tasa de conversión esperada: X%",
  "risks": ["riesgo 1", "riesgo 2"],
  "suggestions": [
    {{
      "id": "s1",
      "category": "precio|contenido|timing|segmento|oferta|formato",
      "title": "Título corto de la sugerencia",
      "problem": "Qué está débil o falta",
      "suggestion": "Exactamente qué cambiar o agregar",
      "impact": "alto|medio|bajo",
      "effort": "fácil|moderado|complejo",
      "example": "Ejemplo concreto de cómo se vería aplicado"
    }}
  ]
}}
Genera entre 4 y 7 sugerencias, ordenadas de mayor a menor impacto."""

    try:
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        # Persist suggestions
        db.save_campaign_suggestions(brand_id, month, year, result.get("suggestions", []))
        return jsonify({"success": True, "evaluation": result})
    except json.JSONDecodeError as e:
        return jsonify({"success": False, "error": f"JSON inválido: {e}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/brands/<brand_id>/campaign/suggestions", methods=["POST"])
def update_suggestion_status(brand_id):
    """Mark individual suggestions as approved or rejected."""
    from datetime import datetime as _dt
    data   = request.json or {}
    month  = int(data.get("month", _dt.utcnow().month))
    year   = int(data.get("year",  _dt.utcnow().year))
    sug_id = data.get("id")
    status = data.get("status")  # "approved" | "rejected"
    camp   = db.get_campaign(brand_id, month, year)
    if not camp:
        return jsonify({"error": "Campaña no encontrada"}), 404
    suggestions = camp.get("suggestions", [])
    for s in suggestions:
        if s.get("id") == sug_id:
            s["status"] = status
            break
    db.save_campaign_suggestions(brand_id, month, year, suggestions)
    return jsonify({"success": True})


@app.route("/api/brands/<brand_id>/generate-strategy", methods=["POST"])
def generate_strategy(brand_id):
    """Generate 90-day strategic plan for a brand via the agent."""
    data = request.json or {}
    strategy_type = data.get("type", "90days")  # "90days" | "monthly" | "weekly"

    with state_lock:
        if generation_state["running"]:
            return jsonify({"success": False, "message": "Ya hay una generación en curso."})
        generation_state["running"] = True
        generation_state["step"] = f"Generando estrategia {strategy_type}..."
        generation_state["started_at"] = time.time()
        generation_state["finished_at"] = None
        generation_state["error"] = None

    def run():
        try:
            # Always read brand fresh from DB — never rely on in-memory BRANDS
            brand = db.get_brand_config(brand_id)
            if not brand:
                raise ValueError(f"Marca '{brand_id}' no encontrada en la base de datos.")

            # Refresh in-memory BRANDS so agent lookup works
            reload_from_db(db)

            agent = get_agent(brand_id)
            goals = brand.get("goals", {})
            positioning = brand.get("positioning", {})

            if strategy_type == "90days":
                with state_lock:
                    generation_state["step"] = "Analizando tendencias y competidores..."
                task = f"""
Eres el estratega de {brand.get('name', brand_id)}.
Crea el PLAN ESTRATÉGICO COMPLETO DE 90 DÍAS para la marca.

CONTEXTO DE LA MARCA:
- Propuesta de valor: {positioning.get('usp', 'Sin definir')}
- Industria: {brand.get('industry', 'Sin definir')}
- Geografía objetivo: {brand.get('geography', 'Sin definir')}
- Misión: {brand.get('mission', 'Sin definir')}
- Diferenciadores: {', '.join(positioning.get('differentiators', []))}
- Competidores clave: {', '.join(c['name'] for c in positioning.get('competitors', []))}

PILARES DE CONTENIDO:
{chr(10).join(f"  • {p['name']} ({int(p.get('percentage',0)*100)}%): {p.get('description','')}" for p in brand.get('content_lines', []))}

OBJETIVOS (KPIs por período):
30 días: {goals.get('30', {})}
60 días: {goals.get('60', {})}
90 días: {goals.get('90', {})}

ENTREGABLES REQUERIDOS:
1. Narrativa estratégica: por qué esta estrategia en este momento
2. Fase 1 (días 1-30): nombre, objetivo central, énfasis de contenido por pilar, KPIs
3. Fase 2 (días 31-60): nombre, objetivo, énfasis, KPIs
4. Fase 3 (días 61-90): nombre, objetivo, énfasis, KPIs
5. Tácticas de crecimiento orgánico por plataforma (Instagram, Facebook)
6. Plan de conversión: cómo pasar de seguidor → lead → cliente
7. Métricas semanales de seguimiento

Usa detect_trends y analyze_competitors para fundamentar con datos actuales.
Devuelve la estrategia completa en español, lista para guiar al agente las próximas 12 semanas.
"""
            elif strategy_type == "monthly":
                from strategy.plan_90days import get_current_phase
                phase = get_current_phase()
                with state_lock:
                    generation_state["step"] = "Analizando rendimiento anterior..."
                task = f"""
Crea el PLAN DE CONTENIDO MENSUAL para {brand.get('name', brand_id)} — Fase {phase}.
Usa analyze_performance para ver qué funcionó el mes anterior.
Usa detect_trends para tendencias actuales.
Entrega:
- Tema central del mes y justificación
- Los 4 temas semanales (uno por semana)
- Distribución de formatos y líneas de contenido este mes
- KPIs a alcanzar y cómo medirlos
- 3 ideas de contenido de alto impacto para este mes
"""
            else:  # weekly
                with state_lock:
                    generation_state["step"] = "Generando contenido semanal..."
                # Pass media assets and campaign as structured data to the agent
                media_assets    = db.list_media(brand_id)
                campaign        = db.get_current_campaign(brand_id) or {}
                campaign_ctx    = _build_campaign_context(brand_id)
                agent.weekly_content_run(
                    extra_context=campaign_ctx,
                    media_assets=media_assets,
                    campaign=campaign,
                )
                with state_lock:
                    generation_state["step"] = "Completado"
                    generation_state["finished_at"] = time.time()
                return

            with state_lock:
                generation_state["step"] = "Generando estrategia con Claude..."
            result = agent.run(task)

            # Save result back to brand config so the form shows it
            if strategy_type == "90days":
                brand["strategy_90days"] = result
                db.save_brand(brand)
                reload_from_db(db)
                _agents.pop(brand_id, None)
            elif strategy_type == "monthly":
                brand["monthly_plan"] = result
                db.save_brand(brand)

            # Also log to weekly_strategy history table
            try:
                db.conn.execute(
                    "INSERT INTO weekly_strategy (week_number, year, phase, theme, analysis, brand_id) VALUES (?,?,?,?,?,?)",
                    (0, 2026, 0, strategy_type, result[:4000], brand_id),
                )
                db.conn.commit()
            except Exception:
                pass

            with state_lock:
                generation_state["step"] = "Estrategia generada"
                generation_state["finished_at"] = time.time()
        except Exception as e:
            with state_lock:
                generation_state["error"] = str(e)
                generation_state["step"] = f"Error: {str(e)[:120]}"
                generation_state["finished_at"] = time.time()
        finally:
            with state_lock:
                generation_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True})


def _build_campaign_context(brand_id: str) -> str:
    """Return campaign brief as text to inject into weekly content task."""
    camp = db.get_current_campaign(brand_id)
    if not camp or not camp.get("product_name"):
        return ""
    lines = ["\n\n════ CAMPAÑA DEL MES — OBLIGATORIO INTEGRAR ════"]
    if camp.get("product_name"):
        lines.append(f"PRODUCTO/SERVICIO A PROMOCIONAR: {camp['product_name']}")
    if camp.get("product_desc"):
        lines.append(f"DESCRIPCIÓN: {camp['product_desc']}")
    if camp.get("product_price"):
        lines.append(f"PRECIO: {camp['product_price']}")
    if camp.get("promo_type"):
        lines.append(f"TIPO DE PROMOCIÓN: {camp['promo_type']}")
    if camp.get("promo_details"):
        lines.append(f"DETALLES DE LA OFERTA: {camp['promo_details']}")
    if camp.get("discount_pct"):
        lines.append(f"DESCUENTO: {camp['discount_pct']}%")
    if camp.get("campaign_goal"):
        lines.append(f"META DE LA CAMPAÑA: {camp['campaign_goal']}")
    if camp.get("target_segment"):
        lines.append(f"SEGMENTO OBJETIVO: {camp['target_segment']}")
    if camp.get("campaign_dates"):
        lines.append(f"FECHAS: {camp['campaign_dates']}")
    if camp.get("notes"):
        lines.append(f"NOTAS: {camp['notes']}")

    # Include approved suggestions
    approved = [s for s in camp.get("suggestions", []) if s.get("status") == "approved"]
    if approved:
        lines.append("\nSUGERENCIAS APROBADAS (aplica en el contenido):")
        for s in approved:
            lines.append(f"  • [{s.get('category','').upper()}] {s.get('title')}: {s.get('suggestion')}")

    # Promotion content rules
    lines.append("\nREGLAS PARA ESTA CAMPAÑA:")
    lines.append("• Al menos 2 de los 5 posts de Instagram DEBEN mencionar este producto/oferta")
    lines.append("• Al menos 2 de los 5 posts de Facebook DEBEN incluir la promoción")
    lines.append("• Integra la oferta de forma natural, sin que parezca publicidad genérica")
    lines.append("• Usa el product_media_id como imagen principal si está disponible")
    lines.append("════════════════════════════════════════════════")
    return "\n".join(lines)


def _build_media_context(brand_id: str) -> str:
    """Return available brand media assets as text to inject into weekly content task."""
    media = db.list_media(brand_id)
    if not media:
        return ""
    images = [m for m in media if m["media_type"] == "image"]
    videos = [m for m in media if m["media_type"] == "video"]
    lines  = ["\n\n════ BIBLIOTECA DE MEDIOS DE LA MARCA ════"]
    lines.append("Tienes acceso a los siguientes assets REALES de la marca.")
    lines.append("PRIORIZA estos assets sobre imágenes generadas por IA:")
    if images:
        lines.append(f"\nIMAGENES DISPONIBLES ({len(images)}):")
        for m in images[:15]:
            desc = m.get("description") or m.get("title") or m.get("filename")
            lines.append(f"  • URL: {m['url']}  — {desc}")
    if videos:
        lines.append(f"\nVIDEOS DISPONIBLES ({len(videos)}):")
        for m in videos[:8]:
            desc = m.get("description") or m.get("title") or m.get("filename")
            lines.append(f"  • URL: {m['url']}  — {desc}")
    lines.append("\nUsa save_content_to_calendar con image_url o video_url apuntando a estos URLs.")
    lines.append("════════════════════════════════════════════════")
    return "\n".join(lines)


@app.route("/api/posts")
def get_posts():
    status_filter = request.args.get("status")
    brand_id = brand_id_from_request()
    rows = db.list_posts(status=status_filter, limit=50, brand_id=brand_id)
    return jsonify([post_to_dict(r) for r in rows])


@app.route("/api/posts/pending")
def get_pending():
    brand_id = brand_id_from_request()
    rows = db.get_posts_pending_approval(brand_id=brand_id)
    return jsonify([post_to_dict(r) for r in rows])


@app.route("/api/approve/<int:post_id>", methods=["POST"])
def approve_post(post_id):
    data = request.json or {}
    image_url = data.get("image_url")
    content = data.get("content")
    if content:
        db.conn.execute("UPDATE scheduled_posts SET content=? WHERE id=?", (content, post_id))
        db.conn.commit()
    db.approve_post(post_id, image_url)
    return jsonify({"success": True})


@app.route("/api/reject/<int:post_id>", methods=["POST"])
def reject_post(post_id):
    db.reject_post(post_id)
    return jsonify({"success": True})


@app.route("/api/manual/<int:post_id>", methods=["POST"])
def mark_manual(post_id):
    db.mark_post_ready_manual(post_id)
    return jsonify({"success": True})


@app.route("/api/retry/<int:post_id>", methods=["POST"])
def retry_post(post_id):
    """Reset a failed post back to approved (pending) so it can be republished."""
    db.conn.execute(
        "UPDATE scheduled_posts SET status='pending', error_message=NULL WHERE id=? AND status='failed'",
        (post_id,)
    )
    db.conn.commit()
    return jsonify({"success": True})


@app.route("/api/retry-all-failed", methods=["POST"])
def retry_all_failed():
    """Reset all failed posts back to approved (pending)."""
    cur = db.conn.execute(
        "UPDATE scheduled_posts SET status='pending', error_message=NULL WHERE status='failed'"
    )
    db.conn.commit()
    return jsonify({"success": True, "reset": cur.rowcount})


@app.route("/api/publish", methods=["POST"])
def publish_approved():
    data = request.json or {}
    post_ids = data.get("post_ids", [])
    brand_id = data.get("brand", DEFAULT_BRAND_ID)
    results = []

    for post_id in post_ids:
        row = db.conn.execute(
            "SELECT id, platform, content_type, content, image_url, video_url FROM scheduled_posts WHERE id=?",
            (post_id,)
        ).fetchone()

        if not row:
            results.append({"id": post_id, "success": False, "error": "Post no encontrado"})
            continue

        _, platform, _, content, image_url, video_url = row
        media_url = video_url or image_url
        result = get_agent(brand_id).publish_post(platform, post_id, content, media_url)

        if result.get("success"):
            db.mark_post_published(post_id, result.get("post_id", ""))
            results.append({"id": post_id, "success": True, "platform": platform})
        else:
            db.mark_post_failed(post_id, result.get("error", "Error desconocido"))
            results.append({"id": post_id, "success": False, "error": result.get("error")})

    return jsonify({"results": results})


@app.route("/api/reschedule", methods=["POST"])
def reschedule():
    data = request.json or {}
    start_date = data.get("start_date", "2026-06-16")
    brand_id = data.get("brand", DEFAULT_BRAND_ID)
    result = db.reschedule_posts(start_date, brand_id=brand_id)
    return jsonify(result)


@app.route("/api/strategy")
def get_strategy():
    from strategy.plan_90days import MONTHLY_TARGETS, CONTENT_LINES, get_current_phase
    from datetime import date
    phase = get_current_phase()
    today = date.today()
    week = today.isocalendar()[1]
    days_elapsed = (today - date(2026, 6, 13)).days
    targets = MONTHLY_TARGETS.get(min(phase, 3), MONTHLY_TARGETS[3])
    lines = [{"id": k, "name": v["name"], "percentage": int(v["percentage"]*100),
              "description": v["description"]} for k, v in CONTENT_LINES.items()]

    recent_strategy = db.conn.execute(
        "SELECT week_number, phase, theme, created_at FROM weekly_strategy ORDER BY id DESC LIMIT 5"
    ).fetchall()

    return jsonify({
        "phase": phase,
        "phase_name": ["", "Posicionamiento", "Tracción", "Conversión"][phase],
        "days_elapsed": days_elapsed,
        "current_week": week,
        "targets": targets,
        "content_lines": lines,
        "recent_weekly_runs": [
            {"week": r[0], "phase": r[1], "created_at": r[3]} for r in recent_strategy
        ],
    })


@app.route("/api/engagement-responses", methods=["POST"])
def generate_engagement_responses():
    brand_id = brand_id_from_request()

    def run():
        with state_lock:
            generation_state["running"] = True
            generation_state["step"] = "Revisando comentarios sin responder..."
            generation_state["started_at"] = time.time()
            generation_state["finished_at"] = None
            generation_state["error"] = None
        try:
            result = get_agent(brand_id).generate_engagement_responses()
            with state_lock:
                generation_state["step"] = "Respuestas generadas"
                generation_state["finished_at"] = time.time()
                generation_state["last_result"] = result
        except Exception as e:
            with state_lock:
                generation_state["error"] = str(e)
                generation_state["finished_at"] = time.time()
        finally:
            with state_lock:
                generation_state["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True})


@app.route("/api/generate-weekly", methods=["POST"])
def generate_weekly():
    brand_id = brand_id_from_request()
    with state_lock:
        if generation_state["running"]:
            return jsonify({"success": False, "message": "Ya hay una generación en curso."})
        generation_state["running"] = True
        generation_state["step"] = "Iniciando agente..."
        generation_state["started_at"] = time.time()
        generation_state["finished_at"] = None
        generation_state["error"] = None

    def run():
        steps = [
            "Analizando rendimiento y tendencias...",
            "Definiendo tema y estrategia de la semana...",
            "Escribiendo posts de Instagram (lunes a viernes)...",
            "Generando imágenes de Instagram con FLUX...",
            "Escribiendo posts de Facebook (lunes a viernes)...",
            "Generando imágenes de Facebook con FLUX...",
            "Generando Reel del viernes...",
            "Escribiendo post de LinkedIn (miércoles)...",
            "Guardando los 11 posts en el calendario...",
        ]
        try:
            step_thread = threading.Thread(target=_cycle_steps, args=(steps,), daemon=True)
            step_thread.start()
            get_agent(brand_id).weekly_content_run(
                extra_context=_build_campaign_context(brand_id),
                media_assets=db.list_media(brand_id),
                campaign=db.get_current_campaign(brand_id) or {},
            )
            with state_lock:
                generation_state["step"] = "Completado"
                generation_state["finished_at"] = time.time()
        except Exception as e:
            with state_lock:
                generation_state["error"] = str(e)
                generation_state["step"] = f"Error: {str(e)[:80]}"
                generation_state["finished_at"] = time.time()
        finally:
            with state_lock:
                generation_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True})


@app.route("/api/generate-extra", methods=["POST"])
def generate_extra():
    """Generate extra content: Stories, Reels, and weekend posts without touching existing posts."""
    brand_id = brand_id_from_request()
    with state_lock:
        if generation_state["running"]:
            return jsonify({"success": False, "message": "Ya hay una generación en curso."})
        generation_state["running"] = True
        generation_state["step"] = "Calculando slots disponibles..."
        generation_state["started_at"] = time.time()
        generation_state["finished_at"] = None
        generation_state["error"] = None

    def run():
        steps = [
            "Calculando slots disponibles para Stories y Reels...",
            "Generando Stories con fotos reales de la marca...",
            "Generando Reels adicionales...",
            "Generando posts de fin de semana...",
            "Guardando en el calendario...",
        ]
        try:
            step_thread = threading.Thread(target=_cycle_steps, args=(steps,), daemon=True)
            step_thread.start()
            get_agent(brand_id).generate_extra_content_run(
                media_assets=db.list_media(brand_id),
                campaign=db.get_current_campaign(brand_id) or {},
            )
            with state_lock:
                generation_state["step"] = "Completado"
                generation_state["finished_at"] = time.time()
        except Exception as e:
            with state_lock:
                generation_state["error"] = str(e)
                generation_state["step"] = f"Error: {str(e)[:80]}"
                generation_state["finished_at"] = time.time()
        finally:
            with state_lock:
                generation_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True})


def _cycle_steps(steps):
    """Cycle through step labels while generation runs."""
    i = 0
    while generation_state["running"]:
        with state_lock:
            if generation_state["running"]:
                generation_state["step"] = steps[i % len(steps)]
        i += 1
        time.sleep(8)


@app.route("/api/generation-status")
def generation_status():
    with state_lock:
        elapsed = None
        if generation_state["started_at"]:
            end = generation_state["finished_at"] or time.time()
            elapsed = int(end - generation_state["started_at"])
        return jsonify({
            "running":  generation_state["running"],
            "step":     generation_state["step"],
            "elapsed":  elapsed,
            "error":    generation_state["error"],
            "finished": generation_state["finished_at"] is not None,
        })


@app.route("/api/stats")
def get_stats():
    brand_id = brand_id_from_request()
    statuses = ["pending_approval", "pending", "published", "ready_manual", "rejected", "failed"]
    stats = {}
    for s in statuses:
        count = db.conn.execute(
            "SELECT COUNT(*) FROM scheduled_posts WHERE status=? AND brand_id=?", (s, brand_id)
        ).fetchone()[0]
        stats[s] = count
    return jsonify(stats)


@app.route("/api/check-token")
def check_token():
    """Full Meta token diagnostic."""
    from config.settings import META_ACCESS_TOKEN, FACEBOOK_PAGE_ID
    result = {}
    try:
        # 1. Permissions on current token
        perms = requests.get(
            "https://graph.facebook.com/v19.0/me/permissions",
            params={"access_token": META_ACCESS_TOKEN}, timeout=10,
        ).json()
        granted = [p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"]
        needed = ["pages_manage_posts", "pages_read_engagement", "pages_show_list"]
        result["granted_permissions"] = granted
        result["missing_permissions"] = [p for p in needed if p not in granted]

        # 2. What type of token (user vs page vs system)
        debug = requests.get(
            "https://graph.facebook.com/v19.0/debug_token",
            params={"input_token": META_ACCESS_TOKEN, "access_token": META_ACCESS_TOKEN},
            timeout=10,
        ).json().get("data", {})
        result["token_type"] = debug.get("type", "unknown")
        result["token_app_id"] = debug.get("app_id")

        # 3. Page token exchange via /{page_id}?fields=access_token (works for System Users)
        page_resp = requests.get(
            f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}",
            params={"fields": "access_token,name", "access_token": META_ACCESS_TOKEN},
            timeout=10,
        ).json()
        if "access_token" in page_resp:
            result["page_token_exchange"] = "OK"
            result["page_name"] = page_resp.get("name")
        else:
            result["page_token_exchange"] = "FAILED"
            result["page_token_error"] = page_resp.get("error", {}).get("message", str(page_resp))
    except Exception as e:
        result["error"] = str(e)
    return jsonify(result)


@app.route("/api/scheduler/trigger/<brand_id>/<platform>", methods=["POST"])
def scheduler_trigger(brand_id, platform):
    """Force-publish next approved post for a brand+platform, ignoring scheduled date. For testing."""
    result = scheduler.trigger_now(brand_id, platform)
    return jsonify(result)


@app.route("/api/scheduler/trigger/<platform>", methods=["POST"])
def scheduler_trigger_default(platform):
    """Trigger for default brand — kept for backward-compat with existing UI buttons."""
    result = scheduler.trigger_now(DEFAULT_BRAND_ID, platform)
    return jsonify(result)


@app.route("/api/scheduler/status")
def scheduler_status():
    brand_id = brand_id_from_request()
    upcoming = scheduler.get_upcoming(brand_id, limit=5)
    return jsonify({
        "running": scheduler.running,
        "upcoming": [
            {"id": r[0], "platform": r[1], "content_type": r[2],
             "scheduled_date": r[3], "status": r[4]}
            for r in upcoming
        ],
    })


@app.route("/api/posts/<int:post_id>/revise", methods=["POST"])
def revise_post(post_id: int):
    data = request.get_json(force=True) or {}
    feedback       = (data.get("feedback") or "").strip()
    brand_id       = data.get("brand") or DEFAULT_BRAND_ID
    current_content = (data.get("current_content") or "").strip()

    if not feedback:
        return jsonify({"error": "Se requiere feedback"}), 400

    row = db.conn.execute(
        "SELECT content, platform, content_type FROM scheduled_posts WHERE id=?",
        (post_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Post no encontrado"}), 404

    db_content, platform, content_type = row
    content = current_content or db_content or ""

    brand = BRANDS.get(brand_id, {})
    brand_name  = brand.get("name", brand_id)
    brand_voice = brand.get("voice", "profesional y cercano")
    brand_bio   = brand.get("bio", "")

    system = (
        f"Eres el director creativo de {brand_name}. "
        f"Voz de la marca: {brand_voice}. "
        f"{brand_bio} "
        "Cuando recibas un borrador de post y retroalimentación del editor, "
        "reescribe el post incorporando exactamente lo que se pide. "
        "Responde SOLO con el texto revisado del post — sin explicaciones, sin cabeceras."
    )

    user_msg = (
        f"Plataforma: {platform} ({content_type})\n\n"
        f"Borrador actual:\n{content}\n\n"
        f"Instrucción del editor:\n{feedback}\n\n"
        "Reescribe el post incorporando esa instrucción. "
        "Responde únicamente con el texto final del post."
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        revised = resp.content[0].text.strip()
        return jsonify({"revised_content": revised})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat_with_agent():
    data     = request.get_json(force=True) or {}
    message  = (data.get("message") or "").strip()
    brand_id = data.get("brand") or DEFAULT_BRAND_ID

    if not message:
        return jsonify({"error": "Mensaje vacío"}), 400

    brand = BRANDS.get(brand_id, {})
    brand_name  = brand.get("name", brand_id)
    brand_voice = brand.get("voice", "profesional y cercano")
    brand_bio   = brand.get("bio", "")
    platforms   = ", ".join(brand.get("platforms", ["instagram", "facebook"]))

    system = (
        f"Eres el director creativo y estratega de redes sociales de {brand_name}. "
        f"Plataformas activas: {platforms}. Voz de marca: {brand_voice}. {brand_bio} "
        "Respondes preguntas sobre estrategia de contenido, crecimiento de audiencia, "
        "tendencias, hashtags, copywriting, y mejores prácticas para redes sociales. "
        "Sé concreto, accionable y orientado a resultados. "
        "Responde en español."
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": message}],
        )
        reply = resp.content[0].text.strip()
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




def open_browser():
    webbrowser.open("http://localhost:5000")


@app.route("/voxify-stats")
def voxify_stats():
    """Devuelve métricas reales de voxify.db para Zeus CEO."""
    import sqlite3, datetime
    db_path = r"C:\Users\yaco8\OneDrive\Documentos\Voxify - Claude\voxify-n8n\voxify.db"
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM prospects_pool")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM prospects_pool WHERE estado_prospecto='CALIFICADO'")
        calificados = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM prospects_pool WHERE estado_prospecto='NUEVO'")
        nuevos = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM prospects_pool WHERE fecha_primer_contacto IS NOT NULL")
        contactados = c.fetchone()[0]
        today = datetime.date.today().isoformat()
        c.execute("SELECT SUM(requests_usados) FROM google_api_usage WHERE fecha=?", (today,))
        google_calls = c.fetchone()[0] or 0
        c.execute("SELECT SUM(costo_estimado) FROM google_api_usage")
        google_cost = c.fetchone()[0] or 0.0
        conn.close()
        return jsonify({
            "total_prospectos": total,
            "calificados": calificados,
            "nuevos": nuevos,
            "contactados": contactados,
            "google_calls_hoy": google_calls,
            "google_costo_total": round(google_cost, 4),
            "fecha": today,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leads/manual", methods=["POST"])
def save_manual_lead():
    """Guarda un lead identificado manualmente (desde Zeus WhatsApp/Telegram)."""
    import sqlite3, datetime
    db_path = r"C:\Users\yaco8\OneDrive\Documentos\Voxify - Claude\voxify-n8n\voxify.db"
    data = request.get_json(silent=True) or {}
    nombre   = (data.get("nombre_negocio") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    ciudad   = (data.get("ciudad") or "Orlando").strip()
    vertical = (data.get("vertical") or "restaurante").strip()
    notas    = (data.get("notas") or "Lead manual de Tatiana").strip()
    fuente   = data.get("fuente", "telegram_tatiana")
    if not nombre:
        return jsonify({"error": "nombre_negocio requerido"}), 400
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO prospects_pool
              (nombre_negocio, telefono, ciudad, vertical, estado, fuente_busqueda,
               notas, estado_prospecto, fecha_encontrado)
            VALUES (?,?,?,?,?,?,?,'NUEVO', date('now'))
        """, (nombre, telefono, ciudad, vertical, "FL", fuente, notas))
        lead_id = c.lastrowid
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "id": lead_id, "nombre": nombre})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.errorhandler(413)
def request_too_large(e):
    return jsonify({"error": "Archivos demasiado grandes. Máximo 200 MB por lote."}), 413


if __name__ == "__main__":
    validate_config()
    scheduler.start()
    atexit.register(scheduler.stop)
    threading.Timer(1.0, open_browser).start()
    print("\n VoxifyHub — Generación de Contenido")
    print(" Abriendo en http://localhost:5000")
    print(" Scheduler activo — posts se publican automáticamente en su horario ET")
    print(" Presiona Ctrl+C para detener.\n")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
