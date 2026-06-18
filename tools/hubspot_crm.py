"""
HubSpot CRM — cerebro central de ventas.
Cada marca tiene su propio pipeline, etapas y propiedad marca_cliente.
"""

import json
import logging
import requests
from config import settings

logger = logging.getLogger(__name__)
BASE = "https://api.hubapi.com"

# Default HubSpot Sales Pipeline stage IDs (portal 244691838)
DEFAULT_PIPELINE_ID = "default"
DEFAULT_STAGE_MAP = {
    "nuevo":       "appointmentscheduled",
    "contactado":  "appointmentscheduled",
    "interesado":  "qualifiedtobuy",
    "demo":        "presentationscheduled",
    "propuesta":   "decisionmakerboughtin",
    "negociacion": "contractsent",
    "cerrado":     "closedwon",
    "perdido":     "closedlost",
}


def _token() -> str:
    return settings.HUBSPOT_API_KEY


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def is_configured() -> bool:
    t = _token()
    return bool(t and t != "PENDIENTE_PAT_NA2")


# ── Contacts ──────────────────────────────────────────────────────────────────

def create_contact(lead: dict, brand_id: str = "") -> dict:
    if not is_configured():
        return {"error": "HUBSPOT_API_KEY no configurado"}
    name_parts = (lead.get("name") or "").split(maxsplit=1)
    # Only standard HubSpot properties — no custom schema required
    props = {
        "firstname":      name_parts[0] if name_parts else "",
        "lastname":       name_parts[1] if len(name_parts) > 1 else "",
        "email":          lead.get("email", ""),
        "phone":          lead.get("phone", ""),
        "company":        lead.get("company", ""),
        "jobtitle":       lead.get("job_title", ""),
        "website":        lead.get("website", ""),
        "hs_lead_status": "NEW",
    }
    # Remove empty values to avoid HubSpot validation errors
    props = {k: v for k, v in props.items() if v}
    try:
        r = requests.post(f"{BASE}/crm/v3/objects/contacts",
                          headers=_headers(), json={"properties": props}, timeout=15)
        data = r.json()
        if r.status_code in (200, 201):
            return {"success": True, "hubspot_id": data["id"]}
        if r.status_code == 409:
            # Already exists — extract ID from error message
            msg = data.get("message", "")
            existing_id = ""
            if "Existing ID:" in msg:
                existing_id = msg.split("Existing ID:")[-1].strip()
            elif msg.split(":")[-1].strip().isdigit():
                existing_id = msg.split(":")[-1].strip()
            return {"success": True, "hubspot_id": existing_id, "existing": True}
        return {"error": data.get("message", str(data))}
    except Exception as e:
        logger.error(f"[hubspot] create_contact: {e}")
        return {"error": str(e)}


def update_contact(hubspot_id: str, props: dict) -> dict:
    if not is_configured() or not hubspot_id:
        return {"error": "Sin token o sin ID"}
    try:
        r = requests.patch(f"{BASE}/crm/v3/objects/contacts/{hubspot_id}",
                           headers=_headers(), json={"properties": props}, timeout=15)
        return {"success": r.status_code in (200, 204)}
    except Exception as e:
        return {"error": str(e)}


def log_activity(contact_id: str, message: str, activity_type: str = "NOTE") -> dict:
    """Log a note or activity to the contact's timeline."""
    if not is_configured():
        return {"error": "Sin token"}
    payload = {
        "engagement": {"active": True, "type": activity_type},
        "associations": {"contactIds": [int(contact_id)]},
        "metadata": {"body": message},
    }
    try:
        r = requests.post(f"{BASE}/engagements/v1/engagements",
                          headers=_headers(), json=payload, timeout=15)
        return {"success": r.status_code in (200, 201)}
    except Exception as e:
        return {"error": str(e)}


def log_email(contact_id: str, subject: str, body: str) -> dict:
    if not is_configured():
        return {"error": "Sin token"}
    payload = {
        "engagement": {"active": True, "type": "EMAIL"},
        "associations": {"contactIds": [int(contact_id)]},
        "metadata": {
            "from": {"email": "agent@voxify.ai"},
            "to": [{"email": ""}],
            "subject": subject,
            "text": body,
            "html": body.replace("\n", "<br>"),
        },
    }
    try:
        r = requests.post(f"{BASE}/engagements/v1/engagements",
                          headers=_headers(), json=payload, timeout=15)
        return {"success": r.status_code in (200, 201)}
    except Exception as e:
        return {"error": str(e)}


