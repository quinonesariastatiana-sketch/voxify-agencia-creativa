"""
Brand research via 6 small focused Claude calls.
- Each call targets one area with max_tokens capped to prevent truncation.
- Results are patched field-by-field into DB (existing data never wiped on failure).
"""

import json
import logging
from datetime import datetime

import anthropic

from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

_CLIENT = None
_MODEL  = "claude-haiku-4-5-20251001"   # Fast + cheap; more than enough for factual research


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _CLIENT


def _ask(prompt: str, max_tokens: int) -> dict:
    """
    Single small Claude call.
    Prefill with '{' guarantees the response starts as JSON — no markdown, no preamble.
    Low max_tokens prevents truncation entirely.
    """
    resp = _client().messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "user",      "content": prompt},
            {"role": "assistant", "content": "{"},
        ],
    )
    raw = "{" + resp.content[0].text
    return _safe_parse(raw)


def _safe_parse(raw: str) -> dict:
    """Parse JSON. If truncated, close any open braces and retry once."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            trimmed = raw.rstrip()
            # Close any unclosed array/object brackets
            open_b = trimmed.count('{') - trimmed.count('}')
            open_a = trimmed.count('[') - trimmed.count(']')
            # Remove trailing incomplete field (last comma or partial key)
            if trimmed.endswith(','):
                trimmed = trimmed[:-1]
            trimmed += ']' * max(0, open_a) + '}' * max(0, open_b)
            return json.loads(trimmed)
        except Exception as e:
            logger.warning(f"[research] Could not parse response: {e} — raw[:200]: {raw[:200]}")
            return {}


def research_brand(brand_data: dict) -> dict:
    """
    Run 6 independent small Claude calls for brand research.
    Returns dict with all research fields ready to patch into DB.
    """
    name        = brand_data.get("name", "")
    industry    = brand_data.get("industry", "")
    geography   = brand_data.get("geography", "")
    description = brand_data.get("description", "")

    ctx = f"Marca: {name} | Industria: {industry} | Mercado: {geography}"
    if description:
        ctx += f" | Descripción: {description[:300]}"

    results  = {}
    errors   = []

    # ── LLAMADA 1: Competidores y diferenciadores ────────────────────────────
    try:
        r = _ask(
            f"""{ctx}

Analiza brevemente los competidores y diferenciadores de esta marca.
Responde SOLO con JSON, sin texto adicional. Usa exactamente estas claves:
{{"competitors": ["nombre competidor 1", "nombre competidor 2", "nombre competidor 3"],
  "differentiators": ["diferenciador clave 1", "diferenciador clave 2", "diferenciador clave 3"]}}""",
            max_tokens=400,
        )
        if r.get("competitors"):
            results["competitors"] = r["competitors"]
        if r.get("differentiators"):
            results["differentiators"] = r["differentiators"]
    except Exception as e:
        errors.append(f"call1: {e}")

    # ── LLAMADA 2: Audiencia y tono ──────────────────────────────────────────
    try:
        r = _ask(
            f"""{ctx}

Define la audiencia ideal y el tono de comunicación de esta marca.
Responde SOLO con JSON, sin texto adicional. Usa exactamente estas claves:
{{"audience_profile": "descripción de la audiencia en máximo 2 líneas",
  "brand_tone": "descripción del tono de voz en máximo 1 línea"}}""",
            max_tokens=300,
        )
        if r.get("audience_profile"):
            results["audience_profile"] = r["audience_profile"]
        if r.get("brand_tone"):
            results["brand_tone"] = r["brand_tone"]
    except Exception as e:
        errors.append(f"call2: {e}")

    # ── LLAMADA 3: Propuesta de valor ────────────────────────────────────────
    try:
        r = _ask(
            f"""{ctx}

Define la propuesta única de valor de esta marca en una sola frase impactante.
Responde SOLO con JSON, sin texto adicional. Usa exactamente esta clave:
{{"unique_value_proposition": "una sola frase que captura el valor único de la marca"}}""",
            max_tokens=200,
        )
        if r.get("unique_value_proposition"):
            results["unique_value_proposition"] = r["unique_value_proposition"]
    except Exception as e:
        errors.append(f"call3: {e}")

    # ── LLAMADA 4: Hashtags ──────────────────────────────────────────────────
    try:
        r = _ask(
            f"""{ctx}

Genera 15 hashtags relevantes para esta marca en su mercado.
Responde SOLO con JSON, sin texto adicional. Usa exactamente esta clave:
{{"hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5", "#tag6", "#tag7", "#tag8", "#tag9", "#tag10", "#tag11", "#tag12", "#tag13", "#tag14", "#tag15"]}}""",
            max_tokens=300,
        )
        if r.get("hashtags"):
            # Merge with any existing hashtags
            existing = set(brand_data.get("hashtags", []))
            new_tags = [t for t in r["hashtags"] if isinstance(t, str)]
            results["hashtags"] = list(existing | set(new_tags))[:40]
    except Exception as e:
        errors.append(f"call4: {e}")

    # ── LLAMADA 5: KPIs ──────────────────────────────────────────────────────
    try:
        r = _ask(
            f"""{ctx}

Define KPIs medibles para esta marca a 30, 60 y 90 días.
Responde SOLO con JSON, sin texto adicional. Usa exactamente estas claves:
{{"kpi_30_days": ["kpi1", "kpi2", "kpi3"],
  "kpi_60_days": ["kpi1", "kpi2", "kpi3"],
  "kpi_90_days": ["kpi1", "kpi2", "kpi3"]}}""",
            max_tokens=400,
        )
        for key in ("kpi_30_days", "kpi_60_days", "kpi_90_days"):
            if r.get(key):
                results[key] = r[key]
    except Exception as e:
        errors.append(f"call5: {e}")

    # ── LLAMADA 6: Fases de estrategia ───────────────────────────────────────
    try:
        r = _ask(
            f"""{ctx}

Define 3 fases de estrategia de crecimiento para esta marca.
Responde SOLO con JSON, sin texto adicional. Usa exactamente estas claves:
{{"strategy_phases": {{"phase_1": "descripción fase 1 (días 1-30)",
                       "phase_2": "descripción fase 2 (días 31-60)",
                       "phase_3": "descripción fase 3 (días 61-90)"}}}}""",
            max_tokens=400,
        )
        if r.get("strategy_phases"):
            results["strategy_phases"] = r["strategy_phases"]
    except Exception as e:
        errors.append(f"call6: {e}")

    results["last_research"]  = datetime.utcnow().isoformat()
    results["research_errors"] = errors

    return {
        "success":  len(results) > 2,
        "research": results,
        "errors":   errors,
    }


def apply_research_to_brand(brand: dict, research: dict) -> dict:
    """
    Merge research results into brand config.
    NEVER overwrites a field if the new value is empty.
    """
    for key, value in research.items():
        if key in ("last_research", "research_errors"):
            brand[key] = value
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        brand[key] = value
    return brand
