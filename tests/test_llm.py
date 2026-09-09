import pytest

from newsbot.llm import LLMError, _text


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
