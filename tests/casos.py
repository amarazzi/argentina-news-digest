"""Casos de calibración del agrupamiento por significado.

Son notas reales de un día guardado (10/09/2026) con sus vectores grabados, para que los
casos den siempre lo mismo y los tests no llamen a ninguna API. Se refrescan con
`tools/grabar_vectores.py`.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from newsbot.models import Article

ARCHIVO = Path(__file__).parent / "data" / "casos.json.gz"
CUANDO = datetime(2026, 9, 10, 12, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))


def _article(nota: dict) -> Article:
    return Article(
        title=nota["titular"],
        url=nota["url"],
        source=nota["medio"],
        scope="ar",
        published=CUANDO,
        summary=nota["copete"],
    )


def cargar() -> tuple[dict[str, list[Article]], dict[str, list[float]]]:
    with gzip.open(ARCHIVO, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    casos = {name: [_article(nota) for nota in notas] for name, notas in data["casos"].items()}
    return casos, data["vectores"]
