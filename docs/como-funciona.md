# brief.ar: qué hace el sistema, paso a paso

Un resumen diario de noticias argentinas que llega solo a Telegram. Abajo, el recorrido completo
de una corrida, en el orden en que pasa.

---

## 0. El disparador

Todos los días a las 6:13 (hora de Argentina) GitHub Actions ejecuta el workflow `digest.yml`.
No hace falta que nadie toque nada: el runner clona el repo, instala las dependencias y corre
`newsbot --save-memory`. Si el cron no corre (GitHub los retrasa y a veces los apaga), al
mediodía otro workflow, `vigia.yml`, chequea que haya habido una corrida en verde y, si no la
hubo, avisa por el mismo bot de Telegram.

**Por qué 6:13 y no 6:00:** la hora en punto es la franja más congestionada del scheduler de
GitHub y es donde más se retrasan los cron.

---

## 1. Qué día se resume

El resumen es del **día calendario anterior completo** (00:00 a 23:59 de ayer, hora argentina),
no de "las últimas 24 horas".

**Por qué importa:** con una ventana móvil, correr el sistema a las 11 y a las 19 daba resultados
distintos, porque el insumo era otro. Con el día cerrado, corrido a cualquier hora cuenta lo
mismo. Es la diferencia entre "qué está pasando" y "qué pasó".

---

## 2. Recolección (agente 1)

Se bajan todas las noticias publicadas ese día desde dos tipos de fuente:

- **Feeds RSS** de medios argentinos.
- **Búsquedas en Google News**, que traen medios que no tienen feed propio: nacionales,
  provinciales, económicos y judiciales.

Cada nota queda como un registro con titular, copete, medio, link y fecha de publicación. Se
descarta lo que cae fuera del día. Un día típico deja entre 700 y 900 notas.

**Detalle no obvio:** Google News limita cuántas notas devuelve por consulta, así que las
búsquedas se piden por tramos de horas para que no se pierda la madrugada.

---

## 3. Limpieza: lo que ni siquiera compite

Antes de puntuar nada, se sacan las notas que nunca van a ser noticia del día:

- **Servicio**: horóscopo, quiniela y Loto, "cuándo cobro la AUH", pronóstico, feriados.
- **Rutina de mercado**: cotizaciones, ADR, bonos, cierres de la bolsa. Salvo un movimiento
  excepcional (derrumbe, récord, corrida).
- **Deportes de rutina**: fechas de liga, MLS, NBA, F1.
- **Anticipos**: "hoy se conoce la inflación", "qué se espera del dato". Lo que se quiere es el
  dato, no el aviso de que va a haber un dato.

**Por qué se sacan antes y no después:** al principio se castigaban una por una, pero cuando se
agrupaban (horóscopo + Loto + ANSES en un mismo bloque) sumaban la cobertura de un montón de
medios y el castigo no alcanzaba: el ítem 1 de un digest llegó a ser "Horóscopo, Loto y ANSES".
Ahora se eliminan antes de que puedan sumar.

---

## 4. Agrupamiento: una noticia, no quince notas

Quince medios cubren el mismo hecho con quince titulares distintos. El sistema los junta en un
solo **hecho**.

- **Con embeddings** (lo normal): cada titular se convierte en un vector con la API de Gemini y
  se agrupan los que están cerca en significado. Así "Murió X" y "Falleció el histórico dirigente
  X" caen juntos aunque no compartan una sola palabra.
- **Sin API** (o con la cuota agotada): se agrupa por raíces de palabras del titular. Es el
  fallback, funciona peor pero nunca deja al sistema sin agrupar.

Los vectores quedan guardados en el registro de la corrida, así volver a procesar un día viejo no
gasta cuota.

---

## 5. Curaduría: qué es importante (agente 2)

Cada hecho se puntúa, sobre todo por **cobertura**: cuántos medios lo publicaron y —clave— cuántos
lo escribieron **con sus propias palabras**. Quince diarios republicando el mismo cable de Télam
no son quince coberturas: las copias suman con peso decreciente.

Después se aplican los filtros de entrada:

- Lo tienen que haber publicado al menos **3 medios**, **2 con redacción propia**.
- Tiene que puntuar al menos **un tercio** de lo que puntúa la noticia más importante del día.
- Entran **hasta 7**.

**El punto central: 7 es un techo, no una cuota.** Si el día da 4 noticias fuertes, salen 4. Antes
el sistema completaba hasta 7 y rellenaba con lo que sobraba — así se colaron una denuncia de
Estudiantes ante la Conmebol y una columna de opinión sobre IA.

---

## 6. Memoria: no repetir lo de ayer

Cada hecho publicado queda anotado en `state/history.json` durante 7 días. Un hecho que ya se
contó no vuelve a entrar.

**La parte fina** es distinguir dos cosas que se parecen:

- **Repetición**: las repercusiones, el análisis, las reacciones de lo que ya se mandó. No entra.
- **Desarrollo**: si ayer entró la internación y hoy la persona murió, eso es un hecho nuevo.
  Entra.

Se resuelve mirando si el hecho de hoy trae un verbo de hecho consumado ("murió", "detuvieron",
"renunció", "condenaron") que no estuviera en lo ya enviado.

**Detalle práctico:** las corridas manuales de prueba **leen** el historial pero no lo escriben.
Por eso probar dos veces muestra lo mismo y no te consume las noticias del día siguiente. Sólo el
envío automático guarda.

