from datetime import datetime

from newsbot.config import TIMEZONE
from newsbot.curate import cluster, curate, rank, select
from newsbot.models import Article
from newsbot.text import keywords, similarity

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)


def article(title: str, source: str, scope: str = "ar", url: str | None = None) -> Article:
    return Article(
        title=title,
        url=url or f"https://{source.lower()}.com/{abs(hash(title))}",
        source=source,
        scope=scope,
        published=WHEN,
    )


def test_keywords_ignora_stopwords_y_acentos():
    assert keywords("El Gobierno anunció un acuerdo con el FMI") == {
        "gobierno",
        "anuncio",
        "acuerdo",
        "fmi",
    }


def test_similarity_es_simetrica():
    a, b = keywords("acuerdo con el FMI"), keywords("nuevo acuerdo del FMI")
    assert similarity(a, b) == similarity(b, a) > 0


def test_cluster_agrupa_el_mismo_hecho():
    events = cluster(
        [
            article("El Gobierno anunció un acuerdo con el FMI", "Infobae"),
            article("Acuerdo con el FMI: el Gobierno anunció los detalles", "Clarín"),
            article("Se define el futuro del club de fútbol", "Olé"),
        ]
    )
    assert len(events) == 2
    assert len(events[0].articles) == 2


def test_curate_prioriza_lo_mas_cubierto_y_deja_lugar_al_mundo():
    articles = [
        article("El Gobierno anunció un acuerdo con el FMI", "Infobae"),
        article("Acuerdo con el FMI: el Gobierno anunció los detalles", "Clarín"),
        article("Acuerdo con el FMI según el Gobierno", "Página/12"),
        article("Paro de colectivos en el AMBA", "Ámbito"),
        article("Argentina peso rally draws investors", "Google News · Argentina", scope="world"),
    ]
    events = curate(articles, max_events=4)

    assert "FMI" in events[0].title
    assert events[0].scope == "ar"
    assert any(e.scope == "world" for e in events)


def test_curate_posterga_el_ruido_deportivo():
    articles = [
        article("Boca ganó la Copa Libertadores", "Olé"),
        article("Copa Libertadores: así fue el gol de Boca", "TyC"),
        article("Copa Libertadores, el partido de Boca", "Clarín"),
        article("El INDEC publicó la inflación de agosto", "Ámbito"),
    ]
    events = curate(articles, max_events=4)

    assert "INDEC" in events[0].title


def test_curate_posterga_la_cotizacion_de_rutina():
    articles = [
        article("Dólar hoy: a cuánto cotiza este martes 9 de septiembre", "Ámbito"),
        article("Dólar blue hoy: a cuánto cerró la cotización", "Infobae"),
        article("Dólar hoy, cotización del martes", "Clarín"),
        article("El INDEC publicó la inflación de agosto", "Perfil"),
    ]
    events = curate(articles, max_events=4)

    assert "INDEC" in events[0].title


def test_curate_no_infla_el_score_con_cables_replicados():
    wire = "Debt piles up for young Argentines"
    articles = [article(wire, f"Diario {i}", scope="world") for i in range(6)]
    articles += [
        article("El INDEC publicó la inflación de agosto", "Ámbito", scope="world"),
        article("Inflación de agosto: el dato del INDEC", "Clarín", scope="world"),
        article("La inflación de agosto según el INDEC", "Perfil", scope="world"),
    ]
    events = curate(articles, max_events=4)

    assert "INDEC" in events[0].title


def test_cluster_fusiona_el_mismo_tema_contado_con_otras_palabras():
    events = cluster(
        [
            article("El Gobierno denunciará penalmente a la petrolera Navitas por Malvinas", "LN"),
            article("El Gobierno denuncia penalmente a cinco petroleras que operan en Malvinas",
                    "Infobae"),
            article("El INDEC publicó la inflación de agosto", "Ámbito"),
        ]
    )
    assert len(events) == 2
    assert len(events[0].articles) == 2


def test_curate_posterga_las_notas_de_servicio():
    articles = [
        article("El error al tomar café que puede elevar tu colesterol", "Infobae"),
        article("El error al tomar café: qué dicen los médicos", "Clarín"),
        article("Cuidado con el error al tomar café todas las mañanas", "Perfil"),
        article("El INDEC publicó la inflación de agosto", "Ámbito"),
    ]
    events = curate(articles, max_events=4)

    assert "INDEC" in events[0].title


def test_replicar_un_cable_suma_pero_cada_vez_menos():
    wire = "Debt piles up for young Argentines"
    pocos = curate([article(wire, f"Diario {i}") for i in range(2)], max_events=1)
    muchos = curate([article(wire, f"Diario {i}") for i in range(12)], max_events=1)

    assert muchos[0].score > pocos[0].score
    assert muchos[0].score < pocos[0].score * 3


def test_un_medio_con_muchas_variantes_no_le_gana_a_varias_redacciones():
    """Nueve notas de un mismo diario sobre el mismo tema no son cobertura amplia."""
    uno = [article(f"Milei firmó el decreto de la reforma laboral, capítulo {i}", "Infobae")
           for i in range(9)]
    varias = [article("El INDEC publicó la inflación de agosto", f"Diario {i}") for i in range(4)]
    varias += [article("Inflación de agosto: el dato del INDEC", "Clarín")]

    events = curate(uno + varias, max_events=2)
    assert "INDEC" in events[0].title


LOCALES = [
    "Paro de colectivos en el AMBA por reclamo salarial",
    "El INDEC publicó la inflación de agosto",
    "La Corte Suprema falló sobre las jubilaciones",
    "Temporal en Bahía Blanca: evacuaron familias",
    "Diputados aprobó la reforma del Código Penal",
    "El Banco Central bajó la tasa de referencia",
    "Renunció el ministro de Infraestructura",
]

