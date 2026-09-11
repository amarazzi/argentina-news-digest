"""Agente 4 — Publicador: manda el resumen a Telegram."""

from __future__ import annotations

import logging
import re
import time

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MAX_LENGTH = 4096
TAG = re.compile(r"<[^>]+>")
ELEMENT = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
RETRIES = 3
BACKOFF = 3.0


class TelegramError(RuntimeError):
    """El envío falló. `sent` son los mensajes que sí llegaron antes del error."""

    def __init__(self, detail: str, sent: list[int] | None = None) -> None:
        super().__init__(detail)
        self.sent = sent or []


def visible_length(text: str) -> int:
    """Telegram cuenta el texto ya renderizado: las etiquetas y los href no suman."""
    return len(TAG.sub("", text))


def open_tags(text: str) -> list[tuple[str, str]]:
    """Etiquetas abiertas y sin cerrar al final del texto, de la más vieja a la más nueva."""
    stack: list[tuple[str, str]] = []
    for match in ELEMENT.finditer(text):
        closing, name = match.group(1), match.group(2).lower()
        if not closing:
            stack.append((name, match.group(0)))
        elif stack and stack[-1][0] == name:
            stack.pop()
    return stack


def wrap_line(line: str, limit: int) -> list[str]:
    """Parte una línea más larga que el límite, cortando entre palabras y nunca dentro
    de una etiqueta."""
    if visible_length(line) <= limit:
        return [line]
    pieces: list[str] = []
    current = ""
    for token in re.split(r"(\s+|<[^>]+>)", line):
        if not token:
            continue
        if current and visible_length(current) + visible_length(token) > limit:
            pieces.append(current)
            current = ""
        current += token
    if current:
        pieces.append(current)
    return pieces


def split_message(text: str, limit: int = MAX_LENGTH) -> list[str]:
    """Corta en varios mensajes sin partir etiquetas: las que quedan abiertas se cierran
    al final del mensaje y se reabren al principio del siguiente."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for raw in text.split("\n"):
        for piece in wrap_line(raw, limit):
            length = visible_length(piece) + 1
            if current and size + length > limit:
                chunk = "\n".join(current)
                opened = open_tags(chunk)
                chunks.append(chunk + "".join(f"</{name}>" for name, _ in reversed(opened)))
                piece = "".join(tag for _, tag in opened) + piece
                current, size = [], 0
            current.append(piece)
            size += length
    chunks.append("\n".join(current))
    return chunks


def _post(chunk: str, *, token: str, chat_id: str, timeout: float, plain: bool = False) -> int:
    payload = {
        "chat_id": chat_id,
        "text": TAG.sub("", chunk) if plain else chunk,
        "disable_web_page_preview": True,
    }
    if not plain:
        payload["parse_mode"] = "HTML"
    response = httpx.post(f"{API_BASE}/bot{token}/sendMessage", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()["result"]["message_id"]


def send_chunk(chunk: str, *, token: str, chat_id: str, timeout: float) -> int:
    for attempt in range(RETRIES):
        try:
            return _post(chunk, token=token, chat_id=chat_id, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 400:
                # Telegram rechaza el HTML: mejor el texto plano que perder el digest.
                log.warning("Telegram rechazó el formato (%s): reenvío sin HTML", exc.response.text)
                return _post(chunk, token=token, chat_id=chat_id, timeout=timeout, plain=True)
            if status not in (429, 500, 502, 503) or attempt == RETRIES - 1:
                raise TelegramError(exc.response.text) from exc
        except httpx.HTTPError as exc:
            if attempt == RETRIES - 1:
                raise TelegramError(str(exc)) from exc
        log.info("Telegram no respondió, reintento %d de %d", attempt + 1, RETRIES - 1)
        time.sleep(BACKOFF * (attempt + 1))
    raise TelegramError("sin respuesta de Telegram")


def send_message(text: str, *, token: str, chat_id: str, timeout: float = 30.0) -> list[int]:
    """Envía el mensaje y devuelve los message_id (para atar el feedback en v2)."""
    message_ids: list[int] = []
    for chunk in split_message(text):
        try:
            message_ids.append(send_chunk(chunk, token=token, chat_id=chat_id, timeout=timeout))
        except TelegramError as exc:
            raise TelegramError(str(exc), sent=message_ids) from exc
    return message_ids
