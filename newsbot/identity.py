"""Identidad de un hecho, compartida por el registro, la memoria y el juez."""

from __future__ import annotations

import hashlib

from .models import Event
from .text import normalize


def event_id(event: Event) -> str:
    """Identidad estable del hecho: sus titulares, sin importar el orden."""
    titles = sorted(normalize(a.title) for a in event.articles)
    return hashlib.sha1("|".join(titles).encode()).hexdigest()[:12]
