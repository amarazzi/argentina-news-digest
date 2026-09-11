"""Orquestador del digest diario: recolecta, cura, redacta y publica."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import alert, record
from .collect import CollectError, collect
from .config import TIMEZONE, Settings, Window, load_sources
from .curate import candidates, rank, select
from .embed import vectors_for
from .logs import configure as configure_logs
from .memory import Memory, drop_repeats
from .models import Article, Digest, Event
from .telegram import TelegramError, send_message
from .write import compose

log = logging.getLogger("newsbot")


@dataclass
class Run:
    """Todo lo que produjo una corrida, para poder registrarla y volver a correrla."""

    digest: Digest
    articles: list[Article]
    ranked: list[Event]
    vectors: dict[str, list[float]]


def curate_run(
    articles: list[Article],
    window: Window,
    settings: Settings,
    memory: Memory,
    vectors: dict[str, list[float]] | None = None,
) -> Run:
    ranked = rank(articles, vectors)
    fresh = drop_repeats(ranked, memory, window.reference_date)
    events = select(fresh, settings.max_events)
    log.info("%d eventos seleccionados", len(events))
    return Run(Digest(period=window.date_label, events=events), articles, ranked, vectors or {})


def build_digest(window: Window, settings: Settings, memory: Memory) -> Run:
    articles = collect(window, load_sources(), settings)
    log.info("%d artículos recolectados", len(articles))
    vectors = vectors_for(candidates(articles), api_key=settings.embeddings_key)
    return curate_run(articles, window, settings, memory, vectors)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumen diario de noticias argentinas")
    parser.add_argument(
        "--hours",
        type=int,
        help=(
            "Ventana móvil hacia atrás desde ahora, en horas. Por defecto el resumen es "
            "del día calendario anterior, que no depende de la hora en que se corra."
        ),
    )
    parser.add_argument(
        "--date",
        help="Día calendario a resumir (YYYY-MM-DD), en vez del día anterior.",
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
    parser.add_argument(
        "--replay",
        help=(
            "Vuelve a curar los artículos guardados de una corrida "
            "(runs/AAAA-MM-DD.json.gz), sin red y sin historial."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings.from_env()
    configure_logs(verbose=args.verbose, secrets=[settings.telegram_token or ""])
    if args.replay:
        return replay(Path(args.replay), settings)

    window = window_for(args)
    memory = Memory(path=Path(), entries=[]) if args.no_memory else Memory.load()
    try:
        run = build_digest(window, settings, memory)
    except CollectError as exc:
        print(f"No pude recolectar noticias: {exc}", file=sys.stderr)
        if not args.dry_run:
            alert.notify(f"<i>Hoy no pude recolectar noticias: {exc}</i>", settings)
        return 1
    digest = run.digest
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
    alert.weak_day(len(digest.events), digest.period, settings)
    if args.save_memory and not args.no_memory:
        remember(digest, memory, window)
    if args.save_memory:
        record.save(
            record.payload(
                label=window.label,
                day=window.reference_date.isoformat(),
                articles=run.articles,
                ranked=run.ranked,
                chosen=digest.events,
                vectors=run.vectors,
            )
        )
    return 0


def replay(path: Path, settings: Settings) -> int:
    """Recalcula la curaduría de un día ya vivido con el código de hoy.

    Va sin historial a propósito: lo que se compara es el criterio del curador, y el
    estado de la memoria de aquel día no quedó registrado.
    """
    data = record.load(path)
    window = Window.day(date.fromisoformat(data["dia"]))
    # Con los vectores guardados el replay agrupa igual que aquel día y sin pedir nada.
    run = curate_run(
        record.articles_of(data),
        window,
        settings,
        Memory(path=Path(), entries=[]),
        record.vectors_of(data),
    )
    print(f"{window.date_label}: {len(run.articles)} artículos, {len(run.digest.events)} eventos")
    for position, event in enumerate(run.digest.events, 1):
        print(f"{position}. {event.title}  [{', '.join(sorted(event.outlets))}]")
    return 0


def window_for(args: argparse.Namespace) -> Window:
    """El resumen es de un día cerrado: corrido a las 6 o a las 19 tiene que contar lo
    mismo, y una ventana móvil de 24 horas devuelve otro recorte en cada corrida."""
    if args.date:
        return Window.day(date.fromisoformat(args.date))
    if args.hours:
        return Window.last_hours(args.hours)
    return Window.day(datetime.now(TIMEZONE).date() - timedelta(days=1))


def remember(digest: Digest, memory: Memory, window: Window) -> None:
    memory.remember(digest.events, window.reference_date)
    memory.save(window.reference_date)


if __name__ == "__main__":
    raise SystemExit(main())
