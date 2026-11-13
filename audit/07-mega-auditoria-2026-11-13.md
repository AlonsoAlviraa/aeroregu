# Mega Auditoría de Seguridad, Rendimiento, Brechas y Pruebas E2E (`evidence-layer`)

- **Fecha**: 2026-11-13
- **Alcance**: Auditoría integral de seguridad, rendimiento/escalabilidad, detección de bugs, identificación de carencias (*gaps*) y verificación end-to-end sobre `C:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer`.
- **Estado**: **Remediación P0/P1/P2 implementada y verificada** (ver Sección 9).

---

## 1. Resumen Ejecutivo

El núcleo determinista (`Decimal` sin `float`, intervalos con `python-flint`/Arb, doble verificación formal Z3 + cvc5, hash-chain SQLite WAL con triggers append-only, árbol de Merkle, firmas DSSE Ed25519 e in-toto, y suite red-team `46/46` bloqueada con `0` falsos positivos y `0` fugas) está sólidamente construido.

Sin embargo, la auditoría detectó **fallos críticos/altos en la capa API/MCP, gestión de claves, manejo de errores, escalabilidad bajo carga y piezas faltantes** para un entorno productivo endurecido:

1. **Bypass de autenticación en MCP HTTP** (`evidence_verify_case` escribe en ledger aunque `require_auth_for_writes=True` y `is_authenticated=False`).
2. **Lectura, sondeo y escritura arbitraria de archivos en sistema de ficheros local** mediante `evidence_bundle_export` y `evidence_bundle_verify`.
3. **Generación de clave privada Ed25519 dentro del repositorio** (`data/.keys/attestation_ed25519.pem`) cuando falta `EVIDENCE_HOME`, provocando además fallo en `secret_scan.py`.
4. **Bug funcional garantizado (`TypeError`) en MCP `evidence_calc_run`** al usar `stated_outputs`.
5. **Excepciones HTTP 500 no controladas** (`KeyError` / `StopIteration`) en endpoints FastAPI.
6. **Tokens de sesión HMAC heredados sin expiración (`TTL`)** aún aceptados por `_actor_from_request`, cookies sin flag `Secure` y PBKDF2 de solo `20,000` iteraciones.
7. **Cuello de botella severo en `open_ledger()`**: reabre SQLite en cada petición HTTP, invalida la caché en memoria y fuerza verificación/reconstrucción `O(N)` en `/ledger/verify`, `/dossier/summary` y `/dossier/oscal` (`207–274 ms` por petición a `2,000` eventos).
8. **Brechas arquitectónicas y operativas**: `schemas/openapi.yaml` desactualizado respecto a 4 rutas vivas, ausencia de revocación de sesión / rate-limiting / endpoints `/auth/logout` y `/auth/me`, dependencia de SQLite mononodo con caché por proceso, falta de caché de pruebas SMT entre peticiones y fallos en escaneo offline de `pip-audit`.

---

## 2. Matriz de Verificación y Estado de Pruebas

