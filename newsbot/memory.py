"""Memoria de lo ya enviado: un hecho no se repite de un día para el otro."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .curate import MIN_TOPIC_STEMS, same_topic, topic
from .models import Event
from .text import similarity

log = logging.getLogger(__name__)

DEFAULT_PATH = Path("state/history.json")
# Después de una semana un tema puede volver legítimamente (una causa que avanza, un paro nuevo).
RETENTION_DAYS = 7
# Jaccard, no contención: con `overlap` alcanzaba con que el hecho nuevo fuera un
# subconjunto de algo viejo, y "Milei anunció cambios en el Gabinete" quedaba tapado por
# cualquier anuncio de la semana.
REPEAT_THRESHOLD = 0.6
# Una historia que sigue cambia casi todo el vocabulario del titular ("internaron a X" y
# "murió X") y el Jaccard se cae: entre días vale el mismo criterio de tema que dentro del
# día, si no la continuación vuelve a entrar como noticia nueva.
# Los temas chicos son además los más identificables ("gelblu", "chich"): pedirles cuatro
# raíces, como al Jaccard, los dejaba sin comparar.
MIN_STORY_STEMS = 2


@dataclass
class Memory:
    path: Path
    entries: list[tuple[str, set[str]]]

    @classmethod
    def load(cls, path: Path | None = None) -> Memory:
        path = path or Path(os.getenv("NEWSBOT_STATE", DEFAULT_PATH))
        if not path.exists():
            return cls(path=path, entries=[])
        try:
            raw = json.loads(path.read_text())
            entries = [(e["date"], set(e["topic"])) for e in raw.get("events", [])]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("no pude leer el historial %s (%s): arranco vacío", path, exc)
            return cls(path=path, entries=[])
        return cls(path=path, entries=entries)

    def _match(self, words: set[str]) -> int:
        """Índice del hecho ya enviado que es el mismo, o -1."""
        if len(words) < MIN_STORY_STEMS:
            return -1
        for index, (_, seen) in enumerate(self.entries):
            jaccard = len(words) >= MIN_TOPIC_STEMS and similarity(words, seen) >= REPEAT_THRESHOLD
            if jaccard or same_topic(words, seen):
                return index
        return -1

    def is_repeat(self, event: Event) -> bool:
        return self._match(topic(event)) >= 0

    def refresh(self, event: Event, today: date) -> None:
        """Un hecho que sigue dando notas mantiene vivo el recuerdo con el vocabulario de
        hoy: si no, la misma historia vuelve a entrar cuando los titulares cambian de palabras.

        Guarda el tema de hoy y no la unión con el viejo: acumular una semana de raíces
        arma un tema gigante que después se parece a cualquier noticia nueva.
        """
        words = topic(event)
        index = self._match(words)
        if index >= 0:
            self.entries[index] = (today.isoformat(), words)

    def remember(self, events: list[Event], today: date) -> None:
        self.entries.extend((today.isoformat(), topic(e)) for e in events if topic(e))

    def save(self, today: date) -> None:
        horizon = (today - timedelta(days=RETENTION_DAYS)).isoformat()
        fresh = [(day, words) for day, words in self.entries if day > horizon]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"events": [{"date": day, "topic": sorted(words)} for day, words in fresh]},
            indent=2,
        )
        # Escritura atómica: una corrida interrumpida no deja el historial a medio escribir.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload)
        tmp.replace(self.path)


def drop_repeats(events: list[Event], memory: Memory, today: date) -> list[Event]:
    fresh = []
    for event in events:
        if memory.is_repeat(event):
            log.info("ya enviado en días previos, lo salteo: %s", event.title)
            memory.refresh(event, today)
            continue
        fresh.append(event)
    return fresh
