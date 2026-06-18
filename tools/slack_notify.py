"""Slack notifications — new leads, escalations, demo alerts and daily reports."""

import logging
import requests
from config import settings

logger = logging.getLogger(__name__)

STAGE_ICONS = {
    "nuevo":       "🆕",
    "contactado":  "📞",
    "interesado":  "⭐",
    "demo":        "📅",
    "propuesta":   "📋",
    "negociacion": "🤝",
    "cerrado":     "✅",
    "perdido":     "❌",
}


def _webhook() -> str:
    return settings.SLACK_WEBHOOK_URL


def _ok() -> bool:
    return bool(_webhook())


def _post(payload: dict) -> bool:
    if not _ok():
        logger.warning("[slack] SLACK_WEBHOOK_URL no configurado")
        return False
    try:
        r = requests.post(_webhook(), json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(f"[slack] HTTP {r.status_code}: {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        logger.error(f"[slack] Error enviando mensaje: {e}")
        return False


def notify_new_lead(brand_name: str, lead_name: str, company: str, score: int,
                    email: str = "", industry: str = "", source: str = "",
                    calendly_url: str = "") -> bool:
    if score >= 8:
        emoji = ":fire:"
        tag   = "CALIENTE"
    elif score >= 6:
        emoji = ":star:"
        tag   = "Interesante"
    else:
        emoji = ":pushpin:"
        tag   = "Por calificar"

    lines = [
        f"{emoji} *Nuevo Lead — {brand_name}*  `{tag}`",
        f"├── 👤 *Nombre:* {lead_name}",
        f"├── 🏢 *Empresa:* {company}" if company else "",
        f"├── 📧 *Email:* {email}" if email else "",
        f"├── 🏭 *Industria:* {industry}" if industry else "",
        f"├── 📊 *Score:* {score}/10",
        f"├── 🔍 *Fuente:* {source}" if source else "",
        f"└── 📅 *Calendly:* {calendly_url}" if calendly_url else "└── ⏳ Pendiente de agendar",
    ]
    text = "\n".join(l for l in lines if l)
    return _post({"text": text, "attachments": [{"color": "#635BFF", "footer": "Voxify Sales Agent"}]})


def notify_demo_booked(brand_name: str, lead_name: str, company: str,
                       meeting_url: str = "") -> bool:
    text = (
        f":calendar: *Demo Agendada — {brand_name}*\n"
        f"├── 👤 *Lead:* {lead_name}\n"
        f"├── 🏢 *Empresa:* {company}\n"
        f"└── 🔗 *Link:* {meeting_url or 'Calendly enviado'}"
    )
    return _post({"text": text, "attachments": [{"color": "#22c55e", "footer": "Voxify Sales Agent"}]})


def notify_deal_stage_change(brand_name: str, lead_name: str, company: str,
                              old_stage: str, new_stage: str) -> bool:
    old_icon = STAGE_ICONS.get(old_stage, "•")
    new_icon = STAGE_ICONS.get(new_stage, "•")
    text = (
        f":arrow_right: *Avance de Deal — {brand_name}*\n"
        f"├── 👤 {lead_name} ({company})\n"
        f"└── {old_icon} {old_stage.title()} → {new_icon} {new_stage.title()}"
    )
    return _post({"text": text})


def notify_escalation(brand_name: str, lead_name: str, company: str,
                      reason: str, channel: str = "email",
                      last_message: str = "") -> bool:
    lines = [
        f":rotating_light: *Escalamiento — {brand_name}*",
        f"├── 👤 *Lead:* {lead_name} ({company})",
        f"├── 📡 *Canal:* {channel}",
        f"├── ⚠️ *Razón:* {reason}",
    ]
    if last_message:
        lines.append(f"└── 💬 *Mensaje:*\n> {last_message[:300]}")
    return _post({
        "text": "\n".join(lines),
        "attachments": [{"color": "#FF4444", "footer": "Voxify Sales Agent"}],
    })


def send_daily_report(brand_name: str, report: dict) -> bool:
    today        = report.get("date", "hoy")
    new_leads    = report.get("leads_generated", 0)
    contacted    = report.get("contacts_made", 0)
    avg_score    = report.get("avg_lead_score", 0)
    avg_sent     = report.get("avg_sentiment", "neutral")
    escalations  = report.get("escalations_pending", 0)
    bottleneck   = report.get("bottleneck_stage", "")
    pipeline     = report.get("pipeline", {})
    recs         = report.get("recommendations", [])
    closed       = report.get("deals_closed", 0)

    sent_emoji = {"positivo": "😊", "neutral": "😐", "negativo": "😟"}.get(avg_sent, "😐")

    # Pipeline tree
    stage_labels = [
        ("nuevo",       "Nuevo"),
        ("contactado",  "Contactado"),
        ("interesado",  "Interesado"),
        ("demo",        "Demo agendada"),
        ("propuesta",   "Propuesta"),
        ("negociacion", "Negociación"),
        ("cerrado",     "Cerrado ganado"),
    ]
    pipe_lines = []
    for i, (key, label) in enumerate(stage_labels):
        count = pipeline.get(key, 0)
        icon  = STAGE_ICONS.get(key, "•")
        connector = "└──" if i == len(stage_labels) - 1 else "├──"
        pipe_lines.append(f"{connector} {icon} {label}: *{count}*")

    rec_lines = []
    for i, rec in enumerate(recs[:3]):
        connector = "└──" if i == len(recs[:3]) - 1 else "├──"
        rec_lines.append(f"{connector} {rec}")

    blocks = [
        f":bar_chart: *Reporte Diario — {brand_name}* | {today}",
        "",
        f"*📈 Actividad de hoy*",
        f"├── 🔥 Leads generados: *{new_leads}*",
        f"├── 📧 Contactados: *{contacted}*",
        f"├── ✅ Cerrados hoy: *{closed}*",
        f"└── 📊 Score promedio: *{avg_score:.1f}/10*" if isinstance(avg_score, float) else f"└── 📊 Score promedio: *{avg_score}/10*",
        "",
        f"*🎯 Pipeline*",
        *pipe_lines,
        "",
        f"*💡 Sentimiento promedio:* {sent_emoji} {avg_sent.title()}",
        f"*🚨 Escalaciones pendientes:* {escalations}",
        f"*🔍 Cuello de botella:* {bottleneck}" if bottleneck else "",
        "",
        f"*⚡ Recomendaciones*",
        *(rec_lines if rec_lines else ["└── Sin recomendaciones nuevas."]),
    ]
    text = "\n".join(l for l in blocks if l is not None)
    return _post({"text": text, "attachments": [{"color": "#635BFF", "footer": "Voxify Sales Agent"}]})


def is_configured() -> bool:
    return _ok()