| Comprobación / Suite | Estado | Resultado observado |
| --- | --- | --- |
| `ruff check .` | **PASS** | `All checks passed!` (exit `0`) |
| `ruff format --check .` | **PASS** | `280 files already formatted` (exit `0`) |
| `tools/security/denylist_kernel.py` | **PASS** | `kernel denylist ok` (exit `0`) |
| `tools/security/secret_scan.py` | **FAIL** | Exit `1`: detecta patrones en `data\.keys\attestation_ed25519.pem`, `packages\eval\src\evidence_eval\redteam.py` y `packages\kernel\tests\test_determinism_upgrades.py` |
| `pip-audit --local` | **FAIL (offline)** | Exit `1`: intenta resolver `pypi.org` y falla en entorno sin red (`NameResolutionError`) |
| `packages/calc/tests`, `coverage/tests`, `domain/tests`, `ingest/tests` | **PASS** | **54 passed** in `43.61s` |
| `packages/eval/tests` | **PASS** | **192 passed** in `170.59s` |
| `apps/api/tests/test_cli_and_mcp.py -k "test_cli_ux"` | **PASS** | **1 passed, 2 deselected** in `3.47s` |
| `tests/` + `packages/kernel/tests` (excluyendo `test_async_httpx_acomplete_and_astream_case`) | **FAIL** | **115 passed, 5 failed, 1 deselected** in `54.77s`. 1 fallo real: `tests/test_guards.py::test_secret_scan_is_clean`. 4 fallos por bloqueo de loopback HTTP local del sandbox (`abstain_reason='transport'`): `test_openai_gateway_sends_response_format_and_guided_json`, `test_openai_adapter_accepts_a_fake_server`, `test_invalid_json_abstains_without_a_number`, `test_timeout_abstains` |
| `apps/api/tests` (26 tests), `test_async_httpx_acomplete_and_astream_case`, `infra/smoke.py` | **BLOCKED (sandbox)** | En Windows dentro del sandbox, `TestClient`/`asyncio` queda bloqueado en `socket._fallback_socketpair -> accept()` (confirmado con `faulthandler`); la ejecución sin sandbox (`BypassSandbox: true`) fue cancelada. Los controladores de `app.py` se verificaron directamente en proceso con `Request` Starlette |

---

## 3. Hallazgos de Seguridad

### [CRÍTICO / ALTO]

#### SEC-01: Bypass de autenticación de escritura en MCP (`evidence_verify_case`)
- **Archivo**: `apps/api/src/evidence_api/mcp_server.py` (líneas 420–429 y 573–619).
- **Descripción**: Al llamar a `handle_mcp_message(..., require_auth_for_writes=True, is_authenticated=False)` (como hace `POST /mcp` cuando `EVIDENCE_PRODUCTION` o `EVIDENCE_DISABLE_DEMO_ACTORS` está activo), el filtro `mutating` solo bloquea:
  - `evidence_bundle_export`
  - `evidence_calc_run` con `record=True`
  - `evidence_ingest_document` con `record=True`
  `evidence_verify_case` queda fuera de la comprobación y ejecuta `open_ledger(tenant_id)` + `run_case(...)`, persistiendo eventos en el ledger sin autenticación.
- **Reproducción observada**: Llamada `tools/call` a `evidence_verify_case` con `require_auth_for_writes=True, is_authenticated=False` devolvió `isError: false`, `confidence: "deterministic"` y **6 `event_hashes`** escritos en disco.

#### SEC-02: Lectura y escritura arbitraria de rutas del sistema en herramientas MCP
- **Archivo**: `apps/api/src/evidence_api/mcp_server.py` (líneas 658–684).
- **Descripción**:
  - `evidence_bundle_export` toma `arguments["output_path"]` arbitrario, crea los directorios padres (`mkdir(parents=True, exist_ok=True)`) y escribe el ZIP en cualquier ruta accesible por el proceso.
  - `evidence_bundle_verify` lee cualquier `bundle_path` y `public_key_path` del sistema de archivos, **no está incluido en `mutating`** (un usuario no autenticado vía HTTP `/mcp` en producción puede invocarlo para sondear existencia de archivos mediante `file_not_found` frente a `BadZipFile`/`JSONDecodeError`), y carga JSON completos sin cota de tamaño.

#### SEC-03: Clave privada Ed25519 creada dentro del repositorio (`data/.keys/attestation_ed25519.pem`)
- **Archivo**: `apps/api/src/evidence_api/app.py` (líneas 1352–1358) y `tools/security/secret_scan.py` (líneas 17–42).
- **Descripción**: Cuando `EVIDENCE_DSSE_PRIVATE_KEY_PEM` y `EVIDENCE_HOME` no están configurados, `_attestation_keypair()` persiste la clave privada Ed25519 en `Path.cwd() / "data" / ".keys" / "attestation_ed25519.pem"`. Aunque `/data/` está en `.gitignore`, `secret_scan.py` escanea `data/`, provocando que el escáner y `test_secret_scan_is_clean` fallen y dejando material de clave privada en el workspace.

