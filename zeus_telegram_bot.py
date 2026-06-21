"""
Zeus VoxifyHub — Telegram bot.
Runs as a background thread inside the Flask server on Railway.
Start via start_bot_thread() called from server.py.
"""
import asyncio
import json
import logging
import os
import re
import threading
from datetime import datetime, time

import pytz
import requests
import anthropic

logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

BOT_TOKEN     = os.environ.get('TELEGRAM_BOT_TOKEN', '')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
HUBSPOT_KEY   = os.environ.get('HUBSPOT_API_KEY', '')
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL', '')
ZEUS_CHAT_ID  = os.environ.get('ZEUS_CHAT_ID', '')
FLASK_URL     = os.environ.get('AGENCIA_CREATIVA_URL',
                               'https://server-production-f212.up.railway.app')

HS_HEADERS = {'Authorization': f'Bearer {HUBSPOT_KEY}', 'Content-Type': 'application/json'}

ZEUS_SYSTEM = """Eres Zeus, CEO virtual de VoxifyHub — agencia de marketing con IA para negocios hispanos en EE.UU.
Tatiana Quiñones (fundadora) es quien te escribe. Trabajas como su brazo ejecutor.

REGLAS ABSOLUTAS — NUNCA las violes:
1. NUNCA pidas copies, textos o mensajes a Tatiana. Si necesitas generar contenido, LO GENERAS TÚ.
2. NUNCA preguntes "¿qué quieres que diga el mensaje?". TÚ decides el mensaje.
3. NUNCA pidas aprobación para generar contenido de outreach/SDR. Lo generas y lo presentas.
4. Solo escalas a Tatiana para: errores técnicos críticos, gasto >$80/mes, cliente cerrado, demo agendada.
5. Para TODO lo creativo (copies, propuestas, mensajes, emails): lo generas solo.

CUÁNDO GENERAR COPY SDR AUTOMÁTICAMENTE:
Si Tatiana menciona un prospecto con cualquier combinación de: nombre de negocio, tipo, ciudad, dolor, canal
→ Generas el copy de inmediato, sin preguntar nada más.
→ Formato: presenta el copy listo para copiar/pegar.
→ Reglas copy SMS (≤160 chars): mencionar negocio por nombre, CTA claro, sin precio día 1, tono Tatiana.
→ Reglas copy WhatsApp (≤300 chars): igual + puede ser levemente más cálido.

MANUAL DE MARCA VOXIFY:
- Voz: cercana, empática, como Tatiana hablando directamente
- Nunca frío ni corporativo
- Español latinoamericano natural
- No mencionar que somos una agencia en día 1
- No revelar IA

ESTADO DEL NEGOCIO (actualizado en cada mensaje):
{stats_block}

Responde en español, directo y ejecutivo. Usa *negrita* para datos clave (Telegram Markdown).
Máximo 400 palabras salvo que generes copies (en ese caso el copy debe estar completo)."""

SDR_PROMPT = """Eres el SDR Agent de VoxifyHub. Genera UN SOLO mensaje de outreach para este prospecto:

Negocio: {nombre_negocio}
Tipo: {vertical}
Ciudad: {ciudad}
Dolor detectado: {dolor}
Canal: {canal} — DÍA {dia}

REGLAS:
- Máximo 160 caracteres para SMS, 300 para WhatsApp
- Mencionar el negocio por nombre, CTA claro al final
- No mencionar precio en día 1 o 3, no revelar IA
- Tono: Tatiana hablando directamente, cálida, latina, español latinoamericano

Responde con SOLO el texto del mensaje. Sin título, sin "Día X:", sin comillas extra."""


# ── Data helpers ──────────────────────────────────────────────────────────────

def voxify_stats() -> dict:
    try:
        r = requests.get(f'{FLASK_URL}/voxify-stats', timeout=8)
        return r.json()
    except Exception as e:
        logger.warning(f'voxify_stats error: {e}')
        return {}


