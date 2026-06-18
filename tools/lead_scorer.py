"""Lead scoring — 0-10 based on ICP match criteria."""

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


def score_lead(lead: dict, icp: dict) -> dict:
    """
    Score a lead against the brand's ICP.
    icp keys: target_industries, company_sizes, decision_maker_titles, main_pain, budget_range
    Returns {"score": 0-10, "reasons": [...], "disqualifiers": [...]}
    """
    if not icp:
        return {"score": 5, "reasons": ["ICP no configurado — score neutro"], "disqualifiers": []}

    prompt = f"""Califica este prospecto contra el perfil de cliente ideal (ICP) de la empresa.

ICP OBJETIVO:
- Industrias: {', '.join(icp.get('target_industries', []))}
- Tamaño empresa: {', '.join(icp.get('company_sizes', []))}
- Cargos objetivo: {', '.join(icp.get('decision_maker_titles', []))}
- Dolor principal: {icp.get('main_pain', '')}
- Presupuesto estimado: {icp.get('budget_range', '')}

DATOS DEL PROSPECTO:
- Nombre: {lead.get('name', '')}
- Empresa: {lead.get('company', '')}
- Cargo: {lead.get('job_title', '')}
- Industria: {lead.get('industry', '')}
- Tamaño empresa: {lead.get('company_size', '')}
- Sitio web: {lead.get('website', '')}
- Notas: {lead.get('notes', '')}

Responde ÚNICAMENTE con JSON válido:
{{
  "score": <0-10 donde 10 es match perfecto>,
  "reasons": ["<razón positiva 1>", "<razón positiva 2>"],
  "disqualifiers": ["<problema 1 si lo hay>"],
  "priority": "<alta|media|baja>",
  "recommended_action": "<acción inmediata recomendada>"
}}"""

    try:
        resp = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[scorer] Error calificando lead: {e}")
        return {"score": 5, "reasons": [], "disqualifiers": [], "priority": "media", "recommended_action": ""}


def score_leads_batch(leads: list, icp: dict) -> list[dict]:
    results = []
    for lead in leads:
        result = score_lead(lead, icp)
        results.append({**lead, "score": result.get("score", 5),
                        "score_details": result})
    return sorted(results, key=lambda x: x["score"], reverse=True)


def quick_score(lead: dict, icp: dict) -> int:
    """Fast rule-based scoring without Claude (for bulk operations)."""
    score = 5
    target_industries = [i.lower() for i in icp.get("target_industries", [])]
    target_sizes = [s.lower() for s in icp.get("company_sizes", [])]
    target_titles = [t.lower() for t in icp.get("decision_maker_titles", [])]

    lead_industry = (lead.get("industry") or "").lower()
    lead_size = (lead.get("company_size") or "").lower()
    lead_title = (lead.get("job_title") or "").lower()

    if target_industries and any(i in lead_industry for i in target_industries):
        score += 2
    if target_sizes and any(s in lead_size for s in target_sizes):
        score += 1
    if target_titles and any(t in lead_title for t in target_titles):
        score += 2

    if lead.get("email"):
        score += 0.5
    if lead.get("phone"):
        score += 0.5

    return min(10, max(0, round(score)))
