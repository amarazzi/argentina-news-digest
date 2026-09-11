"""El juez con el modelo simulado: lo que se prueba es quién entra al digest y que la
corrida no dependa de que el modelo conteste bien."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from newsbot import cli, judge, record
from newsbot.config import LLM
from newsbot.identity import event_id
from newsbot.llm import LLMError
from newsbot.models import Article, Event

WHEN = datetime.now(tz=None).astimezone() - timedelta(days=1)
FAKE_LLM = LLM(provider="gemini", api_key="clave", model="modelo")


def event(title: str, outlets: int = 4) -> Event:
    articles = [
        Article(
            title=f"{title} ({n})",
            url=f"https://medio{n}.com/nota",
            source=f"Medio {n}",
            scope="ar",
            published=WHEN,
            summary="",
        )
        for n in range(outlets)
    ]
    return Event(title=title, articles=articles)


def verdict(event: Event, **campos) -> judge.Verdict:
    base = {
        "id": event_id(event),
        "categoria": "politica",
        "ambito": "nacional",
        "importancia": 8,
        "relacion": "nueva",
        "es_anticipo": False,
        "resumen": "resumen",
        "motivo": "motivo",
    }
    return judge.Verdict(**{**base, **campos})


def picks(*pairs: tuple[Event, dict]) -> list[Event]:
    events = [e for e, _ in pairs]
    verdicts = {event_id(e): verdict(e, **campos) for e, campos in pairs}
    return judge.select(events, verdicts, max_events=7)


def test_el_deporte_entra_solo_si_es_un_hito():
    """No es la sección lo que decide: una final histórica entra y la fecha de la
    Libertadores no, aunque las cubran los mismos medios."""
    final = event("La selección ganó la Copa del Mundo")
    fecha = event("Boca empató con Racing por la Libertadores")

    elegidos = picks(
        (final, {"categoria": "deportes", "importancia": 10}),
        (fecha, {"categoria": "deportes", "importancia": 5}),
    )

    assert elegidos == [final]


def test_lo_internacional_entra_solo_si_es_extraordinario():
    grande = event("Murió el papa")
    mediano = event("Elecciones en Francia")

    elegidos = picks(
        (grande, {"ambito": "internacional", "importancia": 9}),
        (mediano, {"ambito": "internacional", "importancia": 8}),
    )

    assert elegidos == [grande]


def test_un_desarrollo_entra_y_la_repeticion_no():
    """La muerte de quien ayer estaba internado es noticia; las repercusiones de lo mismo
    ya se contaron."""
    nuevo = event("Murió el dirigente internado el lunes")
    viejo = event("Repercusiones por la internación del dirigente")

    elegidos = picks(
        (nuevo, {"relacion": "desarrollo"}),
        (viejo, {"relacion": "repeticion", "importancia": 9}),
    )

    assert elegidos == [nuevo]


def test_el_anticipo_no_entra_aunque_sea_importante():
    """Lo que se quiere es el dato de inflación, no que hoy se anuncia la inflación."""
    anticipo = event("Hoy el INDEC da a conocer la inflación de agosto")

    assert picks((anticipo, {"importancia": 10, "es_anticipo": True})) == []


def test_el_servicio_no_entra():
    assert picks((event("Cuándo cobro la AUH"), {"categoria": "servicio"})) == []


def test_un_hecho_nacional_necesita_cobertura():
    """La importancia la pone el modelo, pero un hecho que publicó un solo medio no entra:
    sin corroboración no hay digest."""
    solo = event("Trascendió un pase de facturas en el Gabinete", outlets=1)

    assert picks((solo, {"importancia": 8})) == []


def test_el_techo_manda():
    eventos = [event(f"Hecho {n}") for n in range(9)]
    verdicts = {event_id(e): verdict(e, importancia=9) for e in eventos}

    assert len(judge.select(eventos, verdicts, max_events=7)) == 7


def test_ordena_por_importancia():
    chico = event("Renunció un secretario")
    grande = event("Renunció el ministro de Economía")

    elegidos = picks((chico, {"importancia": 6}), (grande, {"importancia": 9}))

    assert elegidos == [grande, chico]


def answer(events: list[Event], **campos) -> str:
    return answer_ids([event_id(e) for e in events], **campos)


def answer_ids(ids: list[str], **campos) -> str:
    return json.dumps(
        [
            {
                "id": key,
                "categoria": "politica",
                "ambito": "nacional",
                "importancia": 8,
                "relacion": "nueva",
                "id_enviado": None,
                "es_anticipo": False,
                "resumen": "un resumen",
                "motivo": "un motivo",
                **campos,
            }
            for key in ids
        ]
    )


def test_un_id_que_no_pedi_se_ignora_sin_romper_la_corrida():
    """El modelo se inventa ids: mientras estén todos los que pedí, la corrida sigue."""
    hecho = event("Renunció el ministro")
    inventado = json.loads(answer([hecho]))
    inventado.append({**inventado[0], "id": "inventado"})

    veredictos = judge.parse(json.dumps(inventado), {event_id(hecho)})

    assert set(veredictos) == {event_id(hecho)}


def test_si_se_saltea_un_grupo_la_respuesta_no_sirve():
    hecho = event("Renunció el ministro")
    otro = event("Falló la Corte")

    with pytest.raises(judge.JudgeError):
        judge.parse(answer([hecho]), {event_id(hecho), event_id(otro)})


def test_json_invalido_no_sirve():
    with pytest.raises(judge.JudgeError):
        judge.parse("acá va el análisis: {...", {"x"})


def test_acepta_la_lista_envuelta_en_un_objeto():
    """Los modelos devuelven `{"grupos": [...]}` aunque se les pida una lista."""
    hecho = event("Renunció el ministro")

    veredictos = judge.parse(f'{{"grupos": {answer([hecho])}}}', {event_id(hecho)})

    assert veredictos[event_id(hecho)].importancia == 8


def test_reintenta_una_vez_y_despues_se_rinde(monkeypatch):
    llamadas = []
    monkeypatch.setattr(judge, "complete", lambda *a, **k: llamadas.append(1) or "no es json")

    with pytest.raises(judge.JudgeError):
        judge.judge([event("Hecho")], [], llm=FAKE_LLM)

    assert len(llamadas) == 2


def test_la_segunda_respuesta_vale(monkeypatch):
    hecho = event("Renunció el ministro")
    respuestas = iter(["no es json", answer([hecho])])
    monkeypatch.setattr(judge, "complete", lambda *a, **k: next(respuestas))

    veredictos = judge.judge([hecho], [], llm=FAKE_LLM)

    assert veredictos[event_id(hecho)].categoria == "politica"


@pytest.fixture
def corrida(monkeypatch, tmp_path):
    """El pipeline entero con el juez prendido y el modelo simulado."""
    monkeypatch.setenv("NEWSBOT_STATE", str(tmp_path / "history.json"))
    monkeypatch.setenv("NEWSBOT_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    monkeypatch.setattr(
        cli,
        "collect",
        lambda *a, **k: [
            Article(
                title=title,
                url=f"https://{source.lower()}.com/x",
                source=source,
                scope="ar",
                published=WHEN,
            )
            for title, source in [
                ("El INDEC publicó la inflación de agosto", "D1"),
                ("La inflación de agosto fue de 1,7%, informó el INDEC", "D2"),
                ("Inflación: el INDEC informó un 1,7% en agosto", "D3"),
            ]
        ],
    )
    monkeypatch.setattr(cli, "vectors_for", lambda *a, **k: {})
    monkeypatch.setattr(cli, "compose", lambda digest, settings: "mensaje")
    monkeypatch.setattr(cli, "send_message", lambda *a, **k: [1])
    return tmp_path


def test_sin_bandera_no_se_llama_al_juez(corrida, monkeypatch):
    """El juez está escrito pero no manda: mientras no haya días guardados con qué
    compararlo, elige el curador de siempre."""
    monkeypatch.setattr(
        judge, "complete", lambda *a, **k: pytest.fail("no tendría que llamar al juez")
    )

    assert cli.main(["--save-memory"]) == 0

    guardadas = sorted((corrida / "runs").glob("*.json.gz"))
    assert record.load(guardadas[0])["juez"] is None


def test_con_la_bandera_el_juez_elige_y_queda_registrado(corrida, monkeypatch):
    monkeypatch.setattr(
        judge,
        "complete",
        lambda prompt, **k: answer_ids(
            ids_from(prompt), importancia=9, resumen="la inflación fue 1,7%"
        ),
    )

    assert cli.main(["--judge", "--save-memory"]) == 0

    guardadas = sorted((corrida / "runs").glob("*.json.gz"))
    data = record.load(guardadas[0])
    assert data["juez"]["veredictos"][0]["importancia"] == 9
    # El resumen del juez es lo que ve al día siguiente para saber si algo ya se contó.
    assert "1,7%" in (corrida / "history.json").read_text()


def test_si_el_juez_se_cae_el_digest_sale_igual(corrida, monkeypatch):
    """Lo único inaceptable es no mandar nada: ante cualquier falla elige el curador."""

    def caido(*a, **k):
        raise LLMError("503")

    monkeypatch.setattr(judge, "complete", caido)

    assert cli.main(["--judge", "--save-memory"]) == 0

    guardadas = sorted((corrida / "runs").glob("*.json.gz"))
    data = record.load(guardadas[0])
    assert data["juez"] is None
    assert data["elegidos"]


def test_si_el_juez_devuelve_json_invalido_el_digest_sale_igual(corrida, monkeypatch):
    monkeypatch.setattr(judge, "complete", lambda *a, **k: "no es json")

    assert cli.main(["--judge", "--save-memory"]) == 0

    guardadas = sorted((corrida / "runs").glob("*.json.gz"))
    assert record.load(guardadas[0])["elegidos"]


def ids_from(prompt: str) -> list[str]:
    """Los ids que el prompt le pasó al juez, para contestarle a todos."""
    return [line.split("id: ")[1].split(" ")[0] for line in prompt.splitlines() if "- id: " in line]
