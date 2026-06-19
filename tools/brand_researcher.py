"""
Deep brand research using Claude tool use.
The Anthropic API validates the schema — no JSON parsing errors possible.
"""

import json
import logging
from datetime import datetime

import anthropic

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

_CLIENT = None

# ── Tool schema — Anthropic validates this, so the response is always valid ──

_RESEARCH_TOOL = {
    "name": "save_brand_research",
    "description": "Guarda los resultados completos de la investigación estratégica de marca.",
    "input_schema": {
        "type": "object",
        "properties": {
            "competitors": {
                "type": "array",
                "description": "Competidores directos e indirectos identificados",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":            {"type": "string"},
                        "type":            {"type": "string"},
                        "strengths":       {"type": "array", "items": {"type": "string"}},
                        "weaknesses":      {"type": "array", "items": {"type": "string"}},
                        "market_position": {"type": "string"},
                        "social_presence": {"type": "string"},
                    },
                    "required": ["name", "type", "strengths", "weaknesses", "market_position"],
                },
            },
            "competitive_advantages": {
                "type": "array",
                "description": "Ventajas competitivas reales de la marca",
                "items": {
                    "type": "object",
                    "properties": {
                        "advantage":   {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["advantage", "explanation"],
                },
            },
            "audience": {
                "type": "object",
                "description": "Perfil del cliente ideal",
                "properties": {
                    "primary": {
                        "type": "object",
                        "properties": {
                            "demographics":       {"type": "string"},
                            "psychographics":     {"type": "string"},
                            "pain_points":        {"type": "array", "items": {"type": "string"}},
                            "buying_triggers":    {"type": "array", "items": {"type": "string"}},
                            "preferred_channels": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["demographics", "psychographics", "pain_points"],
                    },
                    "secondary": {
                        "type": "object",
                        "properties": {
                            "demographics":   {"type": "string"},
                            "psychographics": {"type": "string"},
                        },
                    },
                },
                "required": ["primary"],
            },
            "hashtags": {
                "type": "object",
                "description": "Estrategia de hashtags organizada por categoría",
                "properties": {
                    "brand":    {"type": "array", "items": {"type": "string"}},
                    "industry": {"type": "array", "items": {"type": "string"}},
                    "trending": {"type": "array", "items": {"type": "string"}},
                    "niche":    {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "array", "items": {"type": "string"}},
                    "campaign": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["brand", "industry", "niche"],
            },
            "content_pillars": {
                "type": "array",
                "description": "Pilares de contenido para redes sociales",
                "items": {
                    "type": "object",
                    "properties": {
                        "pillar":      {"type": "string"},
                        "description": {"type": "string"},
                        "examples":    {"type": "array", "items": {"type": "string"}},
                        "frequency":   {"type": "string"},
                    },
                    "required": ["pillar", "description"],
                },
            },
            "voice": {
                "type": "object",
                "description": "Voz y tono de marca",
                "properties": {
                    "tone":               {"type": "string"},
                    "personality_traits": {"type": "array", "items": {"type": "string"}},
                    "language_style":     {"type": "string"},
                    "do":                 {"type": "array", "items": {"type": "string"}},
                    "dont":               {"type": "array", "items": {"type": "string"}},
                },
                "required": ["tone", "personality_traits"],
            },
            "positioning":         {"type": "string", "description": "Posicionamiento refinado en 1-2 oraciones"},
            "tagline_suggestions": {"type": "array", "items": {"type": "string"}},
            "keywords":            {"type": "array", "items": {"type": "string"}, "description": "Keywords SEO relevantes"},
            "market_insights": {
                "type": "array",
                "description": "Tendencias, oportunidades y amenazas del mercado",
                "items": {
                    "type": "object",
                    "properties": {
                        "type":    {"type": "string"},
                        "insight": {"type": "string"},
                        "action":  {"type": "string"},
                    },
                    "required": ["type", "insight", "action"],
                },
            },
            "missing_data":      {"type": "array", "items": {"type": "string"}},
            "research_summary":  {"type": "string", "description": "Resumen ejecutivo de los hallazgos más importantes"},
        },
        "required": [
            "competitors", "competitive_advantages", "audience",
            "hashtags", "content_pillars", "voice",
            "positioning", "keywords", "market_insights", "research_summary",
        ],
    },
}

_ANALYZE_TOOL = {
    "name": "save_brand_insights",
    "description": "Guarda los insights extraídos del análisis de recursos de marca.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name":        {"type": "string"},
            "tagline":     {"type": "string"},
            "description": {"type": "string"},
            "mission":     {"type": "string"},
            "industry":    {"type": "string"},
            "geography":   {"type": "string"},
            "values":      {"type": "array", "items": {"type": "string"}},
            "hashtags":    {"type": "array", "items": {"type": "string"}},
            "voice": {
                "type": "object",
                "properties": {
                    "adjectives": {"type": "array", "items": {"type": "string"}},
                    "avoid":      {"type": "string"},
                    "formality":  {"type": "number"},
                    "emoji_use":  {"type": "string"},
                },
            },
            "positioning": {
                "type": "object",
                "properties": {
                    "usp":             {"type": "string"},
                    "competitors":     {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "weakness": {"type": "string"}}}},
                    "differentiators": {"type": "array", "items": {"type": "string"}},
                },
            },
            "audience": {
                "type": "object",
                "properties": {
                    "personas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name":       {"type": "string"},
                                "age":        {"type": "string"},
                                "occupation": {"type": "string"},
                                "pain":       {"type": "string"},
                                "goal":       {"type": "string"},
                            },
                        },
                    },
                    "language":  {"type": "string"},
                    "channels":  {"type": "array", "items": {"type": "string"}},
                    "geography": {"type": "string"},
                },
            },
            "content_lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":        {"type": "string"},
                        "percentage":  {"type": "number"},
                        "description": {"type": "string"},
                    },
                },
            },
            "insights_summary": {"type": "string"},
        },
        "required": ["name", "description", "industry", "voice", "audience", "positioning"],
    },
}


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _CLIENT