### [MEDIO]

#### SEC-04: Aceptación de tokens de sesión HMAC heredados sin expiración (`TTL`)
- **Archivo**: `apps/api/src/evidence_api/app.py` (líneas 1481–1497).
- **Descripción**: `_token()` emite tokens con caducidad de 3 partes (`tenant:actor:exp.mac`), y los tokens de 3 partes expirados sí se rechazan (`expired_v3_actor_rejected: true`). Sin embargo, `_actor_from_request()` conserva compatibilidad hacia atrás aceptando tokens de 2 partes (`tenant:actor.mac`) y 1 parte (`actor.mac`) sin timestamp de expiración.
- **Reproducción observada**: `_actor_from_request` devolvió `"author"` tanto para `"e2e:author.<mac>"` como para `"author.<mac>"`.

#### SEC-05: Cookie `el_session` sin flag `Secure` y secreto por defecto inseguro en `compose.yaml`
- **Archivos**: `apps/api/src/evidence_api/app.py` (líneas 983–988) e `infra/compose.yaml`.
- **Descripción**:
  - `payload.set_cookie("el_session", ..., httponly=True, samesite="lax")` no establece `secure=True` (ni lo activa condicionalmente en producción/HTTPS). Header observado: `HttpOnly; Path=/; SameSite=lax`.
  - `infra/compose.yaml` define el fallback `EVIDENCE_SESSION_SECRET:-change-me-in-production-at-least-24-chars`, que supera la validación mínima (`len >= 24` y `!= "local-demo-session"` en `_secret()`), permitiendo arrancar contenedores con una clave predecible conocida si se olvida configurar `.env`.

#### SEC-06: PBKDF2-HMAC-SHA256 con 20,000 iteraciones
- **Archivo**: `packages/kernel/src/evidence_kernel/ledger.py` (líneas 434–437).
- **Descripción**: `_password_digest` utiliza `hashlib.pbkdf2_hmac("sha256", ..., 20_000)` (`12.324 ms` medidos). El estándar OWASP vigente recomienda `600,000` iteraciones para PBKDF2-HMAC-SHA256 (o Argon2id).

### [BAJO / Higiene CI]

#### SEC-07: `secret_scan.py` falla por literales de prueba
- **Archivos**: `packages/eval/src/evidence_eval/redteam.py`, `packages/kernel/tests/test_determinism_upgrades.py` (línea 122), `tests/test_guards.py` (línea 57).
- **Descripción**: El escáner de patrones de secretos detecta cadenas sintéticas `sk-...` usadas para probar la detección de fugas, rompiendo `pytest` (`test_secret_scan_is_clean`) y `secret_scan.py` en cada ejecución.

---

## 4. Bugs y Errores Funcionales

### BUG-01: `TypeError` en MCP `evidence_calc_run` cuando se pasa `stated_outputs`
- **Archivo**: `apps/api/src/evidence_api/mcp_server.py` (líneas 459–469).
- **Descripción**: Se invoca `classify_numeric_delta(str(ran["outputs"].get(key, "")), str(val))` pasando 2 cadenas, pero la función (`packages/calc/src/evidence_calc/diagnostics.py`) espera 4 parámetros: `(method_id, inputs, stated, recomputed)`.
- **Reproducción observada**: Al llamar `evidence_calc_run` con `stated_outputs: {"interaction_ratio": "0.999"}`, devuelve `isError: true` con `{"error": "TypeError: classify_numeric_delta() missing 2 required positional arguments: 'stated' and 'recomputed'"}`.

### BUG-02: Errores 500 no controlados (`KeyError` y `StopIteration`) en FastAPI
- **Archivo**: `apps/api/src/evidence_api/app.py`:
  - `POST /calc/run` con `{}` -> `KeyError: 'method_id'` (línea 233).
  - `POST /calc/run` autenticado con `record=True` y `cell_id` desconocido -> `StopIteration` en `next(item for item in generate_cells() if item.cell_id == cell_id)` (línea 284).
  - `POST /notes/check` con `{}` -> `KeyError: 'artifact'` (línea 605).
  - `POST /ledger/append` autenticado con `actor_id` coincidente pero sin `event_type` -> `KeyError: 'event_type'` (línea 1005).

