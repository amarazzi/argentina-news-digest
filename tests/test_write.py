from dataclasses import replace
from datetime import datetime

from newsbot.config import LLM, TIMEZONE, Settings
from newsbot.models import Article, Digest, Event
from newsbot.telegram import split_message, visible_length
from newsbot.write import (
    PROMPT,
    compose,
    fallback_message,
    render_events_for_prompt,
    renumber,
    sanitize,
)

WHEN = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)

SETTINGS = Settings(
    telegram_token=None,
    telegram_chat_id=None,
    llm=None,
    embeddings_key=None,
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
    return Digest(period="08/09", events=[local, world])


def test_fallback_escapa_html_y_numera_corrido():
    message = fallback_message(digest())

    assert message.startswith("<b>brief.ar del 08/09</b>")
    assert "Argentina en el mundo" not in message
    assert "1. " in message and "2. " in message
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


def test_compose_agrega_las_noticias_que_el_modelo_se_salteo(monkeypatch):
    """El E2E mostró digests de cinco noticias en vez de siete: el modelo devolvía menos
    bloques de los pedidos y las que faltaban se perdían."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    escrito = '<b>1. Acuerdo</b>\nHubo <a href="https://infobae.com/a">acuerdo</a>.'
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: escrito)

    mensaje = compose(digest(), settings)

    assert "https://ft.com/c?x=1" in mensaje
    assert "Argentine peso" in mensaje


def test_compose_le_pide_al_modelo_las_noticias_que_se_salteo(monkeypatch):
    """Pegar el bloque crudo desentona con el resto: primero se le pide que las redacte."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    corta = '<b>1. Acuerdo</b>\nHubo <a href="https://infobae.com/a">acuerdo</a>.'
    respuestas = [
        corta,
        corta,
        '<b>2. Peso</b>\nEl peso <a href="https://ft.com/c?x=1">repuntó</a>.',
    ]
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: respuestas.pop(0))

    mensaje = compose(digest(), settings)

    assert "<b>2. Peso</b>" in mensaje
    assert "Google News" not in mensaje


def test_compose_pone_el_link_real_donde_el_modelo_dejo_el_marcador(monkeypatch):
    """El modelo escribe un marcador corto: los links de Google News tienen 500 caracteres
    opacos y los devolvía alterados, lo que rompía el link y duplicaba la noticia."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    llamadas = []

    def modelo(prompt, **kwargs):
        llamadas.append(prompt)
        return (
            '<b>1. Acuerdo</b>\nHubo <a href="{{1}}">acuerdo</a>.\n\n'
            '<b>2. Peso</b>\nEl peso <a href="{{2}}">repuntó</a>.'
        )

    monkeypatch.setattr("newsbot.write.complete", modelo)

    mensaje = compose(digest(), settings)

    assert "{{1}}" in llamadas[0] and "{{2}}" in llamadas[0]
    assert len(llamadas) == 1
    assert '<a href="https://infobae.com/a">acuerdo</a>' in mensaje
    assert '<a href="https://ft.com/c?x=1">repuntó</a>' in mensaje


def test_compose_se_queda_sin_link_antes_que_publicar_uno_inventado(monkeypatch):
    """Un href que no es ni el marcador ni una URL del día lo inventó el modelo."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    respuestas = [
        '<b>1. Acuerdo</b>\nHubo <a href="https://inventado.com/x">acuerdo</a>.\n\n'
        '<b>2. Peso</b>\nEl peso <a href="{{2}}">repuntó</a>.',
        '<b>1. Acuerdo</b>\nHubo <a href="{{1}}">acuerdo</a>.',
    ]
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: respuestas.pop(0))

    mensaje = compose(digest(), settings)

    assert "inventado.com" not in mensaje


def test_renumber_corre_la_numeracion_de_los_bloques_pedidos_aparte():
    """Lo que se pide en una segunda llamada vuelve con su propia numeración."""
    cuerpo = "<b>1. Uno</b>\ntexto\n\n<b>1. Dos</b>\ntexto\n\n<b>1. Tres</b>\ntexto"

    assert renumber(cuerpo).count("<b>1.") == 1
    assert "<b>3. Tres</b>" in renumber(cuerpo)


def test_compose_no_repite_la_noticia_cuando_el_link_lleva_ampersand(monkeypatch):
    """El digest salió con dos noticias escritas dos veces: el `&` de la URL viaja
    escapado en el HTML, así que buscarla cruda daba por faltante lo que ya estaba."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    evento = Event(
        title="Revés para el Pata Medina",
        articles=[
            Article(
                "La Corte revocó el sobreseimiento",
                "https://clarin.com/nota?id=7&outputType=amp",
                "Clarín",
                "ar",
                WHEN,
            )
        ],
    )
    completo = (
        '<b>1. Revés judicial</b>\nLa Corte <a href="https://clarin.com/nota?id=7'
        '&outputType=amp">revocó el sobreseimiento</a>.'
    )
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: completo)

    mensaje = compose(Digest(period="10/09", events=[evento]), settings)

    assert mensaje.count("revocó el sobreseimiento") == 1


def test_compose_no_repite_la_noticia_cuando_el_modelo_linkea_a_otro_medio(monkeypatch):
    """Un evento lo cubren varios medios: si el modelo enlaza al segundo, el hecho está
    contado igual y pedirlo de nuevo lo duplica."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    completo = '<b>1. Acuerdo</b>\nHubo <a href="https://clarin.com/b">acuerdo</a>.'
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: completo)
    solo_fmi = Digest(period="08/09", events=digest().events[:1])

    mensaje = compose(solo_fmi, settings)

    assert mensaje.count("Acuerdo") == 1
    assert "https://infobae.com/a" not in mensaje


