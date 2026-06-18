"""
Sales Agent 24/7 — multi-brand, bilingual, autonomous lead generation and nurturing.
Uses Claude Opus for complex tasks, Haiku for sentiment/scoring.
"""

import json
import logging
from datetime import date, datetime

import anthropic

from config.settings import ANTHROPIC_API_KEY, AGENT_MODEL
from tools.sentiment import analyze as analyze_sentiment
from tools.lead_scorer import score_lead, quick_score
from tools.hubspot_crm import (
    onboard_lead, move_deal_stage, log_email, log_activity,
    update_contact, get_pipeline_stages,
    is_configured as hubspot_ok,
)
from tools.slack_notify import (
    notify_escalation, notify_new_lead, notify_demo_booked,
    notify_deal_stage_change, send_daily_report,
    is_configured as slack_ok,
)
from tools.calendly_book import get_scheduling_link, is_configured as calendly_ok
from tools.lead_scraper import scrape_leads, sources_available

logger = logging.getLogger(__name__)


class SalesAgent:
    def __init__(self, db, brand_id: str):
        self.db = db
        self.brand_id = brand_id
        self.brand = self._load_brand()
        self.sales_config = self.brand.get("sales_config", {})
        self.icp = self.sales_config.get("icp", {})
        self.voice = self.sales_config.get("voice", {})
        self.catalog = self.sales_config.get("catalog", [])
        self.pipeline = self.sales_config.get("pipeline", {})
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # HubSpot pipeline — stored in sales_config after brand setup
        self.hs_pipeline_id = self.sales_config.get("hubspot_pipeline_id", "")
        self.hs_stage_ids   = self.sales_config.get("hubspot_stage_ids", {})
        # Refresh stage IDs from HubSpot if we have a pipeline but no stage map
        if self.hs_pipeline_id and not self.hs_stage_ids and hubspot_ok():
            self.hs_stage_ids = get_pipeline_stages(self.hs_pipeline_id)

    def _load_brand(self) -> dict:
        return self.db.get_brand_config(self.brand_id) or {}

    def _system_prompt(self, language: str = "es") -> str:
        name = self.brand.get("name", "Voxify")
        voice_tone = self.voice.get("tone", "profesional y cercano")
        forbidden = self.voice.get("forbidden_phrases", [])
        key_messages = self.voice.get("key_messages", [])
        lang_note = "Responds in English only." if language == "en" else "Responde en español únicamente."

        return f"""Eres un asesor de ventas de {name}. Eres parte del equipo humano de la empresa.
NUNCA reveles que eres un sistema de IA — preséntate como parte del equipo de {name}.
{lang_note}

VOZ DE MARCA: {voice_tone}
{"FRASES PROHIBIDAS: " + ', '.join(forbidden) if forbidden else ""}
{"MENSAJES CLAVE: " + ' | '.join(key_messages) if key_messages else ""}

CATÁLOGO:
{json.dumps(self.catalog, ensure_ascii=False, indent=2) if self.catalog else "Consultar al equipo"}

PERFIL DE CLIENTE IDEAL:
{json.dumps(self.icp, ensure_ascii=False, indent=2) if self.icp else "Sin ICP configurado aún"}

Tu objetivo: calificar prospectos, generar interés genuino, resolver objeciones y avanzar en el pipeline.
Nunca presiones. Escucha primero, ofrece valor segundo, vende tercero."""

    # ── Lead generation ────────────────────────────────────────────────────────

    def generate_leads(self, count: int = 5, source_hint: str = "") -> tuple[list[dict], str]:
        """Scrape real leads from external sources based on ICP.
        Returns (leads, error_message). error_message is empty on success."""
        if not self.sales_config:
            return [], (f"El agente de '{self.brand.get('name', self.brand_id)}' no está configurado. "
                        "Ve a /sales/admin para configurarlo primero.")
        if not self.icp or not self.icp.get("target_industries"):
            return [], (f"El ICP de '{self.brand.get('name', self.brand_id)}' está vacío. "
                        "Completa el Paso 2 (ICP) en /sales/admin.")

        try:
            leads_raw, scrape_error = scrape_leads(self.icp, count=count, source_hint=source_hint)
            if scrape_error and not leads_raw:
                return [], scrape_error

            leads = []
            brand_name = self.brand.get("name", self.brand_id)

            for lead_data in leads_raw:
                score = quick_score(lead_data, self.icp)
                lead_data["score"] = score
                if not lead_data.get("source"):
                    lead_data["source"] = "scraped"
                lead_id = self.db.save_lead(self.brand_id, lead_data)
                lead_data["id"] = lead_id

                # HubSpot: create contact + deal + associate
                hubspot_ids = {"contact_id": "", "deal_id": ""}
                if hubspot_ok():
                    hs = onboard_lead(
                        lead_data, self.brand_id, brand_name,
                        self.hs_pipeline_id, self.hs_stage_ids,
                    )
                    hubspot_ids = hs
                    if hs.get("contact_id"):
                        self.db.save_lead(self.brand_id, {
                            **lead_data,
                            "hubspot_id":      hs["contact_id"],
                            "hubspot_deal_id": hs.get("deal_id", ""),
                        })
                        lead_data["hubspot_id"]      = hs["contact_id"]
                        lead_data["hubspot_deal_id"] = hs.get("deal_id", "")

                # Score >= 7: auto Calendly + HubSpot demo stage + Slack
                calendly_url = ""
                if score >= 7:
                    if calendly_ok():
                        link = get_scheduling_link(
                            name=lead_data.get("name", ""),
                            email=lead_data.get("email", ""),
                        )
                        calendly_url = link.get("url", "")
                        lead_data["calendly_url"] = calendly_url
                        self.db.save_lead(self.brand_id, {**lead_data,
                                                           "calendly_url": calendly_url})

                    # Move HubSpot deal to "Demo agendada"
                    if hubspot_ok() and lead_data.get("hubspot_deal_id"):
                        move_deal_stage(
                            lead_data["hubspot_deal_id"], "demo",
                            self.hs_stage_ids, self.hs_pipeline_id,
                        )
                    # Log Calendly link to HubSpot contact
                    if hubspot_ok() and lead_data.get("hubspot_id") and calendly_url:
                        log_activity(
                            lead_data["hubspot_id"],
                            f"Calendly enviado automáticamente (score {score}/10): {calendly_url}",
                        )

                # Slack notification
                if slack_ok():
                    notify_new_lead(
                        brand_name,
                        lead_data.get("name", ""),
                        lead_data.get("company", ""),
                        score,
                        email=lead_data.get("email", ""),
                        industry=lead_data.get("industry", ""),
                        source=lead_data.get("source", ""),
                        calendly_url=calendly_url if score >= 7 else "",
                    )

                leads.append(lead_data)
            return leads, ""
        except Exception as e:
            logger.error(f"[sales] Error generando leads: {e}")
            return [], str(e)

    # ── Conversation & outreach ───────────────────────────────────────────────

    def draft_outreach(self, lead: dict) -> dict:
        """Draft a personalized first-contact message for a lead."""
        lang    = lead.get("language", "es")
        history = self.db.get_conversations(lead.get("id", 0))
        if history:
            return {"error": "Este lead ya tiene conversación iniciada"}

        try:
            resp = self.client.messages.create(
                model=AGENT_MODEL,
                max_tokens=800,
                system=self._system_prompt(lang),
                messages=[{"role": "user", "content":
                    f"Redacta un email de primer contacto para este prospecto.\n"
                    f"Lead: {json.dumps(lead, ensure_ascii=False)}\n\n"
                    "Devuelve JSON: {\"subject\": \"...\", \"body\": \"...\"}"}],
            )
            raw = resp.content[0].text.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            conv_data = {
                "channel": "email", "direction": "outbound",
                "subject": result.get("subject", ""),
                "message": result.get("body", ""),
                "sentiment_score": 4.0, "sentiment_label": "positivo",
            }
            self.db.save_conversation(lead["id"], self.brand_id, conv_data)
            if hubspot_ok() and lead.get("hubspot_id"):
                log_email(lead["hubspot_id"], result["subject"], result["body"])
            return result
        except Exception as e:
            logger.error(f"[sales] Error redactando outreach: {e}")
            return {"error": str(e)}

    def handle_reply(self, lead_id: int, message: str, channel: str = "email") -> dict:
        """Process an incoming message from a lead and generate a response."""
        lead = self.db.get_lead(lead_id)
        if not lead:
            return {"error": "Lead no encontrado"}

        sent = analyze_sentiment(message, context=f"Prospecto de {self.brand.get('name','')}")
        self.db.save_conversation(lead_id, self.brand_id, {
            "channel": channel, "direction": "inbound", "message": message,
            "sentiment_score": sent.get("score", 3.0),
            "sentiment_label": sent.get("label", "neutral"),
        })

        # Escalation check
        escalate = sent.get("escalate", False) or sent.get("score", 3) <= 1.5
        escalate_reason = sent.get("escalate_reason", "")
        thresh = self.pipeline.get("escalation_threshold", 2)
        if sent.get("score", 3) <= thresh:
            escalate = True
            escalate_reason = escalate_reason or f"Sentimiento bajo: {sent.get('score')}/5"

        if escalate and slack_ok():
            notify_escalation(
                self.brand.get("name", ""), lead.get("name", ""), lead.get("company", ""),
                escalate_reason, channel, message[:300],
            )
            # Mark in HubSpot
            if hubspot_ok() and lead.get("hubspot_id"):
                log_activity(lead["hubspot_id"],
                             f"ESCALAMIENTO: {escalate_reason}\nMensaje: {message[:300]}")

        # Advance stage
        old_stage = lead.get("stage", "nuevo")
        new_stage = self._advance_stage(old_stage, sent)
        self.db.save_lead(self.brand_id, {**lead,
            "sentiment_score": sent.get("score", 3.0),
            "stage": new_stage,
        })

        # Sync stage to HubSpot
        if hubspot_ok() and new_stage != old_stage and lead.get("hubspot_deal_id"):
            move_deal_stage(lead["hubspot_deal_id"], new_stage,
                            self.hs_stage_ids, self.hs_pipeline_id)
            if slack_ok():
                notify_deal_stage_change(
                    self.brand.get("name", ""), lead.get("name", ""), lead.get("company", ""),
                    old_stage, new_stage,
                )

        # Auto Calendly on stage "interesado" if score high enough
        calendly_url = lead.get("calendly_url", "")
        if not calendly_url and new_stage in ("interesado", "demo") and calendly_ok():
            link = get_scheduling_link(
                name=lead.get("name", ""), email=lead.get("email", ""),
            )
            calendly_url = link.get("url", "")
            if calendly_url:
                self.db.save_lead(self.brand_id, {**lead, "calendly_url": calendly_url})
                if hubspot_ok() and lead.get("hubspot_id"):
                    log_activity(lead["hubspot_id"],
                                 f"Calendly enviado (avance a {new_stage}): {calendly_url}")
                if slack_ok():
                    notify_demo_booked(self.brand.get("name",""), lead.get("name",""),
                                       lead.get("company",""), calendly_url)

        # Generate reply
        history = self.db.get_conversations(lead_id)
        history_text = "\n".join(
            f"[{c['direction'].upper()}] {c['message'][:200]}" for c in history[-6:]
        )
        lang = lead.get("language", "es")

        try:
            resp = self.client.messages.create(
                model=AGENT_MODEL,
                max_tokens=600,
                system=self._system_prompt(lang),
                messages=[{"role": "user", "content":
                    f"Historial de conversación:\n{history_text}\n\n"
                    f"NUEVO MENSAJE DEL PROSPECTO:\n{message}\n\n"
                    f"Sentimiento detectado: {sent.get('label','neutral')} ({sent.get('score',3)}/5)\n"
                    f"{'⚠️ ESCALADO: ' + escalate_reason if escalate else ''}\n"
                    f"{'📅 CALENDLY disponible: ' + calendly_url if calendly_url else ''}\n\n"
                    "Redacta la respuesta ideal. Devuelve JSON: {\"subject\": \"...\", \"body\": \"...\"}"}],
            )
            raw = resp.content[0].text.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            self.db.save_conversation(lead_id, self.brand_id, {
                "channel": channel, "direction": "outbound",
                "subject": result.get("subject", ""),
                "message": result.get("body", ""),
                "sentiment_score": 4.0, "sentiment_label": "positivo",
                "escalated": int(escalate),
            })
            if hubspot_ok() and lead.get("hubspot_id"):
                log_email(lead["hubspot_id"], result.get("subject", ""), result.get("body", ""))
            return {**result, "escalated": escalate, "sentiment": sent,
                    "calendly_url": calendly_url}
        except Exception as e:
            logger.error(f"[sales] Error generando respuesta: {e}")
            return {"error": str(e)}

    def _advance_stage(self, current: str, sentiment: dict) -> str:
        stages = ["nuevo", "contactado", "interesado", "propuesta", "negociacion", "cerrado"]
        if sentiment.get("score", 3) >= 4 and current in stages:
            idx = stages.index(current)
            if idx < len(stages) - 1:
                return stages[idx + 1]
        return current

    # ── Scheduling ────────────────────────────────────────────────────────────

    def get_meeting_link(self, lead: dict) -> str:
        link = get_scheduling_link(
            name=lead.get("name", ""),
            email=lead.get("email", ""),
        )
        return link.get("url", "")

    # ── Insights & reports ────────────────────────────────────────────────────

    def analyze_patterns(self) -> dict:
        leads = self.db.list_leads(self.brand_id, limit=200)
        conversations = []
        for lead in leads[:50]:
            convs = self.db.get_conversations(lead["id"])
            conversations.extend(c for c in convs if c["direction"] == "inbound")

        if not conversations:
            return {"recommendations": ["Sin conversaciones suficientes para analizar."], "patterns": []}

        sample = conversations[-20:]
        sample_text = "\n---\n".join(c["message"][:300] for c in sample)
        stages_dist = {}
        for lead in leads:
            s = lead.get("stage", "nuevo")
            stages_dist[s] = stages_dist.get(s, 0) + 1
        avg_score = sum(l.get("score", 0) for l in leads) / max(len(leads), 1)

        prompt = (f"Analiza los patrones de ventas de {self.brand.get('name','')}.\n\n"
                  f"DISTRIBUCIÓN POR ETAPA: {json.dumps(stages_dist)}\n"
                  f"SCORE PROMEDIO DE LEADS: {avg_score:.1f}/10\n"
                  f"MUESTRA DE MENSAJES ENTRANTES:\n{sample_text[:3000]}\n\n"
                  "Genera análisis en JSON:\n"
                  "{\n"
                  '  "objections": ["objeción 1", "objeción 2", "objeción 3"],\n'
                  '  "friction_points": ["fricción 1"],\n'
                  '  "positive_signals": ["señal positiva 1"],\n'
                  '  "recommendations": ["recomendación accionable 1", "2", "3", "4", "5"],\n'
                  '  "bottleneck_stage": "<etapa con más estancamiento>",\n'
                  '  "win_rate_estimate": "<X%>"\n'
                  "}")

        try:
            resp = self.client.messages.create(
                model=AGENT_MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            for rec in result.get("recommendations", []):
                self.db.save_insight(self.brand_id, "recommendation", rec)
            return result
        except Exception as e:
            logger.error(f"[sales] Error analizando patrones: {e}")
            return {"recommendations": [], "patterns": [], "error": str(e)}

    def generate_daily_report(self) -> dict:
        stats = self.db.get_sales_stats(self.brand_id)
        leads = self.db.list_leads(self.brand_id, limit=100)
        today_str = date.today().isoformat()

        new_today = sum(1 for l in leads if (l.get("created_at") or "")[:10] == today_str)
        contacted_today = 0
        for lead in leads:
            convs = self.db.get_conversations(lead["id"])
            if any((c.get("created_at") or "")[:10] == today_str for c in convs):
                contacted_today += 1

        sentiments = [l.get("sentiment_score", 3.0) for l in leads if l.get("last_contact")]
        avg_sentiment_score = sum(sentiments) / max(len(sentiments), 1) if sentiments else 3.0
        if avg_sentiment_score >= 4:
            sentiment_label = "positivo"
        elif avg_sentiment_score >= 3:
            sentiment_label = "neutral"
        else:
            sentiment_label = "negativo"

        patterns = self.analyze_patterns()

        report = {
            "date":                today_str,
            "brand_id":            self.brand_id,
            "brand_name":          self.brand.get("name", ""),
            "leads_generated":     new_today,
            "contacts_made":       contacted_today,
            "pipeline":            stats["by_stage"],
            "deals_closed":        stats["closed_this_month"],
            "projected_revenue":   "$0",
            "avg_sentiment":       sentiment_label,
            "avg_sentiment_score": round(avg_sentiment_score, 1),
            "escalations_pending": stats["escalations_pending"],
            "avg_lead_score":      stats["avg_score"],
            "objections":          patterns.get("objections", []),
            "recommendations":     patterns.get("recommendations", []),
            "bottleneck_stage":    patterns.get("bottleneck_stage", ""),
        }

        self.db.save_report(self.brand_id, report)
        if slack_ok():
            send_daily_report(self.brand.get("name", ""), report)
        return report

    def qualify_lead(self, lead_id: int) -> dict:
        lead = self.db.get_lead(lead_id)
        if not lead:
            return {"error": "Lead no encontrado"}
        result = score_lead(lead, self.icp)
        new_score = result.get("score", lead.get("score", 5))
        self.db.save_lead(self.brand_id, {**lead, "score": new_score})

        # If newly qualified as high score, send Calendly and update HubSpot
        if new_score >= 7 and not lead.get("calendly_url") and calendly_ok():
            link = get_scheduling_link(name=lead.get("name",""), email=lead.get("email",""))
            url  = link.get("url", "")
            if url:
                self.db.save_lead(self.brand_id, {**lead, "score": new_score, "calendly_url": url})
                if hubspot_ok() and lead.get("hubspot_id"):
                    log_activity(lead["hubspot_id"],
                                 f"Re-calificado por IA: score {new_score}/10. Calendly: {url}")
                if hubspot_ok() and lead.get("hubspot_deal_id"):
                    move_deal_stage(lead["hubspot_deal_id"], "demo",
                                    self.hs_stage_ids, self.hs_pipeline_id)
                result["calendly_url"] = url

        return result
