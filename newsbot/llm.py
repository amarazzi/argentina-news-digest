"""Cliente mínimo de LLM vía HTTP, sin SDK: Gemini (tier gratis) u OpenAI."""

from __future__ import annotations

import logging
import time

import httpx

from .config import LLM

log = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# El tier gratis contesta 429/503 cuando el modelo está saturado; conviene reintentar.
RETRIES = 4
BACKOFF = 5.0


class LLMError(RuntimeError):
    pass


def _openai(prompt: str, llm: LLM) -> tuple[str, dict, dict]:
    payload = {
        "model": llm.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    return OPENAI_URL, payload, {"Authorization": f"Bearer {llm.api_key}"}


def _gemini(prompt: str, llm: LLM) -> tuple[str, dict, dict]:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }
    url = GEMINI_URL.format(model=llm.model)
    return url, payload, {"x-goog-api-key": llm.api_key}


def _text(provider: str, data: dict) -> str:
    if provider == "gemini":
        # Los modelos con razonamiento mezclan partes de pensamiento con la respuesta.
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()
    return data["choices"][0]["message"]["content"].strip()


def complete(prompt: str, *, llm: LLM, timeout: float = 180.0) -> str:
    build = _gemini if llm.provider == "gemini" else _openai
    url, payload, headers = build(prompt, llm)
    for attempt in range(RETRIES):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return _text(llm.provider, response.json())
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            busy = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 503)
            if not busy or attempt == RETRIES - 1:
                raise LLMError(str(exc)) from exc
            log.info("modelo saturado, reintento %d de %d", attempt + 1, RETRIES - 1)
            time.sleep(BACKOFF * (attempt + 1))
    raise LLMError("sin respuesta del modelo")
