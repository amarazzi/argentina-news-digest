from datetime import datetime

from newsbot.config import TIMEZONE
from newsbot.curate import cluster, curate
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


def test_curate_prioriza_lo_mas_cubierto_y_reserva_lugar_al_mundo():
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


def test_sources_no_repite_variantes_del_mismo_medio():
    events = cluster(
        [
            article("El INDEC publicó la inflación de agosto", "Ámbito"),
            article("El INDEC publicó la inflación de agosto de 2026", "Ambito"),
        ]
    )
    assert events[0].sources == ["Ámbito"]
