"""
VoxifyHub Creative Director — CLI entry point.

Uso:
  python main.py --weekly               # Flujo completo: genera, aprueba y publica
  python main.py --approve              # Revisar y aprobar posts pendientes
  python main.py --task "tema"          # Tarea libre al agente
  python main.py --post instagram "Tema" https://img.url
  python main.py --schedule             # Scheduler automático
  python main.py --list-posts           # Ver todos los posts
"""

import argparse
import logging
import sys
import time
import json

# Fix emoji display on Windows terminals
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from config.settings import validate_config, LINKEDIN_ENABLED
from database import Database
from agent import VoxifyCreativeDirector
from tools.scheduler import PostScheduler

DIVIDER = "─" * 60
STATUS_LABELS = {
    "pending_approval": "PENDIENTE DE APROBACION",
    "pending":          "APROBADO",
    "published":        "PUBLICADO",
    "ready_manual":     "LISTO PARA SUBIR MANUALMENTE",
    "rejected":         "RECHAZADO",
    "failed":           "ERROR",
    "skipped":          "OMITIDO",
}


def ask(prompt: str) -> str:
    return input(prompt).strip().lower()


def show_post(post, index: int):
    post_id, platform, content_type, content, image_url, scheduled_date = post
    platform_label = platform.upper()
    print(f"\n{DIVIDER}")
    print(f"  POST #{index} — {platform_label} | {content_type} | {scheduled_date[:10]}")
    print(DIVIDER)
    print(content)
    if image_url:
        print(f"\n  Imagen: {image_url}")
    print()


def approval_flow(db: Database, agent: VoxifyCreativeDirector):
    """Show pending posts and handle approval, publishing, and LinkedIn export."""
    posts = db.get_posts_pending_approval()

    if not posts:
        print("\nNo hay posts pendientes de aprobacion.\n")
        return

    print(f"\n{DIVIDER}")
    print(f"  {len(posts)} post(s) esperan tu aprobacion")
    print(DIVIDER)

    approved_to_publish = []  # (post_id, platform, content, image_url)
    linkedin_posts = []       # (post_id, content)

    for i, post in enumerate(posts, 1):
        post_id, platform, content_type, content, image_url, scheduled_date = post
        show_post(post, i)

        if platform == "linkedin":
            print("  LinkedIn no esta configurado — este post quedara listo para subir manualmente.")
            resp = ask("  Guardar como 'listo para subir manualmente'? (s/n): ")
            if resp == "s":
                db.mark_post_ready_manual(post_id)
                linkedin_posts.append((post_id, content))
                print("  Guardado como LISTO PARA SUBIR MANUALMENTE.")
            else:
                db.reject_post(post_id)
                print("  Rechazado.")
            continue

        resp = ask(f"  Aprobar este post de {platform.upper()}? (s/n/editar): ")

        if resp == "n":
            db.reject_post(post_id)
            print("  Post rechazado.")
            continue

        if resp == "editar":
            print("  Pega el nuevo texto (termina con una linea que diga FIN):")
            lines = []
            while True:
                line = input()
                if line.strip().upper() == "FIN":
                    break
                lines.append(line)
            content = "\n".join(lines)
            print("  Texto actualizado.")

        # Instagram needs an image URL
        if platform == "instagram":
            if not image_url:
                img = input("  URL de imagen para Instagram (obligatorio): ").strip()
                if not img:
                    print("  Sin imagen — post omitido.")
                    db.reject_post(post_id)
                    continue
                image_url = img
            else:
                cambiar = ask(f"  Imagen actual: {image_url}\n  Cambiar imagen? (s/n): ")
                if cambiar == "s":
                    image_url = input("  Nueva URL de imagen: ").strip()

        db.approve_post(post_id, image_url)
        approved_to_publish.append((post_id, platform, content, image_url))
        print(f"  Aprobado para publicar en {platform.upper()}.")

    if not approved_to_publish and not linkedin_posts:
        print("\nNingun post fue aprobado.\n")
        return

    # Publish approved posts
    if approved_to_publish:
        print(f"\n{DIVIDER}")
        print(f"  Publicando {len(approved_to_publish)} post(s)...")
        print(DIVIDER)

        for post_id, platform, content, image_url in approved_to_publish:
            print(f"\n  Publicando en {platform.upper()}...")
            result = agent.publish_post(platform, post_id, content, image_url)
            if result.get("success"):
                db.mark_post_published(post_id, result.get("post_id", ""))
                print(f"  PUBLICADO en {platform.upper()}. ID: {result.get('post_id')}")
            else:
                db.mark_post_failed(post_id, result.get("error", "Error desconocido"))
                print(f"  ERROR en {platform.upper()}: {result.get('error')}")

    # Show LinkedIn posts for manual upload
    if linkedin_posts:
        print(f"\n{DIVIDER}")
        print("  POSTS DE LINKEDIN — Copia y pega manualmente")
        print(DIVIDER)
        for _, content in linkedin_posts:
            print(f"\n{content}\n")
        print(DIVIDER)

    print("\nFlujo de aprobacion completado.\n")


