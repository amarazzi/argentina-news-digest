# argentina-news-digest

Resumen diario de las noticias argentinas del día anterior —de 00:00 a 23:59, hora de
Argentina— enviado por Telegram.

Cómo funciona, paso a paso: [docs/como-funciona.md](docs/como-funciona.md).

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
# ver el mensaje por consola, sin enviarlo (el día de ayer completo)
newsbot --dry-run -v

# ventana móvil hacia atrás desde ahora
newsbot --hours 12 --dry-run

# resumir un día calendario puntual
newsbot --date 2026-09-08 --dry-run

# volver a permitir hechos ya enviados en días previos
newsbot --no-memory --dry-run

# enviar a Telegram (requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID)
set -a && source .env && set +a && newsbot

# volver a curar un día ya vivido con el código de hoy, sin red
newsbot --replay runs/2026-09-10.json.gz --dry-run

# qué entra y qué sale en todos los días registrados
python tools/compare.py
```

Una corrida a mano es una prueba: descarta lo que ya se envió en días previos, pero no anota lo
suyo en el historial. Así probar dos veces seguidas muestra el mismo digest, el que va a ver el
usuario. El envío del día lo hace el workflow con `--save-memory`, que sí registra lo publicado.

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
| `newsbot/record.py` | Registra cada envío entero en `runs/AAAA-MM-DD.json.gz` para poder reproducirlo. |
| `newsbot/verify.py` | Antes de publicar, chequea que las cifras y los nombres de cada bloque estén en los titulares de ese hecho. |
| `newsbot/alert.py` | Avisa por el mismo chat si el día salió flojo o si la recolección se cayó. |

El redactor tiene la instrucción explícita de no agregar datos que no estén en los titulares y
copetes recolectados; si el LLM falla, el mensaje cae al formato determinístico. Además se
comprueba: el bloque que trae una cifra o un nombre propio que no está en sus fuentes se pide de
nuevo, y si el modelo insiste se publica el copete del medio en vez del texto generado.

El token del bot nunca sale por el log: `newsbot/logs.py` baja el nivel de `httpx` (que imprime
la URL de Telegram entera) y filtra el secreto de cualquier mensaje.

Después de cada envío se guardan las raíces de los temas publicados en `state/history.json`
(7 días); en la próxima corrida los hechos que coinciden se descartan antes de armar el resumen.
El workflow commitea ese archivo porque el runner de GitHub Actions es efímero.

## Registro de corridas

Cada envío con `--save-memory` deja `runs/AAAA-MM-DD.json.gz` con los artículos crudos (con las
marcas de los filtros que les aplicó el curador), el ranking completo hasta 30 eventos con su
cobertura, puntaje y flags, los ids elegidos, los veredictos del juez (o `null` si la corrida
salió sin juez), el commit con el que corrió y los tokens de LLM consumidos. El workflow los
commitea en la rama `runs`, aparte de `main`.

Con eso, `newsbot --replay` vuelve a curar ese día con el código actual sin salir a la red, y
`tools/compare.py` muestra qué eventos entrarían y cuáles saldrían en todos los días registrados:
es la forma de medir un cambio del curador antes de mergearlo. El replay corre sin historial a
propósito —el estado de la memoria de aquel día no queda registrado—, así que compara criterio
de selección, no la deduplicación entre días.

## Juez editorial (apagado)

Con `--judge` (o `NEWSBOT_JUDGE=1`) la selección la hace un juez con LLM en vez del curador:
en una sola llamada clasifica los 25 grupos de mejor cobertura del día —categoría, ámbito,
importancia del 1 al 10 y si es una repetición, un desarrollo o algo nuevo— y después deciden
reglas determinísticas, con umbrales en variables de entorno (`JUDGE_MIN_IMPORTANCE`,
`JUDGE_MIN_IMPORTANCE_LIGHT`, `JUDGE_MIN_IMPORTANCE_WORLD`, `JUDGE_MIN_OUTLETS`,
`JUDGE_MIN_INDEPENDENT`). El modelo puntúa; el código decide, así cada exclusión se puede
explicar y los umbrales se mueven sin tocar el prompt. `JUDGE_MODEL` permite juzgar con un
modelo distinto al que redacta.

Va apagado a propósito: hace falta comparar su criterio contra el del curador sobre una semana
de días guardados en `runs/` antes de dejarlo elegir lo que se publica. Si el juez se cae,
devuelve algo que no es JSON o se saltea un grupo, se reintenta una vez y después el digest sale
igual con el curador determinístico; la corrida queda registrada como corrida sin juez.
`--judge --dry-run -v` imprime la tabla con lo que dijo de cada grupo.

## Tests

```bash
pytest
ruff check .
```

Flujo completo contra noticias reales, sin tocar el chat de Telegram (levanta un servidor
local que imita la Bot API, valida el HTML y el largo, y fuerza fallas para ver los
reintentos y la caída a texto plano):

```bash
python tools/e2e.py
```

## Roadmap

- **v1**: dejar que el juez editorial elija, después de medirlo contra una semana de `runs/`.
- **v2**: el bot escucha respuestas y arma un perfil de preferencias que alimenta al curador.
- **v3**: digest semanal, comandos (`/mas economia`, `/fuentes`).
