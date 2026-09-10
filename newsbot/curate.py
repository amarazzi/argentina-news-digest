"""Agente 2 — Curador: agrupa artículos en eventos y los rankea.

v0 usa heurísticas (sin LLM): clustering por solapamiento de palabras del titular y
un score por cantidad de medios que cubren el hecho, republicaciones y alcance internacional.
"""

from __future__ import annotations

import math
import re

from .models import Article, Event
from .text import discriminants, keywords, normalize, overlap, similarity, stems

SIMILARITY_THRESHOLD = 0.42
# Segunda pasada: dos grupos que comparten la mayor parte de sus raíces son el mismo hecho
# contado con otras palabras ("denunciará a Navitas" y "denuncia a cinco petroleras").
MERGE_THRESHOLD = 0.6
# Con menos raíces en común el parecido es casualidad ("Milei habló", "Milei viajó").
MIN_TOPIC_STEMS = 4
# Dos titulares pueden compartir "el Gobierno anunció un aumento" y hablar de cosas
# distintas: para agrupar tiene que haber algo propio del hecho en común.
MIN_SHARED_DISCRIMINANTS = 1
# Un tema no puede ocupar dos lugares del resumen: la muerte de alguien, las repercusiones
# y el recuerdo son la misma historia contada por partes. Dos hechos son el mismo tema si
# comparten dos raíces propias (un apellido, un lugar, una causa). Con una sola alcanza
# para un falso positivo: dos fallos distintos de la Corte comparten "corte" y siguen
# siendo dos noticias.
MIN_SHARED_TOPIC = 2
# Con una sola raíz en común también es el mismo tema si esa raíz pesa en el hecho más
# chico ("advertencia del Reino Unido por Malvinas" y "el premier británico será
# implacable" comparten sólo "malvin", y son la misma historia).
SAME_TOPIC_OVERLAP = 0.3
# El resumen es sólo de medios argentinos: la cobertura extranjera se recolecta para
# medir repercusión, pero no ocupa lugares.
WORLD_SLOTS = 0
# La cobertura extranjera sobre Argentina siempre es más chica que la local.
WORLD_BONUS = 2.0

# Temas que en la práctica sólo agregan ruido al resumen del día. Van con contexto: sueltas,
# "copa", "boca" o "selección" aparecen en noticias de política y de policiales.
NOISE = re.compile(
    r"\b(futbol|soccer|goleada|golazo|racing club|boca juniors|river plate|"
    r"copa (libertadores|america|argentina|del mundo|sudamericana)|"
    r"seleccion (argentina|nacional)|scaloneta|scaloni|messi|maradona\b(?!.*juicio)|"
    r"horoscopo|loteria|quiniela|receta|chimentos|farandula|gran hermano|"
    r"escalacao|corinthians|flamengo|palmeiras|gremio|libertadores|"
    r"premier league|laliga|champions|eliminatorias|onefootball|"
    r"transfer window|goalkeeper|midfielder|striker)\b"
)
NOISE_FACTOR = 0.25

# Si el titular es de sección dura, no se castiga aunque comparta vocabulario con el ruido
# ("escándalo por corrupción en la AFA", "boca de urna").
HARD_NEWS = re.compile(
    r"\b(justicia|judicial|fiscal|fiscalia|juez|jueza|fallo|corte suprema|casacion|"
    r"allanamiento|corrupcion|coima|congreso|senado|diputados|gobierno|ministro|"
    r"ministra|presidente|banco central|indec|inflacion|paro|denuncia|denuncio|"
    r"imputad|procesad|detenid|elecciones|votacion|urna|decreto|veto|presupuesto|"
    r"moratoria|jubilad|jubilacion|anses|prevision|paritaria|salario|tarifa)\b"
)

