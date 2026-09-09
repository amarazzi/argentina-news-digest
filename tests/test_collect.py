from datetime import date, datetime

import feedparser

from newsbot.collect import (
    articles_from,
    clean_title,
    dedupe,
    entry_published,
    search_slices,
    strip_html,
)
from newsbot.config import TIMEZONE, Search, Window
from newsbot.models import Article

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Titular &amp;del d&#237;a</title>
    <link>https://medio.com/nota-1?utm_source=rss</link>
    <description>&lt;p&gt;Bajada de la nota&lt;/p&gt;</description>
    <pubDate>Tue, 08 Sep 2026 13:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Nota de otro día</title>
    <link>https://medio.com/nota-2</link>
    <pubDate>Sun, 06 Sep 2026 13:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Nota sin fecha</title>
    <link>https://medio.com/nota-3</link>
  </item>
  <item>
    <title>Nota con fecha sin huso</title>
    <link>https://medio.com/nota-4</link>
    <pubDate>Tue, 08 Sep 2026 23:30:00</pubDate>
  </item>
</channel></rss>
"""


def test_strip_html():
    assert strip_html("<p>Hola &amp; chau</p>") == "Hola & chau"


def test_window_day_usa_hora_argentina():
    window = Window.day(date(2026, 9, 8))
    assert window.start.utcoffset().total_seconds() == -3 * 3600
    assert (window.end - window.start).days == 1
    assert window.label == "08/09/2026"


def test_window_last_hours_cubre_solo_las_ultimas_24_horas():
    now = datetime(2026, 9, 9, 7, 0, tzinfo=TIMEZONE)
    window = Window.last_hours(end=now)

    assert datetime(2026, 9, 8, 8, 0, tzinfo=TIMEZONE) in window
    assert datetime(2026, 9, 8, 6, 0, tzinfo=TIMEZONE) not in window
    assert window.lookback_hours(now=now) == 24


def test_lookback_cubre_un_dia_calendario_ya_terminado():
    """Para el 08/09 mirado el 09/09 a las 07:00 hay que pedir 31 h hacia atrás."""
    now = datetime(2026, 9, 9, 7, 0, tzinfo=TIMEZONE)
    assert Window.day(date(2026, 9, 8)).lookback_hours(now=now) == 31


def test_entry_published_convierte_a_hora_argentina():
    parsed = feedparser.parse(FEED)
    assert entry_published(parsed.entries[0]) == datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)


def test_entry_published_sin_huso_es_hora_argentina():
    """Sin offset, tratarla como UTC corría tres horas todo lo que publica un medio local:
    lo del 08/09 a las 23:30 se iba al 09/09."""
    parsed = feedparser.parse(FEED)
    assert entry_published(parsed.entries[3]) == datetime(2026, 9, 8, 23, 30, tzinfo=TIMEZONE)


def test_articles_from_filtra_por_dia_y_cuenta_las_notas_sin_fecha():
    parsed = feedparser.parse(FEED)
    articles, undated = articles_from(parsed, "Medio", "ar", Window.day(date(2026, 9, 8)))

    assert [a.title for a in articles] == ["Titular &del día", "Nota con fecha sin huso"]
    assert articles[0].summary == "Bajada de la nota"
    assert articles[0].domain == "medio.com"
    assert undated == 1


def test_las_busquedas_internacionales_descartan_lo_que_no_es_sobre_argentina():
    """La edición brasileña de "Argentina" trae política interna de Brasil."""
    feed = FEED.replace("Titular &del día", "Lula suspendeu o diretor da Polícia Federal")
    articles, _ = articles_from(
        feedparser.parse(feed), "Google News", "world", Window.day(date(2026, 9, 8))
    )

    assert [a.title for a in articles] == []


def test_search_slices_trocea_la_ventana():
    """Google News corta en 100 resultados por búsqueda: se pide de a tramos."""
    now = datetime(2026, 9, 9, 7, 0, tzinfo=TIMEZONE)
    window = Window.last_hours(24, end=now)
    assert search_slices(window, now=now) == [6, 12, 18, 24]


def test_dedupe_ignora_query_string():
    when = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)
    articles = [
        Article("A", "https://medio.com/x?utm=1", "Medio", "ar", when),
        Article("A", "https://medio.com/x?utm=2", "Otro", "ar", when),
    ]
    assert len(dedupe(articles)) == 1


def test_dedupe_junta_la_misma_nota_del_mismo_medio_por_dos_vias():
    when = datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)
    articles = [
        Article("Paro general", "https://medio.com/a", "Ámbito", "ar", when),
        Article("paro general", "https://news.google.com/rss/articles/xyz", "Ámbito", "ar", when),
    ]
    assert len(dedupe(articles)) == 1


def test_clean_title_saca_el_sufijo_del_medio():
    assert clean_title("Paro en el AMBA - Clarin.com", "Clarin.com") == "Paro en el AMBA"
    assert clean_title("Nota sin sufijo", "Clarin.com") == "Nota sin sufijo"


def test_search_url_acota_la_ventana_temporal():
    url = Search(query="site:infobae.com", lang="es-419", country="AR", scope="ar").url(24)
    assert "q=site%3Ainfobae.com+when%3A24h" in url
    assert "ceid=AR%3Aes-419" in url
