from datetime import date, datetime

import feedparser

from newsbot.collect import (
    articles_from,
    clean_title,
    day_bounds,
    dedupe,
    entry_published,
    strip_html,
)
from newsbot.config import TIMEZONE, Search
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
</channel></rss>
"""


def test_strip_html():
    assert strip_html("<p>Hola &amp; chau</p>") == "Hola & chau"


def test_day_bounds_usa_hora_argentina():
    start, end = day_bounds(date(2026, 9, 8))
    assert start.utcoffset().total_seconds() == -3 * 3600
    assert (end - start).days == 1


def test_entry_published_convierte_a_hora_argentina():
    parsed = feedparser.parse(FEED)
    assert entry_published(parsed.entries[0]) == datetime(2026, 9, 8, 10, 0, tzinfo=TIMEZONE)


def test_articles_from_filtra_por_dia_y_descarta_sin_fecha():
    parsed = feedparser.parse(FEED)
    articles = list(articles_from(parsed, "Medio", "ar", date(2026, 9, 8)))

    assert len(articles) == 1
    assert articles[0].title == "Titular &del día"
    assert articles[0].summary == "Bajada de la nota"
    assert articles[0].domain == "medio.com"


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
    url = Search(query="site:infobae.com", lang="es-419", country="AR", scope="ar").url
    assert "q=site%3Ainfobae.com+when%3A2d" in url
    assert "ceid=AR%3Aes-419" in url