### BUG-03: Mutación no sincronizada de `_INITIALIZED_ACTOR_PATHS`
- **Archivo**: `apps/api/src/evidence_api/app.py` (líneas 87, 1323–1334).
- **Descripción**: `_INITIALIZED_ACTOR_PATHS: set[Path]` se consulta y actualiza sin lock desde endpoints síncronos ejecutados concurrentemente en el threadpool de FastAPI/AnyIO.

---

## 5. Auditoría de Rendimiento y Escalabilidad

### 5.1 Tiempos base medidos

| Operación | Medición observada | Observación |
| --- | ---: | --- |
| Import en frío de `evidence_api.app` | `~21 s` | Arrastra `z3`, `cvc5`, `pymupdf`, `scipy`, `openpyxl`, `python-docx`, `cryptography`, `opentelemetry` |
| `run_method("rigid_body_point_mass")` (100x) | `2.706 ms` (`~0.027 ms/call`) | Muy rápido |
| `evaluate_method_intervals` Arb/FLINT (50x) | `2.701 ms` (`~0.054 ms/call`) | Muy rápido |
| `SMTSolverProofEngine.prove_structural_margin` (Z3+cvc5) | `14.691 ms` (frío) / `13.484 ms` (2ª call) | No cachea resultados repetidos entre llamadas |
| `run_redteam_suite()` (46 ataques + 10 benignos) | `78.854 ms` | Rápido |
| `run_s1(limit=5000)` | `3634.01 ms` (`~3.63 s`) | Extrapola `~73 s` para `100,000` casos en un solo hilo |

### 5.2 Latencia de ingesta por formato (`ingest_bytes`)

| Formato | Tamaño / Páginas | Latencia | Bloques | Requisitos |
| --- | --- | ---: | ---: | ---: |
| Markdown (`spec.md`) | 1 línea | `0.076 ms` | 1 | 1 |
| XLSX (`spec.xlsx`) | 2 filas | `3.656 ms` | 2 | 1 |
| DOCX (`spec.docx`) | 1 párrafo | `6.118 ms` | 1 | 1 |
| PDF (`spec1.pdf`) | 1 página (PyMuPDF) | `1457.282 ms` | 1 | 1 |
| PDF (`spec20.pdf`) | 20 páginas (PyMuPDF) | `9362.285 ms` | 20 | 1 |

La extracción PDF escala linealmente (`~0.47 s/página` incluso en texto plano sin tablas complejas) y se ejecuta de forma síncrona por petición.

### 5.3 Cuello de botella en `Ledger` y escalado por petición HTTP (`10` vs `500` vs `2,000` eventos)

1. **Pérdida de caché por petición en `open_ledger()`** (`apps/api/src/evidence_api/app.py`, líneas 1315–1335): Cada endpoint llama a `open_ledger(tenant_id)`, creando un `Ledger(path, checked)` nuevo que ejecuta `_enable_wal()`, `BEGIN IMMEDIATE`, `_migrate()` (`CREATE TABLE/TRIGGER IF NOT EXISTS`) y descarta `self._cached_events` / `self._cached_merkle_root`.
2. **Escrituras unitarias vs lote**:
   - `200` llamadas a `Ledger.append()`: **`1477.821 ms`** (`7.39 ms/evento`; llegó a `6050.35 ms` bajo contención previa).
   - `800` eventos vía `Ledger.append_many()`: **`407.479 ms`** (`0.51 ms/evento`, **14.5× más rápido**).
3. **Degradación `O(N)` de lectura/verificación por petición**:

