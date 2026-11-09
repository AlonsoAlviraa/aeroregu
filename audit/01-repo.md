# Parte A — Repositorio y código

El recorrido de las fórmulas, la demo y el candado numérico está en `05-codigo.md`.

Etiquetas: VERIFICADO = ejecutado o leído en esta sesión el 9 nov 2026. El puntuador está en este árbol, `C:\Users\Mariano\Documents\ALONSOO\AIRBUS\evidence-layer`. El nombre publicado es aeroregu. La ruta `C:\Users\Mariano\Documents\ALONSOO\evidence-layer` no contiene el módulo. No hay commit, así que no hubo `git worktree`. Los tests corrieron en el árbol de trabajo, que está sucio respecto del índice.

## 1. Higiene de git

Comandos: `git rev-parse HEAD`, `git status -sb`, `git diff --cached --name-only`, `git config --get user.name`, `git config --get user.email`.

- VERIFICADO: `fatal: your current branch 'master' does not have any commits yet`. No hay hash.
- VERIFICADO: índice con 188 rutas (`git diff --cached --name-only | Measure-Object`). Coincide con la cifra del fundador del 3 nov 2026. Origen probable: el propio árbol, añadido con `git add` y nunca confirmado. Hay además entradas `AM` (en el índice y modificadas en el trabajo) y 69 rutas sin seguimiento, entre ellas `bench/b1`–`b4`, `docs/benchmarks/`, `docs/reports/`, `packages/eval/src/evidence_eval/s1.py` y gran parte del código que los informes citan.
- VERIFICADO: `user.name` y `user.email` no devuelven valor (código de salida 1). No hay identidad de commit configurada en el alcance que Git consultó.
- `.gitignore` ignora `.env`, `/data/`, PDF con `easa` en el nombre, modelos y `*.sqlite3`. VERIFICADO por lectura del fichero. `/data/` existe en disco y no aparece en el índice. Contiene, entre otros, `data\ntrs\NASA-TM-101040.pdf` (5 626 079 bytes), `data\ntrs\NASA-19890004039.pdf` (1 793 780), `data\b4\data_SSF.zip` (16 579 962), `data\as365\DataFiles_Type58UFF_AS365K2_AccelData.uff` (29 495 500) y `data\tenants\demo.sqlite3`. Esos binarios no se han abierto en esta auditoría más allá del listado.

## 2. Secretos

- `gitleaks` y `trufflehog`: no están en el PATH. NO VERIFICADO como escáner de esos productos.
- VERIFICADO: `python tools/security/secret_scan.py` imprimió `secret scan ok`. Ese script busca formas de clave (AKIA, PEM, `sk-`, Slack, GitHub, `api_key=`). No es un escáner completo.
- Hallazgo aparte, no es una clave filtrada de un proveedor: la demo fija un secreto de sesión y contraseñas de actores en el código. Ver sección 11. En este informe el literal va como [REDACTADO]. Evidencia: `apps/api/src/evidence_api/app.py` líneas 192–193 y 261–262.

## 3. Empleador y confidencialidad

No se ha abierto el cuerpo de los documentos de la carpeta `AIRBUS` salvo `regulacion/prompt.md`, el registro regulatorio y el vault. Identificación por nombre:

- `AIRBUS\proyecto-ia-helicopteros.pdf`
- `AIRBUS\proyecto-ia-helicopteros.docx`
- `AIRBUS\paginas\03-airbus-agentes-atajos-30m.md` y el `.docx` homónimo
- el resto de `AIRBUS\paginas\01` a `07`

`docs/data_register.md` dice que no se importa esa carpeta y rechaza el dataset público «ETH-Airbus-accelerometer» por titularidad de Airbus SAS. Eso es una regla escrita. No demuestra que ningún fragmento haya entrado antes. No se ha pasado `exiftool` ni `pdfinfo` (no comprobados en esta sesión) sobre los PDF de empleador, a propósito: la regla es no abrirlos más de lo necesario para identificarlos.

Dentro de aeroregu, la búsqueda de `ITAR`, `confidential`, `proprietary` y `Airbus` en código y docs cae en el registro de datos y en la negativa a usar ese dataset. No se ha visto un PDF de empleador dentro del repo.

## 4. Tests

No hay `pyproject` de entorno limpio separado: se usó el `.venv` ya presente (`uv 0.9.20`, Python 3.11.9).

Tres ejecuciones, VERIFICADO. Las dos que valen son la primera y la tercera. La del medio falló por un fichero de esta auditoría, no por el producto.

