"""Agrupamiento por significado: clustering aglomerativo sobre los vectores del día.

El agrupamiento por palabras del titular no junta "Diputados aprobó el Presupuesto 2027"
con "El oficialismo consiguió el respaldo y lo giró al Senado": comparten una palabra y
quedan como dos hechos, así que el hecho grande del día se parte y puntúa como dos chicos.
"""

from __future__ import annotations

import numpy as np

from .embed import key_of, text_of
from .models import Article, Event

# Umbral de coseno. Los vectores de Gemini viven en un cono angosto —dos noticias sin
# nada que ver ya dan 0,7— así que el corte va alto. Calibrado con los casos de
# `tests/test_group.py` y con los días guardados en `runs/`.
THRESHOLD = 0.84


def matrix(vectors: list[list[float]]) -> np.ndarray:
    """Vectores normalizados: con norma 1 el coseno es el producto punto."""
    data = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(data, axis=1, keepdims=True)
    return data / np.maximum(norms, 1e-12)


def agglomerate(vectors: list[list[float]], threshold: float = THRESHOLD) -> list[list[int]]:
    """Clustering aglomerativo por coseno con enlace promedio.

    Funde en cada paso los dos grupos más parecidos mientras el parecido promedio entre
    sus miembros supere el umbral. La similitud del grupo nuevo sale del promedio pesado
    de los dos que se fundieron (Lance-Williams), que es exactamente el promedio de los
    pares: no hace falta volver a mirar los vectores.
    """
    total = len(vectors)
    if total < 2:
        return [[index] for index in range(total)]

    data = matrix(vectors)
    similarity = data @ data.T
    np.fill_diagonal(similarity, -np.inf)
    sizes = np.ones(total, dtype=np.float32)
    alive = np.ones(total, dtype=bool)
    members: list[list[int]] = [[index] for index in range(total)]

    for _ in range(total - 1):
        flat = int(np.argmax(similarity))
        first, second = divmod(flat, total)
        if similarity[first, second] < threshold:
            break
        weight = sizes[first] + sizes[second]
        blended = (sizes[first] * similarity[first] + sizes[second] * similarity[second]) / weight
        similarity[first] = blended
        similarity[:, first] = blended
        similarity[first, first] = -np.inf
        similarity[second, :] = -np.inf
        similarity[:, second] = -np.inf
        sizes[first] = weight
        alive[second] = False
        members[first].extend(members[second])
        members[second] = []

    return [sorted(members[index]) for index in range(total) if alive[index]]


def cluster(
    articles: list[Article],
    vectors: dict[str, list[float]],
    threshold: float = THRESHOLD,
) -> list[Event]:
    """Un evento por grupo. El orden es estable: no depende de a qué hora publicó cada medio."""
    ordered = sorted(articles, key=lambda a: (a.title, a.url))
    groups = agglomerate([vectors[key_of(text_of(a))] for a in ordered], threshold)
    events = [
        Event(title=ordered[members[0]].title, articles=[ordered[i] for i in members])
        for members in groups
    ]
    return sorted(events, key=lambda e: (e.articles[0].title, e.articles[0].url))