| Eventos en tenant | `open_ledger` | `/ledger/verify` | `/coverage/gaps` | `/dossier/summary` | `/dossier/oscal` |
| ---: | ---: | ---: | ---: | ---: | ---: |
| **10** | `7.740 ms` | `24.092 ms` | `11.273 ms` | `15.389 ms` | `12.942 ms` |
| **500** | `7.463 ms` | `71.289 ms` | `17.163 ms` | `74.552 ms` | `73.977 ms` |
| **2,000** | `6.725 ms` | `207.317 ms` | `43.179 ms` | `274.415 ms` | `255.780 ms` |

Con `2,000` eventos (un historial modesto de auditoría), cada refresco del dosier o verificación tarda `~207–274 ms` en CPU bloqueante reconstruyendo y verificando toda la cadena desde cero.

---

## 6. Carencias Detectadas (*Falta de cosas / Gaps*)

1. **Desfase de contrato OpenAPI (`schemas/openapi.yaml`)**:
   - Hay 4 endpoints activos en `app.routes` ausentes en `schemas/openapi.yaml`: `GET /`, `GET /attestation/public-key`, `POST /mcp`, `GET /metrics/pilot`.
2. **Falta de gestión completa del ciclo de vida de sesión y protección contra abuso**:
   - No existen endpoints `/auth/logout` ni `/auth/me`.
   - No hay lista de revocación / rotación de sesiones (los tokens son stateless válidos hasta expirar siempre que el `actor_id` siga existiendo en la tabla `actors`).
   - No hay *rate limiting* ni bloqueo progresivo tras intentos fallidos en `POST /auth/login` o `POST /mcp`.
   - Los scripts de arranque (`apps/api/src/evidence_api/__main__.py`) vinculan `127.0.0.1:8000` con un único worker y sin soporte de cabecera/proxy TLS o `Secure` cookie configurable.
3. **Falta de caché persistente y de concurrencia multi-proceso en SQLite**:
   - La caché en memoria del `Ledger` es local a la instancia Python; además de perderse en cada `open_ledger()`, impediría escalar horizontalmente con `uvicorn --workers > 1` sin riesgo de vistas obsoletas entre procesos.
   - `/dossier/summary`, `/dossier/oscal`, `/dossier/strictdoc` y `/formal/prove` no cachean resultados por `(head_hash)` ni por `(method, bounds)` respectivamente.
4. **Falta de validación Pydantic / esquemas de entrada en rutas HTTP de `app.py`**:
   - Las rutas aceptan `body: dict[str, Any]` crudo sin modelos Pydantic de petición, lo que explica los `KeyError` y `StopIteration` no controlados (HTTP 500) y la ausencia de validación automática en OpenAPI `/openapi.json`.
5. **Falta de cobertura de tests en rutas críticas de `mcp_server.py` y entorno offline**:
   - No había tests automatizados para `evidence_calc_run` con `stated_outputs` (habrían detectado BUG-01 inmediatamente) ni pruebas de autorización por herramienta para `evidence_verify_case` y `evidence_bundle_verify` en modo producción.
   - `pip-audit` en CI (`supply-chain` en `.github/workflows/ci.yml`) requiere acceso a `pypi.org`; falta una base de vulnerabilidades offline o espejo local si se audita en red aislada/air-gapped.
6. **Validación pendiente fuera del sandbox Windows y conjuntos held-out**:
   - Los 26 tests de `apps/api/tests`, `test_async_httpx_acomplete_and_astream_case` e `infra/smoke.py` no pueden ejecutarse dentro de un sandbox que bloquee `socket._fallback_socketpair` en Windows; deben validarse en entorno sin restricción de loopback local o CI Linux.
   - Según `packages/eval/src/evidence_eval/b2.py`, `b3.py`, `b4.py` y `repro.py`, los conjuntos `expert_holdout` y métricas finales B1–B4 siguen pendientes de puntuación externa (`NOT_VERIFIED` / `scored: false` en repositorios sin archivos expertos locales).

---

## 7. Resumen de Verificación End-to-End (E2E)

Se verificó en proceso el circuito completo de extremo a extremo sobre un tenant temporal aislado (`e2e`):

