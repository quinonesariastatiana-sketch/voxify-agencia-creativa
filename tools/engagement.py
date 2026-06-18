"""
Engagement loop: monitor comments/DMs and generate suggested responses.
Keeps VoxifyHub's 2-hour response rule alive with AI-suggested replies.
"""

import json
import logging
import requests

logger = logging.getLogger(__name__)
GRAPH_API = "https://graph.facebook.com/v19.0"


def get_recent_comments(limit: int = 20) -> list:
    """Fetch recent comments on Instagram posts via Meta Graph API."""
    from config.settings import META_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID
    if not META_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ACCOUNT_ID:
        return []
    try:
        # Get recent media
        media_r = requests.get(
            f"{GRAPH_API}/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
            params={"fields": "id,timestamp", "limit": 5, "access_token": META_ACCESS_TOKEN},
            timeout=15,
        )
        media_data = media_r.json().get("data", [])
        comments = []
        for media in media_data:
            c_r = requests.get(
                f"{GRAPH_API}/{media['id']}/comments",
                params={"fields": "id,text,username,timestamp", "access_token": META_ACCESS_TOKEN},
                timeout=15,
            )
            for c in c_r.json().get("data", []):
                c["media_id"] = media["id"]
                comments.append(c)
            if len(comments) >= limit:
                break
        return comments[:limit]
    except Exception as e:
        logger.error(f"Error fetching comments: {e}")
        return []


def get_unanswered_comments(db) -> list:
    """Return comments stored locally that haven't been responded to yet."""
    rows = db.conn.execute(
        "SELECT id, platform, comment_id, username, text, media_id, created_at FROM engagement_comments WHERE responded = 0 ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return [
        {"id": r[0], "platform": r[1], "comment_id": r[2], "username": r[3],
         "text": r[4], "media_id": r[5], "created_at": r[6]}
        for r in rows
    ]


def sync_comments(db) -> int:
    """Pull latest comments from Instagram and store new ones."""
    comments = get_recent_comments()
    added = 0
    for c in comments:
        existing = db.conn.execute(
            "SELECT id FROM engagement_comments WHERE comment_id=?", (c["id"],)
        ).fetchone()
        if not existing:
            db.conn.execute(
                "INSERT INTO engagement_comments (platform, comment_id, username, text, media_id) VALUES (?,?,?,?,?)",
                ("instagram", c["id"], c.get("username", ""), c.get("text", ""), c.get("media_id", "")),
            )
            added += 1
    db.conn.commit()
    return added


def mark_comment_responded(db, comment_db_id: int):
    db.conn.execute("UPDATE engagement_comments SET responded=1, responded_at=datetime('now') WHERE id=?", (comment_db_id,))
    db.conn.commit()


def get_engagement_summary(db) -> dict:
    """Summary of engagement activity for the agent."""
    total = db.conn.execute("SELECT COUNT(*) FROM engagement_comments").fetchone()[0]
    unanswered = db.conn.execute("SELECT COUNT(*) FROM engagement_comments WHERE responded=0").fetchone()[0]
    recent = db.conn.execute(
        "SELECT username, text FROM engagement_comments WHERE responded=0 ORDER BY created_at DESC LIMIT 5"
    ).fetchall()

    return {
        "total_comentarios": total,
        "sin_responder": unanswered,
        "urgente": unanswered > 5,
        "ejemplos_sin_responder": [{"usuario": r[0], "comentario": r[1][:100]} for r in recent],
        "alerta": f"Tienes {unanswered} comentarios sin responder. La regla es <2 horas." if unanswered > 0 else "Todos los comentarios respondidos.",
    }


# ── Agent tools ────────────────────────────────────────────────────────────

ENGAGEMENT_TOOLS = [
    {
        "name": "get_engagement_data",
        "description": (
            "Obtiene el estado del engagement: comentarios sin responder, "
            "alertas de respuesta tardía, y ejemplos de comentarios recientes. "
            "Úsalo para incluir el contexto de engagement en la estrategia semanal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sync": {
                    "type": "boolean",
                    "description": "Si true, sincroniza comentarios nuevos desde Instagram antes de analizar.",
                    "default": True,
                }
            },
        },
    },
    {
        "name": "generate_comment_responses",
        "description": (
            "Genera respuestas sugeridas para los comentarios sin responder en Instagram. "
            "Las respuestas son en español, cercanas, y en la voz de VoxifyHub. "
            "Retorna una lista de comentario → respuesta sugerida lista para copiar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_comments": {
                    "type": "integer",
                    "description": "Máximo de comentarios a responder (default 10).",
                    "default": 10,
                }
            },
        },
    },
]


def execute_engagement_tool(tool_name: str, tool_input: dict, db) -> str:
    if tool_name == "get_engagement_data":
        if tool_input.get("sync", True):
            added = sync_comments(db)
            logger.info(f"Comentarios sincronizados: {added} nuevos")
        result = get_engagement_summary(db)
        return json.dumps(result, ensure_ascii=False)

    if tool_name == "generate_comment_responses":
        unanswered = get_unanswered_comments(db)[:tool_input.get("max_comments", 10)]
        if not unanswered:
            return json.dumps({"message": "No hay comentarios sin responder. ¡Excelente!"}, ensure_ascii=False)
        # Return the comments for Claude to generate responses inline
        return json.dumps({
            "comentarios_pendientes": unanswered,
            "instruccion": (
                "Genera una respuesta para cada comentario. "
                "Voz: cercana, en español, con el tono de VoxifyHub. "
                "Máximo 2-3 oraciones por respuesta. Termina con una pregunta o CTA cuando aplique."
            ),
        }, ensure_ascii=False)

    return json.dumps({"error": f"Herramienta no reconocida: {tool_name}"}, ensure_ascii=False)
