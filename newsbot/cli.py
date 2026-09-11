"""Orquestador del digest diario: recolecta, cura, redacta y publica."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .collect import CollectError, collect
from .config import DEFAULT_HOURS, Settings, Window, load_sources
from .curate import rank, select
from .memory import Memory, drop_repeats
from .models import Digest
from .telegram import TelegramError, send_message
from .write import compose

log = logging.getLogger("newsbot")


def build_digest(window: Window, settings: Settings, memory: Memory) -> Digest:
    articles = collect(window, load_sources(), settings)
    log.info("%d artículos recolectados", len(articles))
    fresh = drop_repeats(rank(articles), memory, window.reference_date)
    events = select(fresh, settings.max_events)
    log.info("%d eventos seleccionados", len(events))
    return Digest(period=window.date_label, events=events)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumen diario de noticias argentinas")
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        help=f"Ventana hacia atrás desde ahora, en horas (por defecto {DEFAULT_HOURS}).",
    )
    parser.add_argument(
        "--date",
        help="Día calendario a resumir (YYYY-MM-DD), en vez de la ventana de --hours.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime el mensaje por consola en vez de enviarlo a Telegram.",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Ignora el historial: permite repetir hechos ya enviados en días previos.",
    )
    parser.add_argument(
        "--save-memory",
        action="store_true",
        help=(
            "Guarda los hechos enviados en el historial. Sin esta opción la corrida es "
            "una prueba: lee el historial pero no lo modifica, así probar no cambia "
            "el digest de la corrida siguiente."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    window = (
        Window.day(date.fromisoformat(args.date))
        if args.date
        else Window.last_hours(args.hours)
    )
    memory = Memory(path=Path(), entries=[]) if args.no_memory else Memory.load()
    try:
        digest = build_digest(window, settings, memory)
    except CollectError as exc:
        print(f"No pude recolectar noticias: {exc}", file=sys.stderr)
        return 1
    message = compose(digest, settings)

    if args.dry_run:
        print(message)
        return 0

    if not settings.telegram_token or not settings.telegram_chat_id:
        print(
            "Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID. Usá --dry-run para probar sin enviar.",
            file=sys.stderr,
        )
        return 2

    try:
        ids = send_message(
            message, token=settings.telegram_token, chat_id=settings.telegram_chat_id
        )
    except TelegramError as exc:
        print(f"Telegram rechazó el mensaje: {exc}", file=sys.stderr)
        # Si algún mensaje llegó, el historial se guarda igual: repetir mañana todo lo que
        # el usuario ya leyó es peor que perder la parte que no se envió.
        if exc.sent and args.save_memory and not args.no_memory:
            remember(digest, memory, window)
        return 1
    log.info("enviado (message_id=%s)", ids)
    if args.save_memory and not args.no_memory:
        remember(digest, memory, window)
    return 0


def remember(digest: Digest, memory: Memory, window: Window) -> None:
    memory.remember(digest.events, window.reference_date)
    memory.save(window.reference_date)


if __name__ == "__main__":
    raise SystemExit(main())
