from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from .text import normalize


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    source: str
    scope: str
    published: datetime
    summary: str = ""

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.removeprefix("www.")


@dataclass
class Event:
    """Un hecho noticioso, potencialmente cubierto por varios medios."""

    title: str
    articles: list[Article] = field(default_factory=list)
    score: float = 0.0

    @property
    def scope(self) -> str:
        return "world" if any(a.scope == "world" for a in self.articles) else "ar"

    @property
    def sources(self) -> list[str]:
        """Medios distintos, sin repetir variantes del mismo nombre (Ámbito / Ambito)."""
        seen: dict[str, str] = {}
        for article in self.articles:
            seen.setdefault(normalize(article.source), article.source)
        return list(seen.values())

    @property
    def lead(self) -> Article:
        return self.articles[0]


@dataclass
class Digest:
    date: str
    events: list[Event]
