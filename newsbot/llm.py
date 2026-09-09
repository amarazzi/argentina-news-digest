"""Cliente mínimo de LLM (OpenAI-compatible) vía HTTP, sin SDK."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def complete(prompt: str, *, api_key: str, model: str, timeout: float = 60.0) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    try:
        response = httpx.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(str(exc)) from exc
    return response.json()["choices"][0]["message"]["content"].strip()