```text
1) uv run pytest -q --tb=line -p no:cacheprovider
   153 marcas en la barra (72+72+9), 1 aviso StarletteDeprecationWarning, exit 0, 235,6 s

2) la misma orden, con audit/repro/run_audit_metrics.py ya escrito
   FAILED test_product_code_appends_only_through_the_orchestrator
   el escáner vio la cadena ledger.append en ese script
   exit 1, 175,1 s
   salida: audit/repro/out/pytest-2.txt

3) la misma orden, después de quitar esa cadena del script
   160 marcas (72+72+16), el mismo aviso, exit 0, 203,6 s
   salida: audit/repro/out/pytest-2-clean.txt
```

El recuento de `def test_` en el árbol es 160, y coincide con la tercera barra. La primera barra se quedó en 153. No hay un diff de tests entre medias que explique las 7 marcas. Una de las funciones es de Hypothesis (`max_examples=25` en `test_rigid_body_point_mass.py`): en `-q` cuenta como un ítem, no como 25. SUPUESTO: la diferencia 153/160 es de recolección o de cómo se grabó la barra, no un fallo de aserción. Las dos pasadas limpias salieron 0. No son bit a bit el mismo número de marcas.

La cifra «68 tests» del 3 nov 2026 está superada. No es un fallo de la suite; es una afirmación vieja.

El guardián que falló en la pasada 2 hace lo que dice: cualquier `.py` fuera de `tests/` y fuera de la lista blanca, si contiene `ledger.append`, rompe la suite. Un script de reproducción metido en `audit/`, que es donde el prompt manda ponerlo, entra en ese barrido. El orquestador no es el único escritor si el barrido no mira también `app.py` con otra forma de llamada. `app.py` usa `record(`, y el test solo busca el texto `ledger.append`. Eso deja pasar una llamada que no use esa cadena. VERIFICADO por lectura del test.

## 5. Benchmark

Definición escrita, VERIFICADO en `docs/benchmark_spec.md` y en `evidence_eval.detect.llm_numeric_violations`: cuenta turnos de agente con un número físico que no es copia exacta de un `Decimal` producido por el código determinista. Valor exigido: 0.

Test negativo, VERIFICADO en `packages/eval/tests/test_score.py`, `test_llm_numeric_violation_is_counted`: un turno con `"9.999"` sobre un caso `bolt_screen` debe contar 1.

Dos pasadas del score de `bench/dev`, VERIFICADO el 9 nov 2026 (`audit/repro/out/score_dev_two_runs.json`):

- ambas: `false_alarms` 0, `llm_numeric_violation` 0, `mismatches` [], recall 1.0 en `unit_scale`, `arithmetic`, `wrong_input`, `sign`, `outside_validity`, abstenciones 2/2
- tiempos 0,587 s y 0,673 s
- los dos informes coinciden

Ese conjunto lo escribe `evidence_eval.generate`, el mismo paquete que `detect.py`. `docs/benchmark_spec.md` lo dice. `bench/holdout` no se puntúa (`main` devuelve 2). `bench/b1/expert_holdout` no es el número que se reporta. Con 4 casos limpios históricos, un 0 de falsos positivos tiene un intervalo de Wilson (z = 1,96) de 0 a aproximadamente 0,49. La cuenta usada aquí es la fórmula de Wilson; el 4 es el recuento de ficheros `*clean*` del índice, no una medida nueva de S1.

S1, dos pasadas, VERIFICADO en `audit/repro/out/s1_two_runs.json`: informes idénticos. 100 000 casos, generador `s1@1.0.0`, recall 7000/7000 en cada fallo puntuado, `missing_input` 0/0, línea base ingenua 0/7000, falsos positivos con tasa 0.000, `llm_numeric_violation` 0, compuesto 1.000, dificultad 29000/29000, 49000/49000 y 22000/22000. Tiempos 1031 s y 453 s: la primera compartió CPU con pytest. El campo `date` del informe sale `2026-11-03` aunque la corrida es del 9 nov. Esa fecha está escrita en el código, no es el día del proceso.

El intervalo de Wilson que el código imprime para la tasa de falsos positivos es 0.000–0.000. Con 8 000 casos limpios y cero fallos, el límite superior sin redondear (z = 1,96) es aproximadamente 0,00048. Al cuantizar a tres decimales, el intervalo publicado se vuelve un punto. VERIFICADO el 0.000 del JSON; el 0,00048 es la fórmula aplicada a n = 8 000, que es `_N_CLEAN` en `s1.py`.

`S1_SEED = 20261103` se copia al informe. `iter_cases` no lo usa. `seed_changes_output` en el JSON es una constante del script de auditoría, no un experimento con otra semilla. No hay forma de cambiar la semilla sin editar el código auditado.

`make bench` escribe `docs/benchmarks/` y `docs/reproducibility/manifest.json`. No se ha lanzado, para no modificar el árbol auditado.

Líneas base: el score de desarrollo compara con `naive_assess` dentro de `make bench`. En la corrida corta de esta auditoría solo se llamó a `score_cases` del checker. Una línea de un solo LLM en vivo está marcada NOT VERIFIED por el propio `docs/pilot/proposal.md`. No se ha medido latencia ni coste por caso contra un modelo de red. `MODEL_BASE_URL` vacío deja el gateway en fixtures.

