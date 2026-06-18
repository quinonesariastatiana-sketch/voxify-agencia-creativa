"""Sentiment analysis via Claude — scores 1-5 with label."""

import json
import logging
import anthropic
from config.settings import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if not _client:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def analyze(text: str, context: str = "") -> dict:
    """
    Returns {"score": 1-5, "label": "positivo|neutral|negativo", "signals": [...]}
    Score: 1=muy negativo, 3=neutral, 5=muy positivo
    """
    if not text or not text.strip():
        return {"score": 3.0, "label": "neutral", "signals": []}

    prompt = f"""Analiza el sentimiento de este mensaje de un prospecto de ventas.

{"CONTEXTO: " + context if context else ""}
MENSAJE: {text[:1000]}

Responde ÚNICAMENTE con JSON válido sin texto adicional:
{{
  "score": <número 1.0-5.0 donde 1=muy negativo, 3=neutral, 5=muy positivo>,
  "label": "<positivo|neutral|negativo>",
  "signals": ["<señal 1>", "<señal 2>"],
  "escalate": <true si hay frustración alta, amenaza de abandono, o lenguaje agresivo>,
  "escalate_reason": "<razón si escalate es true, sino vacío>"
}}"""

    try:
        resp = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[sentiment] Error analizando: {e}")
        return {"score": 3.0, "label": "neutral", "signals": [], "escalate": False, "escalate_reason": ""}


def batch_analyze(messages: list[str]) -> list[dict]:
    return [analyze(m) for m in messages]
