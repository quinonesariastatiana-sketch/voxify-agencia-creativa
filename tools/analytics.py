"""
Performance analytics: Meta Insights API + local performance tracking.
Feeds the agent with data on what's working before generating new content.
"""

import json
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v19.0"


# ── Meta Insights API ─────────────────────────────────────────────────────

def get_instagram_post_insights(media_id: str) -> dict:
    """Get engagement metrics for a single Instagram post."""
    from config.settings import META_ACCESS_TOKEN
    if not META_ACCESS_TOKEN:
        return {}
    try:
        r = requests.get(
            f"{GRAPH_API}/{media_id}/insights",
            params={
                "metric": "reach,impressions,likes_count,comments_count,saved,shares",
                "access_token": META_ACCESS_TOKEN,
            },
            timeout=15,
        )
        data = r.json()
        if "error" in data:
            return {}
        metrics = {}
        for item in data.get("data", []):
            metrics[item["name"]] = item.get("values", [{}])[-1].get("value", 0)
        return metrics
    except Exception as e:
        logger.error(f"Error getting IG insights: {e}")
        return {}


def get_account_insights(days: int = 28) -> dict:
    """Get account-level metrics for the last N days."""
    from config.settings import META_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID
    if not META_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ACCOUNT_ID:
        return {}
    try:
        since = int((datetime.now() - timedelta(days=days)).timestamp())
        until = int(datetime.now().timestamp())
        r = requests.get(
            f"{GRAPH_API}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/insights",
            params={
                "metric": "reach,impressions,follower_count,profile_views,website_clicks",
                "period": "day",
                "since": since,
                "until": until,
                "access_token": META_ACCESS_TOKEN,
            },
            timeout=15,
        )
        data = r.json()
        if "error" in data:
            return {}
        result = {}
        for item in data.get("data", []):
            values = item.get("values", [])
            total = sum(v.get("value", 0) for v in values)
            result[item["name"]] = total
        return result
    except Exception as e:
        logger.error(f"Error getting account insights: {e}")
        return {}


# ── Local performance analysis ─────────────────────────────────────────────

def analyze_local_performance(db) -> dict:
    """
    Analyze performance of published posts stored in the database.
    Returns insights about what content types, topics, and platforms perform best.
    """
    rows = db.conn.execute(
        """SELECT platform, content_type, content, external_post_id,
                  reach, impressions, likes, comments, saves, shares, engagement_rate
           FROM scheduled_posts
           WHERE status = 'published' AND reach IS NOT NULL
           ORDER BY engagement_rate DESC"""
    ).fetchall()

    if not rows:
        return {"status": "sin_datos", "message": "Aún no hay métricas de posts publicados."}

    analysis = {
        "total_posts_analizados": len(rows),
        "mejor_plataforma": {},
        "mejor_tipo_contenido": {},
        "top_posts": [],
        "promedios": {},
        "insights": [],
    }

    by_platform = {}
    by_type = {}
    all_rates = []

    for row in rows:
        platform, ctype, content, post_id, reach, impressions, likes, comments, saves, shares, er = row
        er = er or 0

        by_platform.setdefault(platform, []).append(er)
        by_type.setdefault(ctype, []).append(er)
        all_rates.append(er)

        analysis["top_posts"].append({
            "platform": platform,
            "content_type": ctype,
            "engagement_rate": round(er, 2),
            "saves": saves or 0,
            "preview": content[:80] + "..." if content else "",
        })

    # Sort top posts
    analysis["top_posts"] = sorted(analysis["top_posts"], key=lambda x: x["engagement_rate"], reverse=True)[:5]

    # Best platform
    for p, rates in by_platform.items():
        analysis["mejor_plataforma"][p] = round(sum(rates) / len(rates), 2)

    # Best content type
    for t, rates in by_type.items():
        analysis["mejor_tipo_contenido"][t] = round(sum(rates) / len(rates), 2)

    # Averages
    analysis["promedios"]["engagement_rate"] = round(sum(all_rates) / len(all_rates), 2)

    # Generate insights
    best_platform = max(analysis["mejor_plataforma"], key=analysis["mejor_plataforma"].get) if analysis["mejor_plataforma"] else None
    best_type = max(analysis["mejor_tipo_contenido"], key=analysis["mejor_tipo_contenido"].get) if analysis["mejor_tipo_contenido"] else None

    if best_platform:
        analysis["insights"].append(f"{best_platform.capitalize()} tiene el mejor engagement ({analysis['mejor_plataforma'][best_platform]}%)")
    if best_type:
        analysis["insights"].append(f"El formato '{best_type}' genera más interacción — priorizar esta semana")
    if analysis["promedios"]["engagement_rate"] < 3:
        analysis["insights"].append("El engagement está bajo del 3% — probar hooks más directos y CTAs más fuertes")
    elif analysis["promedios"]["engagement_rate"] >= 5:
        analysis["insights"].append("Engagement saludable — mantener el estilo de contenido actual")

    return analysis


