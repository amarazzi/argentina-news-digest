"""Avisos operativos: que un día flojo o una corrida rota se vean, y no que no llegue nada."""

from __future__ import annotations

import logging

from .config import Settings
from .telegram import TelegramError, send_message

log = logging.getLogger(__name__)

# Debajo de esto el día no da para un brief: o pasó poco, o algo del pipeline anda mal.
WEAK = 3


def notify(text: str, settings: Settings) -> None:
    """Manda el aviso al mismo chat. Si falla, queda en el log: un aviso nunca hace
    fracasar la corrida."""
    if not settings.telegram_token or not settings.telegram_chat_id:
        log.warning("aviso sin enviar (falta la configuración de Telegram): %s", text)
        return
    try:
        send_message(text, token=settings.telegram_token, chat_id=settings.telegram_chat_id)
    except TelegramError as exc:
        log.warning("no pude enviar el aviso: %s", exc)


def weak_day(events: int, period: str, settings: Settings, floor: int = WEAK) -> None:
    """El digest corto es una decisión editorial, pero conviene saber cuándo confiar menos."""
    if events >= floor:
        return
    noticia = "noticia" if events == 1 else "noticias"
    notify(
        f"<i>Aviso: el brief del {period} salió con {events} {noticia}. "
        f"O el día fue flojo o algo de la recolección falló.</i>",
        settings,
    )