def hs_contacts(limit: int = 5) -> list:
    try:
        r = requests.get(
            'https://api.hubapi.com/crm/v3/objects/contacts', headers=HS_HEADERS,
            params={'limit': limit,
                    'properties': 'firstname,lastname,email,phone,createdate,lifecyclestage'},
            timeout=10)
        return r.json().get('results', [])
    except Exception as e:
        logger.warning(f'hs_contacts error: {e}')
        return []


def hs_deals(limit: int = 10) -> list:
    try:
        r = requests.get(
            'https://api.hubapi.com/crm/v3/objects/deals', headers=HS_HEADERS,
            params={'limit': limit,
                    'properties': 'dealname,amount,dealstage,closedate,pipeline'},
            timeout=10)
        return r.json().get('results', [])
    except Exception as e:
        logger.warning(f'hs_deals error: {e}')
        return []


def zeus_claude(user_text: str, stats: dict) -> str:
    fecha = stats.get('fecha', datetime.now().strftime('%Y-%m-%d'))
    stats_block = (
        f"Fecha: {fecha}\n"
        f"• Prospectos total: {stats.get('total_prospectos', '?')}\n"
        f"• Calificados (score≥8): {stats.get('calificados', '?')}\n"
        f"• Nuevos hoy: {stats.get('nuevos', '?')}\n"
        f"• Contactados: {stats.get('contactados', '?')}\n"
        f"• Google API calls hoy: {stats.get('google_calls_hoy', '?')}\n"
        f"• Costo Google acumulado: ${stats.get('google_costo_total', 0):.4f}"
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1000,
        system=ZEUS_SYSTEM.format(stats_block=stats_block),
        messages=[{'role': 'user', 'content': user_text}]
    )
    return msg.content[0].text


def generate_sdr_copy(nombre: str, vertical: str = 'negocio',
                      ciudad: str = 'Orlando', dolor: str = 'sin presencia digital',
                      canal: str = 'SMS', dia: int = 1) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=300,
        messages=[{'role': 'user', 'content': SDR_PROMPT.format(
            nombre_negocio=nombre, vertical=vertical, ciudad=ciudad,
            dolor=dolor, canal=canal, dia=dia
        )}]
    )
    return msg.content[0].text.strip()


def slack_notify(text: str):
    if not SLACK_WEBHOOK:
        return
    try:
        requests.post(SLACK_WEBHOOK, json={'text': text}, timeout=5)
    except Exception:
        pass


# ── Build application (lazy import to avoid loading at module level) ───────────

