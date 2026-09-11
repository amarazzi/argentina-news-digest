"""Agente 2 — Curador: agrupa artículos en eventos y los rankea.

v0 usa heurísticas (sin LLM): clustering por solapamiento de palabras del titular y
un score por cantidad de medios que cubren el hecho, republicaciones y alcance internacional.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from . import group
from .embed import key_of, text_of
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
# Con una sola raíz en común también es el mismo tema, pero sólo cuando esa raíz es
# prácticamente todo el tema más chico ("advertencia del Reino Unido por Malvinas" y "el
# premier británico será implacable" comparten sólo "malvin"). Con un tercio alcanzaba
# para que dos fallos distintos de la Corte fueran el mismo tema.
SAME_TOPIC_OVERLAP = 0.6
# El resumen es sólo de medios argentinos: la cobertura extranjera se recolecta para
# medir repercusión, pero no ocupa lugares.
WORLD_SLOTS = 0
# La cobertura extranjera sobre Argentina siempre es más chica que la local.
WORLD_BONUS = 2.0
# Piso para entrar al resumen: tres medios lo publicaron y al menos dos lo escribieron con
# sus palabras. Con menos es la columna de opinión o la nota de color de una sola
# redacción, que es justo con lo que se rellenaba el final del digest en un día flojo.
MIN_COVERAGE = 3
MIN_TAKES = 2
# Además del piso de cobertura, el hecho tiene que jugar en la misma escala que lo más
# importante del día: un tercio del puntaje del primero. Es lo que separa una noticia que
# siguieron varias redacciones del relleno con el que se completaba el final del digest.
RELATIVE_FLOOR = 1 / 3
# Cuántas notas por día se vectorizan. El tier gratis de Gemini corta en mil embeddings
# por día y un día cualquiera trae casi mil notas, así que el presupuesto se gasta en las
# candidatas y queda margen para reintentos.
EMBED_LIMIT = 500

# Temas que en la práctica sólo agregan ruido al resumen del día. Van con contexto: sueltas,
# "copa", "boca" o "selección" aparecen en noticias de política y de policiales.
NOISE = re.compile(
    r"\b(futbol|soccer|goleada|golazo|racing club|boca juniors|river plate|"
    r"copa (libertadores|america|argentina|del mundo|sudamericana)|"
    r"seleccion (argentina|nacional)|scaloneta|scaloni|messi|maradona\b(?!.*juicio)|"
    r"horoscopo|loteria|quiniela|receta|chimentos|farandula|gran hermano|"
    r"escalacao|corinthians|flamengo|palmeiras|gremio|"
    r"transfer window|goalkeeper|midfielder|striker)\b"
)

# Deporte sin ambigüedad: acá no vale la excepción de sección dura. La crónica deportiva
# está llena de palabras de tribunal ("denunció a Depay ante la Conmebol", "la FIFA
# sancionó") y con la excepción puesta entraban como si fueran noticias judiciales.
SPORTS = re.compile(
    r"\b(conmebol|fifa|libertadores|premier league|laliga|champions|eliminatorias|"
    r"onefootball|mls|inter miami|nba|nfl|formula 1|gran premio|"
    r"atp|wta|roland garros|wimbledon)\b"
)
NOISE_FACTOR = 0.25

# Si el titular es de sección dura, no se castiga aunque comparta vocabulario con el ruido
# ("escándalo por corrupción en la AFA", "boca de urna").
HARD_NEWS = re.compile(
    r"\b(justicia|judicial|fiscal|fiscalia|juez|jueza|fallo|corte suprema|casacion|"
    r"allanamiento|corrupcion|coima|congreso|senado|diputados|gobierno|ministro|"
    r"ministra|presidente|banco central|indec|inflacion|paro|denuncia|denuncio|"
    r"imputad\w*|procesad\w*|detenid\w*|elecciones|votacion|urna|decreto|veto|presupuesto|"
    r"moratoria|jubilad\w*|jubilacion|anses|prevision|paritaria|salario|tarifa)\b"
)

# Cotizaciones y cierres de mercado que se publican todos los días: sólo interesan si
# hubo un movimiento fuerte.
ROUTINE = re.compile(
    r"a cuanto (cotiza|esta|cerro)|cotizacion(es)? d[eo]|precio del dolar|minuto a minuto|"
    r"dolar (blue|oficial|hoy|cripto|mep|tarjeta|turista)\b|"
    r"pronostico (del tiempo|meteorologico)|alerta meteorologic\w*|"
    r"(el|que) (tiempo|clima) (hoy|manana|para|en el fin de semana)|"
    r"\bcotiza(n|ron)?\b|apertura de los mercados|cierre de (los )?mercados?|"
    r"como (abren|cierran|operan)\b"
)
# El parte diario de mercado: un activo financiero más el verbo de la rueda. Nombrar un
# activo no alcanza — así se caían un canje de deuda, el riesgo país tras un acuerdo con el
# FMI o el pronóstico económico del Fondo.
MARKET = re.compile(
    r"\b(acciones|adrs?|bonos|cedears?|merval|riesgo pais|panel lider|renta fija|"
    r"sp merval|wall street)\b"
)
MARKET_REPORT = re.compile(
    r"\b(suben|subieron|bajan|bajaron|caen|cayeron|avanzan|avanzaron|retroceden|"
    r"retrocedieron|operan|operaron|cierran|cerraron|abren|abrieron|rebotan|rebote|"
    r"en alza|en baja|en rojo|en verde|sin cambios|jornada|rueda)\b"
)
# Movimientos que sí son noticia. Los porcentajes valen de dos cifras para arriba: el
# "subió 0,3%" de todos los días no es una corrida.
SURGE = re.compile(
    r"\b(se dispar\w*|disparo|derrumb\w*|desplom\w*|record|salto|trepo|hundio|escalada|corrida|"
    r"maximo historico|minimo historico|devaluo|devaluacion|supero|cepo|"
    r"por primera vez)\b|\d{2,}([.,]\d+)?\s*(%|por ciento)"
)

# Notas de servicio y clickbait de consumo: "el error al tomar café", "qué pasa si...".
SERVICE = re.compile(
    r"\b(que pasa si|el error (al|de)|el truco|los trucos|por que (no )?deberias|"
    r"esto es lo que (pasa|significa)|que significa|el habito|el secreto|"
    r"cual es el mejor|senales de que|lo que dice la ciencia|paso a paso|"
    r"por que se (celebra|conmemora|festeja|recuerda)|que se (celebra|conmemora) hoy|"
    r"todo lo que hay que saber|de que se trata|cual es el origen|"
    r"como hacer|la receta|segun la inteligencia artificial)\b"
)

# Servicio de todos los días: calendarios de cobro, sorteos, horóscopo. Nombran organismos
# de sección dura ("cuándo cobro la AUH de ANSES") y por eso no pueden salvarse con
# HARD_NEWS como el resto del servicio: el titular es igual de rutinario.
DAILY_SERVICE = re.compile(
    r"\b(cuando (cobro|cobran|se cobra|cobra)|cuanto cobro|quienes cobran|"
    r"calendario de pagos|cronograma de pagos|fechas? de (cobro|pago)|"
    r"resultados? de (la|el) (quiniela|loto|quini)|sorteo|numeros ganadores|"
    r"\bloto\b|quini 6|signos del zodiaco|tarot|cabala)\b"
)

# Anticipos: lo que todavía no pasó. La noticia es el dato, no que hoy se va a publicar.
PREVIEW = re.compile(
    r"\b(da(ra)? a conocer|se conocera|se sabra|se publicara|difundira|"
    r"que se espera|expectativa por|a la espera de|en la previa|previa a|"
    r"pronostican|proyectan|estiman que|se espera que|"
    r"(hoy se|se) (conoce|sabe|publica) |cuando (se conoce|se publica|se sabe)|"
    r"a que hora|todo lo que hay que saber|que puede pasar)\b"
)
# Si el titular ya cuenta el resultado, no es anticipo aunque nombre lo que viene.
REPORTED = re.compile(
    r"\b(fue de|se ubico|alcanzo|marco|cerro en|arrojo|confirmo|anuncio|informo|"
    r"publico|revelo|resulto|termino|quedo en)\b"
)


def is_preview(title: str) -> bool:
    plain = normalize(title)
    return bool(PREVIEW.search(plain)) and not REPORTED.search(plain)


def is_routine(title: str) -> bool:
    plain = normalize(title)
    daily = ROUTINE.search(plain) or (MARKET.search(plain) and MARKET_REPORT.search(plain))
    return bool(daily) and not SURGE.search(plain)


def is_service(title: str) -> bool:
    """Las mismas fórmulas las usa el periodismo político ("qué significa el fallo de la
    Corte", "adiós a la moratoria"): ahí no es una nota de consumo."""
    plain = normalize(title)
    if DAILY_SERVICE.search(plain):
        return True
    return bool(SERVICE.search(plain)) and not HARD_NEWS.search(plain)


def is_noise(title: str) -> bool:
    plain = normalize(title)
    if SPORTS.search(plain):
        return True
    return bool(NOISE.search(plain)) and not HARD_NEWS.search(plain)


def is_junk(title: str) -> bool:
    return is_noise(title) or is_routine(title) or is_service(title)


def penalized(event: Event) -> bool:
    """Se castiga por voto de los titulares del evento, no por el del lead: cuál queda de
    lead depende de qué medio publicó primero y eso no cambia de qué trata el hecho."""
    titles = {normalize(a.title) for a in event.articles}
    marked = sum(1 for t in titles if is_junk(t) or is_preview(t))
    return marked * 2 >= len(titles)


def shares_discriminants(words: set[str], other: set[str]) -> bool:
    return len(discriminants(words) & discriminants(other)) >= MIN_SHARED_DISCRIMINANTS


def candidates(articles: list[Article], limit: int = EMBED_LIMIT) -> list[Article]:
    """Las notas que vale la pena vectorizar, de mayor a menor chance de ser noticia.

    Un día son casi mil notas y el tier gratis de embeddings da para menos, así que se
    gastan en las que podrían pelear un lugar: las que hablan de algo que también están
    contando otras redacciones. Una nota que ninguna otra acompaña no llega al piso de
    tres medios, y si igual aparece se agrupa por palabras como antes.
    """
    outlets: dict[str, set[str]] = defaultdict(set)
    for article in articles:
        for stem in discriminants(keywords(article.title)):
            outlets[stem].add(article.source)

    def reach(article: Article) -> int:
        stems = discriminants(keywords(article.title))
        return max((len(outlets[stem]) for stem in stems), default=0)

    useful = [a for a in articles if not is_junk(a.title)]
    return sorted(useful, key=lambda a: (-reach(a), a.title, a.url))[:limit]


def cluster(articles: list[Article], vectors: dict[str, list[float]] | None = None) -> list[Event]:
    """Agrupa artículos que hablan del mismo hecho.

    Lo que tiene vector se agrupa por significado; el resto —sin `GEMINI_API_KEY`, con la
    API caída o fuera del presupuesto de vectores— por palabras del titular, que parte el
    mismo hecho cuando dos redacciones lo cuentan distinto.
    """
    vectors = vectors or {}
    known = [a for a in articles if key_of(text_of(a)) in vectors]
    rest = [a for a in articles if key_of(text_of(a)) not in vectors]
    if len(known) < 2:
        return merge(cluster_by_words(articles))
    return merge(group.cluster(known, vectors) + cluster_by_words(rest))


def cluster_by_words(articles: list[Article]) -> list[Event]:
    """Agrupa por solapamiento de palabras del titular.

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
    return events


def topic(event: Event) -> set[str]:
    """Raíces propias del hecho, presentes en la mitad de sus titulares: de qué trata."""
    counts: dict[str, int] = {}
    for article in event.articles:
        for stem in stems(article.title):
            counts[stem] = counts.get(stem, 0) + 1
    needed = max(math.ceil(len(event.articles) / 2), 1)
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

    Un medio es independiente si publicó algún titular que ningún otro había publicado
    antes. `min(titulares, medios)` no medía quién escribió: una agencia con tres
    versiones de su cable y dos diarios que copian una contaban como tres redacciones.
    """
    first: dict[str, str] = {}
    independent: set[str] = set()
    for article in sorted(event.articles, key=lambda a: (a.published, a.url)):
        wrote = first.setdefault(normalize(article.title), article.outlet)
        if wrote == article.outlet:
            independent.add(article.outlet)
    copies = len(event.outlets) - len(independent)
    return len(independent), copies, max(takes(event) - len(independent), 0)


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


def drop_previews(event: Event) -> None:
    """Si algún medio ya publicó el hecho, las notas de anticipo del mismo hecho sobran:
    lo que se cuenta es el dato de inflación, no que hoy el INDEC lo va a difundir."""
    reported = [a for a in event.articles if not is_preview(a.title)]
    if reported:
        event.articles = reported


def drop_junk(event: Event) -> None:
    """Saca del evento las notas de ruido y de servicio.

    Castigarlas con un factor no alcanza cuando se juntan muchas: el horóscopo, la quiniela
    y el calendario de pagos los publican todos los medios el mismo día, se agrupan en un
    solo bloque enorme y el volumen le gana al castigo. Además, una nota dura que cae en ese
    grupo dejaba de ser mayoría de ruido y le levantaba el castigo a todo el bloque.
    """
    event.articles = [a for a in event.articles if not is_junk(a.title)]


def rank(articles: list[Article], vectors: dict[str, list[float]] | None = None) -> list[Event]:
    """Todos los hechos del día, del más al menos importante."""
    events = cluster(articles, vectors)
    for event in events:
        drop_junk(event)
        drop_previews(event)
        event.articles.sort(key=lambda a: a.published)
        if not event.articles:
            continue
        event.title = event.lead.title
        event.score = score(event)
    events = [e for e in events if e.articles]
    events.sort(key=lambda e: (e.score, e.lead.published), reverse=True)
    return events


def relevant(event: Event, min_coverage: int = MIN_COVERAGE) -> bool:
    """Si no lo levantaron varios medios, no es un hecho del día."""
    if penalized(event):
        return False
    return len(event.outlets) >= min_coverage and coverage(event)[0] >= min(
        min_coverage, MIN_TAKES
    )


def same_topic(words: set[str], seen: set[str]) -> bool:
    """Dos hechos son la misma historia contada por partes."""
    shared = len(words & seen)
    return shared >= MIN_SHARED_TOPIC or (
        shared >= 1 and overlap(words, seen) >= SAME_TOPIC_OVERLAP
    )


def select(
    events: list[Event],
    max_events: int,
    world_slots: int = WORLD_SLOTS,
    min_coverage: int = MIN_COVERAGE,
) -> list[Event]:
    """Los mejores `max_events` del ranking global, con el bloque mundo acotado y un
    tema por lugar.

    `max_events` es un techo y no una cuota: lo que no llega al piso de cobertura, o lo que
    queda muy por debajo del hecho más importante del día, no entra aunque sobren lugares.
    Un día flojo devuelve cuatro noticias en vez de completar siete con lo que sigue.

    El cupo internacional también es un techo: si no hay cobertura extranjera relevante,
    esos lugares los ocupan noticias argentinas en vez de quedar vacíos.
    """
    floor = events[0].score * RELATIVE_FLOOR if events else 0.0
    chosen: list[Event] = []
    topics: list[set[str]] = []
    world = 0
    for event in events:
        if len(chosen) >= max_events:
            break
        if not relevant(event, min_coverage) or event.score < floor:
            continue
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


def curate(
    articles: list[Article], max_events: int, min_coverage: int = MIN_COVERAGE
) -> list[Event]:
    return select(rank(articles), max_events, min_coverage=min_coverage)
