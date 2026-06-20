"""
Claude API — research (6 calls, selectable modules) + single post + content grid.
KPIs grounded in real Meta data. No SEO/SEM/Google Ads in any prompt.
"""
import json
import logging
import os
from datetime import datetime

import anthropic
from dotenv import load_dotenv

import meta_insights

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL_RESEARCH = "claude-haiku-4-5-20251001"
_MODEL_CONTENT  = "claude-sonnet-4-6"
_CLIENT = None

ALL_MODULES = ["competitors", "audience", "uvp", "hashtags", "kpis", "strategy"]


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    return _CLIENT


def _ask(prompt: str, max_tokens: int = 800) -> dict:
    resp = _client().messages.create(
        model=_MODEL_RESEARCH,
        max_tokens=max_tokens,
        messages=[
            {"role": "user",      "content": prompt},
            {"role": "assistant", "content": "{"},
        ],
    )
    raw = "{" + resp.content[0].text
    return _safe_parse(raw)


def _safe_parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            t = raw.rstrip()
            if t.endswith(","):
                t = t[:-1]
            open_b = t.count("{") - t.count("}")
            open_a = t.count("[") - t.count("]")
            t += "]" * max(0, open_a) + "}" * max(0, open_b)
            return json.loads(t)
        except Exception as e:
            logger.warning(f"[agent] parse failed: {e} | raw[:120]: {raw[:120]}")
            return {}