# Cotizaciones y cierres de mercado que se publican todos los días: sólo interesan si
# hubo un movimiento fuerte.
ROUTINE = re.compile(
    r"a cuanto (cotiza|esta|cerro)|cotizacion(es)? d[eo]|precio del dolar|minuto a minuto|"
    r"dolar (blue|oficial|hoy|cripto|mep|tarjeta|turista)\b|clima en|pronostico|"
    r"\b(acciones|adrs?|bonos|cedears?|merval|riesgo pais|panel lider|renta fija)\b|"
    r"\bcotiza(n|ron)?\b|apertura de los mercados|cierre de (los )?mercados?|"
    r"como (abren|cierran|operan)\b"
)
# Movimientos que sí son noticia. Los porcentajes valen de dos cifras para arriba: el
# "subió 0,3%" de todos los días no es una corrida.
SURGE = re.compile(
    r"\b(se dispar|disparo|derrumb|desplom|record|salto|trepo|hundio|escalada|corrida|"
    r"maximo historico|minimo historico|devaluo|devaluacion|supero|cepo|"
    r"por primera vez)\b|\d{2,}([.,]\d+)?\s*(%|por ciento)"
)

# Notas de servicio y clickbait de consumo: "el error al tomar café", "qué pasa si...".
SERVICE = re.compile(
    r"\b(que pasa si|el error (al|de)|el truco|los trucos|por que (no )?deberias|"
    r"esto es lo que (pasa|significa)|que significa|adios a|el habito|el secreto|"
    r"cual es el mejor|senales de que|lo que dice la ciencia|paso a paso|"
    r"como hacer|la receta|segun la inteligencia artificial)\b"
)


def is_routine(title: str) -> bool:
    plain = normalize(title)
    return bool(ROUTINE.search(plain)) and not SURGE.search(plain)


def is_service(title: str) -> bool:
    """Las mismas fórmulas las usa el periodismo político ("qué significa el fallo de la
    Corte", "adiós a la moratoria"): ahí no es una nota de consumo."""
    plain = normalize(title)
    return bool(SERVICE.search(plain)) and not HARD_NEWS.search(plain)


def is_noise(title: str) -> bool:
    plain = normalize(title)
    return bool(NOISE.search(plain)) and not HARD_NEWS.search(plain)


def penalized(event: Event) -> bool:
    """Se castiga por voto de los titulares del evento, no por el del lead: cuál queda de
    lead depende de qué medio publicó primero y eso no cambia de qué trata el hecho."""
    titles = {normalize(a.title) for a in event.articles}
    marked = sum(1 for t in titles if is_noise(t) or is_routine(t) or is_service(t))
    return marked * 2 >= len(titles)


def shares_discriminants(words: set[str], other: set[str]) -> bool:
    return len(discriminants(words) & discriminants(other)) >= MIN_SHARED_DISCRIMINANTS


def cluster(articles: list[Article]) -> list[Event]:
    """Agrupa artículos que hablan del mismo hecho.

    Recorre los artículos en un orden estable (por titular normalizado) para que el
    resultado no dependa del minuto en que cada medio publicó.
    """
    events: list[Event] = []
    fingerprints: list[set[str]] = []
    for article in sorted(articles, key=lambda a: (normalize(a.title), a.url)):
        words = keywords(article.title)
        best_index, best_score = -1, 0.0
        for index, existing in enumerate(fingerprints):
            score = similarity(words, existing)
            if (
                score > best_score
                and score >= SIMILARITY_THRESHOLD
                and shares_discriminants(words, existing)
            ):
                best_index, best_score = index, score
        if best_index >= 0:
            events[best_index].articles.append(article)
            fingerprints[best_index] |= words
        else:
            events.append(Event(title=article.title, articles=[article]))
            fingerprints.append(words)
    return merge(events)


