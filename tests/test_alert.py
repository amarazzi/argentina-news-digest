import logging
from dataclasses import replace

from newsbot import alert
from newsbot.config import Settings
from newsbot.logs import Redact
from newsbot.telegram import TelegramError

SETTINGS = Settings(
    telegram_token="123:abc",
    telegram_chat_id="9",
    llm=None,
    embeddings_key=None,
    max_events=7,
    request_timeout=20,
)


def test_avisa_cuando_el_dia_salio_flojo(monkeypatch):
    enviados = []
    monkeypatch.setattr(alert, "send_message", lambda text, **kw: enviados.append(text))

    alert.weak_day(1, "10/09", SETTINGS)

    assert len(enviados) == 1
    assert "1 noticia" in enviados[0]


def test_no_avisa_cuando_el_dia_estuvo_normal(monkeypatch):
    enviados = []
    monkeypatch.setattr(alert, "send_message", lambda text, **kw: enviados.append(text))

    alert.weak_day(5, "10/09", SETTINGS)

    assert enviados == []


def test_un_aviso_que_falla_no_rompe_la_corrida(monkeypatch):
    def explota(text, **kwargs):
        raise TelegramError("400")

    monkeypatch.setattr(alert, "send_message", explota)

    alert.notify("hola", SETTINGS)


def test_sin_telegram_el_aviso_queda_en_el_log(monkeypatch, caplog):
    enviados = []
    monkeypatch.setattr(alert, "send_message", lambda text, **kw: enviados.append(text))

    with caplog.at_level(logging.WARNING):
        alert.notify("hola", replace(SETTINGS, telegram_token=None))

    assert enviados == []
    assert "hola" in caplog.text


def test_el_token_no_sale_en_los_logs():
    """httpx loguea la URL de Telegram completa, con el token adentro."""
    limpio = Redact(["123:abc"]).clean("POST https://api.telegram.org/bot123:abc/sendMessage")

    assert "123:abc" not in limpio
    assert "bot***" in limpio