def research_brand(brand: dict, modules=None) -> dict:
    """
    Up to 6 independent Haiku calls for social-media research.
    modules: subset of ALL_MODULES, or None for all.
    KPIs are grounded in real Meta follower/engagement data.
    """
    if modules is None:
        modules = ALL_MODULES

    name     = brand.get("name", "")
    industry = brand.get("industry", "")
    geo      = brand.get("geography", "")
    desc     = brand.get("description", "")
    website  = brand.get("website_url", "")

    ctx = f"Marca: {name} | Industria: {industry} | Mercado: {geo}"
    if website: ctx += f" | Web: {website}"
    if desc:    ctx += f" | Descripción: {desc[:250]}"

    # Fetch real Meta baseline before KPI call
    baseline = {}
    if "kpis" in modules:
        try:
            baseline = meta_insights.brand_baseline(brand)
        except Exception as e:
            logger.warning(f"[agent] meta baseline: {e}")

    results = {}
    errors  = []

    # ── 1: Competitors + Differentiators ──────────────────────────────────────
    if "competitors" in modules:
        try:
            r = _ask(f"""{ctx}
Analiza competidores directos en redes sociales (Instagram, Facebook, TikTok) y diferenciadores clave.
Responde SOLO JSON:
{{"competitors": ["comp1","comp2","comp3","comp4"],
  "differentiators": ["dif1","dif2","dif3"]}}""", 800)
            if r.get("competitors"):     results["competitors"]     = r["competitors"]
            if r.get("differentiators"): results["differentiators"] = r["differentiators"]
        except Exception as e:
            errors.append(f"call1:{e}")

    # ── 2: Audience + Tone ────────────────────────────────────────────────────
    if "audience" in modules:
        try:
            r = _ask(f"""{ctx}
Define la audiencia ideal para redes sociales y el tono de comunicación de la marca.
Responde SOLO JSON:
{{"audience_profile": "2 líneas: edad, plataformas que usa, dolor principal que la marca resuelve",
  "brand_tone": "1 línea describiendo el tono de voz para redes sociales"}}""", 800)
            if r.get("audience_profile"): results["audience_profile"] = r["audience_profile"]
            if r.get("brand_tone"):       results["brand_tone"]       = r["brand_tone"]
        except Exception as e:
            errors.append(f"call2:{e}")

    # ── 3: Unique Value Proposition ───────────────────────────────────────────
    if "uvp" in modules:
        try:
            r = _ask(f"""{ctx}
Define la propuesta única de valor en una frase poderosa para redes sociales.
Responde SOLO JSON:
{{"unique_value_proposition": "una frase que captura el valor único de la marca"}}""", 800)
            if r.get("unique_value_proposition"):
                results["unique_value_proposition"] = r["unique_value_proposition"]
        except Exception as e:
            errors.append(f"call3:{e}")

    # ── 4: Hashtags ───────────────────────────────────────────────────────────
    if "hashtags" in modules:
        try:
            r = _ask(f"""{ctx}
Genera 15 hashtags estratégicos para Instagram y Facebook.
Mezcla hashtags de nicho, industria y alcance masivo.
Responde SOLO JSON:
{{"hashtags": ["#tag1","#tag2","#tag3","#tag4","#tag5","#tag6","#tag7","#tag8","#tag9","#tag10","#tag11","#tag12","#tag13","#tag14","#tag15"]}}""", 800)
            if r.get("hashtags"):
                existing = set(brand.get("hashtags") or [])
                new_tags = [t for t in r["hashtags"] if isinstance(t, str) and t.startswith("#")]
                results["hashtags"] = list(existing | set(new_tags))[:40]
        except Exception as e:
            errors.append(f"call4:{e}")

    # ── 5: KPIs grounded in real Meta data ────────────────────────────────────
    if "kpis" in modules:
        try:
            ig = baseline.get("instagram", {})
            fb = baseline.get("facebook", {})
            ig_followers = ig.get("followers", 0)
            ig_eng       = ig.get("engagement_rate_pct", 0)
            fb_fans      = fb.get("fans", 0)

            if ig_followers or fb_fans:
                data_ctx = (
                    f"DATOS REALES ACTUALES (Meta API):\n"
                    f"- Instagram: {ig_followers:,} seguidores, {ig_eng}% engagement rate\n"
                    f"- Facebook: {fb_fans:,} fans\n"
                    f"Los KPIs DEBEN ser incrementales sobre estas cifras. No inventes números base."
                )
            else:
                data_ctx = "No hay cifras reales disponibles. Define KPIs como porcentajes de crecimiento relativos."

            r = _ask(f"""{ctx}
{data_ctx}

Define KPIs de social media a 30, 60 y 90 días.
SOLO métricas de redes sociales: seguidores, engagement rate, alcance, impresiones, conversiones desde social.
Responde SOLO JSON:
{{"kpi_30_days": ["KPI con número concreto basado en cifras reales"],
  "kpi_60_days": ["KPI con número concreto basado en cifras reales"],
  "kpi_90_days": ["KPI con número concreto basado en cifras reales"]}}""", 800)
            for k in ("kpi_30_days", "kpi_60_days", "kpi_90_days"):
                if r.get(k): results[k] = r[k]
        except Exception as e:
            errors.append(f"call5:{e}")

    # ── 6: Strategy Phases (social media only) ────────────────────────────────
    if "strategy" in modules:
        try:
            r = _ask(f"""{ctx}
Define 3 fases de estrategia de CONTENIDO en redes sociales para 90 días.
SOLO estrategia de social media: tipos de contenido, frecuencia, formatos, comunidad, colaboraciones.
NO incluyas SEO, SEM, Google Ads, email marketing ni otras estrategias de marketing digital.
Responde SOLO JSON:
{{"strategy_phases": {{"phase_1": "Días 1-30: acción concreta en redes sociales",
                       "phase_2": "Días 31-60: acción concreta en redes sociales",
                       "phase_3": "Días 61-90: acción concreta en redes sociales"}}}}""", 800)
            if r.get("strategy_phases"): results["strategy_phases"] = r["strategy_phases"]
        except Exception as e:
            errors.append(f"call6:{e}")

    results["last_research"] = datetime.utcnow().isoformat()
    filled = sum(1 for k, v in results.items() if k != "last_research" and v)

    return {
        "success":       filled >= 4,
        "research":      results,
        "baseline":      baseline,
        "errors":        errors,
        "fields_filled": filled,
    }


def generate_post(brand: dict, platform: str = "instagram", topic: str = "") -> dict:
    name     = brand.get("name", "la marca")
    tone     = brand.get("brand_tone", "profesional y cercano")
    uvp      = brand.get("unique_value_proposition", "")
    hashtags = (brand.get("hashtags") or [])[:12]
    tags_str = " ".join(hashtags)
    industry = brand.get("industry", "")

    topic_line = f"Tema del post: {topic}" if topic else "Elige el tema más relevante hoy."

    resp = _client().messages.create(
        model=_MODEL_CONTENT,
        max_tokens=700,
        messages=[
            {"role": "user", "content": f"""Crea un post para {platform} de la marca {name}.
Industria: {industry} | Tono: {tone} | UVP: {uvp}
{topic_line}
Hashtags disponibles: {tags_str}
Responde SOLO JSON:
{{"caption": "texto completo con emojis y saltos de línea naturales",
  "hashtags_used": ["#tag1","#tag2","#tag3"],
  "topic": "tema elegido"}}"""},
            {"role": "assistant", "content": "{"},
        ]
    )
    raw = "{" + resp.content[0].text
    return _safe_parse(raw)


