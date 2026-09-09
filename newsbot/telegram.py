"""Agente 4 — Publicador: manda el resumen a Telegram."""

from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MAX_LENGTH = 4096
TAG = re.compile(r"<[^>]+>")


class TelegramError(RuntimeError):
    pass


def visible_length(text: str) -> int:
    """Telegram cuenta el texto ya renderizado: las etiquetas y los href no suman."""
    return len(TAG.sub("", text))


def split_message(text: str, limit: int = MAX_LENGTH) -> list[str]:
    """Corta en varios mensajes respetando saltos de línea (así no parte un <a>)."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        length = visible_length(line) + 1
        if current and size + length > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += length
    chunks.append("\n".join(current))
    return chunks


def send_message(text: str, *, token: str, chat_id: str, timeout: float = 30.0) -> list[int]:
    """Envía el mensaje y devuelve los message_id (para atar el feedback en v2)."""
    message_ids: list[int] = []
    for chunk in split_message(text):
        try:
            response = httpx.post(
                f"{API_BASE}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
            raise TelegramError(detail) from exc
        message_ids.append(response.json()["result"]["message_id"])
    return message_ids