def sync_post_metrics(db) -> int:
    """
    Fetch and store metrics for all published posts that don't have metrics yet.
    Returns number of posts updated.
    """
    rows = db.conn.execute(
        "SELECT id, external_post_id, platform FROM scheduled_posts WHERE status='published' AND external_post_id IS NOT NULL AND reach IS NULL"
    ).fetchall()

    updated = 0
    for post_id, ext_id, platform in rows:
        if platform == "instagram" and ext_id:
            metrics = get_instagram_post_insights(ext_id)
            if metrics:
                db.conn.execute(
                    """UPDATE scheduled_posts SET
                       reach=?, impressions=?, likes=?, comments=?, saves=?, shares=?,
                       engagement_rate=?
                       WHERE id=?""",
                    (
                        metrics.get("reach", 0),
                        metrics.get("impressions", 0),
                        metrics.get("likes_count", 0),
                        metrics.get("comments_count", 0),
                        metrics.get("saved", 0),
                        metrics.get("shares", 0),
                        round((metrics.get("likes_count", 0) + metrics.get("comments_count", 0) +
                               metrics.get("saved", 0)) / max(metrics.get("reach", 1), 1) * 100, 2),
                        post_id,
                    ),
                )
                updated += 1
    db.conn.commit()
    return updated


# ── Agent tools ────────────────────────────────────────────────────────────

ANALYTICS_TOOLS = [
    {
        "name": "analyze_performance",
        "description": (
            "Analiza el rendimiento de los posts publicados de VoxifyHub. "
            "Retorna: mejor plataforma, mejor tipo de contenido, engagement rate promedio, "
            "top 5 posts con mayor engagement, e insights accionables para mejorar el contenido esta semana."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sync_metrics": {
                    "type": "boolean",
                    "description": "Si true, sincroniza métricas desde Meta API antes de analizar.",
                    "default": True,
                }
            },
        },
    },
    {
        "name": "get_account_growth",
        "description": (
            "Obtiene métricas de crecimiento de la cuenta de Instagram en los últimos 28 días: "
            "alcance total, impresiones, vistas de perfil, clicks al sitio web."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def execute_analytics_tool(tool_name: str, tool_input: dict, db) -> str:
    if tool_name == "analyze_performance":
        if tool_input.get("sync_metrics", True):
            synced = sync_post_metrics(db)
            logger.info(f"Métricas sincronizadas: {synced} posts actualizados")
        result = analyze_local_performance(db)
        return json.dumps(result, ensure_ascii=False)

    if tool_name == "get_account_growth":
        result = get_account_insights(days=28)
        if not result:
            return json.dumps({"status": "sin_datos", "message": "No se pudo conectar con Meta Insights."}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    return json.dumps({"error": f"Herramienta no reconocida: {tool_name}"}, ensure_ascii=False)
