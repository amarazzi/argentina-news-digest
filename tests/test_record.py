from datetime import date, datetime

from newsbot import cli, record
from newsbot.config import TIMEZONE, Settings, Window
from newsbot.curate import rank
from newsbot.memory import Memory
from newsbot.models import Article

DIA = date(2026, 9, 10)
WHEN = datetime(2026, 9, 10, 9, 0, tzinfo=TIMEZONE)

TITULARES = [
    ("El INDEC publicó la inflación de agosto: 1,7%", "Clarín", "clarin.com"),
    ("La inflación de agosto fue de 1,7%, informó el INDEC", "La Nación", "lanacion.com.ar"),
    ("Inflación: el INDEC midió 1,7% en agosto", "Infobae", "infobae.com"),
    ("Horóscopo de hoy, jueves", "Clarín", "clarin.com"),
]


def articles() -> list[Article]:
    return [
        Article(
            title=title,
            url=f"https://{domain}/{i}",
            source=source,
            scope="ar",
            published=WHEN,
            source_url=f"https://{domain}",
        )
        for i, (title, source, domain) in enumerate(TITULARES)
    ]


def corrida() -> dict:
    todos = articles()
    ranked = rank(todos)
    return record.payload(
        label="del 10/09",
        day=DIA.isoformat(),
        articles=todos,
        ranked=ranked,
        chosen=ranked[:1],
    )


def test_la_corrida_guarda_los_articulos_crudos_y_el_ranking(tmp_path):
    """Sin los artículos no se puede volver a correr el día con otro curador."""
    path = record.save(corrida(), tmp_path)
    data = record.load(path)

    assert path.name == "2026-09-10.json.gz"
    assert len(data["articulos"]) == len(TITULARES)
    assert data["elegidos"] == [data["ranking"][0]["id"]]
    assert data["ranking"][0]["cobertura"]["independientes"] == 3
    assert data["ranking"][0]["flags"]["relevante"]


def test_lo_descartado_queda_registrado_con_su_flag(tmp_path):
    """El horóscopo no llega al ranking porque el curador lo saca antes de puntuar: si no
    queda en el registro con su marca, después no hay forma de revisar qué dejó afuera."""
    data = record.load(record.save(corrida(), tmp_path))
    afuera = [a for a in data["articulos"] if any(a["flags"].values())]

    assert [a["title"] for a in afuera] == ["Horóscopo de hoy, jueves"]
    assert all(e["flags"]["ruido"] == 0 for e in data["ranking"])


def test_el_replay_recalcula_el_dia_sin_red(tmp_path, capsys, monkeypatch):
    path = record.save(corrida(), tmp_path)
    monkeypatch.setattr(
        cli, "collect", lambda *a, **k: pytest_fail("el replay no puede salir a la red")
    )

    assert cli.main(["--replay", str(path), "--dry-run"]) == 0
    assert "inflación" in capsys.readouterr().out.lower()


def test_el_replay_devuelve_lo_mismo_dos_veces(tmp_path):
    data = record.load(record.save(corrida(), tmp_path))
    window = Window.day(DIA)
    settings = Settings.from_env()

    def titulos() -> list[str]:
        run = cli.curate_run(
            record.articles_of(data), window, settings, Memory(path=tmp_path, entries=[])
        )
        return [e.title for e in run.digest.events]

    assert titulos() == titulos()


def pytest_fail(message: str):
    raise AssertionError(message)
