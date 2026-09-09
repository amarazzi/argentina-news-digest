"""Agente 4 — Publicador: manda el resumen a Telegram."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MAX_LENGTH = 4096


class TelegramError(RuntimeError):
    pass


def split_message(text: str, limit: int = MAX_LENGTH) -> list[str]:
    """Corta en varios mensajes respetando saltos de línea."""
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    chunks.append(remaining)
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
