"""Agente 3 — Redactor: arma el mensaje del día.

Con `OPENAI_API_KEY` redacta con LLM; sin clave cae a un formato determinístico
basado sólo en titulares y links (nunca inventa información).
"""

from __future__ import annotations

import logging
import re
from html import escape

from .config import Settings
from .llm import LLMError, complete
from .models import Article, Digest, Event
from .text import keywords

log = logging.getLogger(__name__)

TRAILING = re.compile(r"\s*(Leer más|Seguir leyendo|Ver más)\s*$", re.IGNORECASE)
MAX_SOURCES = 4

PROMPT = """Sos el editor de un resumen diario de noticias argentinas que se envía por Telegram.

Escribí el resumen correspondiente a {period} en español rioplatense. Formato exacto, un
bloque por evento y en el orden en que te los paso:

<b>1. Título corto</b>
Párrafo de 2 a 4 oraciones contando qué pasó y por qué importa. Dentro del texto,
embebé el link en una frase natural, así: el Gobierno <a href="URL">empieza hoy a licitar</a>
los plazos fijos.

Reglas duras:
- El título de cada bloque es tuyo, de 2 a 5 palabras, no el titular copiado del medio.
- Cada bloque tiene exactamente un link, embebido en una frase del párrafo (nunca al final
  suelto, nunca la URL a la vista). Usá la URL que te paso para ese evento, tal cual.
- Nada de bullets, guiones ni numeración aparte de la del título.
- Usá SOLO la información de los titulares y copetes que te paso. No agregues datos, cifras,
  nombres ni contexto que no estén ahí. Si algo no está, no lo digas.
- HTML de Telegram únicamente: <b>, <i>, <a href="...">. Nada de Markdown ni de <br>.
- Los eventos marcados [world] van al final, después de una línea <b>Argentina en el mundo</b>,
  y siguen la misma numeración.
- Máximo 3500 caracteres en total.

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


def _clean(article: Article) -> str:
    """Google News cierra el copete con el nombre del medio, que ya va aparte."""
    summary = TRAILING.sub("", article.summary or "").strip()
    return re.sub(rf"\s*{re.escape(article.source)}\s*$", "", summary).strip()


def _summary(event: Event) -> str:
    """La bajada es el copete que más agrega sobre el titular; el de Google News lo repite."""
    title = keywords(event.lead.title)
    candidates = [s for s in (_clean(a) for a in event.articles) if s]
    if not candidates:
        # Sin copetes, el titular de otro medio es lo único que suma contexto.
        others = [a.title for a in event.articles if a.title != event.lead.title]
        return others[0] if others else ""
    return max(candidates, key=lambda s: len(keywords(s) - title))


def _sources(event: Event) -> str:
    """Las cadenas internacionales replican el mismo cable en decenas de diarios."""
    names = event.sources
    if len(names) <= MAX_SOURCES:
        return ", ".join(names)
    return f"{', '.join(names[:MAX_SOURCES])} y {len(names) - MAX_SOURCES} medios más"


def _block(event: Event, number: int) -> list[str]:
    """Sin LLM el párrafo es el copete del medio: no se genera texto nuevo."""
    link = escape(event.lead.url, quote=True)
    lines = [f'<b>{number}. <a href="{link}">{escape(event.lead.title)}</a></b>']
    summary = _summary(event)
    if summary:
        lines.append(escape(summary))
    lines.extend([f"<i>{escape(_sources(event))}</i>", ""])
    return lines


def fallback_message(digest: Digest) -> str:
    """Resumen sin LLM: titulares, copetes y links, sin texto generado."""
    parts = [f"<b>Noticias de Argentina — {digest.period}</b>", ""]
    number = 0
    for event in (e for e in digest.events if e.scope == "ar"):
        number += 1
        parts.extend(_block(event, number))

    world = [e for e in digest.events if e.scope == "world"]
    if world:
        parts.extend(["<b>Argentina en el mundo</b>", ""])
        for event in world:
            number += 1
            parts.extend(_block(event, number))
    return "\n".join(parts).rstrip()


def compose(digest: Digest, settings: Settings) -> str:
    if not digest.events:
        return f"<b>{digest.period}</b>\nNo encontré noticias en las fuentes configuradas."
    if not settings.openai_api_key:
        log.info("sin OPENAI_API_KEY: uso el resumen determinístico")
        return fallback_message(digest)

    prompt = PROMPT.format(period=digest.period, events=render_events_for_prompt(digest.events))
    try:
        body = complete(prompt, api_key=settings.openai_api_key, model=settings.openai_model)
    except LLMError as exc:
        log.warning("falló el LLM (%s): uso el resumen determinístico", exc)
        return fallback_message(digest)
    return f"<b>Noticias de Argentina — {digest.period}</b>\n\n{body}"
