"""
Trend detection using Google Trends (pytrends) + keyword intelligence.
Identifies what Latino entrepreneurs are searching for right now.
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

VOXIFY_KEYWORDS = [
    "negocios latinos",
    "emprendedores latinos Florida",
    "automatización negocios",
    "chatbot para restaurantes",
    "responder mensajes clientes",
    "IA para pequeños negocios",
    "perder clientes por no responder",
    "software atencion al cliente",
]

COMPETITOR_TERMS = [
    "Birdeye",
    "Podium messaging",
    "Tidio chatbot",
    "Go High Level",
]


def get_trending_topics(keywords: list = None, geo: str = "US") -> dict:
    """
    Get Google Trends data for VoxifyHub's core keywords.
    Returns trending topics and related queries.
    """
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="es-419", tz=300)  # Spanish, ET timezone
        kw_list = (keywords or VOXIFY_KEYWORDS)[:5]  # pytrends max 5 at a time

        pytrends.build_payload(kw_list, cat=0, timeframe="now 7-d", geo=geo)

        interest = pytrends.interest_over_time()
        related_queries = pytrends.related_queries()

        result = {
            "period": "últimos 7 días",
            "geo": geo,
            "trending_keywords": {},
            "rising_queries": {},
            "top_queries": {},
        }

        if not interest.empty:
            for kw in kw_list:
                if kw in interest.columns:
                    avg = int(interest[kw].mean())
                    result["trending_keywords"][kw] = avg

        for kw in kw_list:
            if kw in related_queries:
                rising = related_queries[kw].get("rising")
                top = related_queries[kw].get("top")
                if rising is not None and not rising.empty:
                    result["rising_queries"][kw] = rising.head(3)["query"].tolist()
                if top is not None and not top.empty:
                    result["top_queries"][kw] = top.head(3)["query"].tolist()

        # Identify hottest keyword
        if result["trending_keywords"]:
            hottest = max(result["trending_keywords"], key=result["trending_keywords"].get)
            result["insight"] = f"'{hottest}' es el tema con mayor interés esta semana — úsalo como gancho principal"

        return result

    except ImportError:
        return {
            "error": "pytrends no instalado. Corre: pip install pytrends",
            "fallback_topics": _get_fallback_trends(),
        }
    except Exception as e:
        logger.warning(f"Error en Google Trends: {e}")
        return {
            "status": "error_trends",
            "fallback_topics": _get_fallback_trends(),
            "error": str(e),
        }


def _get_fallback_trends() -> list:
    """Static fallback topics when Trends API is unavailable."""
    month = datetime.now().month
    seasonal = {
        6: ["verano negocios", "turismo Florida", "temporada alta restaurantes"],
        7: ["vacaciones verano", "ofertas julio", "negocios estacionales"],
        8: ["back to school", "regreso clases", "preparar negocio septiembre"],
        9: ["otoño negocios", "metas Q4", "emprendedores hispanos mes"],
        10: ["Hispanic Heritage Month", "negocios hispanos", "emprendimiento latino"],
        11: ["Black Friday pymes", "temporada navidad", "ventas fin de año"],
        12: ["navidad negocios latinos", "año nuevo metas", "balance anual"],
    }
    return seasonal.get(month, [
        "automatización para pymes",
        "atención al cliente digital",
        "negocios latinos crecimiento",
    ])


def get_hook_suggestions(topic: str, platform: str = "instagram") -> list:
    """
    Generate proven hook templates for a given topic and platform.
    Based on patterns that generate high engagement in the Latino business space.
    """
    hooks = {
        "instagram": [
            f"¿Sabías que el 78% de los clientes compran del primero que responde? ({topic})",
            f"Este error está costándole dinero a tu {topic} cada semana",
            f"La razón real por la que tu {topic} no está creciendo (no es lo que crees)",
            f"Stop. Antes de abrir hoy, lee esto si tienes un {topic}",
            f"Lo que los dueños exitosos de {topic} hacen diferente (y nadie habla de esto)",
        ],
        "facebook": [
            f"Pregunta para dueños de {topic}: ¿Cuántos mensajes sin responder tienes ahora mismo?",
            f"Comparte si eres dueño de un {topic} en Florida 👇",
            f"Historia real de un {topic} que cambió su negocio con IA:",
        ],
        "linkedin": [
            f"Después de hablar con 50 dueños de {topic}, aprendí esto:",
            f"El problema más costoso que tienen los {topic} latinos en EE.UU. (y cómo lo resolvemos)",
            f"3 años construyendo para negocios latinos. Esto es lo que aprendí sobre {topic}:",
        ],
    }
    return hooks.get(platform, hooks["instagram"])


# ── Agent tools ────────────────────────────────────────────────────────────

TREND_TOOLS = [
    {
        "name": "detect_trends",
        "description": (
            "Detecta tendencias actuales en Google para keywords relacionadas con VoxifyHub: "
            "negocios latinos, automatización, IA para pymes, emprendedores Florida. "
            "Retorna los temas más buscados esta semana y queries relacionadas para usar en el contenido."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords específicas a analizar (máximo 5). Si se omite, usa las keywords de VoxifyHub.",
                },
                "geo": {
                    "type": "string",
                    "description": "Código de país/región. 'US' para EE.UU., 'US-FL' para Florida.",
                    "default": "US-FL",
                },
            },
        },
    },
    {
        "name": "generate_hooks",
        "description": (
            "Genera ganchos (hooks) de alto impacto para un tema y plataforma específicos. "
            "Basado en patrones que funcionan en la comunidad de emprendedores latinos. "
            "Retorna 5 opciones de hooks listos para usar al inicio del copy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Tipo de negocio o tema del post (ej: 'restaurante', 'salón de belleza', 'leads perdidos').",
                },
                "platform": {
                    "type": "string",
                    "enum": ["instagram", "facebook", "linkedin"],
                    "description": "Plataforma donde se publicará.",
                },
            },
            "required": ["topic", "platform"],
        },
    },
]


def execute_trend_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "detect_trends":
        result = get_trending_topics(
            keywords=tool_input.get("keywords"),
            geo=tool_input.get("geo", "US-FL"),
        )
        return json.dumps(result, ensure_ascii=False)

    if tool_name == "generate_hooks":
        hooks = get_hook_suggestions(
            topic=tool_input.get("topic", "negocio"),
            platform=tool_input.get("platform", "instagram"),
        )
        return json.dumps({"hooks": hooks, "topic": tool_input.get("topic")}, ensure_ascii=False)

    return json.dumps({"error": f"Herramienta no reconocida: {tool_name}"}, ensure_ascii=False)
