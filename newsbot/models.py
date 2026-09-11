from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from .text import normalize, stems


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

    @property
    def outlet(self) -> str:
        """Medio que publicó la nota. El dominio no sirve: 4 de cada 5 artículos llegan
        por Google News y todos comparten el netloc `news.google.com`."""
        return normalize(self.source).strip() or self.domain


@dataclass
class Event:
    """Un hecho noticioso, potencialmente cubierto por varios medios."""

    title: str
    articles: list[Article] = field(default_factory=list)
    score: float = 0.0

    @property
    def scope(self) -> str:
        """Internacional sólo si ningún medio argentino lo cubrió: un hecho local con eco
        afuera sigue siendo local, y así no se duplica en los dos bloques del mensaje."""
        return "ar" if any(a.scope == "ar" for a in self.articles) else "world"

    @property
    def outlets(self) -> set[str]:
        return {a.outlet for a in self.articles}

    @property
    def sources(self) -> list[str]:
        """Medios distintos, sin repetir variantes del mismo nombre (Ámbito / Ambito)."""
        seen: dict[str, str] = {}
        for article in self.articles:
            seen.setdefault(normalize(article.source), article.source)
        return list(seen.values())

    @property
    def lead(self) -> Article:
        """Prefiere un link directo al medio (los de Google News son redirecciones opacas)
        y, entre esos, el titular más representativo del grupo. No depende del orden de
        llegada: dos corridas con los mismos artículos eligen el mismo lead."""
        direct = [a for a in self.articles if a.domain != "news.google.com"] or self.articles
        common: dict[str, int] = {}
        for article in self.articles:
            for stem in stems(article.title):
                common[stem] = common.get(stem, 0) + 1
        def centrality(article: Article) -> tuple[int, str]:
            return sum(common[s] for s in stems(article.title)), article.url
        return max(direct, key=centrality)


@dataclass
class Digest:
    period: str
    events: list[Event]
