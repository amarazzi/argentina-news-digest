"""Agente 2 — Curador: agrupa artículos en eventos y los rankea.

v0 usa heurísticas (sin LLM): clustering por solapamiento de palabras del titular y
un score por cantidad de medios que cubren el hecho, diversidad y alcance internacional.
"""

from __future__ import annotations

import math
import re

from .models import Article, Event
from .text import keywords, normalize, overlap, similarity, stems

SIMILARITY_THRESHOLD = 0.42
# Segunda pasada: dos grupos que comparten la mayor parte de sus raíces son el mismo hecho
# contado con otras palabras ("denunciará a Navitas" y "denuncia a cinco petroleras").
MERGE_THRESHOLD = 0.6
# Con menos raíces en común el parecido es casualidad ("Milei habló", "Milei viajó").
MIN_TOPIC_STEMS = 4

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

# Notas de servicio y clickbait de consumo: "el error al tomar café", "qué pasa si...".
SERVICE = re.compile(
    r"\b(que pasa si|el error (al|de)|el truco|los trucos|por que (no )?deberias|"
    r"esto es lo que (pasa|significa)|que significa|adios a|el habito|el secreto|"
    r"cual es el mejor|senales de que|lo que dice la ciencia|paso a paso|"
    r"como hacer|la receta|segun la inteligencia artificial)\b"
)


def is_routine(title: str) -> bool:
    words = keywords(title)
    return bool(ROUTINE.search(normalize(title))) and not (words & SURGE)


def is_service(title: str) -> bool:
    return bool(SERVICE.search(normalize(title)))


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
    return merge(events)


def topic(event: Event) -> set[str]:
    """Raíces que aparecen en la mitad de los titulares del evento: de qué trata."""
    counts: dict[str, int] = {}
    for article in event.articles:
        for stem in stems(article.title):
            counts[stem] = counts.get(stem, 0) + 1
    needed = max(len(event.articles) // 2, 1)
    return {stem for stem, seen in counts.items() if seen >= needed}


def merge(events: list[Event]) -> list[Event]:
    """Funde los grupos que hablan del mismo tema para que no se pise en el resumen."""
    merged: list[Event] = []
    topics: list[set[str]] = []
    for event in events:
        words = topic(event)
        if len(words) < MIN_TOPIC_STEMS:
            merged.append(event)
            topics.append(words)
            continue
        for index, existing in enumerate(topics):
            if merged[index].scope == event.scope and overlap(words, existing) >= MERGE_THRESHOLD:
                merged[index].articles.extend(event.articles)
                break
        else:
            merged.append(event)
            topics.append(words)
    return merged


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
    if keywords(event.title) & NOISE or is_routine(event.title) or is_service(event.title):
        return relevance * NOISE_FACTOR
    return relevance


def rank(articles: list[Article]) -> list[Event]:
    """Todos los hechos del día, del más al menos importante."""
    events = cluster(articles)
    for event in events:
        event.articles.sort(key=lambda a: a.published)
        event.score = score(event)
    events.sort(key=lambda e: (e.score, e.lead.published), reverse=True)
    return events


def select(events: list[Event], max_events: int) -> list[Event]:
    top_ar = [e for e in events if e.scope == "ar"][: max(max_events - 2, 1)]
    top_world = [e for e in events if e.scope == "world"][:2]
    return top_ar + top_world


def curate(articles: list[Article], max_events: int) -> list[Event]:
    return select(rank(articles), max_events)
