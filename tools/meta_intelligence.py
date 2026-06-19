"""
Meta Intelligence — tendencias, hooks, y calibración semanal de estrategia.
Combina datos reales de Meta Insights API con análisis Claude para:
  • Detectar hooks que detienen el scroll
  • Identificar hashtags en tendencia
  • Sugerir música/mood para Reels
  • Recalibrar estrategia semanalmente con data de performance
"""

import json
import logging
import os
from datetime import datetime, timedelta

import requests
import anthropic

from config.settings import ANTHROPIC_API_KEY, AGENT_MODEL

logger = logging.getLogger(__name__)
GRAPH_API = "https://graph.facebook.com/v19.0"

_claude = None
def _client():
    global _claude
    if _claude is None:
        _claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude


# ── Meta API: sincronización de métricas ─────────────────────────────────────

def _get_token(credentials: dict) -> str:
    return (
        credentials.get("meta_access_token")
        or credentials.get("facebook_page_access_token")
        or os.environ.get("META_ACCESS_TOKEN", "")
    )


def sync_brand_metrics(db, brand_id: str, credentials: dict) -> dict:
    """
    Pull Meta Insights for all published brand posts that don't have metrics yet.
    Updates reach, impressions, likes, comments, saves, shares, engagement_rate in DB.
    Returns summary of what was synced.
    """
    token = _get_token(credentials)
    if not token:
        return {"synced": 0, "error": "No Meta token configured for this brand"}

    rows = db.conn.execute(
        """SELECT id, external_post_id, platform FROM scheduled_posts
           WHERE brand_id=? AND status='published'
           AND external_post_id IS NOT NULL AND reach IS NULL""",
        (brand_id,)
    ).fetchall()

    synced, errors = 0, 0
    for post_id, ext_id, platform in rows:
        try:
            if platform == "instagram":
                r = requests.get(
                    f"{GRAPH_API}/{ext_id}/insights",
                    params={
                        "metric": "reach,impressions,likes_count,comments_count,saved,shares",
                        "access_token": token,
                    }, timeout=12,
                )
                data = r.json()
                if "error" in data:
                    errors += 1
                    continue
                metrics = {item["name"]: item.get("values", [{}])[-1].get("value", 0)
                           for item in data.get("data", [])}
                likes    = metrics.get("likes_count", 0)
                comments = metrics.get("comments_count", 0)
                saves    = metrics.get("saved", 0)
                shares   = metrics.get("shares", 0)
                reach    = max(metrics.get("reach", 1), 1)
                er = round((likes + comments + saves + shares) / reach * 100, 2)
                db.conn.execute(
                    """UPDATE scheduled_posts SET
                       reach=?, impressions=?, likes=?, comments=?,
                       saves=?, shares=?, engagement_rate=? WHERE id=?""",
                    (reach, metrics.get("impressions", 0), likes, comments, saves, shares, er, post_id),
                )
                synced += 1

            elif platform == "facebook":
                r = requests.get(
                    f"{GRAPH_API}/{ext_id}/insights",
                    params={
                        "metric": "post_impressions,post_engaged_users,post_clicks",
                        "access_token": token,
                    }, timeout=12,
                )
                data = r.json()
                if "error" in data:
                    errors += 1
                    continue
                metrics = {item["name"]: item.get("values", [{}])[-1].get("value", 0)
                           for item in data.get("data", [])}
                impressions = max(metrics.get("post_impressions", 1), 1)
                engaged     = metrics.get("post_engaged_users", 0)
                er = round(engaged / impressions * 100, 2)
                db.conn.execute(
                    """UPDATE scheduled_posts SET impressions=?, likes=?, engagement_rate=? WHERE id=?""",
                    (impressions, engaged, er, post_id),
                )
                synced += 1

        except Exception as e:
            logger.error(f"sync_metrics post {ext_id}: {e}")
            errors += 1

    db.conn.commit()
    return {"synced": synced, "errors": errors, "pending": len(rows) - synced - errors}


# ── Performance analysis ──────────────────────────────────────────────────────

