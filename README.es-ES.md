

# central-mcp

<p align="center">
  <img src="https://raw.githubusercontent.com/andy5090/central-mcp/main/docs/logo.png?v=0.11.0" alt="central-mcp logo" width="280"/>
</p>

<p align="center">
  <strong>Español</strong> · <a href="README_KO.md">한국어</a>
</p>

[![PyPI version](https://img.shields.io/pypi/v/central-mcp)](https://pypi.org/project/central-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/central-mcp)](https://pypi.org/project/central-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hub MCP agnóstico del agente de programación para gestionar múltiples agentes de código.**

> **Nunca te detengas. Ejecuta agentes en todos los proyectos en paralelo — multiplica tu rendimiento por 10×, 100×.**

Un solo servidor MCP convierte a cualquier cliente compatible con MCP (Claude Code, Codex CLI, Gemini CLI, opencode, [Hermes Agent](https://github.com/NousResearch/hermes-agent), …) en un plano de control para tu portafolio de proyectos con agentes de programación. Pregunta en lenguaje natural y el orquestador enrutará la solicitud al agente del proyecto correcto — sin bloqueo, con los resultados reportados de forma asíncrona.

## Por qué

Probablemente uses más de un agente de programación. Cada uno tiene su propia terminal, su propia sesión, sus propios registros. Cambiar entre ellos genera fricción y no hay una vista compartida de *qué respondió a qué*.

`central-mcp` te ofrece un único centro:

- **Distribuye** prompts a cualquier agente de proyecto y obtén respuestas vía MCP
- **Trabajo en paralelo** — distribuye a múltiples proyectos y sigue conversando mientras se ejecutan
- **Gestiona** el registro con `add_project` / `remove_project`
- **Orquesta** desde cualquier cliente compatible con MCP — nunca atado a uno solo

Cada envío es un subproceso fresco en el directorio de trabajo actual (cwd) del proyecto (p. ej. `claude -p "..." --continue`). Sin procesos de larga duración, sin scraping de pantalla, sin dependencia de tmux en la ruta crítica.

## Principios de diseño

1. **Agnóstico al agente de programación.** Las herramientas MCP son la superficie canónica. Cualquier cliente compatible con MCP puede ser el orquestador; cualquier CLI de agente de programación compatible puede ser el objetivo de la distribución.
2. **Envío sin bloqueo.** `dispatch` devuelve un `dispatch_id` en <100ms. Los resultados llegan de forma asíncrona. La conversación nunca se congela.
3. **Prefacio del enrutador de envíos.** El orquestador está instruido para actuar como un enrutador puro: analizar el nombre del proyecto, llamar a `dispatch`, y seguir adelante. Esto minimiza la latencia de razonamiento del LLM a ~1-2 segundos por turno.
4. **Estado basado en archivos.** `registry.yaml` es la única fuente de verdad.

## Estado

El instalador de una sola línea con `curl` se encuentra en [https://central-mcp.org](https://central-mcp.org/) — inicializa `uv` si falta, instala central-mcp y ejecuta `central-mcp init`.

## Plataformas compatibles

Ejecuta central-mcp en la plataforma donde se ha probado, y espera un poco de aspereza en otras:

- **macOS** — objetivo principal de desarrollo y pruebas.
- **Linux** — se espera que funcione (puro Python, tmux/zellij son multiplataforma), pero no se prueba regularmente; por favor, reporta issues si encuentras bordes.
- **Windows** — no probado oficialmente. El núcleo (Python + herramientas MCP + los backends de tmux / zellij donde se ejecutan en Windows) debería funcionar en principio; el backend cmux es exclusivo de macOS, por lo que las opciones de la capa de observación en Windows se reducen a tmux o zellij (cualquiera que puedas instalar). Por favor, reporta issues si encuentras bordes.

## Inicio rápido

```bash
# Una sola línea — inicializa uv, instala central-mcp, ejecuta `central-mcp init`.
curl -fsSL https://central-mcp.org/install.sh | sh
```

(`tmux` solo si deseas la capa de observación opcional.)

```bash
# Lanzar — un solo comando hace todo
central-mcp
```

> **Instalación manual** si prefieres no pipe-ear un script:
>
> ```bash
> # 1. Instala uv (https://docs.astral.sh/uv/) si aún no lo tienes
> curl -LsSf https://astral.sh/uv/install.sh | sh
>
> # 2. Instala central-mcp + andamia ~/.central-mcp/
> uv tool install central-mcp
> central-mcp init
> ```
>
> O con pip: `pip install central-mcp`

La primera ejecución de `central-mcp` crea automáticamente `~/.central-mcp/registry.yaml` y registra central-mcp con cada binario de cliente MCP que encuentre en PATH (claude, codex, gemini, opencode). Después de eso, lanza el orquestador en tu agente preferido.

> **Instalación manual** si quieres control fino:
> - `central-mcp install all` — volver a detectar + registrar en todas partes
> - `central-mcp install claude` — registrar con un solo cliente
> - `central-mcp init` — crear el registro sin lanzar

Dentro de la sesión del orquestador, habla de forma natural — catálogo completo de ejemplos en [Primera sesión](#primera-sesión-ejemplos-en-lenguaje-natural) más abajo.

El orquestador llama a `dispatch` para cada solicitud y **continúa la conversación de inmediato** — no esperas. Los resultados llegan a través de tres canales:

- **Piggyback (automático):** cada respuesta de herramienta MCP incluye un array `completed_dispatches` con cualquier resultado que haya terminado desde la última llamada.
- **Poll en segundo plano (intento máximo):** un subagente hace poll a `check_dispatch` cada 3 segundos y reporta automáticamente cuando termina.
- **Verificación dirigida por el usuario (100% confiable):** pregunta "¿hay actualizaciones?" en cualquier momento.

Múltiples envíos se ejecutan en paralelo.

## Primera sesión — ejemplos en lenguaje natural

Todo lo que sigue se habla al orquestador en lenguaje natural. El orquestador elige la herramienta MCP correcta y sigue adelante. NO necesitas memorizar `dispatch(...)` / `add_project(...)` / `check_dispatch(...)` — esos son los verbos de la capa MCP mostrados en otra parte del README para referencia, no comandos que escribas.

**Configuración (una vez):**
- *"Agrega ~/Projects/my-app al centro. Usa claude como su agente."*
- *"Registra ~/Projects/api-server — el agente predeterminado está bien."*
- *"¿Qué proyectos tengo?"*

**Enviar trabajo:**
- *"Pídele a my-app que agregue un interruptor de modo oscuro en la configuración."*
- *"Envía a my-app y api-server el mismo prompt: ajusta el README."*
- *"Envía a my-app con codex en lugar de claude esta vez."*

**Verificar progreso:**
- *"¿Qué se está ejecutando ahora?"*
- *"¿Hay actualizaciones?"* / *"status?"*
- *"¿Cómo salió ese último envío a my-app?"*
- *"Muestra los últimos 3 envíos para my-app."*
- *"Estado general en todos los proyectos?"* (dispara un resumen de todo el portafolio)

**Recuperar / cambiar hilos:**
- *"Cancela el envío de my-app — el prompt estaba mal."*
- *"¿Qué sesiones de conversación tengo para api-server?"*
- *"Cambia api-server a la sesión abc123 para el próximo envío."*
- *"Vuelve a la sesión predeterminada / más reciente para api-server."*

**Preferencias de idioma:**
- *"Para my-app, respóndeme en coreano de ahora en adelante."*
- *"Usa francés para api-server a menos que diga lo contrario."*
- *"Solo este envío en japonés para my-app."*
- *"Limpia el idioma guardado para my-app y vuelve al inglés."*

**Organizar la flota:**
- *"Pon my-app y api-server al principio de la lista."*
- *"Elimina el proyecto legacy-tool antiguo."*

**Consejo de observación para usuarios nuevos.** Al principio, vale la pena ejecutar `central-mcp tmux` (o `zellij` — o `cmcp` dentro de cmux.app en macOS) en una segunda terminal para poder ver los flujos de envío por proyecto en vivo mientras charlas con el orquestador. Construye intuición sobre qué tan rápidos son realmente los envíos y qué tipo de prompts producen salida útil. Una vez que los resúmenes del orquestador coincidan con lo que habrías verificado en los paneles de todos modos, deja la observación y trabaja solo desde el orquestador — ver [Capa de observación opcional](#capa-de-observación-opcional) más abajo para la historia completa.

## Herramientas MCP

`central-mcp` expone 11 herramientas bajo el nombre de servidor `central`:

| Herramienta | ¿Bloqueante? | Propósito |
|---|---|---|
| `list_projects` | sync | Enumera el registro. |
| `project_status` | sync | Metadatos de un proyecto. |
| `dispatch` | **<100ms** | Envía un prompt al agente de un proyecto. Soporta anulación de agente por envío y cadena de respaldo. Devuelve `dispatch_id` de inmediato. |
| `check_dispatch` | sync | Poll a un envío — `running` / `complete` / `error` con salida completa. |
| `list_dispatches` | sync | Todos los envíos activos + recientemente completados. |
| `cancel_dispatch` | sync | Aborta un envío en ejecución. |
| `dispatch_history` | sync | Últimos N envíos para **un proyecto** (lee su log jsonl). |
| `orchestration_history` | sync | Instantánea del portafolio: en vuelo + hitos recientes entre proyectos + conteos por proyecto. Llámalo para "¿cómo va todo?". |
| `list_project_sessions` | sync | Enumera las sesiones de conversación reanudables del agente para un proyecto, incluyendo un fragmento `preview` breve de intento máximo cuando está disponible. Usa el `id` devuelto con `dispatch(session_id=...)` para cambiar hilos. |
| `add_project` | sync | Registra un nuevo proyecto. Valida el nombre del agente. Confía automáticamente en dirs de codex. |
| `update_project` | sync | Cambia el agente, descripción, tags, permission_mode, fallback, pin de `session_id`, o `language` de respuesta preferido de un proyecto existente. |
| `reorder_projects` | sync | Reordena el registro. Indulgente: los nombres listados se mueven al frente, los demás mantienen su orden relativo. El modo estricto requiere listar cada proyecto. |
| `remove_project` | sync | Deregistra un proyecto. |

### Cómo funciona dispatch

```
dispatch("my-app", "add error handling to auth")
  → subprocess.Popen(["claude", "-p", "...", "--continue"], cwd="~/Projects/my-app")
  → devuelve {dispatch_id: "a1b2c3d4"} en <100ms
  → hilo en segundo plano captura stdout cuando el proceso termina
  → check_dispatch("a1b2c3d4") → {status: "complete", output: "...", duration_sec: 45}
```

### Agentes compatibles

| Agente | Invocación no interactiva | Flag modo `bypass` | Flag modo `auto` |
|---|---|---|---|
| `claude` | `claude -p "<prompt>" --continue` | `--dangerously-skip-permissions` | `--enable-auto-mode --permission-mode auto` |
| `codex` | `codex exec "<prompt>"` | `--dangerously-bypass-approvals-and-sandbox` | — |
| `gemini` | `gemini -p "<prompt>"` | `--yolo` | — |
| `droid` | `droid exec "<prompt>"` | `--skip-permissions-unsafe` | — |
| `opencode` | `opencode run "<prompt>" --continue` | `--dangerously-skip-permissions` | — |
| `hermes` | `hermes -z "<prompt>" --continue` | `--yolo --accept-hooks` | — |
| `gjc` | `gjc -p --mode=json -c "<prompt>"` | — (el modo print ejecuta herramientas sin supervisión) | — |

Los nombres de los agentes se validan en el momento del registro — errores tipográficos como `cursor-agent` son detectados inmediatamente, no en el momento del envío.

### Cambiar agentes a mitad de un proyecto

Puedes cambiar el agente registrado de un proyecto en cualquier momento — útil cuando un código base determinado resulta emparejarse mejor con un CLI diferente:

```
update_project(name="my-app", agent="codex")
```

`update_project` también acepta `description`, `tags`, `permission_mode`, y `fallback` — los campos omitidos permanecen intactos. Cambiar a `codex` agrega automáticamente el directorio del proyecto a la lista de confianza de `~/.codex/config.toml`.

### Anulación de agente para una sola ejecución

A veces quieres enrutrar *una* tarea a un agente diferente sin mutar el registro — p. ej. una tarea con mucho diseño va a un agente fuerte en diseño mientras el proyecto se queda en su usual:

```
dispatch(name="my-app", prompt="...", agent="codex")
```

La entrada del registro permanece intacta. El próximo envío sin `agent=` vuelve al agente guardado del proyecto.

### Cadena de respaldo ante fallos

Si el agente principal sale con código no cero (límite de tasa, tope de tokens, crash), central-mcp puede reintentar transparentmente con un respaldo:

```
# por envío (no se persiste):
dispatch(name="my-app", prompt="...", fallback=["codex", "gemini"])

# guarda un predeterminado para este proyecto:
update_project(name="my-app", fallback=["codex", "gemini"])
```

El resultado reporta qué agente produjo realmente la salida (`agent_used`), si se disparó un respaldo (`fallback_used`), y la lista completa de intentos. Los tiempos de espera *no* se reintentan — el usuario debería verlos directamente en lugar de quemar toda la cadena en un agente trabado.

Pasa `fallback=[]` para deshabilitar explícitamente la cadena guardada para un envío único.

### Modos de permiso

La mayoría de los agentes de programación preguntan "¿está bien?" antes de editar archivos, ejecutar comandos o instalar paquetes. Está bien cuando hay un humano en la terminal — pero en cualquier lugar donde ejecute central-mcp, no hay TTY para responder prompts de aprobación, por lo que el trabajo puede **quedarse colgado por siempre esperando una respuesta que nunca llega**. Cada instancia de agente que central-mcp genera (panel del orquestador o envío a nivel de proyecto) se ejecuta en uno de tres **modos de permiso**:

| Modo | Qué aprueba automáticamente | Cuándo usarlo |
|---|---|---|
| `bypass` | Todo. central-mcp emite su propia bandera de omisión de permiso de cada agente (ver mapeo más abajo). | Predeterminado. Más rápido. Sin defensa contra inyección de prompts. Disponible en cada agente compatible. |
| `auto` | Trabajo de archivos local al cwd, deps declaradas, HTTP de solo lectura, pushes a branches creados por Claude. Todo lo demás pasa por un **clasificador** en segundo plano que bloquea `curl \| bash`, despliegues a prod, force-push, borrados masivos en cloud, etc. | Repos sensibles donde la resistencia a inyección de prompts importa. **Solo soportado por `claude`** hoy (y solo con plan Team/Enterprise/API + **Sonnet 4.6 u Opus 4.6** — no Haiku, no 4.7, no proveedores de terceros). central-mcp rechaza `auto` para cualquier agente no-claude o cadena de respaldo. |
| `restricted` | Nada. Cualquier llamada de herramienta que normalmente preguntaría a un humano se niega y el agente muestra el error. | Endurecimiento para tareas de solo lectura — Q&A, explain-code, reportes. Writes/builds/shell fallarán. Disponible en cada agente. |

Cada proveedor marca su omisión de permisos de forma diferente — los `bypass`/`auto` de central-mcp son nombres unificados que mapean a la bandera correcta del proveedor por agente:

| Modo central-mcp | claude | codex | gemini | droid | opencode |
|---|---|---|---|---|---|
| `bypass` | Omitir permisos<br>`--dangerously-skip-permissions` | Omitir aprobaciones + sandbox<br>`--dangerously-bypass-approvals-and-sandbox` | YOLO<br>`--yolo` | Omitir permisos (inseguro)<br>`--skip-permissions-unsafe` | Omitir permisos<br>`--dangerously-skip-permissions` |
| `auto` | Modo auto<br>`--enable-auto-mode --permission-mode auto` | — | — | — | — |
| `restricted` | *(sin bandera)* | *(sin bandera)* | *(sin bandera)* | *(sin bandera)* | *(sin bandera)* |

Si un proveedor agrega un equivalente al modo `auto` de claude más tarde (codex sandbox-warn, gemini review-mode, etc), central-mcp lo conectará a este mismo alias `auto` — la configuración existente sigue funcionando.

Los modos se aplican en dos capas separadas:

#### 1. Capa del orquestador — `central-mcp run` / `central-mcp tmux` / `central-mcp up` / `central-mcp zellij`

Este es el agente *con el que* hablas — el panel del orquestador que llama a herramientas MCP. **Predeterminado: `bypass`.** Cámbialo con `--permission-mode`:

```bash
central-mcp tmux   --permission-mode auto        # solo claude, revisado por clasificador
central-mcp run    --permission-mode restricted  # sin auto-aprobación, los prompts se detendrán
central-mcp zellij --permission-mode bypass      # predeterminado explícito
```

Con el orquestador en `bypass`, el orquestador puede leer/escribir archivos libremente dentro de `~/.central-mcp` sin preguntar — por lo que `CLAUDE.md`, notas rápidas y ediciones a nivel de hub ocurren sin fricción. Con `auto` (solo claude + Sonnet/Opus 4.6), un clasificador en segundo plano verifica cada acción en lugar de una omisión total. `auto` es ignorado (no se emiten banderas) para orquestadores no-claude. El modo del orquestador **no** se propaga a los agentes de proyectos enviados; esos llevan su propio valor por proyecto.

#### 2. Capa de envío por proyecto — `dispatch(..., permission_mode=...)` / `registry.yaml`

Esto controla el agente generado dentro del cwd específico de un proyecto para un envío. El valor se guarda en `registry.yaml` en el primer envío (predeterminado: `"bypass"`) y se reutiliza para cada envío posterior a ese proyecto. Cámbialo en cualquier momento:

```
dispatch(name="my-app", prompt="…", permission_mode="bypass")      # auto-aprobar, guardar
dispatch(name="my-app", prompt="…", permission_mode="auto")        # solo claude, clasificador
dispatch(name="my-app", prompt="…", permission_mode="restricted")  # sin omisión, sin clasificador
update_project(name="my-app", permission_mode="auto")              # cambiar sin enviar
```

`"auto"` es rechazado con un error explícito si la cadena de agentes del proyecto incluye algo que no sea `claude` — central-mcp nunca degrada silenciosamente auto a bypass para un respaldo. Con `"restricted"`, los envíos de solo lectura aún funcionan (respondiendo preguntas, leyendo archivos, explicando código); cualquier cosa que preguntaría (edición, shell, deps) da timeout — reintenta con `bypass`/`auto`, o abre una terminal regular en el cwd del proyecto para aprobación interactiva.

> ### ⚠️ `bypass` es potente — y es bajo tu propio riesgo
>
> En modo `bypass` (en cualquier capa), el agente puede editar archivos, ejecutar comandos de shell, instalar paquetes, llamar a servicios de red y empujar código **sin confirmarte primero**. Eso es lo que hace posible la orquestación sin parar, pero también significa que un prompt mal dirigido, una inyección de prompt de una fuente maliciosa o una alucinación del agente puede causar daño real — tablas borradas, branches force-pushed, archivos eliminados, credenciales filtradas, gasto de API no intencional, etc.
>
> El modo `auto` es un punto intermedio — aún headless, pero un clasificador bloquea un conjunto estándar de patrones destructivos (ver la [docs de permission-modes de Claude Code](https://code.claude.com/docs/permission-modes) para la política predeterminada). Reduce el riesgo de inyección de prompts pero no lo elimina. `restricted` es el más seguro pero solo es útil para agentes que no necesitan escribir.
>
> Razonamiento típico:
> - **Modo del orquestador** controla lo que el agente a *nivel de hub* puede hacer en `~/.central-mcp` y al llamar a herramientas MCP. Menor riesgo en la práctica porque el dir del hub no tiene código de producción, pero aún es lectura/escritura.
> - **Modo por proyecto** controla lo que cada agente a *nivel de proyecto* puede hacer dentro del cwd de ese proyecto. Esta es la capa de mayor riesgo — puede reescribir tu fuente, ejecutar tu build, empujar branches.
>
> **Aléjate de `bypass` (a `auto` para claude, o `restricted`) si aplica alguna de estas**:
> - El proyecto (o `~/.central-mcp`) contiene código sensible, secretos o datos de producción que no puedes perder.
> - No hay un commit/push de red de seguridad en su lugar.
> - No leíste el prompt cuidadosamente o estás delegando trabajo de fuentes no confiables.
> - Quieres revisar cada comando que el agente está a punto de ejecutar.
>
> **Descargo de responsabilidad**: central-mcp es una capa de enrutamiento y no supervisa lo que hacen los agentes. Eres responsable del alcance, objetivos y consecuencias de cada envío que ejecutes en modo `bypass` (o `auto`) en cualquier capa. Los autores y contribuyentes de central-mcp no son responsables de ningún daño, pérdida de datos, brecha de seguridad, costo u otro perjuicio que resulte del modo seleccionado. Usa snapshots (commits de git, backups, protección de branches), credenciales de privilegio mínimo y entornos offline/sandboxed donde sea posible.

Si un proyecto trata con código sensible y no estás cómodo otorgando `bypass` global, cambia a `auto` (claude + Sonnet/Opus 4.6) o mantén `restricted` y quédate con envíos de solo lectura.

### Manejo de sesiones (continuidad de la conversación)

Por defecto, cada envío reanuda la conversación más recientemente modificada del agente en el cwd del proyecto — `claude --continue`, `codex exec resume --last`, `gemini --resume latest`, `opencode --continue`. **Droid es la excepción**: su exec headless no tiene "reanudar la última", por lo que un envío de droid sin un session id explícito siempre inicia un hilo fresco.

Cuando el usuario quiere cambiar a una sesión específica (o recuperarse de desviación ambiental — p. ej., una sesión interactiva en el mismo cwd movió la "última"), `dispatch(session_id=...)` es una **anulación de un solo envío**:

```
list_project_sessions("my-app")
  → [{id: "a1b2...", title: "auth refactor", preview: "Investigar timeout de login tras refresh", modified: "..."}, ...]

dispatch("my-app", "continuar desde ahí", session_id="a1b2...")
  # → claude -p "..." -r a1b2...
```

Después de ese envío, la sesión reanudada es ahora la más recientemente modificada — por lo que el **próximo** `dispatch("my-app", "...")` predeterminado la recoge vía `--continue` automáticamente. Solo vuelves a decir el id cuando quieres cambiar hilos.

`preview` está intencionalmente limitado y es de intento máximo, no un volcado de transcripción. Para agentes respaldados por sistema de archivos, usualmente viene de un mensaje reconocible temprano en el archivo de sesión; para backends solo CLI puede volver a caer en la salida tipo título del propio backend.

Para un comportamiento a prueba de desviaciones (o para droid, que necesita un pin persistente para mantener la continuidad), pin la sesión:

```
update_project("my-app", session_id="a1b2...")
# Todos los envíos futuros llevan -r/-s <id> sin importar el estado ambiental.

update_project("my-app", session_id="")
# Cadena vacía limpia el pin.
```

Precedencia de resolución al enviar: arg `session_id` explícita > `session_id` guardada del proyecto > bandera resume-latest del agente.

| Agente | Bandera de sesión específica | Fuente de lista de sesiones |
|---|---|---|
| `claude` | `-r <uuid>` | `~/.claude/projects/<slug(cwd)>/*.jsonl` |
| `codex` | `resume <uuid>` | `~/.codex/sessions/**/*.jsonl` filtrado por `cwd` en session_meta |
| `gemini` | `--resume <index>` | `gemini --list-sessions` (índices numéricos, no UUIDs) |
| `droid` | `-s <uuid>` | `~/.factory/sessions/<slug(cwd)>/*.jsonl` |
| `opencode` | `-s <uuid>` | `opencode session list` (global, no limitado a cwd) |

### Idioma de respuesta preferido (por proyecto)

Los valores predeterminados de dispatch se mantienen sin cambios: si no hay idioma pinneado o anulado, los agentes reciben el prompt original y responden en su propio idioma predeterminado (inglés para los agentes que central-mcp apunta hoy).

Cuando un proyecto necesita un idioma diferente de forma consistente, guárdalo en el registro:

```
update_project("my-app", language="Korean")
```

Cada envío predeterminado futuro a `my-app` ahora recibe un prefacio como:

```
Respond to the user in Korean.

<prompt original>
```

También puedes configurarlo en el momento del registro:

```
add_project("my-app", "~/Projects/my-app", language="Korean")
```

Comportamiento por envío:

```
dispatch("my-app", "summarize the current status")                     # usa el idioma guardado del proyecto
dispatch("my-app", "summarize the current status", language="Japanese")  # anulación de un solo envío
dispatch("my-app", "summarize the current status", language="")          # suprime el idioma guardado una vez
update_project("my-app", language="")                                    # limpia el pin de idioma guardado
```

La preferencia guardada vive en `registry.yaml` como metadato del proyecto, por lo que es práctica, explícita y compatible hacia atrás con registros más antiguos que simplemente omiten el campo.

### Historial de envíos (por proyecto)

Cada envío emite sus eventos `start` / `output` / `complete` hacia `~/.central-mcp/logs/<project>/dispatch.jsonl` (solo append). `dispatch_history` lee los eventos terminales de vuelta, fusionados con su `start` coincidente:

```
dispatch_history(name="my-app")          # últimos 10 envíos para my-app
dispatch_history(name="my-app", n=50)    # últimos 50
```

Para una vista entre proyectos, usa `orchestration_history` (abajo).

### Historial de orquestación (vista de portafolio)

Pregunta "¿cómo va todo?" en un solo disparo. Lee la línea de tiempo global en `~/.central-mcp/timeline.jsonl` (también solo append) más la tabla en vuelo en memoria del servidor:

```
orchestration_history()                  # en vuelo + últimos 20 hitos en todos los proyectos
orchestration_history(n=100)             # rebanada más ancha del historial
orchestration_history(window_minutes=60) # solo contar actividad en la última hora
```

La respuesta incluye: `in_flight` (ejecutándose ahora), `recent` (hitos más nuevos), `per_project` (conteos de enviado/exitoso/fallado/cancelado, último timestamp), y una instantánea del registro. El orquestador usa esto para escribir un resumen multi-proyecto en un solo pase.

### Consejo de rendimiento / costo: modelo más ligero para el orquestador

El trabajo del orquestador es enrutamiento — no necesita razonamiento de primer nivel. Con Claude Opus 4.7 los turnos ya aterrizan en ~2-3 segundos para enrutamiento, por lo que la latencia no es una razón fuerte para cambiar. La razón más fuerte es **tokens**: cada turno que toma el orquestador se cobra contra su modelo, y un turno de enrutamiento con un modelo más ligero es significativamente más barato. Ajustes opcionales:

| Cliente del orquestador | Consejo |
|---|---|
| Claude Code | `/model sonnet` — aún cómodamente rápido, materialmente menos tokens por turno de enrutamiento. `/model haiku` si quieres ir más barato y tu flujo de trabajo lo tolera. |
| Codex CLI | Usa un modelo más ligero (p. ej. variante `-spark`) vía `/model` o `config.toml`. |
| Gemini CLI | Usa Flash en lugar de Pro si tu cuenta lo ofrece. |
| opencode | Selecciona un modelo más rápido vía `-m provider/model` o en `opencode.json`. |

El modelo del subagente es independiente — cada `dispatch` genera su propio proceso con el modelo predeterminado del agente del proyecto, por lo que aligerar el orquestador no aligera a los subagentes.

## Referencia de CLI

```
central-mcp                        # sin arg → lanza orquestador (igual que `run`)
central-mcp run [--agent X] [--pick] [--permission-mode {bypass,auto,restricted}]
                                   # lanza orquestador (predeterminado: bypass; auto es solo claude)
central-mcp serve                  # ejecuta servidor MCP en stdio (usado por clientes MCP)
central-mcp install CLIENT         # registra con claude | codex | gemini | opencode
central-mcp alias [NAME]           # symlink de nombre corto (predeterminado: cmcp)
central-mcp unalias [NAME]
central-mcp init [PATH]            # andamia registry.yaml (predeterminado: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|droid|opencode|hermes|gjc]
central-mcp remove NAME
central-mcp reorder NAME [NAME ...]  # reordena proyectos — los no listados mantienen orden relativo
central-mcp list                   # volcado de registro de una línea
central-mcp brief                  # instantánea markdown lista para orquestador
central-mcp workspace list         # lista workspaces con conteos de proyectos
central-mcp workspace current      # imprime el workspace activo
central-mcp workspace new NAME     # crea un nuevo workspace
central-mcp workspace use NAME     # cambia el workspace activo
central-mcp workspace add PROJECT --workspace NAME
central-mcp workspace remove PROJECT --workspace NAME
central-mcp up [--no-orchestrator] [--permission-mode {bypass,auto,restricted}] [--max-panes N]
                                   # capa de observación tmux opcional (workspace activo)
central-mcp tmux [same flags as up] [--workspace NAME | --all]
                                   # crea sesión si falta, luego adjunta vía tmux
central-mcp zellij [same flags as up] [--workspace NAME | --all]
                                   # igual, pero vía zellij (genera un layout KDL)
central-mcp tmux switch NAME       # adjunta a sesión cmcp-<NAME> (crea si falta)
central-mcp zellij switch NAME     # igual, vía zellij
central-mcp down                   # mata todas las sesiones de observación cmcp-*
central-mcp watch NAME [--from-start]
                                   # emite eventos de envío de un proyecto
central-mcp upgrade [--check]      # auto-actualización desde PyPI (uv → pip fallback)
```

## Capa de observación opcional

### Por qué es *opcional*

- **El orquestador es la superficie principal.** `dispatch` / `check_dispatch` / `orchestration_history` devuelven resúmenes estructurados; el orquestador los convierte en estado en lenguaje natural — no se requiere scroll por stdout.
- **El trabajo debería ser posible desde cualquier lugar.** central-mcp está diseñado para que un teléfono/tablet por SSH sea suficiente para seguir avanzando. El hub no puede requerir un desktop multi-pane para funcionar.
- **Activa la observación solo cuando la vista en vivo realmente ayuda** — debuggear un agente trabado, tail-ear una migración larga, o compartir pantalla de la flota. Para operación normal añade ruido, no señal.

### Onboarding sugerido — comenzar con observación, migrar a solo orquestador

En tus primeras sesiones casi seguro *quieres* la vista en vivo. Ver los eventos de envío de cada proyecto pasar construye una sensación física de cómo el orquestador elige proyectos, cuánto tardan realmente los envíos, qué prompts producen salida útil y dónde las cosas tienden a trabarse. Trata la observación como una fase de construcción de confianza: `central-mcp tmux` (o `zellij`, o cmux — ver abajo) te da paneles lado a lado con el orquestador, para que puedas evaluar visualmente sus decisiones contra la salida cruda del agente en tiempo real.

Una vez que los resúmenes del orquestador comienzan a coincidir con lo que habrías verificado en los paneles de todos modos, deja la capa de observación. En ese punto has internalizado el pipeline, y trabajar solo desde el orquestador — desde cualquier terminal, en cualquier dispositivo, incluyendo un teléfono por SSH — es el modo para el que central-mcp fue diseñado. La capa de observación permanece a un comando de distancia (`central-mcp tmux` / `central-mcp zellij` / pedirle al orquestador en cmux) para los momentos específicos que aún se benefician de ella.

### Backends

Se soportan dos backends de multiplexación como comandos CLI:

- **tmux** — `central-mcp tmux` (crea la sesión si falta, luego adjunta)
- **zellij** — `central-mcp zellij` (genera un layout KDL, lanza una sesión zellij o adjunta a una existente)

Ambos producen el mismo layout lógico (tab hub + tabs de desbordamiento, paneles de proyectos ejecutando `central-mcp watch <project>`). Elige el que ya tengas instalado; puedes usar ambos desde diferentes terminales siempre que no compartan un nombre de sesión al mismo tiempo.

Las sesiones se nombran `cmcp-<workspace>` (p. ej. `cmcp-default`, `cmcp-work`). Pasa `--workspace NAME` para apuntar a un workspace específico, o `--all` para crear sesiones para cada workspace de una vez. `central-mcp tmux switch NAME` / `central-mcp zellij switch NAME` adjunta a `cmcp-<NAME>`, creando si falta.

Una tercera opción — **cmux** en macOS — no tiene su propio comando CLI: ejecutas `cmcp` dentro de cmux.app tú mismo y le pides al orquestador que construya los paneles de observación. Ver [Ejecutar dentro de cmux](#ejecutar-dentro-de-cmux) más abajo.

`central-mcp up` crea una sesión tmux `central` con:

- **Panel 0 — orquestador** (Claude Code / Codex / Gemini / opencode), lanzado en `~/.central-mcp` para que recoja el `CLAUDE.md` / `AGENTS.md` del hub.
- **Paneles 1…N — uno por proyecto registrado**, cada uno emitiendo la actividad de envío de ese proyecto en vivo vía `central-mcp watch <project>`. El prompt, salida, código de salida y duración de cada envío pasan en tiempo real.

Las ventanas se nombran `cmcp-<N>` con la primera ventana tomando un sufijo `-hub` (`cmcp-1-hub`) cuando contiene el orquestador — para que puedas decir de un vistazo a qué ventana saltar. Ciclo paneles con `Ctrl+b n` / `Ctrl+b <dígito>`. Cuando el registro tiene más proyectos de los que caben en una ventana, se agregan ventanas extra (`cmcp-2`, `cmcp-3`, …) automáticamente. `--max-panes N` establece un tope por ventana; sin él, central-mcp lee el tamaño de la terminal actual y elige cuántos paneles caben por encima del piso de legibilidad (~70 cols × 15 filas por panel — afinado para que un laptop de 13–15" en pantalla completa aterrice en 2 rebanadas de columna).

**Layout del orquestador**: la primera ventana pone el panel del orquestador en una columna izquierda de altura completa sized para coincidir con una columna de proyecto. Así `orch + 1 proyecto` reproduce una división 50/50, `orch + 3 proyectos` da cuatro columnas iguales (orch + 3 proyectos en una sola fila), y `orch + 9 proyectos` da a orch una columna 1/6 con una cuadrícula 2 × 5 de proyectos a la derecha.

```bash
central-mcp tmux                         # workspace activo → crea si falta, luego adjunta
central-mcp tmux --workspace work        # apunta a la sesión del workspace "work"
central-mcp tmux --all                   # crea/adjunta sesiones para cada workspace
central-mcp tmux switch work             # salta a cmcp-work (crea si falta)
central-mcp tmux --permission-mode auto        # solo claude; orquestador revisado por clasificador
central-mcp tmux --permission-mode restricted  # orquestador muestra prompts de aprobación
central-mcp tmux --no-orchestrator       # solo paneles de watch (sin orquestador)
central-mcp tmux --max-panes 6
central-mcp up                           # crea la sesión pero no adjunta (flujos scripteados)
central-mcp down                         # derriba todas las sesiones cmcp-*
```

La ventana del hub (`cmcp-1-hub`) usa el layout `main-vertical` de tmux: el panel del orquestador se sienta a la izquierda tomando espacio de dos celdas, y los paneles de proyectos se apilan a la derecha. Así el hub mantiene `panes_per_window − 1` paneles (predeterminado 3 — orquestador + 2 proyectos), y las ventanas de desbordamiento obtienen `panes_per_window` proyectos cada una. Cada panel lleva su nombre de rol en su borde superior, y el borde del orquestador se resalta en amarillo negrita para que lo notes de un vistazo.

Mata con `central-mcp down` — la ruta de envío MCP nunca depende de esta capa, por lo que derribarla no afecta envíos en vuelo. El comando `watch` es un tail de solo lectura de `~/.central-mcp/logs/<project>/dispatch.jsonl`; también puedes ejecutarlo standalone en cualquier terminal.

#### "<ENTER> to run, <Ctrl-c> to exit" en un panel de watch

Si un panel de watch de zellij muestra `<ENTER> to run, <Ctrl-c> to exit` en lugar de emitir eventos de envío, el hijo `central-mcp watch <project>` subyacente murió o nunca comenzó. Esta es la red de seguridad incorporada de zellij — mantiene el panel abierto (preservando scrollback) y espera acción explícita del usuario en lugar de respawnear o caer a un shell. No presiones ENTER: el panel está desconectado de su comando original en este punto, por lo que un re-run manual aquí no pip-back hacia central-mcp. En su lugar, reconstruye la sesión: `cmcp zellij` (derribo + reconstrucción automática — un comando). Cada panel respawnea con un hijo watch fresco.

#### Actualizar mientras una sesión de observación está adjunta

Solo importa si usas la capa de observación. Cada invocación `cmcp tmux` / `cmcp zellij` derriba incondicionalmente la sesión de observación previa (si la hay) y reconstruye al tamaño de la terminal actual antes de adjuntar, por lo que siempre terminas con paneles frescos llevando el binario recién instalado. `central-mcp upgrade` adicionalmente derriba la sesión de observación antes de reemplazar el binario, por lo que actualizar mientras ya estás adjunto también está cubierto.

Compromiso: si dos terminales están simultáneamente adjuntas a la misma sesión y una ejecuta `cmcp tmux`, la otra se desconecta. A cambio, "sesión estancada vs binario nuevo" no es algo en lo que nunca tengas que pensar.

### Ejecutar dentro de cmux

Solo macOS. [cmux.app](https://github.com/manaflow-ai/cmux) es una terminal GUI nativa diseñada para que los agentes gestionen sus propios paneles. El flujo:

1. Lanza cmux.app.
2. En un panel cmux, ejecuta `cmcp` — el orquestador (claude / codex / gemini) empieza dentro de cmux y hereda `CMUX_WORKSPACE_ID`.
3. Pídele al orquestador que active el modo de observación, p. ej. *"turn on observation mode"*.

El orquestador lee `~/.central-mcp/AGENTS.md` al lanzar — que incluye una receta consciente del tamaño de terminal para este flujo — y usa su herramienta Bash para encadenar `cmux new-split`, `cmux send`, y `cmux send-key` por proyecto. Esa receta intencionalmente ajusta cada workspace a cuadrículas balanceadas seguras de división por la mitad (`2×2`, `2×4`, `4×4`, etc.) en lugar de pedirle a cmux que finge tercios limpios de divisiones 50/50 repetidas. La nomenclatura de workspaces espejea la convención de ventana de tmux / zellij: el workspace propio del orquestador se renombra a `cmcp-hub`, y los paneles de observación van a workspaces dedicados nombrados `cmcp-watch-1`, `cmcp-watch-2`, … (uno por chunk de cuadrícula derivado del tamaño de terminal). cmux te deja tab-ear entre ellos desde su sidebar.

No existe un subcomando `central-mcp cmux`: central-mcp mismo se mantiene fuera del socket de cmux, el agente hace el trabajo. Si la configuración de paneles falla a mitad, el orquestador reporta qué proyectos tuvieron éxito y puedes pedirle que reintente los faltantes.

## Espacios de trabajo

Los workspaces te permiten agrupar proyectos en conjuntos nombrados y cambiar entre ellos sin editar el registro manualmente.

```bash
# Crea y pobla un workspace
central-mcp workspace new work
central-mcp workspace add api-server --workspace work
central-mcp workspace add frontend --workspace work

# Cambia el workspace activo
central-mcp workspace use work

# Inspecciona
central-mcp workspace list     # muestra todos los workspaces con conteos de proyectos y marcador activo
central-mcp workspace current  # imprime "work"
```

Los proyectos no asignados a ningún workspace nombrado caen al workspace `default` incorporado. `central-mcp workspace list` muestra ese conteo también.

**Nomenclatura de sesiones:** cada workspace obtiene su propia sesión de multiplexador — `cmcp-default`, `cmcp-work`, etc. El antiguo nombre de sesión `central` se mantiene como alias de compatibilidad hacia atrás y es limpiado por `central-mcp down`.

**Observación con workspaces:**

```bash
central-mcp tmux                  # solo workspace activo
central-mcp tmux --workspace work # workspace específico
central-mcp tmux --all            # una sesión por workspace simultáneamente
central-mcp tmux switch work      # salta directo a cmcp-work
```

El estado del workspace se almacena dentro de `~/.central-mcp/registry.yaml` (campo `current_workspace`) — no se necesita archivo de config separado.

## Resolución del registro

Cascada de tres niveles:

1. `$CENTRAL_MCP_REGISTRY` (anulación explícita)
2. `./registry.yaml` en cwd (anulación por proyecto)
3. `$HOME/.central-mcp/registry.yaml` (predeterminado global)

El registro es estado por usuario — nunca lo commitees.

## Cambiar el orquestador

```bash
central-mcp run --pick         # re-ejecuta picker, guarda nueva elección
central-mcp run --agent codex  # anulación de un solo envío
$EDITOR ~/.central-mcp/config.toml
```

## Variables de entorno

- `CENTRAL_MCP_HOME` — dir de estado del usuario (predeterminado: `~/.central-mcp`)
- `CENTRAL_MCP_REGISTRY` — anulación de ruta del registro

## Desarrollo

```bash
uv tool install --editable .
uv run --group dev pytest             # 141 unit tests (rápido, sin CLIs reales)
uv run --group dev pytest -m live     # 20 live tests — shell out a binarios reales de agentes
                                      # (claude/codex/gemini/droid); cada caso salta
                                      # limpiamente si ese binario no está en PATH
```

## Licencia

MIT.
