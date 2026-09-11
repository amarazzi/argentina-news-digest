from datetime import datetime

from newsbot.config import TIMEZONE
from newsbot.models import Article, Event
from newsbot.verify import digits, fold, names, source_text, unsupported

WHEN = datetime(2026, 9, 10, 10, 0, tzinfo=TIMEZONE)


def article(title: str, summary: str = "") -> Article:
    return Article(
        title=title,
        url=f"https://medio.com/{abs(hash(title))}",
        source="Medio",
        scope="ar",
        published=WHEN,
        summary=summary,
    )


def event(*articles: Article) -> Event:
    return Event(title=articles[0].title, articles=list(articles))


def fuente(*articles: Article) -> str:
    return source_text(event(*articles), 4)


def test_la_misma_cifra_escrita_distinto_es_la_misma():
    assert digits("1,7%") == digits("1.7 %")


def test_fold_saca_tildes_y_mayusculas():
    assert fold("MILEI") == fold("Milei") == "milei"


def test_los_nombres_se_agrupan_por_aparicion():
    assert names("El presidente Javier Milei viajó a Londres") == [
        ["javier", "milei"],
        ["londres"],
    ]


def test_una_cifra_que_no_esta_en_los_titulares_se_marca():
    fuentes = fuente(article("El INDEC difundió la inflación de agosto", "Fue del 1,7%"))
    figures, invented = unsupported("<b>1. Inflación</b> La inflación de agosto fue 2,4%.", fuentes)
    assert figures == ["24"]
    assert invented == []


def test_la_cifra_que_esta_en_el_copete_pasa():
    fuentes = fuente(article("El INDEC difundió la inflación de agosto", "Fue del 1,7%"))
    figures, _ = unsupported("<b>3. Inflación</b> La inflación de agosto fue del 1,7%.", fuentes)
    assert figures == []


def test_el_numero_del_bloque_no_cuenta_como_dato():
    fuentes = fuente(article("Murió Chiche Gelblung"))
    figures, _ = unsupported("<b>5. Murió Gelblung</b> Murió el periodista.", fuentes)
    assert figures == []


def test_un_nombre_inventado_se_marca():
    fuentes = fuente(article("La Corte Suprema falló contra las tasas municipales"))
    _, invented = unsupported(
        "<b>1. Fallo</b> La Corte Suprema, con el voto de Ricardo Lorenzetti, falló.", fuentes
    )
    assert invented == ["ricardo lorenzetti"]


def test_completar_el_nombre_de_pila_no_es_inventar():
    fuentes = fuente(article("Milei suspendió su viaje a Londres"))
    _, invented = unsupported("<b>1. Viaje</b> Javier Milei suspendió el viaje.", fuentes)
    assert invented == []


def test_el_texto_fiel_no_marca_nada():
    fuentes = fuente(
        article("Estados Unidos aprobó la venta de 4 helicópteros Black Hawk"),
        article("La operación asciende a 140 millones de dólares"),
    )
    assert unsupported(
        "<b>2. Helicópteros</b> Estados Unidos aprobó la venta de 4 helicópteros "
        "Black Hawk por 140 millones de dólares.",
        fuentes,
    ) == ([], [])


def test_los_acentos_y_las_mayusculas_no_alcanzan_para_marcar():
    fuentes = fuente(article("EL INDEC DIFUNDIO EL IPC", "Lo informó el organismo"))
    _, invented = unsupported("<b>1. Inflación</b> El Indec difundió el índice.", fuentes)
    assert invented == []


def test_solo_mira_las_notas_que_vio_el_modelo():
    largo = event(*[article(f"Titular {i}", "") for i in range(6)])
    assert "Titular 5" not in source_text(largo, 4)


def test_la_mayuscula_de_arranque_de_oracion_no_es_un_nombre():
    """En una corrida real 'Balacera' y 'Podés' se marcaban como nombres inventados."""
    fuentes = fuente(
        article("Seis delincuentes balearon a un comisario retirado en El Palomar"),
    )
    _, invented = unsupported(
        "<b>6. Balacera en El Palomar</b>\nBalacera frente a una escuela. "
        "Podés ver el video del ataque al comisario retirado.",
        fuentes,
    )

    assert invented == []


def test_el_titular_del_bloque_no_encadena_con_el_texto():
    """El titular va en <b> y sin punto final: sin el corte, la primera palabra del
    párrafo parecía estar en medio de una oración."""
    fuentes = fuente(article("Acuerdo con el FMI"))
    _, invented = unsupported("<b>1. Acuerdo</b>\nHubo acuerdo con el FMI.", fuentes)

    assert invented == []
