"""Memoria de lo ya enviado: un hecho no se repite de un día para el otro."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .curate import MIN_TOPIC_STEMS, same_topic, topic
from .identity import event_id
from .models import Event
from .text import normalize, similarity

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
# Verbos de hecho consumado. Si la historia ya enviada no los tenía y hoy sí, pasó algo
# nuevo: si ayer entró la internación, hoy la muerte es noticia. Seguir contando lo mismo
# (el parte médico, las repercusiones) no trae ninguno y queda como repetición.
FACTS = re.compile(
    r"\b(murio|muerte|fallecio|falleci\w*|detuvieron|detenid\w*|renuncio|renuncia|"
    r"aprobo|aprobaron|sanciono|sancionaron|veto|vetaron|promulgo|condenaron|condeno|"
    r"absolvieron|absolvio|proceso|procesaron|imputaron|allanaron|destituyo|destituyeron|"
    r"echo|despidio|gano|perdio|firmaron|firmo|lanzo|asumio)\b"
)


@dataclass
class Entry:
    day: str
    topic: set[str]
    # Las entradas viejas del historial no lo tienen: ahí cualquier verbo de hecho de hoy
    # cuenta como novedad.
    facts: set[str] = field(default_factory=set)
    # Identidad del hecho y su resumen de una línea: es lo que ve el juez al día
    # siguiente para saber si lo de hoy es un desarrollo o la misma historia otra vez.
    id: str = ""
    summary: str = ""


@dataclass
class Memory:
    path: Path
    entries: list[Entry]

    @classmethod
    def load(cls, path: Path | None = None) -> Memory:
        path = path or Path(os.getenv("NEWSBOT_STATE", DEFAULT_PATH))
        if not path.exists():
            return cls(path=path, entries=[])
        try:
            raw = json.loads(path.read_text())
            entries = [
                Entry(
                    e["date"],
                    set(e["topic"]),
                    set(e.get("facts", [])),
                    e.get("id", ""),
                    e.get("summary", ""),
                )
                for e in raw.get("events", [])
            ]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("no pude leer el historial %s (%s): arranco vacío", path, exc)
            return cls(path=path, entries=[])
        return cls(path=path, entries=entries)

    def _matches(self, words: set[str]) -> list[int]:
        """Índices de los envíos que cuentan la misma historia."""
        if len(words) < MIN_STORY_STEMS:
            return []
        found = []
        for index, entry in enumerate(self.entries):
            seen = entry.topic
            jaccard = len(words) >= MIN_TOPIC_STEMS and similarity(words, seen) >= REPEAT_THRESHOLD
            if jaccard or same_topic(words, seen):
                found.append(index)
        return found

    def _match(self, words: set[str]) -> int:
        found = self._matches(words)
        return found[0] if found else -1

    def is_repeat(self, event: Event) -> bool:
        """La misma historia vuelve a entrar si hoy trae un hecho que no se contó nunca.

        Se compara contra todos los envíos de esa historia: la internación del lunes y la
        muerte del martes son dos entradas, y el miércoles el funeral no vuelve a entrar.
        """
        found = self._matches(topic(event))
        if not found:
            return False
        told = set().union(*(self.entries[i].facts for i in found))
        return not (facts(event) - told)

    def refresh(self, event: Event, today: date) -> None:
        """Un hecho que sigue dando notas mantiene vivo el recuerdo con el vocabulario de
        hoy: si no, la misma historia vuelve a entrar cuando los titulares cambian de palabras.

        Guarda el tema de hoy y no la unión con el viejo: acumular una semana de raíces
        arma un tema gigante que después se parece a cualquier noticia nueva.
        """
        words = topic(event)
        index = self._match(words)
        if index >= 0:
            old = self.entries[index]
            known = old.facts | facts(event)
            self.entries[index] = Entry(today.isoformat(), words, known, old.id, old.summary)

    def remember(
        self, events: list[Event], today: date, summaries: dict[str, str] | None = None
    ) -> None:
        summaries = summaries or {}
        for event in events:
            words = topic(event)
            if not words:
                continue
            key = event_id(event)
            self.entries.append(
                Entry(today.isoformat(), words, facts(event), key, summaries.get(key, event.title))
            )

    def recent(self, today: date, days: int = RETENTION_DAYS) -> list[Entry]:
        """Lo enviado en la última semana, que es lo que se le pasa al juez."""
        horizon = (today - timedelta(days=days)).isoformat()
        return [e for e in self.entries if e.day > horizon and e.id]

    def save(self, today: date) -> None:
        horizon = (today - timedelta(days=RETENTION_DAYS)).isoformat()
        fresh = [e for e in self.entries if e.day > horizon]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "events": [
                    {
                        "date": e.day,
                        "topic": sorted(e.topic),
                        "facts": sorted(e.facts),
                        "id": e.id,
                        "summary": e.summary,
                    }
                    for e in fresh
                ]
            },
            indent=2,
        )
        # Escritura atómica: una corrida interrumpida no deja el historial a medio escribir.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload)
        tmp.replace(self.path)


def facts(event: Event) -> set[str]:
    """Verbos de hecho consumado que aparecen en los titulares del evento."""
    found: set[str] = set()
    for article in event.articles:
        found |= set(FACTS.findall(normalize(article.title)))
    return found


def drop_repeats(events: list[Event], memory: Memory, today: date) -> list[Event]:
    fresh = []
    for event in events:
        if memory.is_repeat(event):
            log.info("ya enviado en días previos, lo salteo: %s", event.title)
            memory.refresh(event, today)
            continue
        fresh.append(event)
    return fresh
