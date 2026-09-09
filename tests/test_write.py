from dataclasses import replace
from datetime import datetime

from newsbot.config import LLM, TIMEZONE, Settings
from newsbot.models import Article, Digest, Event
from newsbot.telegram import split_message, visible_length
from newsbot.write import compose, fallback_message, sanitize

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)

SETTINGS = Settings(
    telegram_token=None,
    telegram_chat_id=None,
    llm=None,
    max_events=7,
    request_timeout=20,
)


def digest() -> Digest:
    local = Event(
        title="Acuerdo con el FMI",
        articles=[
            Article("Acuerdo con el FMI", "https://infobae.com/a", "Infobae", "ar", WHEN),
            Article("El FMI y el Gobierno", "https://clarin.com/b", "Clarín", "ar", WHEN),
        ],
    )
    world = Event(
        title="Argentine peso rallies",
        articles=[
            Article(
                "Argentine peso <rallies>",
                "https://ft.com/c?x=1",
                "Google News · Argentina",
                "world",
                WHEN,
            )
        ],
    )
    return Digest(period="08/09/2026", events=[local, world])


def test_fallback_escapa_html_y_separa_la_seccion_internacional():
    message = fallback_message(digest())

    assert "Argentina en el mundo" in message
    assert "Argentine peso &lt;rallies&gt;" in message
    assert "Infobae, Clarín" in message


def test_fallback_elige_el_copete_que_mas_agrega_al_titular():
    event = Event(
        title="Acuerdo con el FMI",
        articles=[
            Article(
                "Acuerdo con el FMI",
                "https://infobae.com/a",
                "Infobae",
                "ar",
                WHEN,
                summary="Acuerdo con el FMI  Infobae",
            ),
            Article(
                "El FMI y el Gobierno",
                "https://clarin.com/b",
                "Clarín",
                "ar",
                WHEN,
                summary="El board aprobó el desembolso.",
            ),
        ],
    )
    message = fallback_message(Digest(period="08/09/2026", events=[event]))

    assert "El board aprobó el desembolso." in message
    assert message.count("Acuerdo con el FMI") == 1


def test_compose_sin_clave_de_llm_usa_el_fallback():
    assert compose(digest(), SETTINGS) == fallback_message(digest())


def test_compose_sin_eventos_avisa():
    message = compose(Digest(period="08/09/2026", events=[]), SETTINGS)
    assert "No encontré noticias" in message


def test_sanitize_deja_solo_html_de_telegram():
    sucio = (
        "```html\n<h3>Título</h3>\n<b>1. Nota</b><br>"
        'Ver <a href="https://medio.com/x" target="_blank">acá</a> por Tim & Cía.\n```'
    )
    limpio = sanitize(sucio)

    assert "<h3>" not in limpio and "<br>" not in limpio and "```" not in limpio
    assert '<a href="https://medio.com/x">acá</a>' in limpio
    assert "Tim &amp; C" in limpio


def test_sanitize_cierra_las_etiquetas_que_el_modelo_deja_abiertas():
    assert sanitize("<b>Título sin cerrar") == "<b>Título sin cerrar</b>"


def test_compose_cae_al_fallback_si_el_modelo_devuelve_vacio(monkeypatch):
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: "   ")

    assert compose(digest(), settings) == fallback_message(digest())


def test_compose_cae_al_fallback_si_el_modelo_no_incluye_los_links(monkeypatch):
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: "<b>1. Algo</b>\nPasó algo.")

    assert compose(digest(), settings) == fallback_message(digest())


def test_split_message_corta_en_saltos_de_linea():
    chunks = split_message("a" * 30 + "\n" + "b" * 30, limit=40)
    assert chunks == ["a" * 30, "b" * 30]


def test_split_message_no_cuenta_los_href_ocultos():
    """Los links de Google News son enormes pero Telegram mide el texto renderizado."""
    line = f'<a href="https://news.google.com/rss/articles/{"Z" * 300}">Titular</a>'
    assert split_message("\n".join([line] * 3), limit=40) == ["\n".join([line] * 3)]


def test_split_message_parte_una_linea_mas_larga_que_el_limite():
    """Un párrafo del modelo puede pasar los 4096 sin un solo salto de línea."""
    chunks = split_message(" ".join(["palabra"] * 200), limit=100)

    assert len(chunks) > 1
    assert all(visible_length(c) <= 100 for c in chunks)


def test_split_message_no_corta_una_etiqueta_por_la_mitad():
    parrafo = "<b>" + " ".join(["palabra"] * 60) + "</b>"
    chunks = split_message(parrafo, limit=120)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.count("<b>") == chunk.count("</b>")
        assert visible_length(chunk) <= 120