def generate_grid(brand: dict, weeks: int = 1, post_count: int = 3,
                  reel_count: int = 2, story_count: int = 5,
                  carousel_count: int = 1, platforms=None,
                  topic: str = "") -> dict:
    """
    4 independent calls: posts, reels, stories, carousels.
    Returns {success, grid:[...], total, errors}.
    Each item: {content_type, caption, hashtags, platform, day, time, topic, ...extras}
    """
    if platforms is None:
        platforms = ["instagram"]

    name     = brand.get("name", "")
    tone     = brand.get("brand_tone", "profesional y cercano")
    uvp      = brand.get("unique_value_proposition", "")
    hashtags = (brand.get("hashtags") or [])[:14]
    tags_str = " ".join(hashtags)
    industry = brand.get("industry", "")

    ctx = f"Marca: {name} | Industria: {industry} | Tono: {tone}"
    if uvp:   ctx += f" | UVP: {uvp[:120]}"
    plat_str  = ", ".join(platforms)
    topic_line = f"Tema central: {topic}" if topic else ""

    grid   = []
    errors = []

    # ── Posts estáticos ───────────────────────────────────────────────────────
    n = post_count * weeks
    if n > 0:
        try:
            r = _ask(f"""{ctx}
{topic_line}
Plataformas: {plat_str} | Hashtags: {tags_str}

Crea exactamente {n} publicaciones tipo POST (imagen estática o foto).
Variedad: educativo, inspiracional, behind-the-scenes, testimonial.
Distribuye en Lunes, Miércoles y Viernes a las 10:00, 13:00 o 18:00.
Responde SOLO JSON:
{{"items":[{{"caption":"texto con emojis","hashtags":["#tag"],"platform":"{platforms[0]}","day":"Lunes","time":"10:00","topic":"tema"}}]}}""", 1400)
            for item in r.get("items", []):
                item["content_type"] = "post"
                grid.append(item)
        except Exception as e:
            errors.append(f"posts:{e}")

    # ── Reels ─────────────────────────────────────────────────────────────────
    n = reel_count * weeks
    if n > 0:
        try:
            r = _ask(f"""{ctx}
{topic_line}
Plataformas: {plat_str}

Crea exactamente {n} guiones para REELS (video 15-60 segundos).
Cada reel: hook en los primeros 3 segundos, desarrollo y CTA al final.
Programa en Martes o Jueves a las 18:00 o 20:00 (mayor alcance orgánico).
Responde SOLO JSON:
{{"items":[{{"caption":"caption completo","hashtags":["#tag"],"platform":"instagram","day":"Martes","time":"18:00","topic":"tema","hook":"primeras 5-8 palabras del video"}}]}}""", 1200)
            for item in r.get("items", []):
                item["content_type"] = "reel"
                grid.append(item)
        except Exception as e:
            errors.append(f"reels:{e}")

    # ── Stories ───────────────────────────────────────────────────────────────
    n = story_count * weeks
    if n > 0:
        try:
            r = _ask(f"""{ctx}
{topic_line}

Crea exactamente {n} ideas para STORIES (efímeras, 24h).
Tipos: encuesta, pregunta abierta, behind-the-scenes, dato rápido, CTA, cuenta regresiva.
Distribuye mañana (09:00) y tarde (17:00) a lo largo de la semana.
Responde SOLO JSON:
{{"items":[{{"caption":"texto breve (max 2 líneas)","hashtags":[],"platform":"instagram","day":"Lunes","time":"09:00","topic":"tema","story_type":"encuesta"}}]}}""", 1200)
            for item in r.get("items", []):
                item["content_type"] = "story"
                grid.append(item)
        except Exception as e:
            errors.append(f"stories:{e}")

    # ── Carruseles ────────────────────────────────────────────────────────────
    n = carousel_count * weeks
    if n > 0:
        try:
            r = _ask(f"""{ctx}
{topic_line}
Hashtags: {tags_str}

Crea exactamente {n} carruseles de 5-7 slides.
Estructura: slide 1 = hook, slides 2-6 = desarrollo, último slide = CTA.
Programa en Miércoles o Viernes a las 12:00.
Responde SOLO JSON:
{{"items":[{{"caption":"caption completo del carrusel","hashtags":["#tag"],"platform":"instagram","day":"Miércoles","time":"12:00","topic":"tema","slides":[{{"title":"Slide 1","content":"texto"}}]}}]}}""", 1400)
            for item in r.get("items", []):
                item["content_type"] = "carousel"
                grid.append(item)
        except Exception as e:
            errors.append(f"carousels:{e}")

    return {
        "success": len(grid) > 0,
        "grid":    grid,
        "total":   len(grid),
        "errors":  errors,
    }
