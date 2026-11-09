# Código de aeroregu, leído entero el 9 nov 2026

Árbol: `C:\Users\Mariano\Documents\ALONSOO\AIRBUS\evidence-layer`. El nombre publicado es aeroregu. La ruta hermana `C:\Users\Mariano\Documents\ALONSOO\evidence-layer` no contiene el puntuador. Esto completa la Parte A con lo que el código hace. No es asesoramiento jurídico.

Paquetes leídos: `kernel`, `calc`, `coverage`, `ingest` (contrato), `eval`, `domain`, `apps/api`, `schemas` por el uso que hace el ledger, CI, `tools/security`. Los 160 `def test_` y las dos pasadas de S1 siguen como en `01-repo.md`.

## Qué está construido

Dos métodos de cribado, un libro SQLite con hash, cuatro agentes de fachada sobre un solo gateway, una rejilla de 405 ids, un generador S1 y una demo FastAPI. El README y las tarjetas dicen que no es un método de certificación. Esa frase coincide con el código: las fuentes de las tarjetas tienen `content_hash: "assumption"`.

## Fallos dentro del cálculo

**La altitud no entra en la cuenta.** En `rigid_body_point_mass.py`, `altitude_m` se valida y el valor se tira. La fuerza es `masa * gravedad * factor de carga`. El momento usa la posición del centro de gravedad y de las unidades. La rejilla varía la altitud en tres escalones (`0`, `1500`, `3000`). Esos tres ids repiten la misma fuerza y el mismo momento. De 405 celdas, 135 cambian el resultado; las otras son copias por altitud. VERIFICADO por lectura de `grid.py` y de `run_rigid_body_point_mass`.

**El espesor del tornillo no entra en la cuenta.** `bolt_screen` exige `thickness_mm`, rechaza espesor no positivo y no lo usa. La tensión es fuerza partida por `area_mm2`. Cambiar el espesor no cambia `interaction_ratio`. VERIFICADO por lectura de `run_bolt_screen`. La tarjeta lo lista como entrada con unidad.

**El momento no se juzga.** La tarjeta declara un solo invariante: el residuo vertical, dentro de un quantum. `moment_about_cg_n_m` se calcula y se devuelve con `confidence: "deterministic"` aunque el momento no esté equilibrado. Un caso puede estar «limpio» con un momento grande.

**Las unidades son opcionales.** `check_declared_units` vuelve de inmediato si el dictado no trae `_input_units`. `run_method` la llama siempre, y en el camino normal no hay nada que comprobar. Pint no revisa los números que salen de la demo. `same_unit` convierte la magnitud de Pint, que es un float, con `Decimal(str(magnitude))`. Eso no está en la multiplicación de la fuerza; sí está en la comparación de escala.

N/mm² como MPa, en el tornillo, es coherente. No es el fallo. El fallo es la entrada muerta.

## El candado de los números del modelo tiene un agujero

`llm_numeric_violations` usa `stray_physical_numbers`. El patrón es `-?\d+\.\d+`. Una cadena `"3"` o `"800"` no lleva punto y no cuenta. Un entero JSON sí cuenta, porque el `int` se marca siempre. El test negativo manda `"9.999"`, que sí lleva punto. Un modelo puede escribir un entero en texto y el contador sigue a cero. VERIFICADO por lectura de `numbers.py` y de `test_score.py`.

## Quién escribe el libro

`POST /calc/run` no mira la cookie. Si el cuerpo lleva `record` o `example=first_cell`, llama a `record(...)` con `actor_id` del cuerpo (por defecto `author`) y, si hay celda, `set_cell_status` con `actor_role="human"`. Quien alcance el puerto appende eventos y marca celdas como si fuera la persona.

Sin cookie también: `GET /requirements`, `GET /aircraft`, `GET /coverage/gaps`, `POST /notes/check`, `POST /export/zip`, `GET /`.

Con cookie: `POST /supervisor/run` y `POST /ledger/append`. El supervisor compara el actor del cuerpo con la cookie. El append del cálculo no.

`__main__.py` escucha en `0.0.0.0:8000`. El secreto de sesión y las contraseñas de demostración siguen fijos en `app.py`.

La sal de la contraseña es `sha256(tenant_id:actor_id)`, no un aleatorio. `ensure_actor` hace `ON CONFLICT DO NOTHING`: la primera contraseña se queda. PBKDF2 con 20 000 vueltas. VERIFICADO en `ledger.py`.

El test `test_product_code_appends_only_through_the_orchestrator` busca el texto `ledger.append`. `app.py` escribe con `record(`. El test no ve esa llamada. La pasada de pytest que falló el 9 nov lo hizo por el script de `audit/`, no por `app.py`.

`verify()` rehace la cadena de hashes. No ata el fichero a un reloj externo ni al PDF de origen.

## Agentes y dominio

`gateway_from_env` devuelve un fixture o un solo cliente HTTP. Los cuatro papeles son cuatro llamadas. El kernel no importa `evidence_domain`. La denylist de `tools/security/denylist_kernel.py` solo mira `packages/kernel`. `domain/names.py` rechaza una lista de nombres comerciales y cualquier ruta que contenga `AIRBUS`. Eso es un filtro de cadenas, no una revisión del disco.

`packages/domain/data/requirements.json` guarda identificadores. El README dice que los títulos no se copiaron de un PDF y están `NOT_VERIFIED`. No he visto texto de CS-27 dentro de ese JSON en esta lectura de código; no he recontado cada fila hoy.

## CI frente a esta máquina

`.github/workflows/ci.yml` pide Python 3.12, ruff, pytest, la denylist, el escáner de patrones, `make bench`, `pip-audit` y gitleaks. `pyproject.toml` fija `requires-python >= 3.12` y declara `pip-audit` en el grupo dev. No hay ningún commit ni, en esta sesión, una corrida de GitHub. El fichero de CI no es un resultado. `gitleaks` no está en el PATH local. `pip-audit` está declarado y no se ha ejecutado aquí.

## Lo que el árbol sí sostiene

Decimal en las dos fórmulas de fuerza y de tensión. Abstención si falta un dato, si el método es desconocido o si el residuo vertical pasa de un quantum. El trigger de SQLite rechaza update y delete hasta que alguien lo borra; si se borra y se cambia el cuerpo, `verify()` falla. Eso ya está en `audit/repro/out/ledger_tamper.json`. S1, dos veces, idéntico, y circular: el mismo paquete siembra y puntúa.
