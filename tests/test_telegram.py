import httpx
import pytest

from newsbot import telegram
from newsbot.telegram import TelegramError, send_chunk, send_message


class Response:
    def __init__(self, status: int, message_id: int = 1) -> None:
        self.status_code = status
        self.text = "error"
        self._message_id = message_id

    def json(self) -> dict:
        return {"result": {"message_id": self._message_id}}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)


@pytest.fixture(autouse=True)
def sin_espera(monkeypatch):
    monkeypatch.setattr(telegram.time, "sleep", lambda _: None)


def test_reintenta_cuando_telegram_esta_saturado(monkeypatch):
    respuestas = [Response(429), Response(200, message_id=7)]
    monkeypatch.setattr(telegram.httpx, "post", lambda *a, **k: respuestas.pop(0))

    assert send_chunk("hola", token="t", chat_id="1", timeout=1) == 7


def test_si_rechaza_el_html_reenvia_en_texto_plano(monkeypatch):
    enviados = []

    def post(url, json, timeout):
        enviados.append(json)
        return Response(400) if len(enviados) == 1 else Response(200, message_id=9)

    monkeypatch.setattr(telegram.httpx, "post", post)

    assert send_chunk("<b>hola</b>", token="t", chat_id="1", timeout=1) == 9
    assert "parse_mode" not in enviados[1]
    assert enviados[1]["text"] == "hola"


def test_un_fallo_a_mitad_de_camino_informa_lo_ya_enviado(monkeypatch):
    """El CLI usa `sent` para no repetir mañana lo que el usuario ya leyó."""
    respuestas = [Response(200, message_id=1), Response(403), Response(403), Response(403)]
    monkeypatch.setattr(telegram.httpx, "post", lambda *a, **k: respuestas.pop(0))

    texto = "\n".join(["a" * 4000, "b" * 4000])
    with pytest.raises(TelegramError) as exc:
        send_message(texto, token="t", chat_id="1", timeout=1)

    assert exc.value.sent == [1]
