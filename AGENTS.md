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
- Los cálculos simbólicos (`symbolic.py`) corren en el worker con timeout
  (`worker.py`). Si añades una operación nueva, debe pasar por
  `_execute()`/`_DISPATCH`, nunca ejecutarse directamente en el proceso
  principal (SymPy puede colgarse).

## API (`laplaces_hoard/api.py`)

- Toda operación agente-facing vive en `POST /api/agent/<tool>` y debe
  devolver exactamente lo que el adaptador MCP expone — así el mismo test
  (`TestClient`) cubre ambos caminos.
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
