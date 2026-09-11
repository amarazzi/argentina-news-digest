from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from .text import normalize, stems

AGGREGATORS = {"news.google.com", "google.com"}
# El mismo medio se presenta con distintos nombres según quién lo cite. Sólo hace falta
# cuando no hay dominio de dónde sacarlo.
OUTLET_ALIASES = {
    "tn - todo noticias": "tn.com.ar",
    "tn": "tn.com.ar",
    "todo noticias": "tn.com.ar",
    "clarin": "clarin.com",
    "diario clarin": "clarin.com",
    "la nacion": "lanacion.com.ar",
    "lanacion": "lanacion.com.ar",
    "infobae": "infobae.com",
    "pagina 12": "pagina12.com.ar",
    "pagina12": "pagina12.com.ar",
    "ambito": "ambito.com",
    "ambito financiero": "ambito.com",
    "perfil": "perfil.com",
    "el cronista": "cronista.com",
    "cronista": "cronista.com",
    "eldiarioar": "eldiarioar.com",
    "el diarioar": "eldiarioar.com",
    "la voz del interior": "lavoz.com.ar",
    "la voz": "lavoz.com.ar",
    "el destape": "eldestapeweb.com",
    "el destape web": "eldestapeweb.com",
    "chequeado": "chequeado.com",
}


def host(url: str) -> str:
    """Dominio canónico de una URL, o vacío si no hay uno propio del medio."""
    netloc = urlparse(url).netloc.removeprefix("www.").lower()
    return "" if netloc in AGGREGATORS else netloc


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    source: str
    scope: str
    published: datetime
    summary: str = ""
    # Sitio del medio original. Google News lo trae en <source url="...">; en los RSS
    # propios es el dominio del feed.
    source_url: str = ""

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.removeprefix("www.")

    @property
    def outlet(self) -> str:
        """Medio que publicó la nota, identificado por dominio.

        Por nombre no alcanza: el feed propio dice "TN" y Google News "TN - Todo
        Noticias", y así un mismo medio contaba como dos y llegaba solo al piso de
        cobertura. Los links de Google News son redirecciones, por eso el dominio sale
        de `source_url` cuando está.
        """
        name = normalize(self.source).strip()
        return host(self.source_url) or host(self.url) or OUTLET_ALIASES.get(name, name)


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