---

## 7. Redacción (agente 3)

Los hechos elegidos se le pasan a Gemini, que escribe un bloque por noticia: un título corto y dos
o tres oraciones, con la información de los titulares y copetes de ese hecho y de ningún otro.

Dos cosas que costaron:

- **Los links los pone el sistema, no el modelo.** Los enlaces de Google News son cadenas opacas
  de 500 caracteres y el modelo los devolvía alterados. Ahora escribe un marcador corto y el
  código lo reemplaza por el link real. Si inventa un enlace, se cae el link; nunca se publica uno
  roto.
- **Un bloque por hecho.** El modelo tendía a soldar dos noticias con un "por otra parte". Si
  devuelve menos bloques que hechos, se le vuelven a pedir los que faltan.

---

## 8. Verificación: no publicar lo que nadie dijo (agente 4)

Antes de enviar, cada bloque se compara contra los titulares y copetes de **su** hecho:

- toda **cifra** que aparezca en el resumen tiene que estar en el material;
- todo **nombre propio** también.

Si algo no está, se pide ese bloque de nuevo. Si el modelo insiste, se publica el copete textual
del medio en vez de la versión redactada.

**Detalle:** el chequeo es tolerante donde tiene que serlo. `1,7%` y `1.7 %` son el mismo dato, y
que el modelo complete "Milei" como "Javier Milei" no es inventar. Sin esas tolerancias marcaba
como inventadas palabras como "Balacera" por empezar una oración en mayúscula.

---

## 9. Envío

El mensaje sale por el bot de Telegram con el encabezado `brief.ar del DD/MM`. Si Telegram rechaza
el HTML, se reenvía en texto plano en vez de perder el día. Si el brief salió con menos de 3
noticias, te llega un aviso por el mismo chat: puede ser un día flojo de verdad o algo roto.

---

## 10. Registro: que cada corrida se pueda revisar

Cada envío deja un archivo `runs/AAAA-MM-DD.json.gz` en la rama `runs` con **todo** lo que pasó:
las notas crudas con las marcas de qué filtro les tocó, el ranking completo con cobertura y
puntaje, los ids elegidos, los vectores y el commit con el que corrió.

**Para qué sirve:** con `newsbot --replay` se vuelve a curar un día ya vivido con el código de hoy,
sin salir a internet, y `tools/compare.py` muestra qué entraría y qué saldría con un cambio. Es la
única forma de saber si tocar el curador mejora o empeora, en vez de discutirlo de memoria.

---

## Lo que está escrito pero apagado: el juez editorial

Hoy quién entra lo decide código: cobertura, umbrales, filtros. Eso es previsible pero tosco — no
entiende de qué se trata la noticia.

El juez editorial es un paso donde el modelo, en una sola llamada, clasifica los 25 hechos de mejor
cobertura del día: categoría (política, economía, judicial, deportes…), si es nacional o
internacional, una **importancia del 1 al 10**, y si es algo nuevo, el desarrollo de una historia
en curso o una repetición.

**El modelo puntúa; el código decide.** El prompt no tiene ninguna regla de entrada, sólo la
rúbrica de importancia (10 = hito que todos van a recordar; 1-3 = color, servicio, farándula). Las
reglas están aparte:

- una noticia nacional entra con importancia 6 o más y 3 medios;
- deportes o espectáculos, sólo con 9 o más (la final del Mundial sí, la fecha de la Libertadores
  no);
- lo internacional, sólo con 9 o más;
- un anticipo, una repetición o una nota de servicio no entran nunca, con cualquier puntaje.

Así se puede explicar cada exclusión y mover el borde cambiando un número, sin reescribir el
prompt.

**Está apagado detrás de una bandera** porque es el componente que decide qué se publica y todavía
no hay con qué medirlo: hace falta una semana de días guardados en `runs/` para comparar su
selección contra la del curador determinístico. Si se prende y falla —se cae, devuelve algo que no
es JSON, se saltea un hecho—, se reintenta una vez y después el digest sale igual con el curador
de siempre. Lo único inaceptable es que no llegue nada.

---

## Lo que falta

- **Que el bot escuche tus respuestas**: contestarle al mensaje de Telegram para decirle qué te
  gustó y qué no, y que eso alimente la selección. Es la segunda parte del proyecto original.
- **Digest semanal** y comandos (`/mas economia`, `/fuentes`).

---

## Resumen en una línea por etapa

| # | Etapa | Qué hace |
|---|-------|----------|
| 0 | Cron | GitHub dispara la corrida a las 6:13 ART |
| 1 | Ventana | Fija el día de ayer completo |
| 2 | Recolección | ~800 notas de RSS y Google News |
| 3 | Limpieza | Saca servicio, mercado de rutina, deportes de rutina y anticipos |
| 4 | Agrupamiento | Junta las coberturas del mismo hecho por significado |
| 5 | Curaduría | Puntúa por cobertura independiente; hasta 7, sin relleno |
| 6 | Memoria | Descarta lo ya enviado; deja pasar los desarrollos |
| 7 | Redacción | Gemini escribe un bloque por hecho; los links los pone el sistema |
| 8 | Verificación | Cifras y nombres tienen que estar en el material original |
| 9 | Envío | Telegram, con fallback a texto plano y aviso si el día salió flojo |
| 10 | Registro | Guarda la corrida entera para poder auditarla y reprocesarla |
