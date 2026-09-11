"""Agente 5 — Verificador: ningún dato del resumen puede salir de la cabeza del modelo.

El redactor tiene prohibido agregar información, pero nada lo comprobaba antes de publicar.
Acá se comparan los datos duros del texto escrito contra los titulares y copetes que se le
pasaron: las cifras tienen que estar y los nombres propios también.
"""

from __future__ import annotations

import re
import unicodedata
from html import unescape

from .models import Event

TAG = re.compile(r"<[^>]+>")
# El titular del bloque va en <b> y no termina en punto: sin el corte, la primera
# palabra del texto parecería estar en medio de una oración.
BREAK = re.compile(r"</?(?:b|p|br)\s*/?>", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d.,]*")
WORD = r"[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ]*"
CAPITALIZED = re.compile(WORD)
# 'Corte Suprema de Justicia': las minúsculas de enlace no cortan el nombre.
RUN = re.compile(rf"{WORD}(?:[ ]+(?:de|del|la|y)?[ ]*{WORD})*")
LEADING_NUMBER = re.compile(r"^\s*\d+\.\s*")
MIN_NAME = 4

# Mayúsculas que sólo indican principio de oración: no son nombres de nada.
COMMON = {
    "ademas",
    "ahora",
    "asi",
    "aunque",
    "cada",
    "como",
    "cuando",
    "desde",
    "despues",
    "durante",
    "ellos",
    "entre",
    "esta",
    "este",
    "esto",
    "estos",
    "finalmente",
    "hasta",
    "luego",
    "mientras",
    "mismo",
    "para",
    "pero",
    "porque",
    "segun",
    "sobre",
    "tambien",
    "todos",
    "tras",
    "unos",
}


def fold(word: str) -> str:
    """Sin tildes y en minúscula: el modelo escribe 'Milei' y el titular 'MILEI'."""
    plain = unicodedata.normalize("NFD", word)
    return "".join(char for char in plain if unicodedata.category(char) != "Mn").lower()


def plain_text(html: str) -> str:
    return unescape(TAG.sub(" ", BREAK.sub("\n", html)))


def digits(text: str) -> set[str]:
    """Una cifra es sus dígitos: '1,7%' y '1.7 %' son el mismo dato."""
    return {
        re.sub(r"[.,]", "", match.group()).lstrip("0") or "0" for match in NUMBER.finditer(text)
    }


def opens_sentence(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \t")
    return not before or before[-1] in ".!?:\n"


def names(text: str) -> list[list[str]]:
    """Nombres propios, agrupados por aparición: 'Javier Milei' es un solo nombre.

    La primera palabra de una oración va en mayúscula por gramática y no por ser un
    nombre, así que no cuenta: 'Balacera en El Palomar' aporta 'Palomar'.
    """
    found = []
    for run in RUN.finditer(text):
        words = CAPITALIZED.findall(run.group())
        if opens_sentence(text, run.start()):
            words = words[1:]
        keep = [fold(word) for word in words if len(word) >= MIN_NAME and fold(word) not in COMMON]
        if keep:
            found.append(keep)
    return found


def source_text(event: Event, limit: int) -> str:
    """Lo que efectivamente vio el modelo: titulares y copetes de las notas del evento."""
    parts = []
    for article in event.articles[:limit]:
        parts.extend([article.title, article.summary or ""])
    return " ".join(parts)


def unsupported(block: str, source: str) -> tuple[list[str], list[str]]:
    """Cifras y nombres del bloque que no aparecen en los titulares del evento.

    Un nombre de varias palabras cuenta como respaldado si alguna lo está: el modelo
    completa 'Milei' como 'Javier Milei' y eso no es inventar un dato.
    """
    text = LEADING_NUMBER.sub("", plain_text(block).strip())
    text = "\n".join(line.strip() for line in text.splitlines())
    reference = fold(source)
    known = digits(source)
    figures = sorted(number for number in digits(text) if number not in known)
    invented = [
        " ".join(words) for words in names(text) if not any(word in reference for word in words)
    ]
    return figures, invented
