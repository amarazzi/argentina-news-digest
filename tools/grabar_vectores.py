"""Refresca los vectores de los casos de calibración para que los tests no usen la red.

    python tools/grabar_vectores.py

Las notas ya están en `tests/data/casos.json.gz`: esto sólo pide los vectores que falten,
así que hace falta correrlo si cambian los casos o el modelo de embeddings.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsbot.embed import embed, key_of, text_of  # noqa: E402
from newsbot.record import VECTOR_DIGITS  # noqa: E402
from tests.casos import ARCHIVO, cargar  # noqa: E402


def main() -> int:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("falta GEMINI_API_KEY", file=sys.stderr)
        return 1
    casos, known = cargar()
    notas = [article for articles in casos.values() for article in articles]
    faltan = [a for a in notas if key_of(text_of(a)) not in known]
    if not faltan:
        print(f"{len(known)} vectores al día en {ARCHIVO}")
        return 0
    nuevos = embed([text_of(a) for a in faltan], api_key=key)
    known.update({k: [round(v, VECTOR_DIGITS) for v in values] for k, values in nuevos.items()})
    with gzip.open(ARCHIVO, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    data["vectores"] = known
    with gzip.open(ARCHIVO, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    print(f"{len(nuevos)} vectores nuevos, {len(known)} en {ARCHIVO}")
    return 0 if len(nuevos) == len(faltan) else 1


if __name__ == "__main__":
    raise SystemExit(main())
