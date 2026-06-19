"""
Claude API integration — 6-call research + content generation.
Each research call is independent: if one fails, the rest are unaffected.
max_tokens=800 per call prevents truncation entirely.
Assistant prefill '{' forces pure JSON output with no preamble.
"""
import json
import logging
import os
from datetime import datetime

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL_RESEARCH = "claude-haiku-4-5-20251001"
_MODEL_CONTENT  = "claude-sonnet-4-6"
_CLIENT = None


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
            if t.endswith(','):
                t = t[:-1]
            open_b = t.count('{') - t.count('}')
            open_a = t.count('[') - t.count(']')
            t += ']' * max(0, open_a) + '}' * max(0, open_b)
            return json.loads(t)
        except Exception as e:
            logger.warning(f"[agent] parse failed: {e} | raw[:120]: {raw[:120]}")
            return {}


def research_brand(brand: dict) -> dict:
    """
    6 independent Claude Haiku calls for brand research.
    Returns {success, research: {...}, errors: [...]}.
    """
    name     = brand.get('name', '')
    industry = brand.get('industry', '')
    geo      = brand.get('geography', '')
    desc     = brand.get('description', '')
    website  = brand.get('website_url', '')

    ctx = f"Marca: {name} | Industria: {industry} | Mercado: {geo}"
    if website: ctx += f" | Web: {website}"
    if desc:    ctx += f" | Descripción: {desc[:250]}"

    results = {}
    errors  = []

    # ── Call 1: Competitors + Differentiators ─────────────────────────────────
    try:
        r = _ask(f"""{ctx}
Analiza competidores directos y diferenciadores clave de esta marca.
Responde SOLO con JSON usando exactamente estas claves:
{{"competitors": ["comp1", "comp2", "comp3", "comp4"],
  "differentiators": ["dif1", "dif2", "dif3"]}}""", 800)
        if r.get('competitors'):     results['competitors']    = r['competitors']
        if r.get('differentiators'): results['differentiators'] = r['differentiators']
    except Exception as e:
        errors.append(f"call1:{e}")

    # ── Call 2: Audience + Tone ───────────────────────────────────────────────
    try:
        r = _ask(f"""{ctx}
Define la audiencia ideal y el tono de comunicación.
Responde SOLO con JSON usando exactamente estas claves:
{{"audience_profile": "2 líneas sobre audiencia ideal: edad, intereses, dolor principal",
  "brand_tone": "1 línea describiendo el tono de voz de la marca"}}""", 800)
        if r.get('audience_profile'): results['audience_profile'] = r['audience_profile']
        if r.get('brand_tone'):       results['brand_tone']       = r['brand_tone']
    except Exception as e:
        errors.append(f"call2:{e}")

    # ── Call 3: Unique Value Proposition ─────────────────────────────────────
    try:
        r = _ask(f"""{ctx}
Define la propuesta única de valor en UNA sola frase poderosa.
Responde SOLO con JSON usando exactamente esta clave:
{{"unique_value_proposition": "una frase que captura el valor único de la marca"}}""", 800)
        if r.get('unique_value_proposition'):
            results['unique_value_proposition'] = r['unique_value_proposition']
    except Exception as e:
        errors.append(f"call3:{e}")

    # ── Call 4: Hashtags ──────────────────────────────────────────────────────
    try:
        r = _ask(f"""{ctx}
Genera 15 hashtags estratégicos para esta marca en su mercado.
Responde SOLO con JSON usando exactamente esta clave:
{{"hashtags": ["#tag1","#tag2","#tag3","#tag4","#tag5","#tag6","#tag7","#tag8","#tag9","#tag10","#tag11","#tag12","#tag13","#tag14","#tag15"]}}""", 800)
        if r.get('hashtags'):
            existing = set(brand.get('hashtags') or [])
            new_tags = [t for t in r['hashtags'] if isinstance(t, str) and t.startswith('#')]
            results['hashtags'] = list(existing | set(new_tags))[:40]
    except Exception as e:
        errors.append(f"call4:{e}")

    # ── Call 5: KPIs ──────────────────────────────────────────────────────────
    try:
        r = _ask(f"""{ctx}
Define KPIs medibles y concretos a 30, 60 y 90 días para esta marca.
Responde SOLO con JSON usando exactamente estas claves:
{{"kpi_30_days": ["kpi1","kpi2","kpi3"],
  "kpi_60_days": ["kpi1","kpi2","kpi3"],
  "kpi_90_days": ["kpi1","kpi2","kpi3"]}}""", 800)
        for k in ('kpi_30_days', 'kpi_60_days', 'kpi_90_days'):
            if r.get(k): results[k] = r[k]
    except Exception as e:
        errors.append(f"call5:{e}")

    # ── Call 6: Strategy Phases ───────────────────────────────────────────────
    try:
        r = _ask(f"""{ctx}
Define 3 fases de estrategia de crecimiento para los primeros 90 días.
Responde SOLO con JSON usando exactamente estas claves:
{{"strategy_phases": {{"phase_1": "Días 1-30: acción concreta",
                       "phase_2": "Días 31-60: acción concreta",
                       "phase_3": "Días 61-90: acción concreta"}}}}""", 800)
        if r.get('strategy_phases'): results['strategy_phases'] = r['strategy_phases']
    except Exception as e:
        errors.append(f"call6:{e}")

    results['last_research'] = datetime.utcnow().isoformat()

    filled = sum(1 for k, v in results.items()
                 if k not in ('last_research',) and v)
    return {
        'success':       filled >= 4,
        'research':      results,
        'errors':        errors,
        'fields_filled': filled,
    }


def generate_post(brand: dict, platform: str = 'instagram', topic: str = '') -> dict:
    name     = brand.get('name', 'la marca')
    tone     = brand.get('brand_tone', 'profesional y cercano')
    uvp      = brand.get('unique_value_proposition', '')
    hashtags = (brand.get('hashtags') or [])[:12]
    tags_str = ' '.join(hashtags)
    industry = brand.get('industry', '')

    topic_line = f"Tema del post: {topic}" if topic else "Elige el tema más relevante para la marca hoy."

    resp = _client().messages.create(
        model=_MODEL_CONTENT,
        max_tokens=700,
        messages=[
            {"role": "user", "content": f"""Crea un post para {platform} de la marca {name}.
Industria: {industry}
Tono: {tone}
Propuesta de valor: {uvp}
{topic_line}
Hashtags disponibles: {tags_str}

Responde SOLO con JSON:
{{"caption": "texto completo del post con emojis y saltos de línea naturales",
  "hashtags_used": ["#tag1","#tag2","#tag3"],
  "topic": "tema elegido para el post"}}"""},
            {"role": "assistant", "content": "{"},
        ]
    )
    raw = "{" + resp.content[0].text
    return _safe_parse(raw)
