"""Utilidades de texto compartidas entre el curador y los modelos."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "a", "al", "ante", "como", "con", "contra", "de", "del", "desde", "el", "en", "entre",
    "es", "esta", "este", "fue", "ha", "hasta", "la", "las", "le", "lo", "los", "mas",
    "no", "para", "pero", "por", "que", "se", "segun", "ser", "si", "sin", "sobre", "son",
    "su", "sus", "tras", "un", "una", "uno", "y", "ya",
    "an", "and", "as", "at", "be", "by", "for", "from", "in", "is", "of", "on", "the",
    "to", "with",
}


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def keywords(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", normalize(title))
    return {w for w in words if w not in STOPWORDS}


def similarity(a: set[str], b: set[str]) -> float:
    """Jaccard entre dos conjuntos de palabras."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
