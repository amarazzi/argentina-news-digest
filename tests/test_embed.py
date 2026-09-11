from datetime import datetime

import pytest

from newsbot import embed as embed_module
from newsbot.config import TIMEZONE
from newsbot.embed import BATCH, EmbedError, embed, key_of, text_of, vectors_for
from newsbot.models import Article

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)


def article(title: str, summary: str = "") -> Article:
    return Article(
        title=title,
        url=f"https://medio.com/{abs(hash(title))}",
        source="Medio",
        scope="ar",
        published=WHEN,
        summary=summary,
    )


class Llamadas:
    """Reemplaza la llamada HTTP: devuelve un vector por texto y anota qué se pidió."""

    def __init__(self, fallar_desde: int | None = None) -> None:
        self.chunks: list[list[str]] = []
        self.fallar_desde = fallar_desde

    def __call__(self, texts, *, api_key, model, timeout):
        if self.fallar_desde is not None and len(self.chunks) >= self.fallar_desde:
            raise EmbedError("429")
        self.chunks.append(list(texts))
        return [[float(len(text)), 1.0] for text in texts]


@pytest.fixture
def llamadas(monkeypatch):
    fake = Llamadas()
    monkeypatch.setattr(embed_module, "_post", fake)
    monkeypatch.setattr(embed_module.time, "sleep", lambda _: None)
    return fake


def test_el_texto_es_el_titular_y_el_principio_del_copete():
    texto = text_of(article("Diputados aprobó el Presupuesto", "x" * 500))
    assert texto == "Diputados aprobó el Presupuesto. " + "x" * 200


def test_el_texto_de_una_nota_sin_copete_es_el_titular():
    assert text_of(article("Murió Chiche Gelblung")) == "Murió Chiche Gelblung."


def test_no_vuelve_a_pedir_lo_que_ya_tiene(llamadas):
    conocido = {key_of("uno"): [1.0, 0.0]}
    vectors = embed(["uno", "dos"], api_key="k", known=conocido)
    assert llamadas.chunks == [["dos"]]
    assert vectors[key_of("uno")] == [1.0, 0.0]
    assert key_of("dos") in vectors


def test_pide_una_sola_vez_el_texto_repetido(llamadas):
    embed(["igual", "igual"], api_key="k")
    assert llamadas.chunks == [["igual"]]


def test_parte_el_pedido_en_lotes(llamadas):
    textos = [f"nota {i}" for i in range(BATCH + 5)]
    vectors = embed(textos, api_key="k")
    assert [len(chunk) for chunk in llamadas.chunks] == [BATCH, 5]
    assert len(vectors) == len(textos)


def test_si_la_api_se_corta_devuelve_lo_que_consiguio(monkeypatch):
    fake = Llamadas(fallar_desde=1)
    monkeypatch.setattr(embed_module, "_post", fake)
    monkeypatch.setattr(embed_module.time, "sleep", lambda _: None)
    vectors = embed([f"nota {i}" for i in range(BATCH + 5)], api_key="k")
    assert len(vectors) == BATCH


def test_sin_clave_no_llama_a_nadie(llamadas):
    assert vectors_for([article("Algo pasó")], api_key=None) == {}
    assert llamadas.chunks == []


def test_con_los_vectores_del_registro_no_pide_nada(llamadas):
    """El replay de un día guardado no vuelve a pagar los vectores."""
    nota = article("Algo pasó")
    guardados = {key_of(text_of(nota)): [0.1, 0.2]}
    assert vectors_for([nota], api_key="k", known=guardados) == guardados
    assert llamadas.chunks == []
