"""
Multi-brand Creative Director Agent — agentic tool-use loop with Claude Opus 4.8.
Each brand runs with its own system prompt, strategy, and social credentials.
"""

import json
import logging
import anthropic
from datetime import date

from config.settings import ANTHROPIC_API_KEY, AGENT_MODEL, IMAGES_ENABLED, VIDEO_ENABLED
from config.brands_registry import get_brand, DEFAULT_BRAND_ID
from strategy.plan_90days import get_current_phase
from tools.content_generator import CONTENT_TOOLS, execute_content_tool
from tools.media_generator import MEDIA_TOOLS, execute_media_tool
from tools.social_media import SOCIAL_TOOLS, execute_social_tool
from tools.analytics import ANALYTICS_TOOLS, execute_analytics_tool
from tools.trends import TREND_TOOLS, execute_trend_tool
from tools.competitor import COMPETITOR_TOOLS, execute_competitor_tool
from tools.engagement import ENGAGEMENT_TOOLS, execute_engagement_tool

logger = logging.getLogger(__name__)

ALL_TOOLS = (
    ANALYTICS_TOOLS + TREND_TOOLS + COMPETITOR_TOOLS + ENGAGEMENT_TOOLS +
    CONTENT_TOOLS + MEDIA_TOOLS + SOCIAL_TOOLS
)

TOOL_DISPATCH = {
    **{t["name"]: "analytics"  for t in ANALYTICS_TOOLS},
    **{t["name"]: "trends"     for t in TREND_TOOLS},
    **{t["name"]: "competitor" for t in COMPETITOR_TOOLS},
    **{t["name"]: "engagement" for t in ENGAGEMENT_TOOLS},
    **{t["name"]: "content"    for t in CONTENT_TOOLS},
    **{t["name"]: "media"      for t in MEDIA_TOOLS},
    **{t["name"]: "social"     for t in SOCIAL_TOOLS},
}