def analyze_brand_performance(db, brand_id: str, days: int = 28) -> dict:
    """
    Deep analysis of published posts for a brand in the last N days.
    Returns winning patterns, top posts, format rankings, hook patterns.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT platform, content_type, content, reach, impressions,
                  likes, comments, saves, shares, engagement_rate, published_at
           FROM scheduled_posts
           WHERE brand_id=? AND status='published' AND published_at >= ?
           ORDER BY engagement_rate DESC NULLS LAST""",
        (brand_id, since),
    ).fetchall()

    cols = ["platform", "content_type", "content", "reach", "impressions",
            "likes", "comments", "saves", "shares", "engagement_rate", "published_at"]
    posts = [dict(zip(cols, r)) for r in rows]

    if not posts:
        return {"status": "sin_posts", "days": days,
                "message": "No hay posts publicados en este período."}

    with_metrics = [p for p in posts if p.get("engagement_rate") is not None]
    if not with_metrics:
        return {"status": "sin_metricas", "posts_publicados": len(posts),
                "message": "Posts publicados pero sin métricas de Meta aún. Ejecuta sync_brand_metrics."}

    sorted_posts = sorted(with_metrics, key=lambda x: x.get("engagement_rate", 0), reverse=True)

    def avg(lst, key):
        vals = [p.get(key) or 0 for p in lst]
        return round(sum(vals) / len(vals), 2) if vals else 0

    from collections import Counter
    platform_er    = {}
    content_type_er = {}
    for p in with_metrics:
        platform_er.setdefault(p["platform"], []).append(p.get("engagement_rate", 0))
        content_type_er.setdefault(p["content_type"], []).append(p.get("engagement_rate", 0))

    platform_avg    = {k: round(sum(v)/len(v), 2) for k, v in platform_er.items()}
    content_type_avg = {k: round(sum(v)/len(v), 2) for k, v in content_type_er.items()}

    # Identify best day of week
    day_er = {}
    for p in with_metrics:
        if p.get("published_at"):
            try:
                dt = datetime.fromisoformat(str(p["published_at"])[:10])
                day = dt.strftime("%A")
                day_er.setdefault(day, []).append(p.get("engagement_rate", 0))
            except Exception:
                pass
    day_avg = {k: round(sum(v)/len(v), 2) for k, v in day_er.items()}

    # Hook patterns from top posts
    top_hooks = []
    for p in sorted_posts[:5]:
        content = p.get("content", "")
        first_line = content.split("\n")[0][:80] if content else ""
        top_hooks.append({
            "hook": first_line,
            "platform": p["platform"],
            "type": p["content_type"],
            "er": p.get("engagement_rate", 0),
            "saves": p.get("saves", 0),
        })

    # Saves analysis (saves = educational/evergreen value)
    high_saves = sorted(with_metrics, key=lambda x: x.get("saves") or 0, reverse=True)[:3]

    best_platform = max(platform_avg, key=platform_avg.get) if platform_avg else "?"
    best_format   = max(content_type_avg, key=content_type_avg.get) if content_type_avg else "?"
    best_day      = max(day_avg, key=day_avg.get) if day_avg else "?"

    return {
        "periodo_analizado": f"Últimos {days} días",
        "posts_con_metricas": len(with_metrics),
        "engagement_promedio": avg(with_metrics, "engagement_rate"),
        "mejor_post_er": sorted_posts[0].get("engagement_rate", 0),
        "peor_post_er":  sorted_posts[-1].get("engagement_rate", 0),
        "por_plataforma": platform_avg,
        "por_formato":    content_type_avg,
        "por_dia":        day_avg,
        "mejor_plataforma": best_platform,
        "mejor_formato":    best_format,
        "mejor_dia":        best_day,
        "top_5_posts": top_hooks,
        "posts_mas_guardados": [
            {"hook": p.get("content","")[:60], "saves": p.get("saves",0)} for p in high_saves
        ],
        "insight_principal": (
            f"Tu mejor formato es {best_format} en {best_platform} — "
            f"engagement promedio del {avg(with_metrics, 'engagement_rate')}%"
        ),
    }


# ── Trending elements (Claude-powered) ───────────────────────────────────────