def _call_with_tool(prompt: str, tool: dict, model: str = "claude-opus-4-8", max_tokens: int = 8000) -> dict:
    """
    Call Claude forcing it to use a specific tool.
    Anthropic validates the response against the schema — no JSON errors possible.
    """
    resp = _client().messages.create(
        model=model,
        max_tokens=max_tokens,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return block.input  # Already a valid Python dict
    raise RuntimeError(f"Claude did not call tool '{tool['name']}'")


def research_brand(brand_data: dict) -> dict:
    """
    Run deep competitive and market research for a brand.
    Uses tool use — response schema is validated by Anthropic API.
    """
    name        = brand_data.get("name", "")
    industry    = brand_data.get("industry", "")
    geography   = brand_data.get("geography", "")
    description = brand_data.get("description", "")
    mission     = brand_data.get("mission", "")
    values      = brand_data.get("values", [])
    tagline     = brand_data.get("tagline", "")
    website     = brand_data.get("website_url", "")
    audience    = brand_data.get("audience", {})
    positioning = brand_data.get("positioning", "")

    existing = []
    if description: existing.append(f"Descripción: {description}")
    if mission:     existing.append(f"Misión: {mission}")
    if positioning: existing.append(f"Posicionamiento actual: {positioning}")
    if values:      existing.append(f"Valores: {', '.join(values) if isinstance(values, list) else values}")
    if audience:    existing.append(f"Audiencia definida: {json.dumps(audience, ensure_ascii=False)}")

    existing_text = "\n".join(existing) if existing else "Sin información adicional proporcionada."

    prompt = f"""Eres un estratega de marketing y analista de mercado experto.
Realiza una investigación profunda y exhaustiva para la siguiente marca.

MARCA: {name}
INDUSTRIA: {industry}
GEOGRAFÍA / MERCADO: {geography}
TAGLINE: {tagline}
SITIO WEB: {website}

INFORMACIÓN PROPORCIONADA POR EL DUEÑO:
{existing_text}

Tu misión:
1. Identifica COMPETIDORES directos e indirectos con sus fortalezas y debilidades reales
2. Descubre VENTAJAS COMPETITIVAS reales de esta marca
3. Define el PERFIL DEL CLIENTE IDEAL con demografía, psicografía y puntos de dolor
4. Establece PILARES DE CONTENIDO para redes sociales con ejemplos concretos
5. Crea ESTRATEGIA DE HASHTAGS (30+ hashtags reales organizados por categoría)
6. Refina la VOZ DE MARCA con lo que SÍ y NO hacer
7. Proporciona INSIGHTS DE MERCADO (tendencias, oportunidades, amenazas)
8. Sugiere POSICIONAMIENTO óptimo y taglines alternativos

Sé específico: nombres reales de competidores, hashtags reales de la industria, datos concretos.
Usa la herramienta save_brand_research para guardar todos los resultados."""

    try:
        result = _call_with_tool(prompt, _RESEARCH_TOOL)
        result["researched_at"] = datetime.utcnow().isoformat()
        return {"success": True, "research": result}
    except Exception as e:
        logger.error(f"[research_brand] Error: {e}")
        return {"success": False, "error": str(e)}


def analyze_brand_resources(brand_name: str, context: str, model: str = "claude-opus-4-8") -> dict:
    """
    Extract brand insights from website/manual/social resources.
    Uses tool use — response schema is validated by Anthropic API.
    """
    prompt = f"""Analiza los siguientes recursos de la marca "{brand_name}" y extrae toda la información relevante.

RECURSOS DISPONIBLES:
{context}

Extrae la información real disponible. Si algo no está explícito, infiere valores razonables
basados en el contexto de la marca y la industria.

Usa la herramienta save_brand_insights para guardar todos los datos extraídos."""

    try:
        result = _call_with_tool(prompt, _ANALYZE_TOOL, model=model)
        return {"success": True, "insights": result}
    except Exception as e:
        logger.error(f"[analyze_brand_resources] Error: {e}")
        return {"success": False, "error": str(e)}


def apply_research_to_brand(brand: dict, research: dict) -> dict:
    """Merge research results into the brand config."""
    r = research

    existing_tags = set(brand.get("hashtags", []))
    new_tags = []
    for group in r.get("hashtags", {}).values():
        new_tags.extend(group)
    brand["hashtags"] = list(existing_tags | set(new_tags))[:40]

    if r.get("audience"):
        brand["audience"] = r["audience"]

    research_pos = r.get("positioning", "")
    if research_pos and len(research_pos) > len(str(brand.get("positioning", ""))):
        brand["positioning"] = research_pos

    if r.get("content_pillars"):
        brand["content_pillars"] = r["content_pillars"]

    if r.get("voice"):
        existing_voice = brand.get("voice", {})
        if isinstance(existing_voice, str):
            existing_voice = {"description": existing_voice}
        brand["voice"] = {**existing_voice, **r["voice"]}

    if r.get("competitors"):
        brand["competitors"] = r["competitors"]

    if r.get("competitive_advantages"):
        brand["competitive_advantages"] = r["competitive_advantages"]

    if r.get("keywords"):
        brand["keywords"] = r["keywords"]

    if r.get("market_insights"):
        brand["market_insights"] = r["market_insights"]

    if r.get("tagline_suggestions"):
        brand["tagline_suggestions"] = r["tagline_suggestions"]

    brand["last_research"]    = r.get("researched_at", "")
    brand["research_summary"] = r.get("research_summary", "")

    return brand