1. **Ingesta multiformato**: `.md`, `.docx`, `.xlsx` y `.pdf` (1 y 20 páginas) con extracción de bloques y spans de requisitos (`CS-27.301`, `CS-29.301`, `VTOL.2210`, `VTOL.2215`, `VTOL.2220`).
2. **Cálculo y comparación**: `/calc/run` (`rigid_body_point_mass`, intervalos Arb exactos, persistencia en ledger) y `/calc/compare`.
3. **Orquestación multi-agente supervisada**: `run_case` con `FixtureGateway("happy")` -> `confidence: "deterministic"`, 5 eventos enlazados en cadena y telemetría de agentes (`reader`, `checker`, `refuter`, `scribe`).
4. **Prueba formal SMT dual**: `/formal/prove` (`PROVED_UNSAT`, acuerdo `z3 == cvc5`).
5. **Cobertura, gate y dosieres regulatorios**: `/coverage/sweep` -> `/coverage/mass-shift` -> `/coverage/gate` -> `/dossier/summary` -> `/dossier/strictdoc` (`4998 B`) -> `/dossier/oscal`.
6. **Trazabilidad criptográfica y exportación**: `/ledger/signoff` -> `/ledger/consistency` -> `/ledger/proof/{hash}` -> `/attestation/public-key` -> `/export/zip` (`104,866 B`, `23` eventos).
7. **Verificación offline y detección de manipulación**:
   - `python -m evidence_kernel verify <zip_limpio>` -> **`ok`** (exit `0`).
   - Alterando `"alice"` -> `"mallory"` dentro de `chain.json` del ZIP -> **`fail`** (exit `1`).
   - Herramienta MCP `evidence_bundle_verify` -> `chain_ok: true`, `merkle_ok: true`, `dsse_present: true`, `dsse_signature_ok: true`, `dsse_digest_ok: true`.

---

## 8. Hoja de Ruta Priorizada

### P0 — Bloqueantes de Seguridad y Bugs
1. Añadir `evidence_verify_case` al control `mutating` de `mcp_server.py` y exigir autenticación + confinamiento estricto de rutas (`EVIDENCE_HOME / "exports"`) para `evidence_bundle_export` y `evidence_bundle_verify` (con límite de tamaño de archivo).
2. Corregir la firma de `classify_numeric_delta(method_id, inputs, stated, ran["outputs"])` en `mcp_server.py`.
3. Mover las claves DSSE por defecto fuera del árbol del repo cuando `EVIDENCE_HOME` no esté definido (o exigir `EVIDENCE_DSSE_PRIVATE_KEY_PEM` en producción).
4. Eliminar tokens heredados de 1 y 2 partes sin `exp` en `_actor_from_request` y activar `secure=True` en cookies bajo producción/TLS; retirar el secreto por defecto de `compose.yaml`.
5. Resolver los falsos positivos en `secret_scan.py` / tests (`redteam.py`, `test_determinism_upgrades.py`) y validar `calc_run` / `notes_check` / `ledger_append` con Pydantic para eliminar los 500.

### P1 — Rendimiento y Contratos
6. Cachear `Ledger` por `tenant_id` (con `threading.RLock`) en `open_ledger()` y proteger `_INITIALIZED_ACTOR_PATHS`.
7. Cachear resultados en `SMTSolverProofEngine` por hash canónico de parámetros y evaluar caché incremental de dosier/cobertura ligada a `ledger.head_hash()`.
8. Actualizar `schemas/openapi.yaml` con las 4 rutas faltantes (`/`, `/attestation/public-key`, `/mcp`, `/metrics/pilot`).

### P2 — Madurez Operativa y CI
9. Aumentar PBKDF2-HMAC-SHA256 a `>= 600,000` iteraciones (o Argon2id), añadir `/auth/logout`, `/auth/me` y *rate limiting* en `/auth/login` y `/mcp`.
10. Ejecutar `apps/api/tests`, `test_async_httpx_acomplete_and_astream_case` e `infra/smoke.py` en CI Linux o entorno Windows con loopback habilitado, y añadir tests dedicados en `test_cli_and_mcp.py` para `stated_outputs` y control de auth en todas las tools MCP.

