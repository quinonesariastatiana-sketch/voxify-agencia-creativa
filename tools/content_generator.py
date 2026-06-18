"""Content generation tools exposed to the creative director agent."""

import json
from config.brand import CONTENT_TYPES

# ── Tool definitions ───────────────────────────────────────────────────────

CONTENT_TOOLS = [
    {
        "name": "generate_content_plan",
        "description": (
            "Genera un plan de contenido semanal para VoxifyHub. "
            "Devuelve una lista de ideas con plataforma, formato, tema y objetivo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "week_theme": {
                    "type": "string",
                    "description": "Tema central de la semana (ej: 'automatización de ventas', 'casos de éxito').",
                },
                "num_posts": {
                    "type": "integer",
                    "description": "Número de posts a planear (default 5).",
                    "default": 5,
                },
            },
            "required": ["week_theme"],
        },
    },
    {
        "name": "generate_instagram_post",
        "description": "Genera el copy completo de un post de Instagram (caption + hashtags) listo para publicar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Tema específico del post.",
                },
                "content_type": {
                    "type": "string",
                    "enum": ["instagram_post", "instagram_carousel", "instagram_reel"],
                    "description": "Tipo de contenido de Instagram.",
                },
                "pain_point": {
                    "type": "string",
                    "description": "Dolor o problema del cliente que este post atiende (opcional).",
                },
            },
            "required": ["topic", "content_type"],
        },
    },
    {
        "name": "generate_facebook_post",
        "description": "Genera el texto de un post para la página de Facebook de VoxifyHub.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Tema del post.",
                },
                "audience": {
                    "type": "string",
                    "description": "Audiencia específica (ej: 'restauranteros latinos', 'agentes de bienes raíces').",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "generate_linkedin_post",
        "description": "Genera un post profesional de thought leadership para LinkedIn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Tema o insight a compartir.",
                },
                "format": {
                    "type": "string",
                    "enum": ["historia", "dato_estadistica", "leccion_aprendida", "prediccion"],
                    "description": "Formato narrativo del post.",
                },
            },
            "required": ["topic", "format"],
        },
    },
    {
        "name": "save_content_to_calendar",
        "description": "Guarda un contenido generado en el calendario de publicaciones de la base de datos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["instagram", "facebook", "linkedin"],
                },
                "content_type": {"type": "string"},
                "content": {
                    "type": "string",
                    "description": "Texto completo del post.",
                },
                "scheduled_date": {
                    "type": "string",
                    "description": "Fecha ISO 8601 (ej: '2026-06-15T09:00:00').",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL pública de la imagen generada (opcional).",
                },
                "video_url": {
                    "type": "string",
                    "description": "URL pública del video generado para Reels (opcional).",
                },
            },
            "required": ["platform", "content_type", "content", "scheduled_date"],
        },
    },
]


def execute_content_tool(tool_name: str, tool_input: dict, db, brand_id: str = "voxifyhub") -> str:
    """
    Handle content tools that don't require a Claude call themselves.
    The actual generation happens inside the agent loop via Claude.
    This dispatcher handles side-effect tools (e.g., saving to DB).
    """
    if tool_name == "save_content_to_calendar":
        return _save_content(tool_input, db, brand_id)

    # Generation tools return a prompt for the agent to respond to —
    # Claude handles them inline in the agentic loop.
    fmt = CONTENT_TYPES.get(tool_input.get("content_type", "instagram_post"), {})
    return json.dumps({
        "instruction": f"Genera el contenido según las guías de marca de VoxifyHub.",
        "format_guide": fmt,
        "input": tool_input,
    }, ensure_ascii=False)


def _save_content(data: dict, db, brand_id: str = "voxifyhub") -> str:
    try:
        db.save_scheduled_post(
            platform=data["platform"],
            content_type=data["content_type"],
            content=data["content"],
            scheduled_date=data["scheduled_date"],
            image_url=data.get("image_url"),
            video_url=data.get("video_url"),
            brand_id=brand_id,
        )
        return json.dumps({"success": True, "message": "Contenido guardado en calendario."}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