# ── Pipelines ─────────────────────────────────────────────────────────────────

def create_brand_pipeline(brand_name: str) -> dict:
    """
    Returns the default HubSpot pipeline info.
    Custom pipeline creation requires crm.schemas.deals.write scope;
    we use the existing 'Sales Pipeline' (id=default) instead.
    """
    return {
        "success":     True,
        "pipeline_id": DEFAULT_PIPELINE_ID,
        "stage_ids":   DEFAULT_STAGE_MAP,
    }


def get_pipeline_stages(pipeline_id: str) -> dict:
    """Return stage map for the given pipeline (uses default map)."""
    return DEFAULT_STAGE_MAP


def ensure_marca_cliente_option(brand_name: str) -> bool:
    """No-op: custom property creation requires crm.schemas.contacts.write scope."""
    return True


# ── Deals ─────────────────────────────────────────────────────────────────────

def create_deal(lead: dict, brand_id: str = "", pipeline_id: str = "",
                stage_ids: dict = None, deal_name: str = "") -> dict:
    if not is_configured():
        return {"error": "HUBSPOT_API_KEY no configurado"}

    local_stage = lead.get("stage", "nuevo")
    stage_id    = DEFAULT_STAGE_MAP.get(local_stage, "appointmentscheduled")

    props = {
        "dealname":  deal_name or f"{lead.get('company') or lead.get('name','Lead')} — {brand_id}",
        "dealstage": stage_id,
        "pipeline":  pipeline_id or DEFAULT_PIPELINE_ID,
    }
    amount = lead.get("estimated_value", "")
    if amount:
        props["amount"] = str(amount)

    try:
        r = requests.post(f"{BASE}/crm/v3/objects/deals",
                          headers=_headers(), json={"properties": props}, timeout=15)
        data = r.json()
        if r.status_code in (200, 201):
            return {"success": True, "deal_id": data["id"]}
        return {"error": data.get("message", str(data))}
    except Exception as e:
        logger.error(f"[hubspot] create_deal: {e}")
        return {"error": str(e)}


def move_deal_stage(deal_id: str, local_stage: str,
                    stage_ids: dict = None, pipeline_id: str = "") -> dict:
    if not is_configured():
        return {"error": "Sin token"}
    stage_id = DEFAULT_STAGE_MAP.get(local_stage, "appointmentscheduled")
    props = {"dealstage": stage_id}
    try:
        r = requests.patch(f"{BASE}/crm/v3/objects/deals/{deal_id}",
                           headers=_headers(), json={"properties": props}, timeout=15)
        return {"success": r.status_code in (200, 204)}
    except Exception as e:
        return {"error": str(e)}


def associate_contact_deal(contact_id: str, deal_id: str) -> dict:
    if not is_configured():
        return {"error": "Sin token"}
    try:
        r = requests.put(
            f"{BASE}/crm/v4/objects/contacts/{contact_id}/associations/deals/{deal_id}",
            headers=_headers(),
            json=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 3}],
            timeout=15,
        )
        return {"success": r.status_code in (200, 201, 204)}
    except Exception as e:
        return {"error": str(e)}


# ── Full lead onboarding ──────────────────────────────────────────────────────

def onboard_lead(lead: dict, brand_id: str, brand_name: str,
                 pipeline_id: str = "", stage_ids: dict = None) -> dict:
    """
    Create contact + deal + associate + log activity in one call.
    Returns {contact_id, deal_id, errors[]}.
    """
    errors = []

    contact_result = create_contact(lead, brand_id)
    contact_id = contact_result.get("hubspot_id", "")
    if not contact_id:
        errors.append(f"contact: {contact_result.get('error')}")

    deal_result = create_deal(lead, brand_id, pipeline_id, stage_ids)
    deal_id = deal_result.get("deal_id", "")
    if not deal_id:
        errors.append(f"deal: {deal_result.get('error')}")

    if contact_id and deal_id:
        associate_contact_deal(contact_id, deal_id)

    if contact_id:
        score = lead.get("score", "")
        log_activity(contact_id,
                     f"[Voxify Agent] Lead calificado por IA\n"
                     f"Marca: {brand_name}\n"
                     f"Score: {score}/10\n"
                     f"Industria: {lead.get('industry','')}\n"
                     f"Fuente: {lead.get('source','agent_generated')}\n"
                     f"Notas: {lead.get('notes','')[:300]}")

    return {"contact_id": contact_id, "deal_id": deal_id, "errors": errors}
