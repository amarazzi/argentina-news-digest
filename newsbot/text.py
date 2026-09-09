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


# Un mismo hecho se nombra distinto en cada idioma; sin esto no se agrupa la cobertura
# internacional con la local.
SYNONYMS = {
    "falklands": "malvinas",
    "falkland": "malvinas",
    "argentine": "argentina",
    "argentinian": "argentina",
    "argentinas": "argentina",
    "argentinos": "argentina",
    "government": "gobierno",
    "president": "presidente",
    "inflation": "inflacion",
}

STEM_LENGTH = 6


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def keywords(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", normalize(title))
    return {SYNONYMS.get(w, w) for w in words if w not in STOPWORDS}


def stems(title: str) -> set[str]:
    """Raíces cortas: "denuncia", "denunciará" y "denunciante" quedan en "denunc"."""
    return {w[:STEM_LENGTH] for w in keywords(title)}


def similarity(a: set[str], b: set[str]) -> float:
    """Jaccard entre dos conjuntos de palabras."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap(a: set[str], b: set[str]) -> float:
    """Cuánto del conjunto más chico está contenido en el otro."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
