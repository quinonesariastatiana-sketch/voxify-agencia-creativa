"""
Deep brand research using Claude.
Given partial brand data, returns a comprehensive analysis:
competitors, hashtags, competitive advantages, audience, content pillars, voice.
"""

import json
import logging
from datetime import datetime

import anthropic

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

_CLIENT = None


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _CLIENT


def research_brand(brand_data: dict) -> dict:
    """
    Run deep competitive and market research for a brand.

    Args:
        brand_data: partial or full brand config dict

    Returns:
        dict with keys: competitors, hashtags, competitive_advantages,
        audience, content_pillars, voice, positioning, keywords, insights
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

Tu misión es:
1. Identificar y analizar los PRINCIPALES COMPETIDORES directos e indirectos
2. Descubrir las VENTAJAS COMPETITIVAS reales de esta marca (incluso si el dueño no las mencionó)
3. Definir con precisión el PERFIL DEL CLIENTE IDEAL (demografía, psicografía, comportamiento)
4. Establecer PILARES DE CONTENIDO relevantes para redes sociales
5. Crear una ESTRATEGIA DE HASHTAGS completa (30 hashtags organizados por categoría)
6. Refinar la VOZ DE MARCA y el tono de comunicación
7. Proporcionar INSIGHTS DE MERCADO relevantes (tendencias, oportunidades, amenazas)
8. Sugerir el POSICIONAMIENTO óptimo

Sé específico con nombres reales de competidores, hashtags reales usados en la industria,
y datos concretos. Si el dueño ya proporcionó información, MEJÓRALA y AMPLÍALA.

Devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:

{{
  "competitors": [
    {{
      "name": "Nombre del competidor",
      "type": "directo|indirecto",
      "strengths": ["fortaleza 1", "fortaleza 2"],
      "weaknesses": ["debilidad 1", "debilidad 2"],
      "market_position": "descripción breve de su posición en el mercado",
      "social_presence": "descripción de su presencia en redes"
    }}
  ],
  "competitive_advantages": [
    {{
      "advantage": "ventaja competitiva específica",
      "explanation": "por qué esto es una ventaja real en el mercado"
    }}
  ],
  "audience": {{
    "primary": {{
      "demographics": "descripción demográfica detallada",
      "psychographics": "valores, intereses, estilo de vida",
      "pain_points": ["problema 1", "problema 2", "problema 3"],
      "buying_triggers": ["qué los motiva a comprar"],
      "preferred_channels": ["Instagram", "TikTok", "etc"]
    }},
    "secondary": {{
      "demographics": "descripción del segmento secundario",
      "psychographics": "valores e intereses"
    }}
  }},
  "hashtags": {{
    "brand": ["#hashtag1", "#hashtag2"],
    "industry": ["#hashtag1", "#hashtag2"],
    "trending": ["#hashtag1", "#hashtag2"],
    "niche": ["#hashtag1", "#hashtag2"],
    "location": ["#hashtag1", "#hashtag2"],
    "campaign": ["#hashtag1", "#hashtag2"]
  }},
  "content_pillars": [
    {{
      "pillar": "nombre del pilar",
      "description": "qué tipo de contenido cubre",
      "examples": ["ejemplo de post 1", "ejemplo de post 2"],
      "frequency": "X veces por semana"
    }}
  ],
  "voice": {{
    "tone": "descripción del tono (ej: cálido, experto, inspirador)",
    "personality_traits": ["rasgo 1", "rasgo 2", "rasgo 3"],
    "language_style": "descripción del estilo de lenguaje",
    "do": ["qué SÍ hacer en comunicación"],
    "dont": ["qué NO hacer en comunicación"]
  }},
  "positioning": "propuesta de posicionamiento refinada en 1-2 oraciones",
  "tagline_suggestions": ["sugerencia de tagline 1", "sugerencia de tagline 2", "sugerencia de tagline 3"],
  "keywords": ["keyword SEO 1", "keyword 2", "keyword 3"],
  "market_insights": [
    {{
      "type": "tendencia|oportunidad|amenaza",
      "insight": "descripción del insight",
      "action": "qué hacer al respecto"
    }}
  ],
  "missing_data": ["campo o información que faltó y sería útil tener"],
  "research_summary": "resumen ejecutivo de 3-4 oraciones con los hallazgos más importantes"
}}"""

    try:
        resp = _client().messages.create(
            model="claude-opus-4-8",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        result = json.loads(raw.strip())
        result["researched_at"] = datetime.utcnow().isoformat()
        return {"success": True, "research": result}
    except json.JSONDecodeError as e:
        logger.error(f"[research] JSON parse error: {e}")
        return {"success": False, "error": f"Error procesando respuesta: {e}"}
    except Exception as e:
        logger.error(f"[research] Error: {e}")
        return {"success": False, "error": str(e)}


def apply_research_to_brand(brand: dict, research: dict) -> dict:
    """
    Merge research results into the brand config, filling gaps
    and improving existing data.
    """
    r = research

    # Hashtags — merge unique
    existing_tags = set(brand.get("hashtags", []))
    new_tags = []
    for group in r.get("hashtags", {}).values():
        new_tags.extend(group)
    merged_tags = list(existing_tags | set(new_tags))
    brand["hashtags"] = merged_tags[:40]

    # Audience
    if r.get("audience"):
        brand["audience"] = r["audience"]

    # Positioning (only if empty or shorter than research)
    research_pos = r.get("positioning", "")
    if research_pos and len(research_pos) > len(brand.get("positioning", "")):
        brand["positioning"] = research_pos

    # Content pillars
    if r.get("content_pillars"):
        brand["content_pillars"] = r["content_pillars"]

    # Voice
    if r.get("voice"):
        existing_voice = brand.get("voice", {})
        if isinstance(existing_voice, str):
            existing_voice = {"description": existing_voice}
        brand["voice"] = {**existing_voice, **r["voice"]}

    # Competitors
    if r.get("competitors"):
        brand["competitors"] = r["competitors"]

    # Competitive advantages
    if r.get("competitive_advantages"):
        brand["competitive_advantages"] = r["competitive_advantages"]

    # Keywords
    if r.get("keywords"):
        brand["keywords"] = r["keywords"]

    # Market insights
    if r.get("market_insights"):
        brand["market_insights"] = r["market_insights"]

    # Tagline suggestions (store, don't override chosen tagline)
    if r.get("tagline_suggestions"):
        brand["tagline_suggestions"] = r["tagline_suggestions"]

    # Research metadata
    brand["last_research"] = r.get("researched_at", "")
    brand["research_summary"] = r.get("research_summary", "")

    return brand
