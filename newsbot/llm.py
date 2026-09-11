"""Cliente mínimo de LLM vía HTTP, sin SDK: Gemini (tier gratis) u OpenAI."""

from __future__ import annotations

import logging
import time
from dataclasses import replace

import httpx

from .config import LLM

log = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# El tier gratis contesta 429/503 cuando el modelo está saturado; conviene reintentar.
RETRIES = 4
# Un 429 casi siempre es la cuota diaria agotada: esperar no la devuelve, conviene pasar
# rápido al modelo de respaldo.
QUOTA_RETRIES = 2
BACKOFF = 5.0
# Cuando la cuota diaria del modelo principal se agotó, reintentar no alcanza: el 429 no
# se va hasta la medianoche del Pacífico. Los lite tienen cuota propia y más alta, así que
# antes de caer al resumen determinístico se prueba con ellos.
FALLBACK_MODELS = {
    "gemini": ("gemini-3.5-flash-lite", "gemini-flash-lite-latest"),
    "openai": (),
}


class LLMError(RuntimeError):
    pass


# URL, cuerpo y encabezados de una llamada al proveedor.
Call = tuple[str, dict, dict]


# Lo que consumió la corrida. Sin esto no hay forma de saber cuánto cuesta un día de
# digest cuando el juicio editorial pase a depender del modelo.
USAGE = {"llamadas": 0, "tokens_prompt": 0, "tokens_respuesta": 0}


def _account(provider: str, data: dict) -> None:
    USAGE["llamadas"] += 1
    if provider == "gemini":
        used = data.get("usageMetadata") or {}
        USAGE["tokens_prompt"] += used.get("promptTokenCount", 0)
        USAGE["tokens_respuesta"] += used.get("candidatesTokenCount", 0)
        return
    used = data.get("usage") or {}
    USAGE["tokens_prompt"] += used.get("prompt_tokens", 0)
    USAGE["tokens_respuesta"] += used.get("completion_tokens", 0)


def _openai(prompt: str, llm: LLM, schema: dict | None, temperature: float) -> Call:
    payload: dict = {
        "model": llm.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if schema:
        payload["response_format"] = {"type": "json_object"}
    return OPENAI_URL, payload, {"Authorization": f"Bearer {llm.api_key}"}


def _gemini(prompt: str, llm: LLM, schema: dict | None, temperature: float) -> Call:
    config: dict = {"temperature": temperature}
    if schema:
        config |= {"responseMimeType": "application/json", "responseSchema": schema}
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
    url = GEMINI_URL.format(model=llm.model)
    return url, payload, {"x-goog-api-key": llm.api_key}


def _text(provider: str, data: dict) -> str:
    if provider == "gemini":
        candidate = data["candidates"][0]
        # Los modelos con razonamiento mezclan partes de pensamiento con la respuesta:
        # si se queda sin tokens puede volver sólo con pensamiento y ninguna respuesta.
        parts = candidate["content"]["parts"]
        text = "".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()
        reason = candidate.get("finishReason", "STOP")
        if not text:
            raise LLMError(f"respuesta vacía del modelo (finishReason={reason})")
        if reason not in ("STOP", "MAX_TOKENS"):
            raise LLMError(f"el modelo cortó la respuesta (finishReason={reason})")
        return text
    text = data["choices"][0]["message"]["content"].strip()
    if not text:
        raise LLMError("respuesta vacía del modelo")
    return text


def models(llm: LLM) -> list[str]:
    """El modelo pedido primero y los de respaldo después, sin repetir."""
    chain = [llm.model]
    chain += [m for m in FALLBACK_MODELS.get(llm.provider, ()) if m != llm.model]
    return chain


def _ask(prompt: str, llm: LLM, timeout: float, schema: dict | None, temperature: float) -> str:
    build = _gemini if llm.provider == "gemini" else _openai
    url, payload, headers = build(prompt, llm, schema, temperature)
    for attempt in range(RETRIES):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            _account(llm.provider, data)
            return _text(llm.provider, data)
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
            limit = RETRIES if status == 503 else QUOTA_RETRIES
            if status not in (429, 503) or attempt >= limit - 1:
                raise LLMError(str(exc)) from exc
            log.info("modelo saturado, reintento %d de %d", attempt + 1, RETRIES - 1)
            time.sleep(BACKOFF * (attempt + 1))
    raise LLMError("sin respuesta del modelo")


def complete(
    prompt: str,
    *,
    llm: LLM,
    timeout: float = 180.0,
    schema: dict | None = None,
    temperature: float = 0.3,
) -> str:
    """Con `schema` la respuesta vuelve como JSON de esa forma, para lo que no se lee
    sino que se parsea."""
    last: LLMError | None = None
    for model in models(llm):
        try:
            return _ask(prompt, replace(llm, model=model), timeout, schema, temperature)
        except LLMError as exc:
            log.warning("%s no contestó (%s)", model, exc)
            last = exc
    raise last or LLMError("sin modelos disponibles")
