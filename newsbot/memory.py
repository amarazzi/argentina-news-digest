"""Memoria de lo ya enviado: un hecho no se repite de un día para el otro."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .curate import topic
from .models import Event
from .text import overlap

log = logging.getLogger(__name__)

DEFAULT_PATH = Path("state/history.json")
# Después de una semana un tema puede volver legítimamente (una causa que avanza, un paro nuevo).
RETENTION_DAYS = 7
# Un poco más laxo que la fusión del día: la segunda jornada usa otras palabras.
REPEAT_THRESHOLD = 0.5


@dataclass
class Memory:
    path: Path
    entries: list[tuple[str, set[str]]]

    @classmethod
    def load(cls, path: Path | None = None) -> Memory:
        path = path or Path(os.getenv("NEWSBOT_STATE", DEFAULT_PATH))
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls(path=path, entries=[])
        return cls(
            path=path,
            entries=[(e["date"], set(e["topic"])) for e in raw.get("events", [])],
        )

    def is_repeat(self, event: Event) -> bool:
        words = topic(event)
        return any(overlap(words, seen) >= REPEAT_THRESHOLD for _, seen in self.entries)

    def remember(self, events: list[Event], today: date) -> None:
        self.entries.extend((today.isoformat(), topic(e)) for e in events)

    def save(self, today: date) -> None:
        horizon = (today - timedelta(days=RETENTION_DAYS)).isoformat()
        fresh = [(day, words) for day, words in self.entries if day >= horizon]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"events": [{"date": day, "topic": sorted(words)} for day, words in fresh]},
                indent=2,
            )
        )


def drop_repeats(events: list[Event], memory: Memory) -> list[Event]:
    fresh = []
    for event in events:
        if memory.is_repeat(event):
            log.info("ya enviado en días previos, lo salteo: %s", event.title)
            continue
        fresh.append(event)
    return fresh
