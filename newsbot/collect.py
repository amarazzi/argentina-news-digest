"""Agente 1 — Recolector: baja artículos de RSS y de búsquedas de Google News."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from zoneinfo import ZoneInfo

import feedparser
import httpx

from .config import TIMEZONE, Search, Settings, Sources, Window
from .models import Article

log = logging.getLogger(__name__)

USER_AGENT = "argentina-news-digest/0.1 (+https://github.com/amarazzi/argentina-news-digest)"
UTC = ZoneInfo("UTC")
RETRIES = 3
BACKOFF = 2.0
# Google News devuelve como mucho 100 ítems por búsqueda: pedir la ventana en tramos
# cortos y unir los resultados es la única forma de ver el día entero.
SLICE_HOURS = 6

# Los feeds mezclan páginas de sección y de etiqueta con las notas del día.
SECTION_PAGE = re.compile(r"últimas noticias de|\| [a-z0-9.]+\.com", re.IGNORECASE)
# Una fecha sin offset la publicó el medio en hora local, no en UTC.
HAS_OFFSET = re.compile(r"(GMT|UTC|[+-]\d{2}:?\d{2}|Z)\s*$", re.IGNORECASE)
# Las búsquedas internacionales matchean por el cuerpo de la nota: la edición brasileña de
# "Argentina" trae política interna de Brasil. Afuera sólo entra lo que es sobre Argentina.
ABOUT_ARGENTINA = re.compile(
    r"argentin|milei|malvinas|falkland|buenos aires|casa rosada|kirchner|patagon",
    re.IGNORECASE,
)


class CollectError(RuntimeError):
    """No se pudo recolectar: mejor no mandar nada que mandar medio digest."""


def strip_html(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def _raw_date(entry: dict) -> str:
    return (entry.get("published") or entry.get("updated") or "").strip()


def entry_published(entry: dict) -> datetime | None:
    """Fecha del artículo en hora argentina.

    feedparser sólo devuelve la fecha ya parseada cuando reconoce el formato, y a las que
    no traen huso las trata como UTC: eso corría tres horas todo lo que publica un medio
    argentino con `pubDate` sin offset.
    """
    raw = _raw_date(entry)
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        origin = UTC if (not raw or HAS_OFFSET.search(raw)) else TIMEZONE
        return datetime(*parsed[:6], tzinfo=origin).astimezone(TIMEZONE)
    if not raw:
        return None
    for parse in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            moment = parse(raw)
        except (TypeError, ValueError):
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=TIMEZONE)
        return moment.astimezone(TIMEZONE)
    return None


def fetch_feed(client: httpx.Client, url: str) -> feedparser.FeedParserDict:
    for attempt in range(RETRIES):
        try:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            return feedparser.parse(response.content)
        except httpx.HTTPError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(BACKOFF * (attempt + 1))
    raise httpx.HTTPError("sin respuesta")


def entry_source(entry: dict, default: str) -> str:
    """Google News expone el medio original en <source>; los RSS propios no."""
    return (entry.get("source") or {}).get("title") or default


def entry_source_url(entry: dict, feed_url: str) -> str:
    """Sitio del medio original: Google News lo trae en <source url="...">, y en un RSS
    propio es el dominio del feed. Es lo único que permite saber que "TN" y "TN - Todo
    Noticias" son el mismo medio."""
    return (entry.get("source") or {}).get("href") or feed_url


def clean_title(title: str, source: str) -> str:
    """Google News agrega ' - Medio' al final del titular."""
    suffix = f" - {source}"
    return title[: -len(suffix)].strip() if source and title.endswith(suffix) else title


def articles_from(
    parsed: feedparser.FeedParserDict,
    source: str,
    scope: str,
    window: Window,
    feed_url: str = "",
) -> tuple[list[Article], int]:
    """Artículos del feed dentro de la ventana, y cuántos se descartaron por fecha ilegible."""
    articles: list[Article] = []
    undated = 0
    for entry in parsed.entries:
        published = entry_published(entry)
        if published is None:
            undated += 1
            continue
        if published not in window:
            continue
        link = entry.get("link")
        outlet = entry_source(entry, source)
        title = clean_title(strip_html(entry.get("title", "")), outlet)
        if not link or not title or SECTION_PAGE.search(title):
            continue
        summary = strip_html(entry.get("summary", ""))[:600]
        if scope == "world" and not ABOUT_ARGENTINA.search(f"{title} {summary}"):
            continue
        articles.append(
            Article(
                title=title,
                url=link,
                source=outlet,
                scope=scope,
                published=published,
                summary=summary,
                source_url=entry_source_url(entry, feed_url),
            )
        )
    return articles, undated


def search_label(search: Search) -> str:
    return f"Google News · {search.query}"


def search_slices(window: Window, *, now: datetime | None = None) -> list[int]:
    """Tramos de `when:Nh` que cubren la ventana sin chocar contra el tope de 100 ítems.

    `when:Nh` es "las últimas N horas desde ahora", así que los tramos se solapan en vez
    de partir el día. Los que terminan antes del inicio de la ventana —a las 06:13,
    `when:6h` contra el día de ayer— traen sólo notas que después se descartan por fecha.
    """
    now = now or datetime.now(TIMEZONE)
    total = window.lookback_hours(now=now)
    since_end = (now - window.end).total_seconds() / 3600
    slices = [hours for hours in range(SLICE_HOURS, total, SLICE_HOURS) if hours > since_end]
    slices.append(total)
    return slices


def dedupe(articles: list[Article]) -> list[Article]:
    """Saca repetidos por URL y la misma nota llegada por dos fuentes distintas."""
    seen: set[str] = set()
    unique: list[Article] = []
    for article in sorted(articles, key=lambda a: a.published, reverse=True):
        keys = {article.url.split("?")[0], f"{article.source}|{article.title.casefold()}"}
        if keys & seen:
            continue
        seen |= keys
        unique.append(article)
    return unique


def targets_for(window: Window, sources: Sources) -> list[tuple[str, str, str]]:
    targets = [(f.name, f.url, f.scope) for f in sources.feeds]
    for search in sources.searches:
        for hours in search_slices(window):
            targets.append((search_label(search), search.url(hours), search.scope))
    return targets


def collect(window: Window, sources: Sources, settings: Settings) -> list[Article]:
    """Devuelve los artículos publicados dentro de `window` (hora de Argentina)."""
    articles: list[Article] = []
    targets = targets_for(window, sources)
    failed = 0

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=settings.request_timeout, headers=headers) as client:
        for name, url, scope in targets:
            try:
                parsed = fetch_feed(client, url)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("no pude leer %s: %s", name, exc)
                failed += 1
                continue
            if parsed.bozo and not parsed.entries:
                log.warning("%s no devolvió un RSS válido (%s)", name, parsed.bozo_exception)
                failed += 1
                continue
            found, undated = articles_from(parsed, name, scope, window, feed_url=url)
            if undated:
                log.warning("%s: %d artículos sin fecha legible, descartados", name, undated)
            log.info("%s: %d artículos de %s", name, len(found), window.label)
            articles.extend(found)

    if failed:
        log.warning("%d de %d fuentes fallaron", failed, len(targets))
    if failed == len(targets):
        raise CollectError("todas las fuentes fallaron")
    unique = dedupe(articles)
    if not unique:
        raise CollectError(f"ninguna fuente devolvió artículos de {window.label}")
    return unique