MUNDIALES = [
    "Argentine bonds rally as investors return",
    "Falklands dispute escalates at the United Nations",
    "Buenos Aires hosts a summit on trade",
    "Argentine wine exports reach a new market",
    "IMF board reviews the Argentine programme",
]


def test_select_nunca_devuelve_mas_de_lo_pedido():
    articles = [article(t, f"Diario {i}") for i, t in enumerate(LOCALES)]
    articles += [article(MUNDIALES[0], "Reuters", scope="world")]
    events = rank(articles)

    for cupo in range(0, 5):
        assert len(select(events, cupo)) <= cupo


def test_select_no_reserva_lugares_para_el_mundo():
    """Sin cobertura internacional, los 7 lugares son para noticias argentinas."""
    articles = [article(t, f"Diario {i}") for i, t in enumerate(LOCALES)]
    assert len(curate(articles, max_events=7)) == 7


def test_select_no_le_da_dos_lugares_al_mismo_tema():
    """La muerte de alguien, las repercusiones y el recuerdo son la misma historia: no
    tienen que ocupar tres de las siete noticias del día."""
    articles = [
        article("Murió Chiche Gelblung a los 82 años", "La Nación"),
        article("Falleció Chiche Gelblung, histórico conductor", "Clarín"),
        article("Reacciones y mensajes de despedida a Chiche Gelblung", "TN"),
        article("El recuerdo de Chiche Gelblung en la televisión", "Perfil"),
        article("Chiche Gelblung y su historia de amor con Cristina Seoane", "Infobae"),
    ]
    articles += [article(t, f"Diario {i}") for i, t in enumerate(LOCALES)]
    titulares = [e.title for e in curate(articles, max_events=7)]

    assert sum("Gelblung" in t for t in titulares) == 1


def test_select_acota_el_bloque_internacional():
    articles = [article(t, f"Outlet {i}", scope="world") for i, t in enumerate(MUNDIALES)]
    articles += [article(t, f"Diario {i}") for i, t in enumerate(LOCALES)]
    events = curate(articles, max_events=6)

    assert sum(1 for e in events if e.scope == "world") == 2


def test_un_cable_extranjero_no_convierte_un_hecho_argentino_en_internacional():
    articles = [
        article("El Gobierno denunció a las petroleras que operan en Malvinas", "Clarín"),
        article("El Gobierno denunció penalmente a las petroleras de Malvinas", "Infobae"),
        article("El Gobierno denuncia a las petroleras que operan en Malvinas", "Reuters",
                scope="world"),
    ]
    events = curate(articles, max_events=3)

    assert len(events) == 1
    assert events[0].scope == "ar"


def test_el_clustering_no_depende_del_orden_de_llegada():
    titles = [
        ("El Gobierno denunciará penalmente a la petrolera Navitas por Malvinas", "LN"),
        ("El Gobierno denuncia penalmente a cinco petroleras que operan en Malvinas", "Infobae"),
        ("El INDEC publicó la inflación de agosto", "Ámbito"),
        ("Inflación de agosto: el dato que publicó el INDEC", "Clarín"),
    ]
    directo = curate([article(t, s) for t, s in titles], max_events=4)
    reves = curate([article(t, s) for t, s in reversed(titles)], max_events=4)

    assert [e.title for e in directo] == [e.title for e in reves]


def test_no_fusiona_dos_anuncios_distintos_del_gobierno():
    events = cluster(
        [
            article("El Gobierno anunció un aumento para los jubilados", "Infobae"),
            article("El Gobierno anunció un aumento en las tarifas de luz y gas", "Clarín"),
        ]
    )
    assert len(events) == 2


def test_agrupa_el_mismo_hecho_contado_en_ingles():
    events = cluster(
        [
            article("El Gobierno argentino cerró un acuerdo con el FMI", "Ámbito"),
            article("Argentine government seals IMF agreement", "Reuters", scope="world"),
        ]
    )
    assert len(events) == 1


def test_no_castiga_una_noticia_judicial_por_hablar_de_la_afa():
    articles = [
        article("La Justicia allanó la AFA por la causa de corrupción", "Clarín"),
        article("Allanamiento en la AFA: la Justicia investiga la corrupción", "Infobae"),
        article("Se define el pase del delantero al Manchester", "Olé"),
    ]
    events = curate(articles, max_events=3)

    assert "AFA" in events[0].title


def test_el_dolar_entra_cuando_el_movimiento_es_fuerte():
    articles = [
        article("El dólar superó los $2.000 y tocó un máximo histórico", "Ámbito"),
        article("El dólar blue superó los $2.000: máximo histórico", "Infobae"),
        article("Se firmó un convenio menor de capacitación docente", "Perfil"),
    ]
    events = curate(articles, max_events=3)

    assert "dólar" in events[0].title


def test_no_castiga_una_nota_politica_con_forma_de_servicio():
    articles = [
        article("Qué significa el fallo de la Corte Suprema para las jubilaciones", "Clarín"),
        article("El fallo de la Corte Suprema sobre las jubilaciones, explicado", "Infobae"),
        article("Se firmó un convenio menor de capacitación docente", "Perfil"),
    ]
    events = curate(articles, max_events=3)

    assert "Corte" in events[0].title


def test_sources_no_repite_variantes_del_mismo_medio():
    events = cluster(
        [
            article("El INDEC publicó la inflación de agosto", "Ámbito"),
            article("El INDEC publicó la inflación de agosto de 2026", "Ambito"),
        ]
    )
    assert events[0].sources == ["Ámbito"]
