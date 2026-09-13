from datetime import date, datetime

from newsbot.config import TIMEZONE
from newsbot.curate import cluster
from newsbot.memory import STALE_FACTOR, Memory, penalize_repeats
from newsbot.models import Article

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)
HOY = date(2026, 9, 8)


def events(*titles: str, score: float = 10.0):
    articles = [
        Article(title=t, url=f"https://d{i}.com/x", source=f"D{i}", scope="ar", published=WHEN)
        for i, t in enumerate(titles)
    ]
    found = cluster(articles)
    for event in found:
        event.score = score
    return found


def test_no_repite_el_hecho_al_dia_siguiente(tmp_path):
    """Un hecho ya contado sigue en la lista, pero con el puntaje castigado."""
    path = tmp_path / "history.json"
    ayer = events("El Gobierno denunciará penalmente a la petrolera Navitas por Malvinas")

    memory = Memory.load(path)
    memory.remember(ayer, date(2026, 9, 7))
    memory.save(date(2026, 9, 7))

    hoy = events(
        "El Gobierno denunció penalmente a las petroleras que operan en Malvinas",
        "El INDEC publicó la inflación de agosto",
    )
    quedan = penalize_repeats(hoy, Memory.load(path), HOY)

    by_title = {e.title: e.score for e in quedan}
    assert set(by_title) == {
        "El Gobierno denunció penalmente a las petroleras que operan en Malvinas",
        "El INDEC publicó la inflación de agosto",
    }
    assert by_title["El Gobierno denunció penalmente a las petroleras que operan en Malvinas"] == (
        10.0 * STALE_FACTOR
    )
    assert by_title["El INDEC publicó la inflación de agosto"] == 10.0


def test_un_hecho_nuevo_no_se_bloquea_por_vocabulario_generico(tmp_path):
    """Compartir "Gobierno" y "anunció" con algo de la semana pasada no lo hace repetido."""
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("El Gobierno anunció un aumento para los jubilados"), date(2026, 9, 7)
    )
    memory.save(date(2026, 9, 7))

    hoy = events("El Gobierno anunció un aumento en las tarifas de luz y gas")
    quedan = penalize_repeats(hoy, Memory.load(path), HOY)
    assert quedan[0].score == 10.0


def test_el_seguimiento_castiga_el_puntaje_y_refresca_el_recuerdo(tmp_path):
    """Si el hecho ya se contó sin novedad, el puntaje se castiga y el recuerdo se
    actualiza con las palabras y la fecha de hoy: si no, la misma historia vuelve a
    entrar sin castigo en tres días."""
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("El Gobierno denunció a las petroleras que operan en Malvinas"),
        date(2026, 9, 7),
    )
    memory.save(date(2026, 9, 7))

    memory = Memory.load(path)
    hoy = events("El Gobierno denunció penalmente a las petroleras de Malvinas")
    quedan = penalize_repeats(hoy, memory, HOY)
    assert quedan[0].score == 10.0 * STALE_FACTOR
    assert memory.entries[0].day == HOY.isoformat()


def test_dos_hechos_distintos_con_un_protagonista_en_comun_pasan(tmp_path):
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("Milei encabezó el acto de cierre de campaña en Córdoba con Bullrich"),
        date(2026, 9, 7),
    )
    memory.save(date(2026, 9, 7))

    hoy = events("Milei vetó la ley de financiamiento universitario aprobada por el Senado")
    quedan = penalize_repeats(hoy, Memory.load(path), HOY)
    assert quedan[0].score == 10.0


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
    quedan = penalize_repeats(hoy, Memory.load(tmp_path / "vacio.json"), HOY)
    assert quedan[0].score == 10.0


def test_un_repetido_que_sobrevive_no_duplica_la_entrada(tmp_path):
    """Si un hecho castigado igual entra al digest final, `remember()` no le agrega una
    segunda entrada al historial — ya se refrescó al puntuarlo."""
    path = tmp_path / "history.json"
    memory = Memory.load(path)
    memory.remember(
        events("El Gobierno denunció a las petroleras que operan en Malvinas"), date(2026, 9, 7)
    )
    memory.save(date(2026, 9, 7))

    memory = Memory.load(path)
    hoy = events("El Gobierno denunció penalmente a las petroleras de Malvinas")
    sobrevive = penalize_repeats(hoy, memory, HOY)

    memory.remember(sobrevive, HOY)
    assert len(memory.entries) == 1
    assert memory.entries[0].day == HOY.isoformat()