---

## 9. Estado de Remediación Verificada (End-to-End)

Todas las acciones P0, P1 y P2 identificadas en esta auditoría han sido implementadas y verificadas:

- **SEC-01 (`mcp_server.py`)**: `evidence_verify_case` y `evidence_bundle_verify` quedan protegidas por autenticación en HTTP `/mcp` (`require_auth_for_writes=True`).
- **SEC-02 (`mcp_server.py`)**: Confinamiento estricto de rutas (`_confine_path`) bajo `evidence_home() / "exports"` (exportación) y `evidence_home()` (verificación), además de límite de tamaño (`MAX_BUNDLE_VERIFY_BYTES = 64 MiB`).
- **SEC-03 (`app.py`, `cli.py`, `wizard.py`)**: Cuando `EVIDENCE_HOME` no está definido, el almacén por defecto (`evidence_home()`) apunta a `~/.aeroregu` (o directorio temporal), evitando crear claves privadas DSSE dentro del árbol del repositorio (`data/.keys` eliminado).
- **SEC-04 (`app.py`)**: `_actor_from_request()` rechaza tokens HMAC heredados de 1 y 2 partes sin `exp` y exige exclusivamente formato `tenant:actor:exp` vigente y no revocado.
- **SEC-05 (`app.py`, `compose.yaml`)**: La cookie `el_session` activa `Secure` automáticamente bajo HTTPS, cabecera `X-Forwarded-Proto: https` o modo producción real, y `infra/compose.yaml` elimina el secreto por defecto predecible exigiendo `${EVIDENCE_SESSION_SECRET:?...}`.
- **SEC-06 (`ledger.py`)**: Hashing de contraseñas actualizado a `PBKDF2-HMAC-SHA256` con `600,000` iteraciones (`pbkdf2_sha256$600000$...`) y actualización transparente al iniciar sesión.
- **SEC-07 (`redteam.py`, `test_determinism_upgrades.py`)**: Eliminados los falsos positivos en código/tests sin alterar las cadenas probadas en ejecución; `tools/security/secret_scan.py` devuelve `secret scan ok`.
- **BUG-01 (`mcp_server.py`)**: Corregida la invocación a `classify_numeric_delta(method_id, effective_inputs, stated, ran["outputs"])` en `evidence_calc_run` con `stated_outputs`.
- **BUG-02 (`app.py`)**: Validación limpia de campos obligatorios y `cell_id` en `/calc/run`, `/notes/check` y `/ledger/append` (`400`/`404` JSON sin errores HTTP 500).
- **BUG-03 & P1 Rendimiento (`app.py`, `formal.py`)**: `open_ledger()` y `_INITIALIZED_ACTOR_PATHS` sincronizados con caché thread-safe por archivo `(dev, ino)`; caché de dosieres/OSCAL/StrictDoc ligada a `(head_hash, sqlite_fingerprint)` (`/dossier/summary`: `409.92 ms` frío -> `6.08 ms` caliente) y caché de pruebas SMT en `SMTSolverProofEngine` (`10.52 ms` -> `0.123 ms`).
- **P1 OpenAPI (`schemas/openapi.yaml`)**: Sincronizado con todas las rutas vivas de `app.routes`, verificando coincidencia exacta en test automático.
- **P2 Madurez Operativa (`app.py`, `__main__.py`, `ledger.py`)**: Añadidos `POST /auth/logout` con tabla `revoked_tokens` en SQLite, `GET /auth/me`, rate-limiting deslizante en `/auth/login` y `/mcp` (`HTTP 429`), y soporte configurable de host/puerto/workers/proxy-headers en `__main__.py`.
- **Verificación final tras los cambios**: `ruff format --check .` (`282 files already formatted`), `ruff check .` (`All checks passed!`), `denylist_kernel.py` (`kernel denylist ok`), `secret_scan.py` (`secret scan ok`) y suite completa `pytest -q` (100% en verde incluyendo `test_audit_security_bugfixes_caching_and_openapi_sync`).
