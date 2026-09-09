"""Agente 1 — Recolector: baja artículos de RSS y de búsquedas de Google News."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from html import unescape
from zoneinfo import ZoneInfo

import feedparser
import httpx

from .config import TIMEZONE, Search, Settings, Sources
from .models import Article

log = logging.getLogger(__name__)

USER_AGENT = "argentina-news-digest/0.1 (+https://github.com/amarazzi/argentina-news-digest)"
UTC = ZoneInfo("UTC")


def strip_html(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def entry_published(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC).astimezone(TIMEZONE)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=TIMEZONE)
    return start, start + timedelta(days=1)


def fetch_feed(client: httpx.Client, url: str) -> feedparser.FeedParserDict:
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    return feedparser.parse(response.content)


def entry_source(entry: dict, default: str) -> str:
    """Google News expone el medio original en <source>; los RSS propios no."""
    return (entry.get("source") or {}).get("title") or default


def clean_title(title: str, source: str) -> str:
    """Google News agrega ' - Medio' al final del titular."""
    suffix = f" - {source}"
    return title[: -len(suffix)].strip() if source and title.endswith(suffix) else title


def articles_from(
    parsed: feedparser.FeedParserDict, source: str, scope: str, day: date
) -> Iterator[Article]:
    start, end = day_bounds(day)
    for entry in parsed.entries:
        published = entry_published(entry)
        if published is None or not (start <= published < end):
            continue
        link = entry.get("link")
        outlet = entry_source(entry, source)
        title = clean_title(strip_html(entry.get("title", "")), outlet)
        if not link or not title:
            continue
        yield Article(
            title=title,
            url=link,
            source=outlet,
            scope=scope,
            published=published,
            summary=strip_html(entry.get("summary", ""))[:600],
        )


def search_label(search: Search) -> str:
    return f"Google News · {search.query}"


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


def collect(day: date, sources: Sources, settings: Settings) -> list[Article]:
    """Devuelve los artículos publicados durante `day` (hora de Argentina)."""
    articles: list[Article] = []
    targets = [(f.name, f.url, f.scope) for f in sources.feeds]
    targets += [(search_label(s), s.url, s.scope) for s in sources.searches]

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=settings.request_timeout, headers=headers) as client:
        for name, url, scope in targets:
            try:
                parsed = fetch_feed(client, url)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("no pude leer %s: %s", name, exc)
                continue
            found = list(articles_from(parsed, name, scope, day))
            log.info("%s: %d artículos del %s", name, len(found), day)
            articles.extend(found)
    return dedupe(articles)