def get_trending_elements(brand: dict, performance: dict, week_num: int) -> dict:
    """
    Generate scroll-stopping hooks, trending hashtags, and Reel music moods
    calibrated to this brand, industry, and current Meta trends.
    """
    today = datetime.now()
    industry   = brand.get("industry", "")
    brand_name = brand.get("name", "")
    audience   = brand.get("audience", {})
    geo        = audience.get("geography", "hispanohablantes en EE.UU.")
    hashtags   = brand.get("hashtags", [])

    perf_summary = ""
    if performance.get("status") not in ("sin_posts", "sin_metricas"):
        perf_summary = f"""
RENDIMIENTO REAL DE POSTS ANTERIORES:
- Engagement promedio: {performance.get('engagement_promedio', '?')}%
- Mejor formato: {performance.get('mejor_formato', '?')}
- Mejor plataforma: {performance.get('mejor_plataforma', '?')}
- Mejor día: {performance.get('mejor_dia', '?')}
- Hooks que funcionaron:
{chr(10).join(f"  • [{p['type']}] {p['hook']} (ER: {p['er']}%)" for p in performance.get('top_5_posts', [])[:3])}
"""

    prompt = f"""Eres el director de estrategia de contenido y tendencias de Meta (Instagram + Facebook) para el mercado hispano en EE.UU.

MARCA: {brand_name}
INDUSTRIA: {industry}
AUDIENCIA: {geo}
FECHA: {today.strftime('%d de %B de %Y')} | Semana {week_num}
HASHTAGS BASE DE LA MARCA: {', '.join(hashtags[:8])}
{perf_summary}

TAREA: Genera los elementos de inteligencia de tendencias para la semana que empieza.

Responde ÚNICAMENTE con JSON válido (sin texto antes ni después):
{{
  "hooks_scroll_stopping": [
    {{
      "hook": "texto del hook — máximo 15 palabras en primera línea",
      "tipo": "pregunta_retórica|estadística_sorpresa|verdad_incómoda|identificación|transformación",
      "formato_ideal": "reel|carrusel|post_estático|story",
      "por_que_funciona": "razón psicológica en 1 frase",
      "engagement_esperado": "alto|muy_alto|explosivo"
    }}
  ],
  "hashtag_clusters": {{
    "principal": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
    "nicho_industria": ["#tag6", "#tag7", "#tag8", "#tag9", "#tag10"],
    "comunidad_hispana": ["#tag11", "#tag12", "#tag13", "#tag14", "#tag15"],
    "tendencia_semana": ["#tag16", "#tag17", "#tag18", "#tag19", "#tag20"],
    "hashtag_semana_recomendado": "#tagPrincipal"
  }},
  "musica_reels": [
    {{
      "mood": "nombre del mood",
      "descripcion": "describe el estilo musical",
      "bpm_referencia": "90-110",
      "tipo_contenido": "qué tipo de reel va mejor con este mood",
      "ejemplos_genero": ["género1", "género2"]
    }}
  ],
  "formatos_tendencia_semana": [
    {{
      "formato": "nombre del formato",
      "descripcion": "cómo ejecutarlo",
      "duracion_ideal": "7s|15s|30s|60s|carrusel",
      "pilar_recomendado": "pilar de contenido que mejor aplica"
    }}
  ],
  "tendencias_contenido": [
    {{
      "tendencia": "nombre de la tendencia",
      "como_aplicar_a_marca": "instrucción específica para {brand_name}",
      "urgencia": "esta_semana|próximo_mes"
    }}
  ],
  "resumen_ejecutivo": "3 frases sobre qué priorizar esta semana para máximo alcance y engagement"
}}

Genera exactamente 10 hooks, 20 hashtags totales (5 por cluster), 3 moods de música, 3 formatos tendencia, 2 tendencias de contenido."""

    try:
        msg = _client().messages.create(
            model=AGENT_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"get_trending_elements error: {e}")
        return {"error": str(e), "hooks_scroll_stopping": [], "hashtag_clusters": {}, "musica_reels": []}


def calibrate_weekly_strategy(brand: dict, performance: dict, trends: dict) -> str:
    """
    Generate full weekly strategy calibration.
    Returns an actionable brief for the content agent to use.
    """
    brand_name = brand.get("name", "")
    content_lines = brand.get("content_lines") or brand.get("content_pillars", [])

    prompt = f"""Eres el estratega jefe de {brand_name}. Genera la CALIBRACIÓN ESTRATÉGICA SEMANAL.

═══ DATOS DE RENDIMIENTO (semana/mes anterior) ═══
{json.dumps(performance, ensure_ascii=False, indent=2)}

═══ TENDENCIAS DETECTADAS ═══
Resumen: {trends.get('resumen_ejecutivo', 'Sin datos de tendencias')}
Formato tendencia: {json.dumps(trends.get('formatos_tendencia_semana', [])[:2], ensure_ascii=False)}
Hooks recomendados: {json.dumps([h['hook'] for h in trends.get('hooks_scroll_stopping', [])[:3]], ensure_ascii=False)}

═══ ESTRATEGIA ACTUAL DE LA MARCA ═══
Pilares de contenido: {json.dumps([p.get('name','?') + ' (' + str(int(float(p.get('percentage',0))*100 if float(p.get('percentage',0))<=1 else p.get('percentage',0))) + '%)' for p in content_lines], ensure_ascii=False)}
Research summary: {brand.get('research_summary', 'No disponible')[:500]}

Genera la CALIBRACIÓN en este formato exacto:

## ANÁLISIS DE LA SEMANA ANTERIOR
• [qué funcionó — dato específico]
• [qué falló — dato específico]
• [patrón más importante detectado]

## AJUSTES PARA ESTA SEMANA
**Formato a priorizar:** [nombre del formato + razón basada en datos]
**Formato a reducir:** [nombre + razón]
**Pilar a reforzar:** [nombre + % sugerido esta semana]
**Pilar a reducir:** [nombre + razón]

## HOOK CONDUCTOR DE LA SEMANA
[El hook principal — esta frase debe aparecer o adaptarse en cada post como hilo conductor]

## HASHTAG CLUSTER SEMANAL (20 tags)
[Los 20 hashtags en formato #tag1 #tag2... ordenados de mayor a menor volumen]

## MÚSICA PARA REELS ESTA SEMANA
1. [mood + descripción + qué reel aplica]
2. [mood + descripción + qué reel aplica]

## ALERTA SEMANAL
[Si hay algo urgente que cambiar. Si todo está bien, escribe "Sin alertas críticas"]

## INSTRUCCIÓN ESPECIAL PARA EL AGENTE
[Una instrucción específica que el agente debe priorizar en la generación de contenido esta semana]"""

    try:
        msg = _client().messages.create(
            model=AGENT_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"calibrate_strategy error: {e}")
        return f"Error generando calibración: {e}"


