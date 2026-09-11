"""Registro de cada corrida: sin datos guardados no hay nada que calibrar.

Cada envío deja `runs/AAAA-MM-DD.json.gz` con los artículos crudos y el ranking completo,
así un cambio del curador se puede evaluar contra los días ya vividos (`--replay`) en vez
de contra titulares inventados a mano.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .curate import coverage, is_noise, is_preview, is_routine, is_service, penalized, relevant
from .llm import USAGE
from .models import Article, Event
from .text import normalize

log = logging.getLogger(__name__)

DEFAULT_DIR = Path("runs")
# Más abajo del puesto 30 no hay nada que revisar: lo que se discute es el borde de los
# primeros diez.
RANKED_LIMIT = 30
VERSION = 1


def event_id(event: Event) -> str:
    """Identidad estable del hecho: sus titulares, sin importar el orden."""
    titles = sorted(normalize(a.title) for a in event.articles)
    return hashlib.sha1("|".join(titles).encode()).hexdigest()[:12]


def commit_sha() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def title_flags(title: str) -> dict:
    plain = normalize(title)
    return {
        "ruido": is_noise(plain),
        "rutina": is_routine(plain),
        "servicio": is_service(plain),
        "anticipo": is_preview(plain),
    }


def article_payload(article: Article) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "source_url": article.source_url,
        "scope": article.scope,
        "published": article.published.isoformat(),
        "summary": article.summary,
        # Los descartados no llegan al ranking —el curador los saca del evento antes de
        # puntuarlo— y son justo los que hay que poder revisar después.
        "flags": title_flags(article.title),
    }


def article_from(raw: dict) -> Article:
    return Article(
        title=raw["title"],
        url=raw["url"],
        source=raw["source"],
        scope=raw["scope"],
        published=datetime.fromisoformat(raw["published"]),
        summary=raw.get("summary", ""),
        source_url=raw.get("source_url", ""),
    )


def flags(event: Event) -> dict:
    """Por qué el curador lo trató como lo trató."""
    marked = [title_flags(a.title) for a in event.articles]
    counts = {
        name: sum(1 for m in marked if m[name])
        for name in ("ruido", "rutina", "servicio", "anticipo")
    }
    return {"penalizado": penalized(event), "relevante": relevant(event), **counts}


def event_payload(event: Event) -> dict:
    independent, copies, variants = coverage(event)
    return {
        "id": event_id(event),
        "titulares": [a.title for a in event.articles],
        "medios": sorted(event.outlets),
        "cobertura": {
            "independientes": independent,
            "copias": copies,
            "variantes": variants,
        },
        "puntaje": round(event.score, 3),
        "flags": flags(event),
    }


def payload(
    *,
    label: str,
    day: str,
    articles: list[Article],
    ranked: list[Event],
    chosen: list[Event],
) -> dict:
    return {
        "version": VERSION,
        "dia": day,
        "ventana": label,
        "commit": commit_sha(),
        "llm": dict(USAGE),
        "articulos": [article_payload(a) for a in articles],
        "ranking": [event_payload(e) for e in ranked[:RANKED_LIMIT]],
        "elegidos": [event_id(e) for e in chosen],
    }


def runs_dir() -> Path:
    return Path(os.getenv("NEWSBOT_RUNS", DEFAULT_DIR))


def path_for(day: str, directory: Path | None = None) -> Path:
    return (directory or runs_dir()) / f"{day}.json.gz"


def save(data: dict, directory: Path | None = None) -> Path:
    destination = path_for(data["dia"], directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    log.info("corrida registrada en %s", destination)
    return destination


def load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def articles_of(data: dict) -> list[Article]:
    return [article_from(raw) for raw in data["articulos"]]
