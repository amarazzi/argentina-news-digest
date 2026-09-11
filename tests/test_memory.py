from datetime import date, datetime

from newsbot.config import TIMEZONE
from newsbot.curate import cluster
from newsbot.memory import Memory, drop_repeats
from newsbot.models import Article

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)
HOY = date(2026, 9, 8)


def events(*titles: str):
    articles = [
        Article(title=t, url=f"https://d{i}.com/x", source=f"D{i}", scope="ar", published=WHEN)
        for i, t in enumerate(titles)
    ]
    return cluster(articles)


def test_no_repite_el_hecho_al_dia_siguiente(tmp_path):
    path = tmp_path / "history.json"
    ayer = events("El Gobierno denunciará penalmente a la petrolera Navitas por Malvinas")

    memory = Memory.load(path)
    memory.remember(ayer, date(2026, 9, 7))
    memory.save(date(2026, 9, 7))

    hoy = events(
        "El Gobierno denunció penalmente a las petroleras que operan en Malvinas",
        "El INDEC publicó la inflación de agosto",
    )
    quedan = drop_repeats(hoy, Memory.load(path), HOY)

    assert [e.title for e in quedan] == ["El INDEC publicó la inflación de agosto"]


def test_un_hecho_nuevo_no_se_bloquea_por_vocabulario_generico(tmp_path):
    """Compartir "Gobierno" y "anunció" con algo de la semana pasada no lo hace repetido."""
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("El Gobierno anunció un aumento para los jubilados"), date(2026, 9, 7)
    )
    memory.save(date(2026, 9, 7))

    hoy = events("El Gobierno anunció un aumento en las tarifas de luz y gas")
    assert drop_repeats(hoy, Memory.load(path), HOY) == hoy


def test_el_seguimiento_refresca_el_recuerdo(tmp_path):
    """Si el hecho sigue dando notas, el recuerdo se actualiza con las palabras de hoy y
    con la fecha de hoy: si no, la misma historia vuelve a entrar en tres días."""
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("El Gobierno denunció a las petroleras que operan en Malvinas"),
        date(2026, 9, 7),
    )
    memory.save(date(2026, 9, 7))

    memory = Memory.load(path)
    hoy = events("El Gobierno denunció penalmente a las petroleras de Malvinas")
    assert drop_repeats(hoy, memory, HOY) == []
    assert memory.entries[0][0] == HOY.isoformat()


def test_la_continuacion_de_una_historia_no_vuelve_a_entrar(tmp_path):
    """El E2E mostró "internaron a Gelblung" un día y "murió Gelblung" al otro: el titular
    cambia casi todas las palabras y el Jaccard solo no lo detecta."""
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("Internaron a Chiche Gelblung en terapia intensiva en el sanatorio"),
        date(2026, 9, 7),
    )
    memory.save(date(2026, 9, 7))

    hoy = events("Murió Chiche Gelblung a los 82 años tras estar internado")
    assert drop_repeats(hoy, Memory.load(path), HOY) == []


def test_dos_hechos_distintos_con_un_protagonista_en_comun_pasan(tmp_path):
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("Milei encabezó el acto de cierre de campaña en Córdoba con Bullrich"),
        date(2026, 9, 7),
    )
    memory.save(date(2026, 9, 7))

    hoy = events("Milei vetó la ley de financiamiento universitario aprobada por el Senado")
    assert drop_repeats(hoy, Memory.load(path), HOY) == hoy


def test_el_historial_vencido_se_descarta(tmp_path):
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(events("El Gobierno denunció a las petroleras de Malvinas"), date(2026, 8, 1))
    memory.save(date(2026, 9, 7))

    assert Memory.load(path).entries == []


def test_la_retencion_dura_exactamente_una_semana(tmp_path):
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(events("El Gobierno denunció a las petroleras de Malvinas"), date(2026, 9, 1))
    memory.save(date(2026, 9, 8))

    assert Memory.load(path).entries == []


def test_un_historial_corrupto_no_rompe_la_corrida(tmp_path, caplog):
    path = tmp_path / "history.json"
    path.write_text("{roto")

    assert Memory.load(path).entries == []
    assert "no pude leer el historial" in caplog.text


def test_sin_historial_no_filtra_nada(tmp_path):
    hoy = events("El INDEC publicó la inflación de agosto")
    assert drop_repeats(hoy, Memory.load(tmp_path / "vacio.json"), HOY) == hoy
