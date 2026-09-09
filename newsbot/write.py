"""Agente 3 — Redactor: arma el mensaje del día.

Con `OPENAI_API_KEY` redacta con LLM; sin clave cae a un formato determinístico
basado sólo en titulares y links (nunca inventa información).
"""

from __future__ import annotations

import logging
from html import escape

from .config import Settings
from .llm import LLMError, complete
from .models import Digest, Event

log = logging.getLogger(__name__)

PROMPT = """Sos el editor de un resumen diario de noticias argentinas que se envía por Telegram.

Escribí el resumen del {date} en español rioplatense, con este formato exacto:
- Un párrafo inicial de 2 líneas con el clima general del día.
- Un bullet por evento, en este orden, empezando con un titular propio en negrita HTML (<b>).
  Debajo, 2 o 3 líneas explicando qué pasó y por qué importa.
- Al final, una línea "Argentina en el mundo:" sólo si hay eventos de alcance internacional.

Reglas duras:
- Usá SOLO la información de los titulares y copetes que te paso. No agregues datos, cifras,
  nombres ni contexto que no estén ahí. Si algo no está, no lo digas.
- HTML de Telegram únicamente: <b>, <i>, <a href="...">. Nada de Markdown ni de <br>.
- Máximo 1200 caracteres en total.

Eventos:
{events}
"""


def render_events_for_prompt(events: list[Event]) -> str:
    blocks = []
    for index, event in enumerate(events, start=1):
        sources = ", ".join(event.sources)
        lines = [f"{index}. [{event.scope}] {event.lead.title} (fuentes: {sources})"]
        for article in event.articles[:3]:
            if article.summary:
                lines.append(f"   - {article.summary[:280]}")
        lines.append(f"   - link: {event.lead.url}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _bullet(event: Event) -> list[str]:
    link = escape(event.lead.url, quote=True)
    return [
        f'• <a href="{link}">{escape(event.lead.title)}</a>',
        f"  <i>{escape(', '.join(event.sources))}</i>",
    ]


def fallback_message(digest: Digest) -> str:
    """Resumen sin LLM: titulares y links, sin texto generado."""
    parts = [f"<b>Noticias de Argentina — {digest.date}</b>", ""]
    for event in (e for e in digest.events if e.scope == "ar"):
        parts.extend(_bullet(event))

    world = [e for e in digest.events if e.scope == "world"]
    if world:
        parts.extend(["", "<b>Argentina en el mundo</b>"])
        for event in world:
            parts.extend(_bullet(event))
    return "\n".join(parts)


def compose(digest: Digest, settings: Settings) -> str:
    if not digest.events:
        return f"<b>{digest.date}</b>\nNo encontré noticias en las fuentes configuradas."
    if not settings.openai_api_key:
        log.info("sin OPENAI_API_KEY: uso el resumen determinístico")
        return fallback_message(digest)

    prompt = PROMPT.format(date=digest.date, events=render_events_for_prompt(digest.events))
    try:
        body = complete(prompt, api_key=settings.openai_api_key, model=settings.openai_model)
    except LLMError as exc:
        log.warning("falló el LLM (%s): uso el resumen determinístico", exc)
        return fallback_message(digest)
    return f"<b>Noticias de Argentina — {digest.date}</b>\n\n{body}"
