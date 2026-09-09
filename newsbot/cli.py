"""Orquestador del digest diario: recolecta, cura, redacta y publica."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

from .collect import collect
from .config import TIMEZONE, Settings, load_sources
from .curate import curate
from .models import Digest
from .telegram import TelegramError, send_message
from .write import compose

log = logging.getLogger("newsbot")


def yesterday() -> date:
    return (datetime.now(TIMEZONE) - timedelta(days=1)).date()


def build_digest(day: date, settings: Settings) -> Digest:
    articles = collect(day, load_sources(), settings)
    log.info("%d artículos recolectados", len(articles))
    events = curate(articles, settings.max_events)
    log.info("%d eventos seleccionados", len(events))
    return Digest(date=day.isoformat(), events=events)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumen diario de noticias argentinas")
    parser.add_argument("--date", help="Día a resumir (YYYY-MM-DD). Por defecto, ayer.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime el mensaje por consola en vez de enviarlo a Telegram.",
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
    day = date.fromisoformat(args.date) if args.date else yesterday()
    message = compose(build_digest(day, settings), settings)

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
        return 1
    log.info("enviado (message_id=%s)", ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