## 6. Determinismo

VERIFICADO por lectura y por `packages/calc/tests/test_no_float.py`: el cálculo de cargas usa `Decimal`. La búsqueda de `float(` en `packages/` solo encuentra `gateway.py`, la temperatura que se envía al cliente HTTP. Las dos pasadas del score de desarrollo coincidieron. S1, por construcción, no tiene azar: dos pasadas deben coincidir. La temperatura de los cuatro agentes se registra como la cadena `"0"` en `supervisor.py`. En fixtures no hay modelo ni versión de modelo; hay hash del prompt.

## 7. Ledger

VERIFICADO en esta sesión (`audit/repro/out/ledger_tamper.json`): un evento nuevo verifica; tras `DROP TRIGGER` y un `UPDATE` del cuerpo, `verify()` devuelve falso. Los tests del repo también rechazan `UPDATE` y `DELETE` mientras el trigger existe.

Eso no prueba que el número de origen sea cierto, ni quién lo escribió fuera de la máquina, ni que el fichero SQLite no haya sido sustituido entero por otra cadena coherente. La firma humana exige la frase fija `reviewed this event` y prohíbe la palabra `compliant`. No comprueba la competencia ni la autorización de la persona.

## 8. Cobertura de 405 celdas

VERIFICADO en `packages/coverage/src/evidence_coverage/grid.py`: 3 masas × 3 centros de gravedad × 3 altitudes × 3 factores de carga × 5 estados de unidad = 405. El comentario del código dice ASSUMPTION. `test_default_grid_has_405_cells` exige 405 huecos. La criticidad la elige ese producto cartesiano, no una especificación de certificación. No es el juicio de VTOL.2210 ni de VTOL.2215. El README ya dice que los métodos de carga son ilustraciones.

## 9. Agentes

VERIFICADO en `agents.py` y `supervisor.py`: reader, checker, refuter y scribe. Pueden abstenerse (`CaseAbstain`, esquema inválido, desacuerdo de etiquetas, ataque del refuter). Los cuatro pasan por un solo `gateway_from_env`: o `FixtureGateway` o un único `OpenAICompatibleGateway` si hay `MODEL_BASE_URL`. No son modelos distintos. El orquestador (`orchestrator.record`) es quien llama a `Ledger.append`. El comentario del módulo dice que los agentes especialistas no importan el ledger. No se ha hecho una prueba de importación estática más allá de esa lectura; es SUPUESTO que ningún otro módulo de producto escriba eventos, salvo `app.py`, que también llama a `record`.

## 10. Licencias

`uv run pip-audit` el 9 nov 2026 terminó con código 0 y el texto «No known vulnerabilities found». Saltó los siete paquetes del propio workspace (`evidence-api`, `evidence-calc`, `evidence-coverage`, `evidence-domain`, `evidence-eval`, `evidence-ingest`, `evidence-kernel`) porque no están en PyPI. La salida está en `audit/repro/out/pip-audit.txt`. Eso cubre las dependencias de terceros que pip-audit pudo resolver. No cubre el código propio.

El inventario declara sobre todo MIT, Apache y BSD. La excepción vista es `certifi` 2026.10.23, MPL-2.0. No ha aparecido GPL, AGPL ni una licencia de uso no comercial en esas cadenas. Una cadena vacía o un clasificador que no leí no queda cubierta: el fichero tiene 140 distribuciones.

## 11. Seguridad básica

- VERIFICADO: `apps/api/src/evidence_api/__main__.py` usa `host="0.0.0.0"`, puerto 8000.
- VERIFICADO: `open_ledger()` crea actores `author` y `reviewer` con contraseña [REDACTADO] cada vez que se abre el libro.
- VERIFICADO: `_secret()` usa la variable de entorno o, si falta, [REDACTADO].
- VERIFICADO: `POST /ledger/append` exige cookie. `POST /export/zip` no recibe `Request` y devuelve `chain.json` del tenant `demo`.
- `POST /calc/run` y `POST /case` no aparecen protegidos en el fragmento leído. SUPUESTO de alcance: la demo no distingue inquilinos reales (constante `DEMO_TENANT`).
- `pip-audit` el 9 nov 2026: sin vulnerabilidades conocidas en lo que pudo auditar. Los paquetes locales quedaron fuera. Ver sección 10.

## Lo que esta parte no da por superado

`gitleaks` sigue sin estar en el PATH. Los PDF de la carpeta del empleador no se han abierto. La semilla de S1 no se puede cambiar sin editar `s1.py`. `make bench` no se ha lanzado porque reescribe `docs/benchmarks/`. El checkout no es limpio: no hay commit del que colgar un worktree.
