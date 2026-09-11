import httpx
import pytest

from newsbot import llm as llm_module
from newsbot.config import LLM
from newsbot.llm import LLMError, _text, complete, models


def gemini(parts, finish="STOP"):
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


def test_gemini_devuelve_el_texto():
    assert _text("gemini", gemini([{"text": "Resumen del día"}])) == "Resumen del día"


def test_gemini_solo_con_pensamiento_es_un_error():
    """Sin esto se enviaba un digest vacío y el proceso terminaba en verde."""
    data = gemini([{"text": "pensando...", "thought": True}], finish="MAX_TOKENS")
    with pytest.raises(LLMError):
        _text("gemini", data)


def test_gemini_cortado_por_seguridad_es_un_error():
    with pytest.raises(LLMError):
        _text("gemini", gemini([{"text": "Resu"}], finish="SAFETY"))


def test_openai_vacio_es_un_error():
    with pytest.raises(LLMError):
        _text("openai", {"choices": [{"message": {"content": "  "}}]})


def test_la_cascada_no_repite_el_modelo_pedido():
    assert models(LLM("gemini", "k", "gemini-3.5-flash-lite")) == [
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
    ]


def test_si_el_modelo_principal_agoto_la_cuota_responde_el_de_respaldo(monkeypatch):
    """El 429 del tier gratis dura hasta el otro día: sin cascada no hay resumen redactado."""
    usados = []

    def fake_post(url, **kwargs):
        usados.append(url)
        request = httpx.Request("POST", url)
        if "gemini-3.5-flash:" in url:
            return httpx.Response(429, request=request, json={"error": "quota"})
        return httpx.Response(200, request=request, json=gemini([{"text": "Resumen"}]))

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    monkeypatch.setattr(llm_module, "BACKOFF", 0)

    assert complete("hola", llm=LLM("gemini", "k", "gemini-3.5-flash")) == "Resumen"
    assert "gemini-3.5-flash-lite:" in usados[-1]


def test_si_ningun_modelo_contesta_falla(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(429, request=httpx.Request("POST", url), json={"error": "quota"})

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    monkeypatch.setattr(llm_module, "BACKOFF", 0)

    with pytest.raises(LLMError):
        complete("hola", llm=LLM("gemini", "k", "gemini-3.5-flash"))