def _build_application():
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "⚡ *Zeus VoxifyHub — activo y listo.*\n\n"
            "Comandos:\n"
            "/stats — métricas de prospectos\n"
            "/leads — últimos 5 contactos en HubSpot\n"
            "/pipeline — deals activos\n"
            "/reporte — resumen ejecutivo del día\n"
            "/copy — generar copy SDR\n"
            "/myid — tu chat ID para configurar reportes automáticos\n\n"
            "O escríbeme directamente.",
            parse_mode='Markdown'
        )

    async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        cid = update.message.chat.id
        await update.message.reply_text(
            f"🆔 Tu chat ID: `{cid}`\n\n"
            f"Configura `ZEUS_CHAT_ID={cid}` en Railway → Variables de entorno.",
            parse_mode='Markdown'
        )
        logger.info(f'chat_id solicitado: {cid}')

    async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Obteniendo métricas...")
        s = voxify_stats()
        nota = "\n\n⚠️ _Pipeline aún no ha corrido hoy_" if not s else ''
        text = (
            f"📊 *Stats VoxifyHub — {s.get('fecha', 'hoy')}*\n\n"
            f"Prospectos total: *{s.get('total_prospectos', 0)}*\n"
            f"Calificados: *{s.get('calificados', 0)}*\n"
            f"Nuevos hoy: *{s.get('nuevos', 0)}*\n"
            f"Contactados: *{s.get('contactados', 0)}*\n"
            f"Google API calls hoy: *{s.get('google_calls_hoy', 0)}*\n"
            f"Costo Google acumulado: *${s.get('google_costo_total', 0):.4f}*"
            f"{nota}"
        )
        await update.message.reply_text(text, parse_mode='Markdown')

    async def cmd_leads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Consultando HubSpot...")
        contacts = hs_contacts(5)
        if not contacts:
            await update.message.reply_text("❌ Sin contactos en HubSpot o error de API.")
            return
        lines = ["👥 *Últimos 5 contactos (HubSpot):*\n"]
        for c in contacts:
            p = c.get('properties', {})
            name = f"{p.get('firstname', '')} {p.get('lastname', '')}".strip() or 'Sin nombre'
            stage = p.get('lifecyclestage', '—')
            created = p.get('createdate', '')[:10] if p.get('createdate') else '—'
            lines.append(f"• *{name}* — {stage} ({created})")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    async def cmd_pipeline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Consultando pipeline...")
        deals = hs_deals()
        if not deals:
            await update.message.reply_text("❌ Sin deals en HubSpot o error de API.")
            return
        total = sum(float(d.get('properties', {}).get('amount') or 0) for d in deals)
        lines = [f"💼 *Pipeline HubSpot ({len(deals)} deals — ${total:,.0f} total):*\n"]
        for d in deals[:8]:
            p = d.get('properties', {})
            name = p.get('dealname', 'Sin nombre')
            amt = float(p.get('amount') or 0)
            stage = p.get('dealstage', '—')
            lines.append(f"• *{name}* — ${amt:,.0f} | {stage}")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    async def cmd_reporte(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Generando reporte ejecutivo...")
        stats = voxify_stats()
        deals = hs_deals()
        contacts = hs_contacts(3)
        total_deals = sum(float(d.get('properties', {}).get('amount') or 0) for d in deals)
        prompt = (
            f"Genera un reporte ejecutivo diario para VoxifyHub.\n"
            f"Stats prospectos: {json.dumps(stats)}\n"
            f"HubSpot: {len(deals)} deals activos, ${total_deals:,.0f} en pipeline, "
            f"{len(contacts)} contactos recientes.\n"
            "Incluye: resumen de situación, logros del día, próximos pasos, alertas si hay algo urgente. "
            "Bullet points, tono ejecutivo, máximo 400 palabras."
        )
        reply = zeus_claude(prompt, stats)
        slack_notify(f"📋 *Reporte Zeus — {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n{reply}")
        await update.message.reply_text(f"📋 *Reporte del día*\n\n{reply}", parse_mode='Markdown')

    async def cmd_copy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = ' '.join(ctx.args) if ctx.args else ''
        if not args:
            await update.message.reply_text(
                "📝 *Generador de Copy SDR*\n\n"
                "Uso: `/copy NombreNegocio | tipo | ciudad | dolor | canal`\n\n"
                "Ejemplo:\n"
                "`/copy Ají Pique | restaurante colombiano | Orlando | sin website | SMS`\n\n"
                "O dime: _\"genera un SMS para Ají Pique, restaurante colombiano en Orlando\"_",
                parse_mode='Markdown'
            )
            return
        parts = [p.strip() for p in args.split('|')]
        nombre   = parts[0] if len(parts) > 0 else args
        vertical = parts[1] if len(parts) > 1 else 'negocio'
        ciudad   = parts[2] if len(parts) > 2 else 'Orlando'
        dolor    = parts[3] if len(parts) > 3 else 'sin presencia digital'
        canal    = parts[4] if len(parts) > 4 else 'SMS'
        await update.message.reply_text(f"⏳ Generando copy {canal} para *{nombre}*...", parse_mode='Markdown')
        copy_text = generate_sdr_copy(nombre, vertical, ciudad, dolor, canal, dia=1)
        char_count = len(copy_text)
        limit = 160 if canal.upper() == 'SMS' else 300
        status = "✅" if char_count <= limit else "⚠️"
        await update.message.reply_text(
            f"📱 *Copy {canal} — {nombre}*\n_{status} {char_count}/{limit} chars_\n\n`{copy_text}`",
            parse_mode='Markdown'
        )

    async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.message.from_user.first_name or 'Tatiana'
        logger.info(f'Zeus mensaje de {user}: {update.message.text[:60]}')
        await update.message.reply_text("⏳ Procesando...")
        stats = voxify_stats()
        reply = zeus_claude(update.message.text, stats)
        await update.message.reply_text(reply, parse_mode='Markdown')

    async def _daily_report(ctx: ContextTypes.DEFAULT_TYPE):
        if not ZEUS_CHAT_ID:
            logger.warning('ZEUS_CHAT_ID no configurado — reporte 4pm omitido. Usa /myid para obtenerlo.')
            return
        logger.info('Enviando reporte diario 4pm ET...')
        try:
            stats = voxify_stats()
            deals = hs_deals()
            contacts = hs_contacts(3)
            total_deals = sum(float(d.get('properties', {}).get('amount') or 0) for d in deals)
            prompt = (
                f"Genera un reporte ejecutivo diario para VoxifyHub.\n"
                f"Stats prospectos: {json.dumps(stats)}\n"
                f"HubSpot: {len(deals)} deals activos, ${total_deals:,.0f} en pipeline, "
                f"{len(contacts)} contactos recientes.\n"
                "Incluye: resumen, logros del día, próximas acciones, alertas urgentes. "
                "Bullet points, tono ejecutivo, máximo 400 palabras."
            )
            reply = zeus_claude(prompt, stats)
            slack_notify(f"📋 *Reporte Zeus — {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n{reply}")
            await ctx.bot.send_message(
                chat_id=ZEUS_CHAT_ID,
                text=f"📋 *Reporte diario — {datetime.now(ET).strftime('%A %d %b, %H:%M ET')}*\n\n{reply}",
                parse_mode='Markdown'
            )
            logger.info('Reporte 4pm enviado OK')
        except Exception as e:
            logger.error(f'Error reporte 4pm: {e}')
            try:
                await ctx.bot.send_message(chat_id=ZEUS_CHAT_ID, text=f"⚠️ Error reporte diario: {e}")
            except Exception:
                pass

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start',    cmd_start))
    app.add_handler(CommandHandler('stats',    cmd_stats))
    app.add_handler(CommandHandler('leads',    cmd_leads))
    app.add_handler(CommandHandler('pipeline', cmd_pipeline))
    app.add_handler(CommandHandler('reporte',  cmd_reporte))
    app.add_handler(CommandHandler('copy',     cmd_copy))
    app.add_handler(CommandHandler('myid',     cmd_myid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.job_queue.run_daily(
        _daily_report,
        time=time(16, 0, 0, tzinfo=ET),
        days=(0, 1, 2, 3, 4),
    )
    return app


# ── Background thread entry point ─────────────────────────────────────────────

def _run_bot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _main():
        app = _build_application()
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=['message'])
        logger.info('Zeus bot polling activo')
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    try:
        loop.run_until_complete(_main())
    except Exception as e:
        logger.error(f'Zeus bot loop error: {e}')
    finally:
        loop.close()


def start_bot_thread():
    """Start Zeus Telegram bot in a daemon background thread."""
    if not BOT_TOKEN:
        logger.info('TELEGRAM_BOT_TOKEN no configurado — Zeus bot desactivado')
        return
    if not ANTHROPIC_KEY:
        logger.warning('ANTHROPIC_API_KEY faltante — Zeus bot no puede iniciar')
        return
    t = threading.Thread(target=_run_bot_loop, daemon=True, name='zeus-telegram-bot')
    t.start()
    logger.info(f'Zeus bot iniciado en thread (ZEUS_CHAT_ID: {ZEUS_CHAT_ID or "no configurado"})')
