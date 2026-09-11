"""Casos adversariales del curador — fase 1.

Salen de la revisión adversarial del 11/09/2026. Los tests marcados "falla hoy" documentan
errores reales del curador y se tienen que poner en verde con los arreglos de la fase 1.
Los marcados "guarda" pasan hoy y tienen que seguir pasando: evitan que un arreglo abra
el agujero contrario.

Los nombres de personas son ficticios salvo cuando el caso depende de un nombre compuesto
real (Corte Suprema, Banco Central, Cristina Kirchner).
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from newsbot.collect import search_slices
from newsbot.config import TIMEZONE, Window
from newsbot.curate import (
    HARD_NEWS,
    SURGE,
    coverage,
    is_junk,
    is_preview,
    relevant,
    same_topic,
    topic,
)
from newsbot.memory import Memory
from newsbot.models import Article, Event

WHEN = datetime(2026, 9, 10, 10, 0, tzinfo=TIMEZONE)
AYER = date(2026, 9, 9)


def article(title: str, source: str, minute: int = 0, **extra) -> Article:
    return Article(
        title=title,
        url=extra.pop("url", f"https://{source.lower().replace(' ', '')}.com/{abs(hash(title))}"),
        source=source,
        scope="ar",
        published=WHEN + timedelta(minutes=minute),
        **extra,
    )


def event(*pairs: tuple[str, str]) -> Event:
    """Un evento con una nota por par (titular, medio), publicadas en ese orden."""
    articles = [article(title, source, minute) for minute, (title, source) in enumerate(pairs)]
    return Event(title=articles[0].title, articles=articles)


# --- Filtros ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern, text",
    [
        (HARD_NEWS, "imputado"),
        (HARD_NEWS, "procesada"),
        (HARD_NEWS, "detenidos"),
        (HARD_NEWS, "jubilados"),
        (SURGE, "se desplomaron"),
        (SURGE, "se derrumbo"),
    ],
    ids=["imputado", "procesada", "detenidos", "jubilados", "desplomaron", "derrumbo"],
)
def test_las_raices_truncadas_matchean_la_palabra_completa(pattern, text):
    """Falla hoy: `\\b(imputad|...)\\b` exige que la palabra termine en la raíz."""
    assert pattern.search(text)


@pytest.mark.parametrize(
    "title",
    [
        "El Gobierno canjeó bonos por US$ 10.000 millones para despejar vencimientos",
        "El riesgo país perforó los 500 puntos tras el acuerdo con el FMI",
        "Tenso clima en el Congreso antes de la votación del Presupuesto",
        "El pronóstico del FMI para la economía argentina: recesión en 2027",
        "Adiós a Ernesto Valdivieso: murió a los 91 años el creador de la historieta",
        "Los gremios anticipan un paro general de 36 horas",
        "Las acciones de YPF se desplomaron 9% en Wall Street",
        "Messi, imputado por evasión en España",
    ],
)
def test_los_filtros_no_tiran_noticias_duras(title):
    """Falla hoy: cada titular cae en ruido, rutina, servicio o anticipo."""
    assert not is_junk(title)
    assert not is_preview(title)


@pytest.mark.parametrize(
    "title",
    [
        "A cuánto cotiza el dólar blue hoy, jueves 10 de septiembre",
        "Cuándo cobro la AUH de ANSES en septiembre",
        "Horóscopo de hoy para todos los signos",
        "Resultados de la Quiniela Nacional del jueves",
        "El error al tomar café que casi todos cometen",
        "Pronóstico del tiempo para el fin de semana en Buenos Aires",
    ],
)
def test_los_filtros_siguen_sacando_el_servicio(title):
    """Guarda: arreglar los falsos positivos no puede dejar pasar el servicio real."""
    assert is_junk(title)


# --- Conteo de medios -------------------------------------------------------------------


def test_el_mismo_medio_con_dos_nombres_es_un_solo_medio():
    """Falla hoy: el medio se identifica por el nombre en texto. Google News trae la URL
    del medio en <source url="...">; con eso el medio se identifica por dominio."""
    e = Event(
        title="Renunció el jefe de Gabinete",
        articles=[
            article("Renunció el jefe de Gabinete", "TN", url="https://tn.com.ar/politica/x"),
            article(
                "Renunció el jefe de Gabinete",
                "TN - Todo Noticias",
                url="https://news.google.com/rss/articles/abc",
                source_url="https://tn.com.ar",
            ),
            article("Se fue el jefe de Gabinete: los motivos", "Clarín"),
        ],
    )
    assert len(e.outlets) == 2
    assert not relevant(e)


def test_un_cable_republicado_no_cuenta_como_redacciones_independientes():
    """Falla hoy: una agencia saca tres versiones y dos diarios copian una. Eso es una
    redacción, no tres: `min(titulares, medios)` no mide quién escribió."""
    e = event(
        ("Detuvieron al intendente de Quilmes por lavado", "Agencia NA"),
        ("El intendente de Quilmes quedó detenido por lavado de dinero", "Agencia NA"),
        ("Lavado: el intendente de Quilmes, detenido", "Agencia NA"),
        ("Detuvieron al intendente de Quilmes por lavado", "Diario Popular"),
        ("Detuvieron al intendente de Quilmes por lavado", "El Día"),
    )
    independent, copies, _ = coverage(e)
    assert independent == 1
    assert copies == 2
    assert not relevant(e)


def test_tres_redacciones_reales_siguen_contando_como_tres():
    """Guarda."""
    e = event(
        ("Detuvieron al intendente de Quilmes por lavado", "Clarín"),
        ("El intendente de Quilmes quedó detenido por lavado de dinero", "La Nación"),
        ("Lavado: el intendente de Quilmes, detenido", "Infobae"),
    )
    assert coverage(e)[0] == 3
    assert relevant(e)


# --- Tema -------------------------------------------------------------------------------


def test_el_tema_es_lo_que_comparte_al_menos_la_mitad_de_los_titulares():
    """Falla hoy: con 3 notas `len // 2` da 1 y el tema es la unión de todo."""
    e = event(
        ("Caputo anunció una baja de retenciones a la soja", "Clarín"),
        ("Caputo baja las retenciones a la soja y el trigo", "La Nación"),
        ("Retenciones: Caputo confirmó la baja para la soja", "Infobae"),
    )
    assert "trigo" not in topic(e)
    assert {"caputo", "retenc", "soja"} <= topic(e)


@pytest.mark.parametrize(
    "a, b",
    [
        (
            [
                ("La Corte Suprema declaró inconstitucional la ley de glaciares", "Clarín"),
                ("Glaciares: la Corte Suprema anuló la ley", "Infobae"),
                ("Fallo de la Corte Suprema contra la ley de glaciares", "La Nación"),
            ],
            [
                ("La Corte Suprema confirmó la condena por la tragedia de Once", "Clarín"),
                ("Once: la Corte Suprema dejó firme la condena", "Infobae"),
                ("Tragedia de Once: la Corte Suprema confirmó la condena", "La Nación"),
            ],
        ),
        (
            [
                ("El Banco Central levantó el cepo para empresas", "Clarín"),
                ("Fin del cepo para empresas: la decisión del Banco Central", "Ámbito"),
                ("El Banco Central liberó el cepo a las empresas", "Infobae"),
            ],
            [
                ("El Banco Central compró reservas por quinto día seguido", "Clarín"),
                ("Reservas: el Banco Central sumó compras por quinta rueda", "Ámbito"),
                ("El Banco Central sigue comprando reservas", "Infobae"),
            ],
        ),
        (
            [
                ("Cristina Kirchner presentó un libro en Avellaneda", "Clarín"),
                ("Cristina Kirchner reapareció en la presentación de su libro", "Página 12"),
                ("Libro de Cristina Kirchner: el acto en Avellaneda", "La Nación"),
            ],
            [
                ("La Justicia rechazó el pedido de Cristina Kirchner por su pensión", "Clarín"),
                ("Pensión: revés judicial para Cristina Kirchner", "Infobae"),
                ("Cristina Kirchner pierde la pelea por su pensión", "Perfil"),
            ],
        ),
    ],
    ids=["corte-suprema", "banco-central", "cristina-kirchner"],
)
def test_un_nombre_compuesto_no_alcanza_para_ser_el_mismo_tema(a, b):
    """Falla hoy: "Corte Suprema" aporta dos raíces y cumple MIN_SHARED_TOPIC solo."""
    assert not same_topic(topic(event(*a)), topic(event(*b)))


def test_la_misma_historia_contada_por_partes_sigue_siendo_el_mismo_tema():
    """Guarda: la muerte y las repercusiones del mismo día ocupan un solo lugar."""
    muerte = event(
        ("Murió Ernesto Valdivieso, el creador de la historieta", "Clarín"),
        ("Murió Ernesto Valdivieso a los 91 años", "Infobae"),
        ("Ernesto Valdivieso murió en su casa de Olivos", "La Nación"),
    )
    repercusiones = event(
        ("Repercusiones por la muerte de Ernesto Valdivieso", "Clarín"),
        ("El mundo de la cultura despide a Ernesto Valdivieso", "Página 12"),
        ("Así despidieron a Ernesto Valdivieso en las redes", "TN"),
    )
    assert same_topic(topic(muerte), topic(repercusiones))


# --- Recolección ------------------------------------------------------------------------


def test_no_se_piden_tramos_que_caen_enteros_despues_de_la_ventana():
    """Falla hoy: `when:Nh` es "últimas N horas". A las 06:13, `when:6h` cubre sólo la
    madrugada de hoy y todo lo que trae se descarta."""
    window = Window.day(date(2026, 9, 10))
    now = datetime(2026, 9, 11, 6, 13, tzinfo=TIMEZONE)
    since_end = (now - window.end).total_seconds() / 3600
    assert all(hours > since_end for hours in search_slices(window, now=now))


# --- Memoria ----------------------------------------------------------------------------


def _sent(path: Path, *pairs: tuple[str, str]) -> Memory:
    memory = Memory.load(path)
    memory.remember([event(*pairs)], AYER)
    memory.save(AYER)
    return Memory.load(path)


def test_un_desarrollo_de_una_historia_enviada_vuelve_a_entrar(tmp_path):
    """Falla hoy (y reemplaza a test_la_continuacion_de_una_historia_no_vuelve_a_entrar):
    decisión editorial del 11/09. Si ayer entró la internación, hoy la muerte es noticia
    nueva sobre la misma historia y tiene que entrar."""
    memory = _sent(
        tmp_path / "history.json",
        ("Internaron a Ernesto Valdivieso en terapia intensiva", "Clarín"),
        ("Ernesto Valdivieso, internado en terapia intensiva", "Infobae"),
        ("Preocupación por la salud de Ernesto Valdivieso", "La Nación"),
    )
    hoy = event(
        ("Murió Ernesto Valdivieso a los 91 años", "Clarín"),
        ("Murió Ernesto Valdivieso tras una semana internado", "Infobae"),
        ("Ernesto Valdivieso murió en el sanatorio", "La Nación"),
    )
    assert not memory.is_repeat(hoy)


def test_la_repercusion_de_una_historia_enviada_no_vuelve_a_entrar(tmp_path):
    """Guarda: seguir hablando de la internación no es un hecho nuevo."""
    memory = _sent(
        tmp_path / "history.json",
        ("Internaron a Ernesto Valdivieso en terapia intensiva", "Clarín"),
        ("Ernesto Valdivieso, internado en terapia intensiva", "Infobae"),
        ("Preocupación por la salud de Ernesto Valdivieso", "La Nación"),
    )
    hoy = event(
        ("Cómo sigue la salud de Ernesto Valdivieso", "Clarín"),
        ("Ernesto Valdivieso sigue en terapia intensiva", "Infobae"),
        ("El parte médico de Ernesto Valdivieso", "TN"),
    )
    assert memory.is_repeat(hoy)


def test_otro_fallo_de_la_corte_en_la_semana_no_es_repetido(tmp_path):
    """Falla hoy: la memoria usa la misma regla de tema y bloquea siete días cualquier
    noticia que nombre a la Corte Suprema."""
    memory = _sent(
        tmp_path / "history.json",
        ("La Corte Suprema declaró inconstitucional la ley de glaciares", "Clarín"),
        ("Glaciares: la Corte Suprema anuló la ley", "Infobae"),
        ("Fallo de la Corte Suprema contra la ley de glaciares", "La Nación"),
    )
    hoy = event(
        ("La Corte Suprema confirmó la condena por la tragedia de Once", "Clarín"),
        ("Once: la Corte Suprema dejó firme la condena", "Infobae"),
        ("Tragedia de Once: la Corte Suprema confirmó la condena", "La Nación"),
    )
    assert not memory.is_repeat(hoy)