# ── Agent tools ───────────────────────────────────────────────────────────────

META_INTELLIGENCE_TOOLS = [
    {
        "name": "sync_and_analyze_meta_performance",
        "description": (
            "Sincroniza métricas reales de Meta API (reach, engagement, saves, shares) para los posts "
            "publicados de la marca actual, luego analiza qué formatos, hooks y días generan más "
            "engagement. Úsalo SIEMPRE al inicio de la generación semanal para fundamentar decisiones con datos reales."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Período de análisis en días (default 28)",
                    "default": 28,
                }
            },
        },
    },
    {
        "name": "get_trending_hooks_and_hashtags",
        "description": (
            "Genera los 10 hooks que detienen el scroll, los 20 hashtags en tendencia, "
            "3 moods de música para Reels, y 3 formatos de tendencia para esta semana — "
            "calibrados a la industria de la marca y los resultados de performance previos. "
            "Retorna todo listo para usar en los posts de la semana."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "calibrate_weekly_strategy",
        "description": (
            "Genera la calibración estratégica completa de la semana: qué ajustar en los pilares, "
            "qué formato priorizar, el hook conductor de la semana, el hashtag cluster de 20 tags, "
            "música para Reels, y alertas — todo basado en data real de Meta + tendencias detectadas. "
            "Llámalo después de sync_and_analyze_meta_performance y get_trending_hooks_and_hashtags."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def execute_meta_intelligence_tool(tool_name: str, tool_input: dict,
                                   db, brand: dict) -> str:
    """Dispatch handler for META_INTELLIGENCE_TOOLS."""
    credentials = brand.get("credentials", {})
    brand_id    = brand.get("id", "")

    if tool_name == "sync_and_analyze_meta_performance":
        days = int(tool_input.get("days", 28))
        sync_result = sync_brand_metrics(db, brand_id, credentials)
        perf = analyze_brand_performance(db, brand_id, days)
        return json.dumps({
            "sync": sync_result,
            "performance": perf,
        }, ensure_ascii=False)

    if tool_name == "get_trending_hooks_and_hashtags":
        perf = analyze_brand_performance(db, brand_id, 28)
        week_num = datetime.now().isocalendar()[1]
        trends = get_trending_elements(brand, perf, week_num)
        # Cache trends in brand's session state
        db.conn.execute(
            """INSERT INTO weekly_strategy (week_number, year, phase, theme, analysis, brand_id)
               VALUES (?,?,?,?,?,?)""",
            (week_num, datetime.now().year, 0, "trends_cache",
             json.dumps(trends, ensure_ascii=False)[:4000], brand_id),
        )
        db.conn.commit()
        return json.dumps(trends, ensure_ascii=False)

    if tool_name == "calibrate_weekly_strategy":
        perf = analyze_brand_performance(db, brand_id, 28)
        week_num = datetime.now().isocalendar()[1]
        # Try to load cached trends from this week
        trends_row = db.conn.execute(
            """SELECT analysis FROM weekly_strategy
               WHERE brand_id=? AND theme='trends_cache' AND week_number=? AND year=?
               ORDER BY id DESC LIMIT 1""",
            (brand_id, week_num, datetime.now().year),
        ).fetchone()
        trends = json.loads(trends_row[0]) if trends_row else get_trending_elements(brand, perf, week_num)
        calibration = calibrate_weekly_strategy(brand, perf, trends)
        # Save calibration
        db.conn.execute(
            """INSERT INTO weekly_strategy (week_number, year, phase, theme, analysis, brand_id)
               VALUES (?,?,?,?,?,?)""",
            (week_num, datetime.now().year, 0, "calibration",
             calibration[:4000], brand_id),
        )
        db.conn.commit()
        return json.dumps({"calibration": calibration}, ensure_ascii=False)

    return json.dumps({"error": f"Herramienta no reconocida: {tool_name}"}, ensure_ascii=False)
