"""
Competitor intelligence for VoxifyHub.
Tracks competitor content patterns and identifies differentiation opportunities.
"""

import json
import logging
from datetime import date

logger = logging.getLogger(__name__)

# Known competitors and reference accounts to monitor
COMPETITORS = {
    "directos": [
        {"name": "Birdeye", "ig": "birdeyeapp", "focus": "Review management + messaging, English-only"},
        {"name": "Podium", "ig": "podiumhq", "focus": "SMS messaging for local businesses, no Spanish"},
        {"name": "Tidio", "ig": "tidio_official", "focus": "AI chatbots, very technical, no Latino focus"},
        {"name": "Go High Level", "ig": "gohighlevel", "focus": "Agency-focused CRM, complex for SMBs"},
    ],
    "referentes_latinos": [
        {"name": "Latinos en Business", "ig": "latinosinbusiness", "focus": "Educación financiera y negocios en español"},
        {"name": "Negocios en USA", "ig": "negociosenusa", "focus": "Tips negocios para hispanos en EE.UU."},
        {"name": "Emprendedor Latino", "ig": "emprendedorlatino", "focus": "Motivación y estrategia para emprendedores"},
    ],
}

CONTENT_GAPS = [
    "Ningún competidor directo crea contenido en español para pymes latinas",
    "Los referentes latinos no hablan de IA ni automatización — espacio disponible",
    "Nadie está haciendo contenido de casos de éxito con negocios latinos específicos (restaurantes, salones, contractors)",
    "El contenido de IA para negocios es muy técnico — oportunidad de simplificarlo para el público latino",
    "Nadie conecta 'perder leads' con una solución concreta en español",
]

DIFFERENTIATION_ANGLES = [
    "Somos los únicos especializados en negocios latinos en EE.UU.",
    "Hablamos el idioma — literalmente y culturalmente",
    "Casos de éxito reales con negocios que tu audiencia reconoce",
    "Tatiana como fundadora latina = credibilidad inmediata con la comunidad",
    "Precio accesible diseñado para pymes, no para empresas corporativas",
]


def analyze_competitors(focus_area: str = "general") -> dict:
    """
    Return competitive intelligence analysis.
    Since we can't scrape Instagram in real-time, this combines
    known intelligence with strategic recommendations.
    """
    current_week = date.today().isocalendar()[1]
    current_month = date.today().month

    seasonal_opportunities = _get_seasonal_opportunities(current_month)

    analysis = {
        "fecha_analisis": date.today().isoformat(),
        "competidores_directos": len(COMPETITORS["directos"]),
        "principal_debilidad_competencia": (
            "Ningún competidor directo habla español ni entiende la cultura de negocio latina. "
            "Todos son herramientas genéricas en inglés orientadas a empresas medianas-grandes."
        ),
        "brechas_de_contenido": CONTENT_GAPS,
        "angulos_diferenciacion": DIFFERENTIATION_ANGLES,
        "oportunidades_estacionales": seasonal_opportunities,
        "recomendaciones_contenido": _get_content_recommendations(focus_area),
        "temas_que_competencia_no_toca": [
            "Historias reales de emprendedores latinos perdiendo clientes",
            "Demostración en español de cómo funciona la IA",
            "Casos específicos por industria: restaurantes, salones, contractors latinos",
            "El costo real en dólares de no responder a tiempo",
            "Cómo competir contra cadenas grandes siendo un negocio pequeño con IA",
        ],
    }

    return analysis


def _get_seasonal_opportunities(month: int) -> list:
    opportunities = {
        6: [
            "Temporada de verano — restaurantes y spas están en su pico, habla de manejar el volumen",
            "Vacaciones escolares — contractors y servicios de casa están ocupados",
            "Hispanic Heritage Month se acerca (septiembre) — empieza a preparar contenido",
        ],
        7: [
            "Mitad del año — ideal para hablar de metas y ajustes de negocio",
            "Pico de turismo en Florida — restaurantes y hospitality necesitan automatización",
        ],
        8: [
            "Back to school — familias latinas reorganizando presupuestos y negocios",
            "Preparación para Q4 — planificación de fin de año para pymes",
        ],
        9: [
            "Hispanic Heritage Month (15 sep - 15 oct) — momento CLAVE para VoxifyHub",
            "Contenido de celebración de emprendedores latinos tiene alcance orgánico altísimo",
        ],
        10: [
            "Hispanic Heritage Month cierra — publicar resultados y agradecimientos",
            "Halloween marketing para negocios locales latinos",
        ],
        11: [
            "Black Friday — muchos negocios latinos no están preparados para el volumen",
            "Thanksgiving — contenido de gratitud y comunidad funciona muy bien",
        ],
        12: [
            "Navidad — temporada alta para la mayoría de negocios latinos",
            "Balance de año y metas 2027 — contenido de reflexión y crecimiento",
        ],
    }
    return opportunities.get(month, ["Momento neutro — enfocarse en contenido educativo evergreen"])


def _get_content_recommendations(focus_area: str) -> list:
    base = [
        "Crear contenido específico por industria (no genérico) — restaurantes, salones, contractors, realtors",
        "Usar números reales: '78% de clientes compran del primero que responde'",
        "Mostrar la herramienta en acción con pantallazos reales (sin mostrar datos privados de clientes)",
        "Contar la historia de Tatiana como colombiana construyendo en EE.UU. — es un gancho poderoso",
        "Hacer preguntas que generen debate: '¿Cuántos mensajes sin leer tienes ahora mismo?'",
    ]
    if focus_area == "restaurants":
        base.insert(0, "Restaurantes: enfócate en reservas perdidas y pedidos de catering ignorados — son los más caros")
    elif focus_area == "contractors":
        base.insert(0, "Contractors: el costo de un lead perdido es de $500-5000 — ese dato es el gancho más fuerte")
    elif focus_area == "realtors":
        base.insert(0, "Realtors: una respuesta tardía puede costar una comisión de $10,000+ — el urgency es máximo")
    return base


# ── Agent tools ────────────────────────────────────────────────────────────

COMPETITOR_TOOLS = [
    {
        "name": "analyze_competitors",
        "description": (
            "Analiza el panorama competitivo de VoxifyHub. "
            "Identifica brechas de contenido que los competidores no están aprovechando, "
            "ángulos de diferenciación, oportunidades estacionales, y temas de contenido "
            "que la competencia no toca pero que conectan con la audiencia latina. "
            "Úsalo siempre antes de definir el tema semanal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "focus_area": {
                    "type": "string",
                    "description": "Industria en la que enfocarse (restaurants, contractors, realtors, salons, general).",
                    "default": "general",
                },
            },
        },
    },
]


def execute_competitor_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "analyze_competitors":
        result = analyze_competitors(focus_area=tool_input.get("focus_area", "general"))
        return json.dumps(result, ensure_ascii=False)
    return json.dumps({"error": f"Herramienta no reconocida: {tool_name}"}, ensure_ascii=False)
