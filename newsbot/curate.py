"""Agente 2 — Curador: agrupa artículos en eventos y los rankea.

v0 usa heurísticas (sin LLM): clustering por solapamiento de palabras del titular y
un score por cantidad de medios que cubren el hecho, diversidad y alcance internacional.
"""

from __future__ import annotations

import math
import re

from .models import Article, Event
from .text import keywords, normalize, similarity

SIMILARITY_THRESHOLD = 0.42

# Temas que en la práctica sólo agregan ruido al resumen del día.
NOISE = {
    "libertadores", "copa", "futbol", "soccer", "gol", "goles", "river", "boca", "seleccion",
    "messi", "horoscopo", "loteria", "quiniela", "recetas", "celebrity", "chimentos",
    "escalacao", "corinthians", "flamengo", "palmeiras", "gremio", "sudamericana",
    "scaloneta", "scaloni", "afa", "fifa", "eliminatorias", "captain", "striker",
    "midfielder", "goalkeeper", "transfer", "premier", "laliga", "onefootball",
}
NOISE_FACTOR = 0.25

# Notas de servicio que se repiten todos los días: sólo interesan si el titular indica
# un movimiento fuerte.
ROUTINE = re.compile(
    r"a cuanto (cotiza|esta|cerro)|cotizacion del|precio del dolar|"
    r"dolar (blue|oficial|hoy|cripto|mep)\b|clima en|pronostico"
)
SURGE = {
    "dispara", "disparo", "derrumba", "derrumbe", "desplome", "desploma", "record",
    "salto", "trepa", "hundio", "escalada", "corrida", "techo", "maximo", "minimo",
}


def is_routine(title: str) -> bool:
    words = keywords(title)
    return bool(ROUTINE.search(normalize(title))) and not (words & SURGE)


def cluster(articles: list[Article]) -> list[Event]:
    """Agrupa artículos que hablan del mismo hecho."""
    events: list[Event] = []
    fingerprints: list[set[str]] = []
    for article in articles:
        words = keywords(article.title)
        best_index, best_score = -1, 0.0
        for index, existing in enumerate(fingerprints):
            score = similarity(words, existing)
            if score > best_score:
                best_index, best_score = index, score
        if best_score >= SIMILARITY_THRESHOLD:
            events[best_index].articles.append(article)
            fingerprints[best_index] |= words
        else:
            events.append(Event(title=article.title, articles=[article]))
            fingerprints.append(words)
    return events


def takes(event: Event) -> int:
    """Redacciones que escribieron el hecho con sus propias palabras."""
    return len({normalize(a.title) for a in event.articles})


def echo(event: Event) -> float:
    """Republicar un cable también es una decisión editorial, pero con peso decreciente:
    la nota 12 que reproduce el mismo texto agrega mucho menos que la segunda."""
    copies = len({a.domain for a in event.articles}) - takes(event)
    return math.sqrt(max(copies, 0))


def score(event: Event) -> float:
    """Más medios cubriendo el hecho = más importante. El alcance mundial suma."""
    coverage = takes(event)
    diversity = min(len({a.domain for a in event.articles}), coverage)
    world_bonus = 2.5 if event.scope == "world" else 0.0
    relevance = coverage * 2.0 + diversity + echo(event) + world_bonus
    if keywords(event.title) & NOISE or is_routine(event.title):
        return relevance * NOISE_FACTOR
    return relevance


def curate(articles: list[Article], max_events: int) -> list[Event]:
    events = cluster(articles)
    for event in events:
        event.articles.sort(key=lambda a: a.published)
        event.score = score(event)
    events.sort(key=lambda e: (e.score, e.lead.published), reverse=True)

    top_ar = [e for e in events if e.scope == "ar"][: max(max_events - 2, 1)]
    top_world = [e for e in events if e.scope == "world"][:2]
    return top_ar + top_world
