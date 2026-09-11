"""Compara lo que el curador de hoy elegiría contra lo que se envió cada día.

    python tools/compare.py [runs/]

Sirve para medir un cambio del curador antes de mergearlo: sin esto, la única evidencia
de que una regla mejora el digest es mirar la corrida del día y acordarse de las de antes.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from newsbot import record
from newsbot.cli import Run, curate_run
from newsbot.config import Settings, Window
from newsbot.memory import Memory


def compare(path: Path, settings: Settings) -> tuple[int, int]:
    data = record.load(path)
    day = data["dia"]
    window = Window.day(date.fromisoformat(day))
    run = curate_run(record.articles_of(data), window, settings, Memory(path=Path(), entries=[]))

    before = {e["id"]: e for e in data["ranking"]}
    sent = list(data["elegidos"])
    now = [record.event_id(e) for e in run.digest.events]

    print(f"\n{day}: {len(sent)} enviados, {len(now)} con el curador de hoy")
    for event_id in now:
        if event_id not in sent:
            title = _title(run, event_id)
            print(f"  + {title}")
    for event_id in sent:
        if event_id not in now:
            titles = before.get(event_id, {}).get("titulares") or ["(sin registro)"]
            print(f"  - {titles[0]}")
    return len([e for e in now if e not in sent]), len([e for e in sent if e not in now])


def _title(run: Run, event_id: str) -> str:
    for event in run.digest.events:
        if record.event_id(event) == event_id:
            return event.title
    return event_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default=None, type=Path)
    args = parser.parse_args(argv)

    directory = args.directory or record.runs_dir()
    runs = sorted(directory.glob("*.json.gz"))
    if not runs:
        print(f"no hay corridas registradas en {directory}")
        return 1

    settings = Settings.from_env()
    entran = salen = 0
    for path in runs:
        added, removed = compare(path, settings)
        entran += added
        salen += removed
    print(f"\nTotal: {entran} entran, {salen} salen, sobre {len(runs)} días")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
