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
    "to", "with", "da", "das", "do", "dos", "em", "nao", "os", "uma",
}


# Un mismo hecho se nombra distinto en cada idioma; sin esto no se agrupa la cobertura
# internacional con la local.
SYNONYMS = {
    "falklands": "malvinas", "falkland": "malvinas",
    "argentine": "argentina", "argentinian": "argentina", "argentinas": "argentina",
    "argentinos": "argentina", "argentino": "argentina",
    "government": "gobierno", "governo": "gobierno", "cabinet": "gabinete",
    "president": "presidente", "presidency": "presidencia",
    "minister": "ministro", "ministry": "ministerio",
    "congress": "congreso", "senate": "senado", "lawmakers": "diputados",
    "inflation": "inflacion", "inflacao": "inflacion",
    "imf": "fmi", "currency": "moneda", "dollar": "dolar",
    "devaluation": "devaluacion", "devaluacao": "devaluacion",
    "economy": "economia",
    "rate": "tasa", "rates": "tasa", "juros": "tasa", "bank": "banco",
    "strike": "paro", "greve": "paro", "protest": "protesta",
    "court": "corte", "judge": "juez", "ruling": "fallo", "trial": "juicio",
    "prosecutor": "fiscal", "charges": "denuncia", "lawsuit": "demanda",
    "election": "elecciones", "elections": "elecciones", "eleicoes": "elecciones",
    "vote": "voto", "poll": "encuesta",
    "bill": "ley", "law": "ley", "lei": "ley", "veto": "veto",
    "reform": "reforma", "budget": "presupuesto", "orcamento": "presupuesto",
    "pension": "jubilacion", "pensions": "jubilacion", "pensioners": "jubilados",
    "oil": "petroleo", "energy": "energia",
    "mining": "mineria", "soy": "soja", "wheat": "trigo", "exports": "exportaciones",
    "poverty": "pobreza", "unemployment": "desempleo",
    "deal": "acuerdo", "agreement": "acuerdo", "acordo": "acuerdo",
    "talks": "negociacion", "loan": "prestamo", "debt": "deuda", "divida": "deuda",
    "died": "murio", "dies": "murio", "death": "muerte", "morte": "muerte",
    "killed": "muerto", "crash": "choque", "storm": "temporal", "flood": "inundacion",
    "police": "policia", "arrested": "detenido", "corruption": "corrupcion",
    "scandal": "escandalo", "investigation": "investigacion",
    "announced": "anuncio", "announces": "anuncio", "anuncia": "anuncio",
    "britain": "reinounido", "british": "reinounido", "uk": "reinounido",
    "brazil": "brasil", "chinese": "china",
    "washington": "eeuu", "usa": "eeuu", "american": "eeuu",
}

STEM_LENGTH = 6
# El mismo mapeo, ya recortado, para que la fusión por raíces cruce idiomas.
STEM_SYNONYMS = {k[:STEM_LENGTH]: v[:STEM_LENGTH] for k, v in SYNONYMS.items()}

# Raíces que aparecen todos los días en cualquier tema: dos titulares que sólo comparten
# esto no hablan del mismo hecho.
GENERIC_STEMS = {
    "milei", "gobier", "argent", "presid", "nacion", "pais", "nuevo", "nueva", "tras",
    "anunci", "confir", "asegur", "afirmo", "dijo", "habla", "hablo", "advirt", "adelan",
    "buenos", "aires", "hoy", "ayer", "manana", "dia", "dias", "ano", "anos", "hora",
    "horas", "millon", "menos", "primer", "ultimo", "ultima", "detall", "revelo",
    "cifra", "clave", "claves", "polemi", "fuerte", "duro", "dura", "medida",
    "oficia", "casa", "rosada", "gestio", "ahora", "asi", "video", "fotos",
    "quien", "quiene", "cual", "cuales", "cuanto", "todo", "todos",
    "aument", "suba", "subio", "bajo", "cambio", "empez", "comenz", "llego",
    "report", "inform", "presen", "lanzo", "pidio", "busca", "quiere",
}


# Entidades de varias palabras que son un solo nombre. Sin esto "Corte Suprema" aporta dos
# raíces y dos fallos distintos del mismo día cumplen solos el piso de tema compartido: la
# memoria terminaba bloqueando una semana cualquier noticia que nombrara a la Corte.
ENTITIES = {
    "corte suprema de justicia": "cortesuprema",
    "corte suprema": "cortesuprema",
    "supreme court": "cortesuprema",
    "banco central": "bancocentral",
    "central bank": "bancocentral",
    "cristina fernandez de kirchner": "cristinakirchner",
    "cristina kirchner": "cristinakirchner",
    "jefe de gabinete": "jefedegabinete",
    "jefa de gabinete": "jefedegabinete",
    "casa rosada": "casarosada",
    "buenos aires": "buenosaires",
    "reino unido": "reinounido",
    "estados unidos": "estadosunidos",
    "united states": "estadosunidos",
    "fondo monetario internacional": "fmi",
    "seguridad social": "seguridadsocial",
    "derechos humanos": "derechoshumanos",
    "boca juniors": "bocajuniors",
    "river plate": "riverplate",
}
COMPOUND = re.compile(
    r"\b(" + "|".join(sorted(ENTITIES, key=len, reverse=True)) + r")\b"
)


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))


def join_entities(text: str) -> str:
    """Un nombre de varias palabras pasa a ser un solo token, y cuenta como una raíz."""
    return COMPOUND.sub(lambda m: ENTITIES[m.group(0)], text)


def keywords(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", join_entities(normalize(title)))
    return {SYNONYMS.get(w, w) for w in words if w not in STOPWORDS}


def stems(title: str) -> set[str]:
    """Raíces cortas: "denuncia", "denunciará" y "denunciante" quedan en "denunc"."""
    return {STEM_SYNONYMS.get(w[:STEM_LENGTH], w[:STEM_LENGTH]) for w in keywords(title)}


def discriminants(words: set[str]) -> set[str]:
    """Las que identifican el hecho. Sin ellas, el parecido es vocabulario de todos los
    días: "el Gobierno anunció un aumento" describe dos noticias por semana."""
    return {w for w in words if w[:STEM_LENGTH] not in GENERIC_STEMS}


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