class VoxifyCreativeDirector:
    def __init__(self, db, brand_id: str = DEFAULT_BRAND_ID):
        self.db = db
        self.brand = get_brand(brand_id)
        self.brand_id = brand_id
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        linkedin_token = self.brand["credentials"].get("linkedin_access_token", "")
        linkedin_org   = self.brand["credentials"].get("linkedin_organization_id", "")
        self.linkedin_enabled = bool(linkedin_token and linkedin_org)

    def run(self, task: str, max_iterations: int = 30, tools: list = None) -> str:
        """Execute a task through the agentic tool-use loop."""
        logger.info(f"Iniciando tarea: {task[:100]}")
        messages = [{"role": "user", "content": task}]
        final_response = ""
        active_tools = tools if tools is not None else ALL_TOOLS

        # Build rich system context: base prompt + strategy + research + content lines + monthly plan
        research_ctx = ""
        if self.brand.get("research_summary"):
            research_ctx += f"\n\n══ INVESTIGACIÓN DE MERCADO ══\n{self.brand['research_summary'][:2000]}"
        market_insights = self.brand.get("market_insights", [])
        if market_insights and isinstance(market_insights, list):
            research_ctx += "\n\n══ INSIGHTS DE MERCADO ══\n" + "\n".join(f"• {i}" for i in market_insights[:10])

        content_lines = self.brand.get("content_lines") or self.brand.get("content_pillars", [])
        content_lines_ctx = ""
        if content_lines:
            content_lines_ctx = "\n\n══ PILARES DE CONTENIDO (respetar proporciones) ══\n"
            for p in content_lines:
                pct = p.get("percentage", 0)
                if isinstance(pct, float) and pct <= 1:
                    pct = int(pct * 100)
                content_lines_ctx += f"• {p.get('name','?')} ({pct}%): {p.get('description','')}\n"

        monthly_ctx = ""
        if self.brand.get("monthly_plan"):
            monthly_ctx = f"\n\n══ PLAN MENSUAL ACTIVO ══\n{self.brand['monthly_plan'][:1500]}"

        full_system = (
            self.brand["system_prompt"]
            + "\n\n" + self.brand.get("strategy_90days", "")
            + research_ctx
            + content_lines_ctx
            + monthly_ctx
        )

        for iteration in range(max_iterations):
            with self.client.messages.stream(
                model=AGENT_MODEL,
                max_tokens=8096,
                thinking={"type": "adaptive"},
                system=full_system,
                tools=active_tools,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()

            stop_reason = response.stop_reason

            if stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        final_response = block.text
                logger.info(f"Agente completó en {iteration + 1} iteraciones.")
                break

            if stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input
                    category = TOOL_DISPATCH.get(tool_name, "unknown")
                    logger.info(f"[{category}] {tool_name}")

                    try:
                        if category == "analytics":
                            result_str = execute_analytics_tool(tool_name, tool_input, self.db)
                        elif category == "trends":
                            result_str = execute_trend_tool(tool_name, tool_input)
                        elif category == "competitor":
                            result_str = execute_competitor_tool(tool_name, tool_input)
                        elif category == "engagement":
                            result_str = execute_engagement_tool(tool_name, tool_input, self.db)
                        elif category == "content":
                            result_str = execute_content_tool(tool_name, tool_input, self.db,
                                                              brand_id=self.brand_id)
                        elif category == "media":
                            result_str = execute_media_tool(tool_name, tool_input)
                        elif category == "social":
                            result_str = execute_social_tool(tool_name, tool_input)
                        else:
                            result_str = json.dumps({"error": f"Herramienta no reconocida: {tool_name}"})
                    except Exception as e:
                        logger.error(f"Error en herramienta {tool_name}: {e}")
                        result_str = json.dumps({"error": str(e)})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

                messages.append({"role": "user", "content": tool_results})
            else:
                logger.warning(f"Stop reason inesperado: {stop_reason}")
                break

        self.db.log_session(task[:200], final_response[:500])
        return final_response

    @staticmethod
    def _get_week_schedule() -> dict:
        """Calculate exact ISO dates for NEXT week's posting schedule (Mon-Fri).
        Always targets the upcoming week so posts never land in the past."""
        from datetime import timedelta
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7  # always next Monday
        monday = today + timedelta(days=days_until_monday)
        days = {
            "mon": monday,
            "tue": monday + timedelta(days=1),
            "wed": monday + timedelta(days=2),
            "thu": monday + timedelta(days=3),
            "fri": monday + timedelta(days=4),
        }
        return {
            # Instagram: Mon–Fri, 9 AM (Friday is a Reel)
            "ig_mon": f"{days['mon'].isoformat()}T09:00:00",
            "ig_tue": f"{days['tue'].isoformat()}T09:00:00",
            "ig_wed": f"{days['wed'].isoformat()}T09:00:00",
            "ig_thu": f"{days['thu'].isoformat()}T09:00:00",
            "ig_fri": f"{days['fri'].isoformat()}T09:00:00",
            # Facebook: Mon–Fri, 10 AM
            "fb_mon": f"{days['mon'].isoformat()}T10:00:00",
            "fb_tue": f"{days['tue'].isoformat()}T10:00:00",
            "fb_wed": f"{days['wed'].isoformat()}T10:00:00",
            "fb_thu": f"{days['thu'].isoformat()}T10:00:00",
            "fb_fri": f"{days['fri'].isoformat()}T10:00:00",
            # LinkedIn: Wednesday only, 8 AM
            "li_wed": f"{days['wed'].isoformat()}T08:00:00",
            "dates": {k: v.strftime("%A %d %b") for k, v in days.items()},
        }

    def weekly_content_run(self, extra_context: str = "",
                           media_assets: list = None, campaign: dict = None) -> str:
        """
        Full strategic weekly run — generates 11 posts (5 IG + 5 FB + 1 LI).
        When real media assets are provided, prioritizes them over FLUX generation
        and adds a second pass of posts using the real photos.
        """
        phase = get_current_phase()
        today = date.today()
        week = today.isocalendar()[1]
        monthly_targets = self.brand.get("monthly_targets", {})
        targets = monthly_targets.get(min(phase, 3), monthly_targets.get(3, {}))
        sched = self._get_week_schedule()
        dates = sched["dates"]

        BASE_URL = "http://localhost:5000"
        real_images = [m for m in (media_assets or []) if m.get("media_type") == "image"]
        real_videos  = [m for m in (media_assets or []) if m.get("media_type") == "video"]
        has_real_media = bool(real_images or real_videos)

        # Tools to use: remove generate_post_image when real images exist so agent cannot bypass
        if has_real_media:
            weekly_tools = [t for t in ALL_TOOLS if t["name"] != "generate_post_image"]
        else:
            weekly_tools = ALL_TOOLS

        if has_real_media:
            # Use absolute URLs so the agent can reference them directly
            img_list = "\n".join(
                f"     [{i+1}] {BASE_URL}{m['url']}  | {m.get('title') or m.get('filename')}"
                for i, m in enumerate(real_images[:20])
            )
            vid_list = "\n".join(
                f"     [{i+1}] {BASE_URL}{m['url']}  | {m.get('title') or m.get('filename')}"
                for i, m in enumerate(real_videos[:10])
            ) if real_videos else ""

            images_note = (
                "   → IMAGEN: elige la URL de la lista del PASO 0 que mejor ilustre este post\n"
                "     y guárdala directamente en image_url de save_content_to_calendar.\n"
                "     (generate_post_image NO está disponible en esta sesión — usa fotos reales.)\n"
            )
        else:
            img_list = ""
            vid_list = ""
            images_note = (
                "   → Genera la imagen con generate_post_image (FLUX). Describe la escena EN INGLÉS\n"
                "     con personas reales en el tipo de negocio elegido. Guarda la image_url en save_content_to_calendar.\n"
                if IMAGES_ENABLED else
                "   → (Imágenes no configuradas — guarda sin image_url.)\n"
            )
        video_note = (
            "   → Genera el video con generate_reel_video (solo visual, sin audio).\n"
            "   → Decide si este Reel necesita voz en off (si el mensaje es narrativo o emotivo, SÍ):\n"
            "     - Si SÍ: escribe un guion ≤100 palabras en español y usa generate_voiceover.\n"
            "     - Siempre: usa generate_background_music (mood: brand o según el tono del Reel).\n"
            "   → Mezcla video + voiceover + música con mix_reel_audio.\n"
            "   → Guarda la video_url resultante (con audio) en save_content_to_calendar.\n"
            if VIDEO_ENABLED else ""
        )
        li_note = "   → LinkedIn NO lleva imagen. Solo texto. Se sube manualmente.\n"

        ig_target  = targets.get("instagram_followers", "N/A")
        eng_target = targets.get("instagram_engagement_rate", "N/A")
        cli_target = targets.get("clients", "N/A")

        # Build PASO 0 block only when real media exists
        paso0 = ""
        if has_real_media:
            paso0 = f"""
─── PASO 0: BIBLIOTECA VISUAL DE LA MARCA ───
⚠️ TIENES FOTOS Y VIDEOS REALES DE LA MARCA. ÚSALOS. NO generes imágenes con FLUX salvo que
   una foto específica no exista para el concepto del post.

{"IMÁGENES DISPONIBLES:" if real_images else ""}
{img_list}
{"VIDEOS DISPONIBLES:" if real_videos else ""}
{vid_list}

REGLA DE USO: Para cada post, elige la imagen de esta lista que mejor ilustre el contenido.
Pon su URL directamente en image_url de save_content_to_calendar. Varía — no repitas la misma
foto en todos los posts. Distribuye las imágenes a lo largo de la semana.
"""

        # Build PASO 5 block for extra posts with real photos
        paso5 = ""
        if has_real_media and real_images:
            img_pairs = "\n".join(
                f"  [{i+1}] {BASE_URL}{m['url']}  — {m.get('title') or m.get('filename')}"
                for i, m in enumerate(real_images)
            )
            paso5 = f"""
─── PASO 5: POSTS ADICIONALES CON FOTOS REALES ───
Ahora crea posts EXTRA (NO borres ni modifiques los anteriores) para cada foto real de la marca
que no haya sido usada en los posts del PASO 3. El objetivo es que cada imagen cargada tenga
al menos una propuesta de contenido lista para aprobación.

Fotos a cubrir:
{img_pairs}

Para cada foto:
  • Plataforma: instagram_post (9:00 AM) o facebook_post (10:00 AM) — alterna
  • Fecha: usa cualquier slot de la semana siguiente (Mon–Fri) — puedes repetir fecha con
    horario diferente (+1h) para que no colisionen
  • Caption: copy nativo de la plataforma elegida, alineado a la campaña del mes si existe
  • image_url: la URL de la foto de la lista de arriba
  • Guarda con save_content_to_calendar (status="pending", brand="{self.brand_id}")

Termina este paso confirmando cuántos posts adicionales guardaste.
"""

        task = f"""
Hoy es {today.strftime('%A %d de %B de %Y')}. Semana {week}. FASE {phase} de la estrategia de 90 días.
Marca activa: {self.brand['name']} — {self.brand['tagline']}

OBJETIVOS FASE {phase}:
- Instagram: {ig_target} seguidores | Engagement ≥ {eng_target}%
- Clientes meta: {cli_target}
{paso0}
════════════════════════════════════════════════════════
MISIÓN: Generar los 11 posts de la semana + posts adicionales con fotos reales
5 Instagram + 5 Facebook (uno por día, lunes a viernes) + 1 LinkedIn (miércoles)
{"+ posts adicionales — uno por cada foto real de la marca" if has_real_media else ""}
════════════════════════════════════════════════════════

─── PASO 1: ANÁLISIS PREVIO ───
Ejecuta estas 4 herramientas antes de crear cualquier contenido:
• analyze_performance → qué funcionó, engagement promedio, mejor tipo de contenido
• detect_trends con geo="US-FL" → tendencias actuales de la audiencia
• analyze_competitors → brechas y ángulos de diferenciación disponibles
• get_engagement_data → comentarios sin responder (alerta si hay urgentes)

─── PASO 2: DECISIÓN ESTRATÉGICA ───
Define:
• Tema central de la semana (hilo conductor para todos los posts)
• Tipo de negocio a destacar (restaurantes / salones / contractors / realtors / spas / clínicas)
• Ángulo de diferenciación frente a la competencia

─── PASO 3: GENERA LOS 11 POSTS (UNO POR UNO, en este orden) ───

Regla: cada post tiene contenido DIFERENTE y formato NATIVO de su plataforma.
El tema central une la semana, pero el tono y formato cambian por red.

INSTAGRAM — 9:00 AM ET cada día
Los pilares rotan: Educación → Dolor/Solución → Comunidad → Prueba Social → Reel

📸 IG LUNES — {dates['mon']} | Pillar: Educación
   Tipo: instagram_post | Fecha: {sched['ig_mon']}
   Formato: hook + desarrollo + CTA + 20 hashtags
{images_note}
📸 IG MARTES — {dates['tue']} | Pillar: Dolor→Solución
   Tipo: instagram_post | Fecha: {sched['ig_tue']}
   Formato: problema real del negocio + cómo {self.brand['name']} lo resuelve + CTA + hashtags
{images_note}
📸 IG MIÉRCOLES — {dates['wed']} | Pillar: Comunidad
   Tipo: instagram_post | Fecha: {sched['ig_wed']}
   Formato: historia o testimonio de cliente + CTA + hashtags
{images_note}
📸 IG JUEVES — {dates['thu']} | Pillar: Prueba Social
   Tipo: instagram_post | Fecha: {sched['ig_thu']}
   Formato: dato concreto o resultado + CTA + hashtags
{images_note}
🎬 IG VIERNES — {dates['fri']} | REEL
   Tipo: instagram_reel | Fecha: {sched['ig_fri']}
   CAPTION: hook visual + 2-3 oraciones de valor + CTA + 15-20 hashtags
{images_note}{video_note}

FACEBOOK — 10:00 AM ET cada día
Tono conversacional, termina siempre con pregunta para generar comentarios.

📘 FB LUNES — {dates['mon']} | Pillar: Educación
   Tipo: facebook_post | Fecha: {sched['fb_mon']}
{images_note}
📘 FB MARTES — {dates['tue']} | Pillar: Comunidad
   Tipo: facebook_post | Fecha: {sched['fb_tue']}
{images_note}
📘 FB MIÉRCOLES — {dates['wed']} | Pillar: Dolor→Solución
   Tipo: facebook_post | Fecha: {sched['fb_wed']}
{images_note}
📘 FB JUEVES — {dates['thu']} | Pillar: Behind the Scenes
   Tipo: facebook_post | Fecha: {sched['fb_thu']}
{images_note}
📘 FB VIERNES — {dates['fri']} | Pillar: Prueba Social
   Tipo: facebook_post | Fecha: {sched['fb_fri']}
{images_note}

LINKEDIN — 8:00 AM ET (solo miércoles)

💼 LI MIÉRCOLES — {dates['wed']} | Pillar: Thought Leadership
   Tipo: linkedin_post | Fecha: {sched['li_wed']}
   Formato: historia profesional o dato de industria + insight + CTA de conexión
{li_note}

─── PASO 4: REPORTE DE LOS 11 POSTS ───
✦ Tema de la semana y justificación basada en datos
✦ Confirmación de los 11 posts guardados con fechas e imagen usada
✦ Tendencia aprovechada y brecha competitiva usada
✦ Alerta de engagement si hay comentarios urgentes
{paso5}
─── PASO 6: REPORTE FINAL ───
✦ Total de posts guardados (11 base + adicionales con fotos reales)
✦ Lista de fotos reales usadas y en qué post apareció cada una
✦ Cualquier foto que no pudo asociarse a un concepto (explicar por qué)

⚠️ REGLAS CRÍTICAS:
- Guarda CADA post con save_content_to_calendar ANTES de pasar al siguiente
- SIEMPRE pasa brand="{self.brand_id}" en cada llamada a save_content_to_calendar
- NO publiques nada — solo genera y guarda para aprobación
- LinkedIn NO lleva image_url
- El contenido de IG y FB del mismo día debe ser diferente entre sí
- NO elimines ni modifiques posts ya guardados de runs anteriores
{extra_context}
"""
        result = self.run(task, tools=weekly_tools)

        # Save weekly strategy record
        try:
            self.db.conn.execute(
                "INSERT INTO weekly_strategy (week_number, year, phase, theme, analysis, brand_id) VALUES (?,?,?,?,?,?)",
                (week, today.year, phase, "weekly_run", result[:500], self.brand_id),
            )
            self.db.conn.commit()
        except Exception:
            pass

        return result

    def publish_post(self, platform: str, post_id: int, content: str, image_url: str = None) -> dict:
        """Publish a single approved post directly via the social media API."""
        from tools.social_media import execute_social_tool

        creds = self.brand.get("credentials", {})

        if platform == "instagram":
            if not image_url:
                return {"success": False, "error": "Instagram requiere una URL de imagen."}
            result = execute_social_tool("post_to_instagram", {"caption": content, "image_url": image_url}, creds=creds)
        elif platform == "facebook":
            result = execute_social_tool("post_to_facebook", {"message": content, "image_url": image_url}, creds=creds)
        else:
            return {"success": False, "error": f"Publicación automática no soportada para: {platform}"}

        return json.loads(result)

    def generate_engagement_responses(self) -> str:
        """Generate suggested responses for unanswered comments."""
        task = (
            "Usa get_engagement_data (con sync=true) para ver los comentarios sin responder en Instagram. "
            "Luego usa generate_comment_responses para obtener la lista de comentarios. "
            "Genera una respuesta personalizada para cada uno, en español, con la voz cercana y profesional de VoxifyHub. "
            "Presenta las respuestas listas para copiar y pegar, ordenadas por comentario."
        )
        return self.run(task)

    def generate_extra_content_run(self, media_assets: list = None, campaign: dict = None) -> str:
        """
        Generate extra content for the remaining days of the month:
        - 2 Instagram Stories/week (Tue+Thu at 18:00 ET) using real photos
        - 3 extra Reels/week (Mon+Wed+Sat at 18:00 ET)
        - Weekend posts (Sat+Sun 09:00 IG / 10:00 FB) for empty slots
        Does NOT touch or modify existing approved posts.
        """
        from datetime import date, timedelta

        today = date.today()
        from_date = today + timedelta(days=1)
        if today.month == 12:
            to_date = date(today.year, 12, 31)
        else:
            to_date = date(today.year, today.month + 1, 1) - timedelta(days=1)

        # Fetch occupied slots to avoid conflicts
        existing_ig = {
            row[0] for row in self.db.conn.execute(
                """SELECT scheduled_date FROM scheduled_posts
                   WHERE brand_id=? AND platform='instagram'
                   AND status IN ('pending','pending_approval')
                   AND scheduled_date BETWEEN ? AND ?""",
                (self.brand_id, from_date.isoformat() + "T00:00:00", to_date.isoformat() + "T23:59:59")
            ).fetchall()
        }
        existing_fb = {
            row[0] for row in self.db.conn.execute(
                """SELECT scheduled_date FROM scheduled_posts
                   WHERE brand_id=? AND platform='facebook'
                   AND status IN ('pending','pending_approval')
                   AND scheduled_date BETWEEN ? AND ?""",
                (self.brand_id, from_date.isoformat() + "T00:00:00", to_date.isoformat() + "T23:59:59")
            ).fetchall()
        }

        stories, reels, weekend_posts = [], [], []
        current = from_date
        while current <= to_date:
            dow = current.weekday()  # 0=Mon … 6=Sun
            date_str = current.isoformat()

            # Stories: Tue (1) + Thu (3) at 18:00
            if dow in (1, 3):
                slot = f"{date_str}T18:00:00"
                if slot not in existing_ig:
                    stories.append({"slot": slot, "day": current.strftime("%A %d %b")})

            # Extra Reels: Mon (0) + Wed (2) + Sat (5) at 18:00
            if dow in (0, 2, 5):
                slot = f"{date_str}T18:00:00"
                if slot not in existing_ig:
                    reels.append({"slot": slot, "day": current.strftime("%A %d %b")})

            # Weekend posts: Sat (5) + Sun (6) at 09:00 IG / 10:00 FB
            if dow in (5, 6):
                ig_slot = f"{date_str}T09:00:00"
                fb_slot = f"{date_str}T10:00:00"
                ig_free = ig_slot not in existing_ig
                fb_free = fb_slot not in existing_fb
                if ig_free or fb_free:
                    weekend_posts.append({
                        "date": date_str, "day": current.strftime("%A"),
                        "ig_slot": ig_slot, "fb_slot": fb_slot,
                        "ig_free": ig_free, "fb_free": fb_free,
                    })

            current += timedelta(days=1)

        BASE_URL = "http://localhost:5000"
        real_images = [m for m in (media_assets or []) if m.get("media_type") == "image"]
        real_videos  = [m for m in (media_assets or []) if m.get("media_type") == "video"]

        img_list = "\n".join(
            f"  [{i+1}] {BASE_URL}{m['url']}  — {m.get('title') or m.get('filename')}"
            for i, m in enumerate(real_images[:20])
        ) if real_images else "  (No hay fotos reales en la biblioteca)"

        vid_list = ("\nVIDEOS REALES:\n" + "\n".join(
            f"  [{i+1}] {BASE_URL}{m['url']}  — {m.get('title') or m.get('filename')}"
            for i, m in enumerate(real_videos[:10])
        )) if real_videos else ""

        brand_name    = self.brand["name"]
        brand_tagline = self.brand.get("tagline", "")
        brand_industry = self.brand.get("industry", brand_name)
        brand_hashtags = " ".join(self.brand.get("hashtags", [])[:5]) or f"#{brand_name.replace(' ','')}"

        # Build Stories block
        stories_block = ""
        if stories:
            lines = "".join(
                f"📱 STORY #{i+1} — {s['day']} 18:00 ET\n"
                f"   scheduled_date: {s['slot']}\n"
                f"   content_type: instagram_story | platform: instagram\n"
                f"   image_url: elige la foto que mejor represente {brand_name}\n"
                f"   content: máx 5 palabras o vacío — las Stories son 100% visuales\n\n"
                for i, s in enumerate(stories)
            )
            stories_block = (
                f"─── STORIES DE INSTAGRAM — {len(stories)} stories para generar ───\n"
                f"Marca: {brand_name}. Usa fotos reales de la lista. Sin caption largo — máx 5 palabras.\n\n" + lines
            )

        # Build Reels block
        reels_block = ""
        if reels:
            if real_videos and VIDEO_ENABLED:
                video_instr = f"Hay videos reales — úsalos si encajan, si no usa generate_reel_video."
            elif VIDEO_ENABLED:
                video_instr = f"Genera cada reel con generate_reel_video (escena visual de {brand_name} — {brand_industry}, solo visual)."
            else:
                video_instr = "VIDEO_ENABLED=false — guarda con image_url como Reel de foto."
            lines = "".join(
                f"🎬 REEL #{i+1} — {r['day']} 18:00 ET\n"
                f"   scheduled_date: {r['slot']}\n"
                f"   content_type: instagram_reel | platform: instagram\n"
                f"   caption: hook visual + propuesta de valor de {brand_name} + CTA + 15 hashtags de la marca\n"
                f"   video_url: {video_instr if i == 0 else '(ídem)'}\n\n"
                for i, r in enumerate(reels)
            )
            reels_block = (
                f"─── REELS EXTRA — {len(reels)} reels para generar ───\n"
                f"Marca: {brand_name} — {brand_tagline}\n{video_instr}\n\n" + lines
            )

        # Build Weekend block
        weekend_block = ""
        if weekend_posts:
            lines = []
            for w in weekend_posts:
                block = f"📅 {w['day'].upper()} {w['date']}\n"
                if w["ig_free"]:
                    block += (
                        f"   IG 09:00 → scheduled_date: {w['ig_slot']}\n"
                        f"            content_type: instagram_post | platform: instagram\n"
                        f"            caption: tono cálido y relajado, conecta con la comunidad de {brand_name}\n"
                        f"            image_url: foto real de la lista\n"
                    )
                if w["fb_free"]:
                    block += (
                        f"   FB 10:00 → scheduled_date: {w['fb_slot']}\n"
                        f"            content_type: facebook_post | platform: facebook\n"
                        f"            message: versión FB con pregunta al final, voz de {brand_name}\n"
                        f"            image_url: misma foto que en IG\n"
                    )
                lines.append(block)
            weekend_block = (
                f"─── POSTS DE FIN DE SEMANA — {len(weekend_posts)} días ───\n"
                f"Sábados y domingos: contenido cálido y cercano de {brand_name}. "
                f"Tono relajado, sin vender — conectar con la comunidad.\n\n"
                + "\n".join(lines)
            )

        campaign_ctx = ""
        if campaign:
            campaign_ctx = f"\nCAMPAÑA DEL MES: {campaign.get('theme', campaign.get('product_name', ''))}"

        total_weekend = sum(int(w["ig_free"]) + int(w["fb_free"]) for w in weekend_posts)

        task = f"""
Hoy es {today.strftime('%A %d de %B de %Y')}. Marca: {self.brand['name']} — {self.brand['tagline']}
{campaign_ctx}

MISIÓN: Generar ÚNICAMENTE el contenido EXTRA indicado abajo.
⚠️ NO toques ni modifiques ningún post ya existente.
⚠️ NO generes los posts de lunes a viernes en horario de mañana (ya están aprobados).

FOTOS REALES DE LA MARCA (úsalas para Stories y fin de semana):
{img_list}
{vid_list}

{stories_block}
{reels_block}
{weekend_block}

REGLAS CRÍTICAS:
• Guarda CADA post con save_content_to_calendar ANTES de pasar al siguiente
• SIEMPRE pasa brand="{self.brand_id}" en cada llamada a save_content_to_calendar
• Usa imágenes DIFERENTES en cada post — no repitas la misma foto
• IG y FB del mismo día: misma foto, texto nativo diferente para cada plataforma
• Stories content = "" o máx 5 palabras — son visuales, no de texto
• Status siempre pending (para aprobación manual antes de publicar)

Al terminar confirma:
✦ Stories guardadas: X de {len(stories)} objetivo
✦ Reels guardados: X de {len(reels)} objetivo
✦ Posts fin de semana guardados: X de {total_weekend} objetivo
"""
        return self.run(task)

    def create_post_now(self, platform: str, topic: str, image_url: str = None) -> str:
        """Generate and immediately publish a post on the specified platform."""
        image_instruction = f"\nURL de imagen: {image_url}" if image_url else ""
        task = (
            f"Crea y publica AHORA un post en {platform} sobre: '{topic}'.\n"
            f"Antes de crear, usa detect_trends para ver si hay tendencias actuales relacionadas con el tema.\n"
            f"Genera el contenido con un hook de alto impacto, luego usa la herramienta de publicación.{image_instruction}\n"
            "Confirma el resultado."
        )
        return self.run(task)
