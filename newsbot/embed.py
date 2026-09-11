"""Vectores de las notas: agrupar por significado y no por palabras compartidas.

Dos titulares del mismo hecho escritos por dos redacciones comparten menos palabras de
las que uno esperaría ("Diputados le dio media sanción al Presupuesto 2027" y "El
oficialismo consiguió el respaldo para el Presupuesto"), así que el solapamiento de
palabras parte las noticias grandes en varios grupos chicos y les baja el puntaje.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

import httpx

from .models import Article

log = logging.getLogger(__name__)

# Modelo de embeddings de texto de Gemini: el multimodal (`gemini-embedding-2`) devuelve
# un solo vector agregado para varias entradas y acá hace falta uno por nota.
MODEL = "gemini-embedding-001"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
TASK = "SEMANTIC_SIMILARITY"
# El vector completo son 3072 números por nota: con mil notas por día el registro de la
# corrida se vuelve impublicable y la similitud no mejora.
DIMENSIONS = 768
# El lote es una sola llamada HTTP pero para la cuota cuenta una nota por vector: el tier
# gratis corta en cien por minuto, así que los lotes van por debajo del tope y espaciados.
BATCH = 50
RATE_PER_MINUTE = 90
SUMMARY_CHARS = 200
RETRIES = 4
BACKOFF = 20.0
MAX_WAIT = 90.0


class EmbedError(RuntimeError):
    pass


def text_of(article: Article) -> str:
    """Titular y el principio del copete: el resto del copete agrega más ruido que tema."""
    summary = " ".join((article.summary or "").split())
    return f"{article.title}. {summary[:SUMMARY_CHARS]}".strip()


def key_of(text: str) -> str:
    """Los vectores se guardan por texto: dos notas idénticas no se piden dos veces."""
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def retry_delay(exc: Exception) -> float:
    """Cuando corta la cuota, la API dice cuánto falta para el minuto siguiente."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return BACKOFF
    try:
        detail = exc.response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return BACKOFF
    match = re.search(r"retry in ([\d.]+)s", detail)
    return min(float(match.group(1)) + 1.0, MAX_WAIT) if match else BACKOFF


def _post(texts: list[str], *, api_key: str, model: str, timeout: float) -> list[list[float]]:
    payload = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
                "taskType": TASK,
                "outputDimensionality": DIMENSIONS,
            }
            for text in texts
        ]
    }
    url = URL.format(model=model)
    for attempt in range(RETRIES):
        try:
            response = httpx.post(
                url, json=payload, headers={"x-goog-api-key": api_key}, timeout=timeout
            )
            response.raise_for_status()
            values = [item["values"] for item in response.json()["embeddings"]]
            if len(values) != len(texts):
                raise EmbedError(f"pedí {len(texts)} vectores y volvieron {len(values)}")
            return values
        except (httpx.HTTPError, KeyError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
            if status not in (429, 503) or attempt >= RETRIES - 1:
                raise EmbedError(str(exc)) from exc
            wait = retry_delay(exc) if status == 429 else BACKOFF * (attempt + 1)
            log.info("embeddings saturados, reintento %d en %.0fs", attempt + 1, wait)
            time.sleep(wait)
    raise EmbedError("sin respuesta del modelo de embeddings")


def embed(
    texts: list[str],
    *,
    api_key: str,
    model: str = MODEL,
    timeout: float = 120.0,
    known: dict[str, list[float]] | None = None,
) -> dict[str, list[float]]:
    """Vector por texto, indexado por `key_of`. Lo que ya está en `known` no se vuelve a pedir.

    Si la API se corta a mitad devuelve lo que consiguió: quien llama decide si con eso
    alcanza. Guardar los lotes que sí salieron evita volver a pagarlos en la corrida
    siguiente.
    """
    vectors = dict(known or {})
    pending = sorted({t for t in texts if key_of(t) not in vectors})
    for start in range(0, len(pending), BATCH):
        chunk = pending[start : start + BATCH]
        if start:
            time.sleep(60.0 * BATCH / RATE_PER_MINUTE)
        try:
            got = _post(chunk, api_key=api_key, model=model, timeout=timeout)
        except EmbedError as exc:
            log.warning("me quedé sin vectores en la nota %d de %d (%s)", start, len(pending), exc)
            break
        for text, values in zip(chunk, got, strict=True):
            vectors[key_of(text)] = values
    if pending:
        log.info("%d vectores nuevos, %d en total", len(pending), len(vectors))
    return vectors


def vectors_for(
    articles: list[Article],
    *,
    api_key: str | None,
    known: dict[str, list[float]] | None = None,
    timeout: float = 120.0,
) -> dict[str, list[float]]:
    """Los vectores del día, o los que haya: sin clave o con la API caída el curador
    agrupa por palabras, que es peor pero sigue saliendo el digest."""
    if not api_key:
        return dict(known or {})
    return embed([text_of(a) for a in articles], api_key=api_key, known=known, timeout=timeout)