def main():
    parser = argparse.ArgumentParser(description="VoxifyHub Creative Director Agent")
    parser.add_argument("--weekly",     action="store_true", help="Genera plan semanal + aprobacion + publicacion")
    parser.add_argument("--approve",    action="store_true", help="Revisar y aprobar posts pendientes")
    parser.add_argument("--task",       type=str,            help="Tarea libre para el agente")
    parser.add_argument("--post",       nargs="+", metavar=("PLATFORM", "TOPIC"),
                        help="Crea y publica un post: --post instagram 'tema' [url_imagen]")
    parser.add_argument("--schedule",   action="store_true", help="Inicia el scheduler automatico")
    parser.add_argument("--list-posts", action="store_true", help="Lista todos los posts")
    args = parser.parse_args()

    try:
        validate_config()
    except EnvironmentError as e:
        print(f"\nERROR DE CONFIGURACION:\n{e}\n")
        sys.exit(1)

    db = Database()
    agent = VoxifyCreativeDirector(db)

    # ── --weekly ──────────────────────────────────────────────────────────
    if args.weekly:
        print(f"\n{DIVIDER}")
        print("  VOXIFYHUB — PLAN SEMANAL DE CONTENIDO")
        print(DIVIDER)
        print("\nEl agente esta creando el contenido de la semana...\n")

        result = agent.weekly_content_run()
        print("\n" + result + "\n")

        continuar = ask("Contenido generado. Quieres revisar y aprobar ahora? (s/n): ")
        if continuar == "s":
            approval_flow(db, agent)
        else:
            print("\nPuedes aprobar despues con: python main.py --approve\n")

        db.close()
        return

    # ── --approve ─────────────────────────────────────────────────────────
    if args.approve:
        approval_flow(db, agent)
        db.close()
        return

    # ── --list-posts ──────────────────────────────────────────────────────
    if args.list_posts:
        posts = db.list_posts()
        if not posts:
            print("\nNo hay posts en el calendario aun.\n")
        else:
            print(f"\n{'ID':<4} {'PLATAFORMA':<12} {'ESTADO':<28} {'FECHA':<12} {'PREVIEW'}")
            print(DIVIDER)
            for p in posts:
                estado = STATUS_LABELS.get(p[6], p[6])
                print(f"{p[0]:<4} {p[1].upper():<12} {estado:<28} {p[5][:10]:<12} {p[3][:50]}...")
        db.close()
        return

    # ── --post ────────────────────────────────────────────────────────────
    if args.post:
        platform  = args.post[0]
        topic     = args.post[1] if len(args.post) > 1 else "Automatizacion con IA"
        image_url = args.post[2] if len(args.post) > 2 else None
        print(f"\nPublicando en {platform}: '{topic}'...\n")
        result = agent.create_post_now(platform, topic, image_url)
        print("\n" + result)
        db.close()
        return

    # ── --task ────────────────────────────────────────────────────────────
    if args.task:
        print(f"\nEjecutando: {args.task}\n")
        result = agent.run(args.task)
        print("\n" + result)
        db.close()
        return

    # ── --schedule ────────────────────────────────────────────────────────
    if args.schedule:
        scheduler = PostScheduler(db)
        scheduler.start()
        print("\nScheduler iniciado. Presiona Ctrl+C para detener.\n")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nDeteniendo scheduler...")
            scheduler.stop()
        db.close()
        return

    # ── Modo interactivo ──────────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print("  VOXIFYHUB Creative Director — Modo Interactivo")
    print(f"{DIVIDER}")
    print("Comandos: 'aprobar' | 'semanal' | 'posts' | 'salir'\n")

    while True:
        try:
            task = input("Tarea > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not task:
            continue
        if task.lower() in ("salir", "exit", "quit"):
            break
        if task.lower() == "aprobar":
            approval_flow(db, agent)
            continue
        if task.lower() == "semanal":
            print("\nGenerando plan semanal...\n")
            result = agent.weekly_content_run()
            print("\n" + result + "\n")
            continuar = ask("Quieres aprobar ahora? (s/n): ")
            if continuar == "s":
                approval_flow(db, agent)
            continue
        if task.lower() == "posts":
            posts = db.list_posts()
            for p in posts:
                estado = STATUS_LABELS.get(p[6], p[6])
                print(f"[{p[0]}] {p[1].upper()} | {estado} | {p[3][:60]}...")
            continue

        print("\nProcesando...\n")
        result = agent.run(task)
        print("\n" + result + "\n")

    db.close()
    print("Hasta luego.")


if __name__ == "__main__":
    main()
