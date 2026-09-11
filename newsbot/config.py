from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import yaml

PACKAGE_DIR = Path(__file__).parent
TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")
DEFAULT_HOURS = 24


@dataclass(frozen=True)
class Window:
    """Ventana temporal `[start, end)` en hora de Argentina."""

    start: datetime
    end: datetime

    @classmethod
    def last_hours(cls, hours: int = DEFAULT_HOURS, *, end: datetime | None = None) -> Window:
        end = end or datetime.now(TIMEZONE)
        return cls(end - timedelta(hours=hours), end)

    @classmethod
    def day(cls, day: date) -> Window:
        start = datetime.combine(day, time.min, tzinfo=TIMEZONE)
        return cls(start, start + timedelta(days=1))

    def __contains__(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def lookback_hours(self, *, now: datetime | None = None) -> int:
        """Horas hacia atrás que hay que pedirle a Google News para cubrir la ventana."""
        elapsed = (now or datetime.now(TIMEZONE)) - self.start
        return max(1, math.ceil(elapsed.total_seconds() / 3600))

    @property
    def reference_date(self) -> date:
        """Día al que corresponde la ventana. `end` es exclusivo: para un día calendario
        apunta a la medianoche del día siguiente."""
        return (self.end - timedelta(microseconds=1)).date()

    @property
    def date_label(self) -> str:
        """Fecha del resumen para el encabezado, sin hora ni ventana."""
        return self.reference_date.strftime("%d/%m")

    @property
    def label(self) -> str:
        """Ventana completa, para los logs."""
        span = self.end - self.start
        if self.start.timetz() == time.min.replace(tzinfo=self.start.tzinfo) and span == timedelta(
            days=1
        ):
            return self.start.strftime("%d/%m/%Y")
        hours = round(span.total_seconds() / 3600)
        return f"últimas {hours} h (hasta el {self.end.strftime('%d/%m %H:%M')})"


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    scope: str


@dataclass(frozen=True)
class Search:
    """Búsqueda en Google News."""

    query: str
    lang: str
    country: str
    scope: str

    def url(self, lookback_hours: int) -> str:
        query = quote_plus(f"{self.query} when:{lookback_hours}h")
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
class LLM:
    """Modelo que redacta el resumen. Gemini tiene tier gratis; OpenAI se paga."""

    provider: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Settings:
    telegram_token: str | None
    telegram_chat_id: str | None
    llm: LLM | None
    # Los vectores para agrupar salen de Gemini: sin clave el curador agrupa por palabras.
    embeddings_key: str | None
    max_events: int
    request_timeout: float
    # El juez editorial todavía no decide en producción: hace falta comparar su criterio
    # contra el curador determinístico sobre varios días guardados en `runs/`.
    judge: bool = False
    judge_model: str | None = None

    @property
    def judge_llm(self) -> LLM | None:
        """El modelo que juzga: el mismo que redacta, salvo que se pida otro."""
        if not self.llm:
            return None
        return replace(self.llm, model=self.judge_model or self.llm.model)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            llm=llm_from_env(),
            embeddings_key=os.getenv("GEMINI_API_KEY"),
            max_events=int(os.getenv("MAX_EVENTS", "7")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
            judge=flag("NEWSBOT_JUDGE"),
            judge_model=os.getenv("JUDGE_MODEL"),
        )


def flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def llm_from_env() -> LLM | None:
    if key := os.getenv("GEMINI_API_KEY"):
        return LLM("gemini", key, os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    if key := os.getenv("OPENAI_API_KEY"):
        return LLM("openai", key, os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    return None
