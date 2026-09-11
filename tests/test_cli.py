from datetime import datetime

import pytest

from newsbot import cli
from newsbot.config import TIMEZONE
from newsbot.models import Article

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)


@pytest.fixture
def corrida(monkeypatch, tmp_path):
    """El pipeline con un hecho cubierto por varios medios, Telegram falso y un historial
    propio: con una sola nota el curador lo descarta por falta de cobertura."""
    monkeypatch.setenv("NEWSBOT_STATE", str(tmp_path / "history.json"))
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


def test_la_corrida_de_prueba_no_toca_el_historial(corrida):
    """Probar a mano tiene que mostrar lo que vería el usuario, no consumirle noticias."""
    assert cli.main([]) == 0

    assert not corrida.exists()


def test_el_envio_diario_registra_lo_publicado(corrida):
    assert cli.main(["--save-memory"]) == 0

    assert "inflac" in corrida.read_text()