def topic(event: Event) -> set[str]:
    """Raíces propias del hecho, presentes en la mitad de sus titulares: de qué trata."""
    counts: dict[str, int] = {}
    for article in event.articles:
        for stem in stems(article.title):
            counts[stem] = counts.get(stem, 0) + 1
    needed = max(len(event.articles) // 2, 1)
    return discriminants({stem for stem, seen in counts.items() if seen >= needed})


def merge(events: list[Event]) -> list[Event]:
    """Funde los grupos que hablan del mismo tema para que no se pise en el resumen.

    Repite hasta punto fijo: fusionar A con B agranda el tema de A y puede habilitar
    una fusión con C que en la primera pasada no llegaba al umbral.
    """
    pending = events
    while True:
        merged: list[Event] = []
        topics: list[set[str]] = []
        for event in pending:
            words = topic(event)
            target = -1
            if len(words) >= MIN_TOPIC_STEMS:
                for index, existing in enumerate(topics):
                    if overlap(words, existing) >= MERGE_THRESHOLD and shares_discriminants(
                        words, existing
                    ):
                        target = index
                        break
            if target < 0:
                merged.append(event)
                topics.append(words)
                continue
            merged[target].articles.extend(event.articles)
            topics[target] = topic(merged[target])
        if len(merged) == len(pending):
            return merged
        pending = merged


def takes(event: Event) -> int:
    """Titulares distintos: cuántas versiones propias del hecho se escribieron."""
    return len({normalize(a.title) for a in event.articles})


def coverage(event: Event) -> tuple[int, int, int]:
    """Redacciones que escribieron el hecho, medios que lo republicaron y variantes extra.

    Los medios se cuentan por `Article.source`, no por dominio: casi todo llega vía
    Google News y ahí todas las URLs comparten el mismo `news.google.com`.
    """
    outlets = len(event.outlets)
    independent = min(takes(event), outlets)
    return independent, outlets - independent, takes(event) - independent


def score(event: Event) -> float:
    """Más redacciones cubriendo el hecho = más importante.

    Cada redacción que lo escribe con sus palabras pesa el doble; republicar un cable
    también es una decisión editorial pero con peso decreciente, y las variantes de más
    de un mismo medio suman todavía menos: nueve notas de un solo diario no son cobertura
    amplia.
    """
    independent, copies, variants = coverage(event)
    world_bonus = WORLD_BONUS if event.scope == "world" else 0.0
    relevance = independent * 2.0 + math.sqrt(copies) + math.sqrt(variants) + world_bonus
    return relevance * NOISE_FACTOR if penalized(event) else relevance


def rank(articles: list[Article]) -> list[Event]:
    """Todos los hechos del día, del más al menos importante."""
    events = cluster(articles)
    for event in events:
        event.articles.sort(key=lambda a: a.published)
        event.title = event.lead.title
        event.score = score(event)
    events.sort(key=lambda e: (e.score, e.lead.published), reverse=True)
    return events


def same_topic(words: set[str], seen: set[str]) -> bool:
    """Dos hechos son la misma historia contada por partes."""
    shared = len(words & seen)
    return shared >= MIN_SHARED_TOPIC or (
        shared >= 1 and overlap(words, seen) >= SAME_TOPIC_OVERLAP
    )


def select(events: list[Event], max_events: int, world_slots: int = WORLD_SLOTS) -> list[Event]:
    """Los mejores `max_events` del ranking global, con el bloque mundo acotado y un
    tema por lugar.

    El cupo internacional es un techo y no una reserva: si no hay cobertura extranjera
    relevante, esos lugares los ocupan noticias argentinas en vez de quedar vacíos.
    """
    chosen: list[Event] = []
    topics: list[set[str]] = []
    world = 0
    for event in events:
        if len(chosen) >= max_events:
            break
        words = topic(event)
        if any(same_topic(words, seen) for seen in topics):
            continue
        if event.scope == "world":
            if world >= world_slots:
                continue
            world += 1
        chosen.append(event)
        topics.append(words)
    return chosen


def curate(articles: list[Article], max_events: int) -> list[Event]:
    return select(rank(articles), max_events)
