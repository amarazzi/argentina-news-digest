from datetime import datetime

from newsbot.config import TIMEZONE, Settings
from newsbot.models import Article, Digest, Event
from newsbot.telegram import split_message
from newsbot.write import compose, fallback_message

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)

SETTINGS = Settings(
    telegram_token=None,
    telegram_chat_id=None,
    openai_api_key=None,
    openai_model="gpt-4o-mini",
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


def test_split_message_corta_en_saltos_de_linea():
    chunks = split_message("a" * 30 + "\n" + "b" * 30, limit=40)
    assert chunks == ["a" * 30, "b" * 30]


def test_split_message_no_cuenta_los_href_ocultos():
    """Los links de Google News son enormes pero Telegram mide el texto renderizado."""
    line = f'<a href="https://news.google.com/rss/articles/{"Z" * 300}">Titular</a>'
    assert split_message("\n".join([line] * 3), limit=40) == ["\n".join([line] * 3)]
