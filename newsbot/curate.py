"""Agente 2 — Curador: agrupa artículos en eventos y los rankea.

v0 usa heurísticas (sin LLM): clustering por solapamiento de palabras del titular y
un score por cantidad de medios que cubren el hecho, diversidad y alcance internacional.
"""

from __future__ import annotations

from .models import Article, Event
from .text import keywords, similarity

SIMILARITY_THRESHOLD = 0.42

# Temas que en la práctica sólo agregan ruido al resumen del día.
NOISE = {
    "libertadores", "copa", "futbol", "soccer", "gol", "goles", "river", "boca", "seleccion",
    "messi", "horoscopo", "loteria", "quiniela", "recetas", "celebrity", "chimentos",
}
NOISE_FACTOR = 0.25


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


def score(event: Event) -> float:
    """Más medios cubriendo el hecho = más importante. El alcance mundial suma."""
    coverage = len(event.sources)
    diversity = len({a.domain for a in event.articles})
    world_bonus = 2.5 if event.scope == "world" else 0.0
    relevance = coverage * 2.0 + diversity + world_bonus
    return relevance * NOISE_FACTOR if keywords(event.title) & NOISE else relevance


def curate(articles: list[Article], max_events: int) -> list[Event]:
    events = cluster(articles)
    for event in events:
        event.articles.sort(key=lambda a: a.published)
        event.score = score(event)
    events.sort(key=lambda e: (e.score, e.lead.published), reverse=True)

    top_ar = [e for e in events if e.scope == "ar"][: max(max_events - 2, 1)]
    top_world = [e for e in events if e.scope == "world"][:2]
    return top_ar + top_world
