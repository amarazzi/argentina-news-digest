"""Calibración del agrupamiento por significado, con notas reales y vectores grabados."""

import math

import pytest

from newsbot.curate import cluster
from newsbot.embed import key_of, text_of
from newsbot.group import agglomerate
from tests.casos import cargar

CASOS, VECTORES = cargar()


def grupos(nombre: str, vectors=VECTORES) -> list[set[str]]:
    return [{a.title for a in event.articles} for event in cluster(CASOS[nombre], vectors)]


def test_las_ocho_coberturas_del_viaje_suspendido_son_un_solo_hecho():
    """Ocho medios contaron que Milei suspendió el viaje a Londres y ninguno lo tituló
    igual; por palabras del titular quedaban en cuatro hechos distintos."""
    notas = CASOS["viaje_suspendido"]
    assert len(grupos("viaje_suspendido")) == 1
    assert len(cluster(notas)) > 1


def test_dos_fallos_distintos_de_la_corte_el_mismo_dia_son_dos_hechos():
    assert len(grupos("fallos_corte")) == 2


def test_tres_coberturas_del_mismo_fallo_son_un_hecho():
    assert len(grupos("tasas_municipales")) == 1


def test_dos_anuncios_del_mismo_ministro_son_dos_hechos():
    assert len(grupos("caputo")) == 2


def test_la_muerte_y_su_repercusion_ocupan_un_solo_lugar():
    """"Murió Victoria Fraga" y "murió una famosa actriz a los 73 años" no comparten
    ninguna palabra propia y son la misma noticia."""
    assert len(grupos("muerte_actriz")) == 1


def test_tres_noticias_del_mismo_tema_no_se_funden():
    """Malvinas fue el tema del día con tres hechos distintos: el sistema de control en
    Cancillería, la carta de 1833 y los dichos del diputado chileno."""
    assert len(grupos("malvinas_distintos")) == 3


def test_sin_vectores_agrupa_por_palabras():
    """Sin `GEMINI_API_KEY` no hay vectores y el curador sigue agrupando como antes."""
    assert len(cluster(CASOS["viaje_suspendido"], {})) == len(cluster(CASOS["viaje_suspendido"]))


def test_las_notas_sin_vector_se_agrupan_por_palabras():
    """El presupuesto de vectores no alcanza para todas: las que quedan afuera se agrupan
    por palabras en vez de perderse."""
    notas = CASOS["tasas_municipales"]
    sin_una = {k: v for k, v in VECTORES.items() if k != key_of(text_of(notas[-1]))}
    events = cluster(notas, sin_una)
    assert sum(len(e.articles) for e in events) == len(notas)


def test_el_enlace_promedio_no_encadena_grupos_por_un_solo_par():
    """Con enlace simple, A pegado a B y B pegado a C hacen un solo grupo aunque A y C no
    se parezcan: así se arman los bloques que juntan media agenda del día."""
    angles = [0.0, math.radians(25.8), math.radians(54.2)]
    vectors = [[math.cos(angle), math.sin(angle)] for angle in angles]
    # B se parece a A (0,90) y a C (0,88), pero el promedio de C contra el grupo A-B
    # —que incluye A y C, que dan 0,59— no llega al umbral.
    assert agglomerate(vectors, threshold=0.85) == [[0, 1], [2]]


def test_una_sola_nota_es_un_grupo():
    assert agglomerate([[1.0, 0.0]]) == [[0]]


@pytest.mark.parametrize("nombre", sorted(CASOS))
def test_los_vectores_grabados_corresponden_a_las_notas(nombre):
    for article in CASOS[nombre]:
        assert key_of(text_of(article)) in VECTORES
