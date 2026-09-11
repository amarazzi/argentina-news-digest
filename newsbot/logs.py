"""Configuración de logs: nunca imprimir el token del bot."""

from __future__ import annotations

import logging


class Redact(logging.Filter):
    """httpx loguea la URL completa de Telegram, que lleva el token adentro."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.clean(record.getMessage())
        record.args = ()
        return True

    def clean(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return text


def configure(*, verbose: bool, secrets: list[str]) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # Con -v, httpx imprime "POST https://api.telegram.org/bot<token>/sendMessage".
    logging.getLogger("httpx").setLevel(logging.WARNING)
    redact = Redact(secrets)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redact)
