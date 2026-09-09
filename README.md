# argentina-news-digest

Resumen diario de las noticias argentinas de las últimas 24 horas —y de los temas argentinos
con repercusión internacional— enviado por Telegram.

## Estado: v0

```
Recolector (RSS + Google News) -> Curador (dedup + ranking) -> Redactor -> Telegram
```

El feedback del usuario por Telegram (responder al mensaje para ajustar qué noticias llegan)
está planificado para v2 y todavía no está implementado.

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # completá el token del bot y tu chat_id
```

## Uso

```bash
# ver el mensaje por consola, sin enviarlo (últimas 24 h)
newsbot --dry-run -v

# otra ventana hacia atrás
newsbot --hours 12 --dry-run

# resumir un día calendario puntual
newsbot --date 2026-09-08 --dry-run

# volver a permitir hechos ya enviados en días previos
newsbot --no-memory --dry-run

# enviar a Telegram (requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID)
set -a && source .env && set +a && newsbot
```

## Automático con GitHub Actions

`.github/workflows/digest.yml` corre todos los días a las 7 de la mañana de Argentina (10:00 UTC)
y se puede disparar a mano desde la pestaña Actions ("Run workflow"). Antes hay que cargar en
**Settings → Secrets and variables → Actions** los secrets `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID` y `GEMINI_API_KEY`.

GitHub puede demorar el arranque de los cron unos minutos y desactiva el schedule si el repo pasa
60 días sin commits.

## Automático con cron propio

```cron
0 7 * * * cd /ruta/al/repo && set -a && . ./.env && set +a && .venv/bin/newsbot
```

## Crear el bot de Telegram

1. `/newbot` con [@BotFather](https://t.me/BotFather) -> te da el `TELEGRAM_BOT_TOKEN`.
2. Escribile un mensaje a tu bot (si no, no puede iniciar la conversación).
3. `https://api.telegram.org/bot<TOKEN>/getUpdates` -> `chat.id` es tu `TELEGRAM_CHAT_ID`.

## Cómo funciona

| Módulo | Rol |
| --- | --- |
| `newsbot/collect.py` | Baja los feeds y se queda con lo publicado dentro de la ventana pedida (hora de Argentina). |
| `newsbot/curate.py` | Agrupa artículos que cuentan el mismo hecho y los rankea por cobertura. |
| `newsbot/write.py` | Redacta el mensaje. Con `GEMINI_API_KEY` (o `OPENAI_API_KEY`) usa un LLM; sin clave arma titulares + copetes + links. |
| `newsbot/memory.py` | Historial de lo ya enviado (`state/history.json`): un hecho no se repite al día siguiente. |
| `newsbot/telegram.py` | Envía el mensaje (parte los que superan los 4096 caracteres). |
| `newsbot/sources.yaml` | Medios y búsquedas. Editá acá para sumar o sacar fuentes. |

El redactor tiene la instrucción explícita de no agregar datos que no estén en los titulares y
copetes recolectados; si el LLM falla, el mensaje cae al formato determinístico.

Después de cada envío se guardan las raíces de los temas publicados en `state/history.json`
(7 días); en la próxima corrida los hechos que coinciden se descartan antes de armar el resumen.
El workflow commitea ese archivo porque el runner de GitHub Actions es efímero.

## Tests

```bash
pytest
ruff check .
```

## Roadmap

- **v1**: clustering por embeddings y scoring de relevancia con LLM.
- **v2**: el bot escucha respuestas y arma un perfil de preferencias que alimenta al curador.
- **v3**: verificador anti-alucinación, digest semanal, comandos (`/mas economia`, `/fuentes`).
