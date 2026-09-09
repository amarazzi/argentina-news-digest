"""Flujo E2E del digest: recolección real, curado, redacción y envío a un Telegram falso.

El servidor local imita la API de Telegram (valida largo y HTML como lo hace Bot API) y
permite forzar fallas para ver cómo reacciona el pipeline. No manda nada al chat real ni
necesita credenciales de Telegram; con `GEMINI_API_KEY` el resumen sale redactado y sin
ella cae al determinístico.

    python tools/e2e.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from newsbot import cli, telegram
from newsbot.config import TIMEZONE
from newsbot.text import discriminants, stems

ALLOWED = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "blockquote"}
ELEMENT = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
STATE = {"received": [], "fail_next": 0, "fail_status": 500}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencio
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if STATE["fail_next"]:
            STATE["fail_next"] -= 1
            return self.reply(STATE["fail_status"], {"ok": False, "description": "forzado"})
        text = body["text"]
        if len(re.sub(r"<[^>]+>", "", text)) > 4096:
            return self.reply(400, {"ok": False, "description": "message is too long"})
        if body.get("parse_mode") == "HTML" and (bad := invalid_html(text)):
            return self.reply(400, {"ok": False, "description": f"can't parse entities: {bad}"})
        STATE["received"].append(body)
        message_id = len(STATE["received"])
        self.reply(200, {"ok": True, "result": {"message_id": message_id}})

    def reply(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def invalid_html(text: str) -> str | None:
    """Telegram rechaza tags desconocidos o sin cerrar."""
    stack = []
    for closing, name in ((m.group(1), m.group(2).lower()) for m in ELEMENT.finditer(text)):
        if name not in ALLOWED:
            return f"unsupported start tag \"{name}\""
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return f"unmatched end tag \"{name}\""
    return f"unclosed start tag \"{stack[-1]}\"" if stack else None


def start_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    telegram.API_BASE = f"http://127.0.0.1:{server.server_port}"
    return server


def run(label: str, argv: list[str]) -> int:
    STATE["received"].clear()
    print(f"\n=== {label} ===")
    code = cli.main(argv)
    for body in STATE["received"]:
        visible = len(re.sub(r"<[^>]+>", "", body["text"]))
        print(f"  chunk: {visible} caracteres visibles, parse_mode={body.get('parse_mode')}")
    print(f"  exit={code}, mensajes={len(STATE['received'])}")
    return code


def titles(text: str) -> list[str]:
    return re.findall(r"<b>\d+\.\s*(?:<a[^>]*>)?(.*?)(?:</a>)?</b>", text)


def same_story(a: str, b: str) -> bool:
    """Comparar titulares exactos no alcanza: "internaron a X" y "murió X" son la misma
    historia con otras palabras. Estos títulos son de tres o cuatro palabras, así que se
    piden dos raíces propias en común: con una sola, "Extradición a Brasil" y "Crisis en
    la Corte brasileña" parecen el mismo hecho."""
    return len(discriminants(stems(a)) & discriminants(stems(b))) >= 2


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    start_server()
    state = Path(tempfile.mkdtemp(prefix="newsbot-e2e-")) / "history.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.unlink(missing_ok=True)
    os.environ["NEWSBOT_STATE"] = str(state)
    # El servidor falso no valida credenciales: no hace falta el bot real.
    os.environ["TELEGRAM_BOT_TOKEN"] = "e2e-token"
    os.environ["TELEGRAM_CHAT_ID"] = "e2e-chat"

    ok = True

    # 1) Día completo: recolecta, cura, redacta, envía y guarda historial.
    ayer_fecha = (datetime.now(TIMEZONE).date() - timedelta(days=1)).isoformat()
    assert run("1. digest de ayer, envío completo", ["--date", ayer_fecha]) == 0
    ayer = "\n".join(b["text"] for b in STATE["received"])
    ayer_titulos = titles(ayer)
    print(f"  titulares: {ayer_titulos}")
    ok &= state.exists() and len(json.loads(state.read_text())["events"]) > 0
    print(f"  historial guardado: {state.exists()}")

    # 2) Al día siguiente no se repiten los hechos ya enviados.
    assert run("2. digest de hoy con el historial de ayer", ["--hours", "24"]) == 0
    hoy = "\n".join(b["text"] for b in STATE["received"])
    repetidos = {t for t in titles(hoy) if any(same_story(t, v) for v in ayer_titulos)}
    print(f"  titulares: {titles(hoy)}")
    print(f"  repetidos respecto de ayer: {repetidos or 'ninguno'}")
    ok &= not repetidos

    # 3) Telegram falla dos veces con 500: el cliente reintenta y el mensaje llega igual.
    telegram.BACKOFF = 0.1
    STATE["fail_next"], STATE["fail_status"] = 2, 500
    assert run("3. Telegram 500 dos veces", ["--hours", "24", "--no-memory"]) == 0
    ok &= len(STATE["received"]) >= 1

    # 4) Telegram rechaza el HTML: se reenvía en texto plano en vez de perder el digest.
    STATE["fail_next"], STATE["fail_status"] = 1, 400
    assert run("4. Telegram 400 al HTML", ["--hours", "24", "--no-memory"]) == 0
    ok &= any(b.get("parse_mode") is None for b in STATE["received"])

    print(f"\nE2E {'OK' if ok else 'CON FALLAS'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
