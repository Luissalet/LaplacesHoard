# Laplace's Hoard

### ¿Te fiarías de la aritmética de un modelo de lenguaje? Este no tiene por qué.

**Una herramienta local de calculadora exacta, matemática simbólica, unidades,
estadística y SQL sobre archivos locales para un espacio de trabajo de LLM —
cada cálculo es exacto cuando la exactitud es posible, y queda registrado con
un id que el modelo puede citar y una persona puede volver a ejecutar.**

[English](README.md) · [Ejecutar en local](#ejecutar-en-local-en-windows) · [Conectar una IA](docs/MCP.md) · [Portfolio](https://luissalet.github.io/Portfolio/#projects)

![Cuaderno de Laplace's Hoard, con una conversión de unidades, una factorización simbólica y un cambio porcentual exacto](docs/media/notebook.png)
*Aplicación real, datos de demostración (`--demo`), cálculos reales.*

## Por qué

Los modelos de lenguaje son malos haciendo aritmética, peores haciendo
estadística, y "resumen" tablas mirando por encima las primeras filas.
Pregúntale a uno cuánto es el 15% de 2.347, o si un p-valor de 0,03 es
"significativo", o cuántos días laborables hay entre dos fechas en Madrid,
y responderá con fluidez y a veces mal. Laplace's Hoard da al modelo motores
que son *exactos* — `0.1 + 0.2` se calcula como el racional exacto `3/10`,
no como una aproximación de punto flotante — o explícitamente aproximados
con una precisión indicada, y **registra cada cálculo** con un id
(`L-000042`) para que una respuesta pueda citar su fuente y una persona
pueda abrir el mismo cálculo en la interfaz y repetirlo.

## Qué está implementado

| Área | Disponible ahora | Límite |
| --- | --- | --- |
| Aritmética exacta (`calc`) | +,-,*,/,//,%,**, comparaciones, porcentajes (`pct`, `pct_change`, `ratio`), `sqrt cbrt root exp log ln log10 log2`, trigonometría, `floor ceil round abs min max sum mean median factorial binomial gcd lcm mod isprime nextprime factorint`. Cada literal es un `Rational`/`Integer` exacto, nunca un float con pérdida. Pasa por un parser AST con lista blanca — nunca `eval`/`sympify` sobre texto sin procesar. | Sin variables en `calc` (usa `math`); precisión limitada a 1000 cifras significativas. |
| Matemática simbólica (`math`) | `simplify expand factor apart together solve nsolve diff integrate limit series summation product matrix (det/inv/rank/rref/eigenvals/transpose/multiply) dsolve inequality`. `solve` verifica cada raíz por sustitución. Cada llamada corre en un proceso worker con un timeout estricto que se autorrecupera si SymPy se cuelga. | `dsolve` solo cubre ecuaciones diferenciales de primer orden escritas como `dy/dx = f(x, y)` con símbolos normales (convención documentada) — la sintaxis de SymPy `y(x)`/`Derivative()` se deja fuera del parser seguro a propósito. |
| Unidades (`units_convert`) | Conversión con Pint, cantidades compuestas ("5 ft 11 in"), desplazamientos de temperatura correctos, comprobación de consistencia dimensional, listado de unidades compatibles. | Sin conversión de divisas — los tipos de cambio varían y necesitan acceso a red que esta herramienta local no realiza por sí sola. |
| Fechas (`date_calc`) | Diferencias con calendario, sumar días/semanas/meses/años, días laborables excluyendo fines de semana y festivos (España/Madrid por defecto, cualquier país/comunidad), día de la semana, semana ISO, edad, conversión de zona horaria IANA, parseo de texto libre. | Los calendarios de festivos llegan hasta donde cubre el paquete `holidays`. |
| Estadística (`stats`) | `describe ttest_1samp ttest_ind (Welch) ttest_rel mannwhitneyu wilcoxon chi2_contingency fisher_exact pearson spearman linregress proportion_ci (Wilson) normal_ci binom_test`, con números directos o una columna de un dataset registrado, con una interpretación neutra de una línea. | La interpretación indica solo significación — nunca tamaño del efecto ni causalidad más allá de lo que reporta SciPy. |
| Catálogo de datos (`data_*`) | Registra CSV/TSV/Parquet/JSON/NDJSON/Excel (por hoja)/SQLite (por tabla)/una carpeta con patrón como dataset; esquema + perfil por columna (% de nulos, distintos, min/max, media/desviación, top-5 valores); SQL de solo lectura limitado a `SELECT`/`WITH`/`DESCRIBE`/`SUMMARIZE`/`EXPLAIN`/un `PIVOT`; gráficos (barras/líneas/área/dispersión/histograma/tarta/mapa de calor) como PNG vía Vega-Lite. | Los archivos de más de 1 GB se consultan como `VIEW` perezosa ("linked") en vez de materializarse; la garantía de solo lectura se aplica mediante la validación de sentencias más una transacción que siempre se deshace, en vez de una segunda conexión DuckDB de solo lectura a nivel de sistema operativo (esta versión de DuckDB rechaza dos conexiones con configuración distinta al mismo archivo — ver `docs/ARCHITECTURE.md`). |
| Registro de cálculos | Cada cálculo (interfaz o asistente) recibe un id, aparece listado, es buscable y se puede volver a ejecutar desde la interfaz; las llamadas del propio asistente se muestran aparte en "Actividad del asistente" para auditoría. | Las entradas del registro se limitan a 20.000 caracteres de entrada/salida cada una. |

## Conectarlo a Faustus

Laplace's Hoard se declara a Faustus mediante `faustus-plugin.json` en la
raíz del repositorio. Arranca la aplicación y en Faustus:
**Conectores → Aplicaciones cercanas → Añadir**.

También funciona con cualquier cliente MCP (stdio) — ver
[docs/MCP.md](docs/MCP.md) para la tabla completa de herramientas y un
fragmento de configuración. Cada resultado lleva un id como `L-000042`,
pensado para citarse como `[L-000042]`.

| herramienta | solo lectura | qué hace |
| --- | --- | --- |
| `calc` | sí | Aritmética exacta y porcentajes |
| `math` | sí | Matemática simbólica (resolver, cálculo, matrices) |
| `units_convert` | sí | Conversión de unidades |
| `stats` | sí | Estadística descriptiva y pruebas de hipótesis |
| `date_calc` | sí | Aritmética de fechas, días laborables, zonas horarias |
| `data_list` | sí | Listar datasets registrados |
| `data_register` | no | Registrar un archivo/carpeta como dataset |
| `data_describe` | sí | Esquema, perfil, filas de muestra |
| `data_query` | sí | SQL de solo lectura |
| `data_chart` | sí | Gráfico como imagen |
| `work_log` | sí | Recuperar un cálculo anterior por id |

## Ejecutar en local en Windows

Haz doble clic en **`Iniciar Laplace's Hoard.cmd`** (crea el entorno
virtual, instala dependencias, construye la interfaz la primera vez, y
luego arranca la aplicación y abre una pestaña del navegador), o desde
PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-lock.txt
cd frontend; npm ci; npm run build; cd ..
.venv\Scripts\python -m laplaces_hoard
```

Añade `--demo` para ejecutar con datos sintéticos de muestra en vez de los
tuyos (`data-demo/` en vez de `data/`), o `--port 8813 --data-dir D:\ruta`
para cambiar los valores por defecto. `--no-browser` evita abrir una
pestaña automáticamente.

## Arquitectura

FastAPI + un conjunto de motores en Python puro (sin imports de FastAPI) +
SQLite para el registro/cuaderno + DuckDB para el catálogo de datos. Ver
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para el modelo de datos, el
diseño con proceso worker para la matemática simbólica, las reglas exactas
de la validación SQL y la protección contra ataques desde el navegador.

## Tests

```
.venv/bin/python -m pytest -q
```

83 tests, todos sin red, ~9 segundos. Cubren: la lista blanca del AST
(rechaza `__import__`, acceso a atributos, lambdas, comprensiones, nombres
desconocidos); aritmética decimal exacta (`0.1 + 0.2 == 3/10`); verificación
de `solve` por sustitución; el timeout y recuperación del worker simbólico;
los desplazamientos de temperatura de Pint; el t-test de Welch coincidiendo
con SciPy al bit; días laborables excluyendo un festivo real de Madrid; la
validación SQL contra cada tipo de sentencia peligrosa
(`ATTACH`/`COPY`/`INSTALL`/`LOAD`/`PRAGMA`/múltiples sentencias/...); hoja
de Excel → dataset, tabla de SQLite → dataset, carpeta con patrón →
dataset; números de perfil comprobados contra una tabla conocida; los bytes
mágicos del PNG del gráfico; el validador del manifiesto
`faustus-plugin.json`; y el protocolo MCP completo — el adaptador lanzado
por stdio real contra una instancia viva de la aplicación, listando
herramientas y llamando a `calc` y `data_query`.

## Privacidad y límites

Solo escucha en `127.0.0.1`. Sin telemetría, sin acceso a red salvo que una
función lo necesite explícitamente (actualmente ninguna lo hace — los tipos
de cambio y la descarga de calendarios de festivos quedan fuera de alcance
a propósito). Todos los datos se quedan en `data/` (ignorado por git) salvo
que indiques otra ruta con `--data-dir`. El middleware de protección contra
ataques desde el navegador rechaza el DNS rebinding (cabecera `Host`
incorrecta) y las escrituras cross-site (`Origin`/`Sec-Fetch-Site`
incorrectos en peticiones que no son GET) en todas las rutas.
