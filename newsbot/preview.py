"""Vista previa local del mensaje: cómo se va a ver en Telegram, sin tocar el bot.

`compose()` ya devuelve HTML de Telegram (sólo <b>, <i>, <a>, con las entidades escapadas),
así que alcanza con envolverlo en una burbuja de chat: no hay nada que traducir.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>brief.ar — __PERIOD__</title>
<style>
  body {
    margin: 0;
    padding: 40px 16px;
    background: #0e1621;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    display: flex;
    justify-content: center;
  }
  .container { max-width: 480px; width: 100%; }
  .meta {
    color: #7c8a97;
    font-size: 12px;
    text-align: center;
    margin-bottom: 10px;
  }
  .bubble {
    background: #182533;
    color: #e7ecf0;
    border-radius: 14px;
    padding: 14px 16px;
    font-size: 15px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-wrap: break-word;
    box-shadow: 0 2px 8px rgba(0, 0, 0, .3);
  }
  .bubble b { font-weight: 600; }
  .bubble a { color: #6ab7ff; text-decoration: none; }
  .bubble a:hover { text-decoration: underline; }
</style>
</head>
<body>
  <div class="container">
    <div class="meta">brief.ar &middot; vista previa local &middot; no se envió a Telegram</div>
    <div class="bubble">__MESSAGE__</div>
  </div>
</body>
</html>
"""


def render(message: str, period: str) -> str:
    return TEMPLATE.replace("__PERIOD__", period).replace("__MESSAGE__", message)


def write(message: str, period: str, day: str, directory: Path = Path("previews")) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{day}.html"
    path.write_text(render(message, period), encoding="utf-8")
    return path
