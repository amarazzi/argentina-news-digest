from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import yaml

PACKAGE_DIR = Path(__file__).parent
TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    scope: str


@dataclass(frozen=True)
class Search:
    """Búsqueda en Google News. `window` acota la ventana temporal (sintaxis `when:`)."""

    query: str
    lang: str
    country: str
    scope: str
    window: str = "2d"

    @property
    def url(self) -> str:
        query = quote_plus(f"{self.query} when:{self.window}")
        ceid = quote_plus(f"{self.country}:{self.lang}")
        return (
            "https://news.google.com/rss/search"
            f"?q={query}&hl={self.lang}&gl={self.country}&ceid={ceid}"
        )


@dataclass(frozen=True)
class Sources:
    feeds: list[Feed]
    searches: list[Search]


def load_sources(path: Path | None = None) -> Sources:
    raw = yaml.safe_load((path or PACKAGE_DIR / "sources.yaml").read_text(encoding="utf-8"))
    return Sources(
        feeds=[Feed(**item) for item in raw.get("feeds", [])],
        searches=[Search(**item) for item in raw.get("searches", [])],
    )


@dataclass(frozen=True)
class Settings:
    telegram_token: str | None
    telegram_chat_id: str | None
    openai_api_key: str | None
    openai_model: str
    max_events: int
    request_timeout: float

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            max_events=int(os.getenv("MAX_EVENTS", "7")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
        )