def test_compose_le_pide_de_nuevo_el_resumen_cuando_el_modelo_solda_dos_hechos(monkeypatch):
    """El modelo devolvió un bloque con la denuncia de Estudiantes y, "por otra parte", el
    debate sobre las IA: menos bloques que eventos es la señal de que soldó dos hechos."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    soldado = (
        '<b>1. Acuerdo</b>\nHubo <a href="https://infobae.com/a">acuerdo</a>. Por otra '
        'parte, el peso <a href="https://ft.com/c?x=1">repuntó</a>.'
    )
    separado = (
        '<b>1. Acuerdo</b>\nHubo <a href="https://infobae.com/a">acuerdo</a>.\n\n'
        '<b>2. Peso</b>\nEl peso <a href="https://ft.com/c?x=1">repuntó</a>.'
    )
    respuestas = [soldado, separado]
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: respuestas.pop(0))

    mensaje = compose(digest(), settings)

    assert "Por otra parte" not in mensaje
    assert "<b>2. Peso</b>" in mensaje


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


def test_compose_le_pide_de_nuevo_el_bloque_con_una_cifra_inventada(monkeypatch):
    """El modelo tiene prohibido agregar datos, pero nada lo comprobaba antes de publicar."""
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    respuestas = [
        '<b>1. Acuerdo</b>\nEl <a href="{{1}}">acuerdo</a> es por 20.000 millones.\n\n'
        '<b>2. Peso</b>\nEl peso <a href="{{2}}">repuntó</a>.',
        '<b>1. Acuerdo</b>\nHubo <a href="{{1}}">acuerdo</a> con el FMI.',
    ]
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: respuestas.pop(0))

    mensaje = compose(digest(), settings)

    assert "20.000 millones" not in mensaje
    assert "Hubo <a" in mensaje
    assert "<b>2. Peso</b>" in mensaje


def test_compose_publica_el_copete_si_el_modelo_insiste_con_el_dato_inventado(monkeypatch):
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    inventado = (
        '<b>1. Acuerdo</b>\nEl <a href="{{1}}">acuerdo</a> lo firmó Kristalina Georgieva.\n\n'
        '<b>2. Peso</b>\nEl peso <a href="{{2}}">repuntó</a>.'
    )
    monkeypatch.setattr("newsbot.write.complete", lambda *a, **k: inventado)

    mensaje = compose(digest(), settings)

    assert "Georgieva" not in mensaje
    assert "Acuerdo con el FMI" in mensaje
    assert mensaje.count("<b>1.") == 1


def test_compose_no_toca_el_bloque_fiel_a_los_titulares(monkeypatch):
    settings = replace(SETTINGS, llm=LLM(provider="gemini", api_key="x", model="m"))
    llamadas = []

    def modelo(prompt, **kwargs):
        llamadas.append(prompt)
        return (
            '<b>1. Acuerdo</b>\nHubo <a href="{{1}}">acuerdo</a> con el FMI.\n\n'
            '<b>2. Peso</b>\nEl peso <a href="{{2}}">repuntó</a>.'
        )

    monkeypatch.setattr("newsbot.write.complete", modelo)

    mensaje = compose(digest(), settings)

    assert len(llamadas) == 1
    assert "Hubo <a" in mensaje

def test_el_prompt_arranca_por_el_hecho_y_no_por_el_tramite():
    tramite = Article(
        "El Gobierno estudia declarar feriado por la visita",
        "https://ambito.com/feriado",
        "Ámbito",
        "ar",
        WHEN,
    )
    event = Event(
        title="Visita del Papa",
        articles=[
            tramite,
            Article(
                "Confirmada la visita del papa León XIV a la Argentina",
                "https://infobae.com/visita",
                "Infobae",
                "ar",
                WHEN,
            ),
            Article(
                "El papa León XIV visita la Argentina en noviembre",
                "https://clarin.com/visita",
                "Clarín",
                "ar",
                WHEN,
            ),
        ],
    )

    prompt = render_events_for_prompt([event], [1])
    titulares = [line for line in prompt.splitlines() if line.startswith("   * ")]

    assert tramite.title not in titulares[0]
    assert "visita del papa" in titulares[0].lower()
    assert any(tramite.title in line for line in titulares)

def test_los_hechos_de_un_dia_conmemorativo_van_distinguidos_en_el_prompt():
    event = Event(
        title="Día del Maestro",
        articles=[
            Article(
                "Polémica por el video de Milei hecho con inteligencia artificial",
                "https://infobae.com/video",
                "Infobae",
                "ar",
                WHEN,
            ),
            Article(
                "El discurso del ministro en el Palacio Sarmiento por el Día del Maestro",
                "https://clarin.com/discurso",
                "Clarín",
                "ar",
                WHEN,
            ),
            Article(
                "Estrenan un cortometraje sobre Sarmiento",
                "https://lanacion.com.ar/corto",
                "La Nación",
                "ar",
                WHEN,
            ),
        ],
    )

    prompt = render_events_for_prompt([event], [1])
    titulares = [line for line in prompt.splitlines() if line.startswith("   * ")]

    assert len(titulares) == 3
    for article in event.articles:
        assert any(line == f"   * {article.source}: {article.title}" for line in titulares)
    assert "elegí el más importante y contá sólo ese" in PROMPT
