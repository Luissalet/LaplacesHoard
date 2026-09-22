# AGENTS.md

Reglas para agentes de código que trabajen en este repositorio.

## No negociable

- **Software real y probado.** Nunca añadas un stub presentado como
  funcionalidad terminada. Si algo queda fuera de alcance, dilo en el README
  (columna "Boundary"), no lo escondas.
- **Windows es el objetivo de producción.** El código debe funcionar igual
  en Linux (donde se desarrolla) y en Windows (donde se ejecuta): usa
  siempre `pathlib`, `encoding="utf-8"` al abrir texto, y evita rutas o
  scripts que solo funcionen en un shell.
- **Local y privado.** La app escucha solo en `127.0.0.1`. No añadas
  telemetría ni llamadas de red que el usuario no haya pedido
  explícitamente.

## Motores (`laplaces_hoard/engines/*.py`)

- No importan FastAPI. Son funciones puras que reciben tipos de Python y
  devuelven `dict`s JSON-safe. Así se pueden probar sin levantar un
  servidor y se reutilizan igual desde la API HTTP y desde los tests.
- Cualquier expresión de usuario (calc, math) pasa por
  `engines/safe_ast.py`. Nunca añadas una ruta que llame a `eval` o
  `sympify` sobre texto sin pasar antes por el whitelist de nodos AST.
- Todo lo que evalúa texto del usuario (`calc`, `units`, `math`) se
  ejecuta en el proceso de trabajo con límite de tiempo, a través de
  `engines/sandbox.py`. Si añades una operación, pásala por
  `sandbox._execute()`; nunca la ejecutes directamente en el proceso del
  servidor (SymPy y Pint pueden colgarse o agotar la memoria).
- El catálogo de DuckDB mantiene una sola conexión abierta: de solo lectura
  y sin acceso a archivos para consultar, de escritura solo mientras se
  registra un dataset. No cambies `enable_external_access` en una conexión
  abierta: DuckDB no permite volver a activarlo.

## API (`laplaces_hoard/api.py`)

- Toda herramienta vive en `POST /api/agent/<tool>` (adaptador MCP) y,
  con el mismo código, en `POST /api/ui/<tool>` (interfaz web). La interfaz
  nunca debe llamar a `/api/agent/*`: esas llamadas se registran como del
  asistente y aparecen en "Actividad del asistente".
- Los errores siempre son `{"error": "<código>", "message": "<texto>"}`,
  con un mensaje que diga qué cambiar.
- Cada llamada debe quedar registrada en el work log (`db.log_computation`)
  con `source="agent"` o `source="ui"`, éxito o error. No añadas un endpoint
  agente-facing que se salte este registro.
- Antes de tocar la gate de SQL (`engines/data.py::gate_sql`), lee
  `docs/ARCHITECTURE.md#the-sql-gate`: DuckDB clasifica `PRAGMA` como tipo
  `SELECT`, así que la gate también filtra por palabra clave, no solo por
  tipo de sentencia.

## Tests

- `pytest -q` debe tardar menos de 90s y no necesitar red.
- Si tocas `mcp_server.py`, vuelve a correr
  `tests/test_mcp_protocol.py` — es la única prueba que habla el protocolo
  MCP de verdad (spawn por stdio contra una instancia real de la app), no
  solo importa las funciones de Python.
- Todo commit que cambie `faustus-plugin.json` debe pasar
  `tests/test_manifest.py`.

## Commits

Identidad fija: `Luissalet <luissalet@users.noreply.github.com>`, rama
`main` únicamente, mensajes en inglés con prefijo convencional
(`feat:`, `fix:`, `test:`, `docs:`, `chore:`). Nunca menciones productos de
la competencia ni datos personales en el mensaje.
