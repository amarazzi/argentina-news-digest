from datetime import date, datetime

from newsbot.config import TIMEZONE
from newsbot.curate import cluster
from newsbot.memory import Memory, drop_repeats
from newsbot.models import Article

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)


def events(*titles: str):
    articles = [
        Article(title=t, url=f"https://d{i}.com/x", source=f"D{i}", scope="ar", published=WHEN)
        for i, t in enumerate(titles)
    ]
    return cluster(articles)


def test_no_repite_el_hecho_al_dia_siguiente(tmp_path):
    path = tmp_path / "history.json"
    ayer = events("El Gobierno denunciará penalmente a la petrolera Navitas por Malvinas")

    memory = Memory.load(path)
    memory.remember(ayer, date(2026, 9, 7))
    memory.save(date(2026, 9, 7))

    hoy = events(
        "El Gobierno denunció penalmente a las petroleras que operan en Malvinas",
        "El INDEC publicó la inflación de agosto",
    )
    quedan = drop_repeats(hoy, Memory.load(path))

    assert [e.title for e in quedan] == ["El INDEC publicó la inflación de agosto"]


def test_el_historial_vencido_se_descarta(tmp_path):
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(events("El Gobierno denunció a las petroleras de Malvinas"), date(2026, 8, 1))
    memory.save(date(2026, 9, 7))

    assert Memory.load(path).entries == []


def test_sin_historial_no_filtra_nada(tmp_path):
    hoy = events("El INDEC publicó la inflación de agosto")
    assert drop_repeats(hoy, Memory.load(tmp_path / "vacio.json")) == hoy
