from datetime import datetime, timedelta

import pytest

from newsbot import cli, record
from newsbot.config import TIMEZONE, Window
from newsbot.models import Article

WHEN = datetime.now(TIMEZONE) - timedelta(days=1)


@pytest.fixture
def corrida(monkeypatch, tmp_path):
    """El pipeline con un hecho cubierto por varios medios, Telegram falso y un historial
    propio: con una sola nota el curador lo descarta por falta de cobertura."""
    monkeypatch.setenv("NEWSBOT_STATE", str(tmp_path / "history.json"))
    monkeypatch.setenv("NEWSBOT_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(
        cli,
        "collect",
        lambda *a, **k: [
            Article(
                title=title,
                url=f"https://{source.lower()}.com/x",
                source=source,
                scope="ar",
                published=WHEN,
            )
            for title, source in [
                ("El INDEC publicó la inflación de agosto", "D1"),
                ("La inflación de agosto fue de 1,7%, informó el INDEC", "D2"),
                ("Inflación: el INDEC informó un 1,7% en agosto", "D3"),
            ]
        ],
    )
    monkeypatch.setattr(cli, "compose", lambda digest, settings: "mensaje")
    monkeypatch.setattr(cli, "send_message", lambda *a, **k: [1])
    return tmp_path / "history.json"


def test_el_resumen_es_del_dia_anterior_completo():
    """A las 7 y a las 19 tiene que contar lo mismo: con la ventana móvil de 24 horas
    cada corrida agarraba otro recorte y devolvía noticias distintas."""
    ventana = cli.window_for(cli.parse_args([]))
    ayer = datetime.now(TIMEZONE).date() - timedelta(days=1)

    assert ventana == Window.day(ayer)
    assert ventana.date_label == ayer.strftime("%d/%m")


def test_hours_vuelve_a_la_ventana_movil():
    assert cli.window_for(cli.parse_args(["--hours", "6"])).end.date() == (
        datetime.now(TIMEZONE).date()
    )


def test_la_corrida_de_prueba_no_toca_el_historial(corrida):
    """Probar a mano tiene que mostrar lo que vería el usuario, no consumirle noticias."""
    assert cli.main([]) == 0

    assert not corrida.exists()


def test_el_envio_diario_registra_lo_publicado(corrida):
    assert cli.main(["--save-memory"]) == 0

    assert "inflac" in corrida.read_text()


def test_el_envio_diario_deja_la_corrida_registrada(corrida):
    """Cada envío tiene que quedar guardado entero: es el único insumo para evaluar un
    cambio del curador contra los días ya vividos."""
    assert cli.main(["--save-memory"]) == 0

    guardadas = sorted((corrida.parent / "runs").glob("*.json.gz"))
    data = record.load(guardadas[0])
    assert len(data["articulos"]) == 3
    assert data["elegidos"] and data["elegidos"][0] == data["ranking"][0]["id"]


def test_la_prueba_no_deja_registro(corrida):
    assert cli.main([]) == 0

    assert not (corrida.parent / "runs").exists()
