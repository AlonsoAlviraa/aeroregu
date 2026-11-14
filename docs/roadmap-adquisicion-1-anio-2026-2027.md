# Roadmap a 1 Año (2026–2027): Capacidades Faltantes y Mega-Tests para Adquisición Enterprise / OEM

> **Estado base auditado**: commit `4ff830d` en `master` (`aeroregu`, `evidence-layer`).  
> **Nota regulatoria y de alcance (`ADR-018` / `ADR-020`)**: esta herramienta **asiste a ingenieros y revisores humanos (CVE)**; **no determina cumplimiento normativo** ni reclama cualificación DO-330 / TQL por sí sola. Ningún ítem de este documento constituye asesoramiento legal ni previsión financiera comprometida.

---

## 0. Punto de Partida Real vs. Lo que Todavía Falta (Sin Autoengaños)

Antes de planificar los próximos 12 meses, conviene fijar con precisión quirúrgica **qué ya funciona y pasa CI hoy** frente a **qué no existe, está simulado o carece de pruebas industriales reales**:

| Área | Ya construido y probado hoy (`master`) | Brecha crítica real para compra OEM / Tier-1 en 12 meses |
| --- | --- | --- |
| **Motor de cálculo y plugins** | 7 métodos (`rigid_body_point_mass`, `bolt_screen`, `hover_power_screen`, `margin_of_safety`, `column_plate_buckling`, `palmgren_miner_fatigue`, `composite_failure_criteria`), expresiones declarativas (`plugins.py`), intervalos Arb/FLINT y Pint (`units.py`) | Faltan ~25–40 métodos reales de *Stress Manual* (pandeo local+global acoplado, CLT completo `[A,B,D]`, Puck/LaRC04, OHT/OHC/BVID, crecimiento de grieta NASGRO/Paris, uniones híbridas/adhesivas) y tablas estadísticas **A/B-Basis (MMPDS / CMH-17)** con interpolación acotada por intervalos |
| **CAD / CAE / PLM** | Parsers texto STEP AP242, IGES, CATIA XML/Knowledgeware & OLE2 con XML embebido, NASTRAN `.bdf`/`.f06` y ABAQUS `.inp`; watcher de carpetas locales y diffs Git (`daemon.py`) | Sin conectividad viva con **3DEXPERIENCE/ENOVIA, Teamcenter o Windchill**; sin kernel B-Rep 3D (**OpenCASCADE / OCCT**) para recalcular volúmenes/inercias/espesores en `.CATPart`/STEP opacos; sin lectores **binarios CAE** (`.op2`, HDF5 Nastran, `.odb`, `.rst`); sin **visor WebGL de malla FEA + campos `MS_min`** |
| **Ingesta Documental & OCR** | PDF texto nativo (`PyMuPDF` / `Docling` opcional), DOCX, XLSX, Markdown; extractor de bbox (`pdf_report.py`) | Extracción PDF síncrona lineal (~`0.47 s/pág` medida); sin pipeline asíncrono distribuido para **pliegos escaneados de 500–2,000 páginas** con tablas densas multi-columna y verificación OCR dual |
| **Persistencia, S3 y Escala** | SQLite WAL + `pg_ledger.py` (probado solo contra cursor fake), `S3ObjectBlobStore` SigV4 (probado solo contra transporte mock HTTP), migraciones `v1..v3`, DLQ webhooks | Sin suite CI contra **PostgreSQL 16+ y MinIO/S3 WORM reales** bajo concurrencia de 50+ workers; caché de ledger/SMT/dosier ligada a proceso Python único (`uvicorn --workers 1`), lo que bloquea balanceo multi-réplica real |
| **Seguridad, Firma e IdP** | OIDC JWKS y SAML 2.0 XMLDSig (`sso.py`), RBAC + SoD Author≠CVE, HMAC webhooks, DSSE Ed25519 offline + QR ISO + `PBKDF2 600k` + `revoked_tokens` | Claves DSSE sin integración **HSM / AWS KMS / Azure Key Vault / PKCS#11**; `human_signoff` no integra firma electrónica cualificada (**eIDAS QES**); falta **MFA step-up WebAuthn** antes de batch sign-off CVE, **SCIM 2.0** desde Entra ID/Okta y escaneo **CVE/SBOM offline** para redes air-gapped |
| **IA, Holdouts & Evaluación** | `FixtureGateway`, `HybridAgentRouter`, `envelope_critic` (Z3+cvc5) y `bench_attacker`, métricas B1–B4 sintéticas / dev | **`B1 expert_holdout` = 0 casos externos** (`weakness-register.md` W-07), `B3/B4` sin *gold set* independiente ni unidades reales multi-sesión, cero validación medida sobre modelos **on-prem reales** (vLLM/Ollama cuantizados) frente a `FixtureGateway` |
| **Legal, IP & Cualificación** | `docs/legal/open_items.md`, `ADR-018`, `ADR-020` documentados | **5 bloqueantes legales abiertos** (exclusividad laboral, no competencia, cesión IP, contrato del experto B1, control de exportación Ley 53/2007 y Reg. UE 2021/821); sin **Paquete IQ/OQ TQL-5** ni 10+ programas de cliente en renovación |

---

## 1. Arquitectura de Bloqueantes a Resolver (Por Qué Comprará un OEM en 12 Meses)

Un equipo de M&A de Airbus / Safran / Leonardo / RTX / Dassault o un fondo industrial no compra una demo con tests unitarios en mocks: exige **cuatro pruebas verificables en auditoría técnica (*Technical & Legal Due Diligence*)**:

1. **Cero fricción con el flujo real del Stress Office**: leer directo desde PLM + CATIA/STEP B-Rep + `.op2`/`.h5`/`.odb` + pliegos PDF gigantes, y devolver evidencias visuales sin pedirle al calculista que convierta archivos a mano a XML/ASCII.
2. **Validez física y matemática indiscutible**: cubrir el 80%+ de las comprobaciones diarias de estructuras metálicas, compuestas y fatiga/tolerancia al daño con tablas MMPDS/CMH-17 reales y doble verificación SMT/intervalos.
3. **Resiliencia Enterprise real sin mocks**: funcionar semanas sin supervisión en clúster PostgreSQL HA + S3 Object Lock + Kubernetes air-gapped + KMS/eIDAS con p99 acotado a `100,000+` eventos.
4. **Propiedad Intelectual limpia, seguridad certificable y tracción pagada**: `open_items.md` en `CLOSED`, benchmarks `B1–B4` puntuados por expertos externos independientes y pilotos convertidos en renovaciones anuales.

---

## 2. Roadmap Detallado por Trimestres (Meses 1–12)

---

### Q1 (Meses 1–3): Infraestructura Real Cloud-Native, Concurrencia Multi-Worker y Cadena Documental Pesada

**Objetivo del trimestre**: eliminar toda dependencia de mocks de persistencia/almacenamiento y preparar la plataforma para **múltiples réplicas API + workers paralelos sin estado en proceso**.

#### Features a construir (Hoy NO existen)
1. **PostgreSQL 16+ & S3/MinIO reales de extremo a extremo**:
   - Pool de conexiones `psycopg[pool]` con reintentos transitorios, *Row-Level Security (RLS)* nativo por `tenant_id` en PostgreSQL y verificación estricta de triggers `append-only` en PG real.
   - Caché distribuida compartida (Redis / tablas materializadas en PostgreSQL + `LISTEN/NOTIFY`) para invalidación cross-proceso de `head_hash`, cobertura y resultados SMT, permitiendo `uvicorn --workers N` tras balanceador L7.
   - S3/Blob Object Lock (**WORM Retention** / `Compliance` o `Governance` mode) + cifrado **SSE-KMS** + subidas multipart con checksum SHA-256 por chunk para pliegos/CAD de >500 MB.
2. **Worker Pool asíncrono de ingesta PDF + OCR dual verificable**:
   - Desacoplar `POST /ingest` para PDFs pesados (>20 pág o escaneados): cola en `daemon_jobs` con workers OCR/layout paralelos (Docling + OCR determinista de respaldo), extrayendo texto + tablas + `bbox` por página sin bloquear el hilo FastAPI.
   - Detector automático de páginas rasterizadas/escaneadas vs texto vectorial, aplicando doble pasada con abstención (`low_ocr_confidence`) ante tablas borrosas o fórmulas ilegibles.
3. **Observabilidad de producción completa**:
   - Exportador **OTLP gRPC/HTTP** (trazas distribuidas API -> Worker -> Z3/cvc5 -> PG -> S3), dashboard **Grafana** listo para importar + reglas **Prometheus Alertmanager** (lag de cola > umbral, DLQ > 0, tasa de `ABSTAIN` anómala, latencia SMT p99).

#### Mega-Tests de Aceptación Q1 (`tests/mega_q1_infra.py` — CI con Docker / Testcontainers)
- **Test de Contención & Atomicidad PostgreSQL Real**: levantar PostgreSQL 16 en contenedor; lanzar **32 procesos/hilos concurrentes** ejecutando `append()`, `human_signoff()`, `run_overnight_cycle()` y invalidaciones masivas durante 60 s. **Criterio**: 0 deadlocks no recuperados, 0 corrupciones de hash-chain, `verify_chain_document` + árbol Merkle 100% válidos y RLS bloqueando fugas entre 3 tenants simultáneos.
- **Test de Escala Ledger 100k**: sembrar **100,000 eventos** en PostgreSQL real con snapshot incremental. **Criterio**: `GET /coverage/summary`, `GET /ledger/verify` (incremental por checkpoint + verificación aleatoria completa) y `GET /overnight/briefing` responden con **p95 < 150 ms** y uso de RAM por worker API < 512 MB.
- **Test S3/MinIO WORM & Multipart**: subir artefacto binario de **150 MB** en streaming a MinIO con Object Lock activo, intentar sobreescritura o borrado antes de retención y verificar rechazo `403 AccessDenied` + coincidencia SHA-256 exacta al descargar.
- **Mega-Test Documental PDF 500 Páginas Híbridas**: ingestar un pliego sintético de **500 páginas** (mezcla de texto vectorial, tablas multi-página y 50 páginas escaneadas a 150 DPI con ruido/sellos). **Criterio**: throughput > 8 pág/s multi-worker, 100% de `bbox` localizables en PDF de salida, y abstención determinista en las páginas degradadas artificialmente.

---

### Q2 (Meses 4–6): Kernel CAD B-Rep Real, CAE Binario (`.op2`/`.h5`/`.odb`) y Conectores PLM Vivos

**Objetivo del trimestre**: que un calculista o diseñador CATIA conecte `aeroregu` a un paquete real de programa sin convertir ficheros a texto manualmente.

#### Features a construir (Hoy NO existen)
1. **Kernel Geométrico B-Rep (`OpenCASCADE / OCP`) para STEP/IGES y Extractores CATIA reales**:
   - Cálculo geométrico independiente en **STEP AP203/AP214/AP242** binarios/complejos sin depender de propiedades textuales declaradas: volumen exacto por sólido, masa = volumen × densidad verificada, centro de gravedad $(x_{cg}, y_{cg}, z_{cg})$, tensor de inercia $I_{xx..xz}$, detección de interferencias / holguras mínimas y espesores de placa/alma.
   - Puente opcional **CATIA V5/V6 COM / CAA headless** (en runner Windows autorizado) + exportación estructurada de árboles de diseño, parámetros *Knowledgeware*, publicaciones y zonas compuestas (*Ply Book* / orientaciones `[0/45/-45/90]`).
2. **Parsers Binarios CAE Industriales (Streaming Out-of-Core)**:
   - **NASTRAN `.op2` y HDF5 (`.h5` MSC/NX Nastran)**: lectura binaria sin cargar todo en RAM (modelos >1M DOFs, múltiples subcases `LC 1..5,000`), extrayendo desplazamientos, fuerzas en elementos (`CBAR`, `CBEAM`, `CQUAD4`, `CTRIA3`, `CBUSH`, `CFAST`), `GPFORCE` / *Freebody diagrams* por interfaz de herraje, `OLOAD` y `SPCFORCE` para todos los load cases.
   - **ABAQUS `.odb` / Ansys `.rst`**: adaptador aislado por worker (subproceso sandboxed con timeout y cota de memoria) extrayendo campos nodales/elementales con trazabilidad por `Part/Instance/ElementSet`.
3. **Conectores PLM Bidireccionales Enterprise (Read/Write-Status)**:
   - Conectores autenticados (OAuth2 / OIDC M2M / mTLS + circuit breaker) para **Dassault 3DEXPERIENCE / ENOVIA**, **Siemens Teamcenter (Active Workspace / SOA)** y **PTC Windchill (REST OData)**:
     - Polling/webhooks de cambios por revisión (`Rev A -> Rev B`), ciclo de vida (`In Work -> Frozen -> Released`) y aplicabilidad por **MSN / Effectivity**.
     - Publicación de metadato/enlace de trazabilidad (`Audit Trail Link` + Merkle Root) hacia el objeto PLM sin sobreescribir la aprobación humana del PDM.
4. **Visor 3D CAE Interactivo WebGL (Malla FEA + Mapa de Margen `MS_min`)**:
   - Evolución del visor actual en `demo.html` a **Three.js / VTK.js** con renderizado real de malla FEA (`CQUAD4`/`CHEXA`), coloreado por `MS_min` o esfuerzo de Von Mises/Tsai-Wu, filtrado por *Property ID (PID)* y navegación click-to-evidence desde un elemento crítico al cálculo y fragmento PDF que lo justifica.

#### Mega-Tests de Aceptación Q2 (`tests/mega_q2_cad_cae_plm.py`)
- **Test de Fidelidad Geométrica B-Rep vs Analítico**: conjunto de 30 sólidos STEP AP242 reales (vigas en I, herrajes con aligeramientos, depósitos, conjuntos multi-cuerpo con distintas densidades). **Criterio**: discrepancia de masa y CG respecto a solución analítica / referencia CAD `< 0.01%` y detección automática al desplazar un subcomponente `+15 mm` fuera de la caja de CG.
- **Test Streaming `.op2`/`.h5` de Alta Escala**: procesar un fichero binario Nastran sintético/benchmark con **250,000 elementos** y **500 subcases** con cota estricta de RAM `< 1.5 GB` y tiempo `< 20 s`. **Criterio**: 100% de equilibrio `sum(applied) + sum(spcforce) ≈ 0` verificado en todos los subcases y extracción exacta del *Envelope Worst-Case `MS_min`* por grupo `PID`.
- **Test E2E Conectores PLM Simulados (Mock Server + Contrato Real + Replay)**: simular flujo completo `Rev A -> ECN modifica espesor -> Rev B publicada en Teamcenter/3DEXPERIENCE` con caída temporal de red (HTTP 503 x3 + token expirado). **Criterio**: reintento con refresh de token sin duplicar eventos, invalidación selectiva exclusiva de las celdas afectadas por ese `PID` y trazabilidad completa de deltas `Rev A vs Rev B`.
- **Test Browser E2E Visor WebGL 3D**: carga de malla de 50,000 triángulos/quads en navegador headless (`>= 30 FPS`), selección de elemento crítico rojo, apertura sincronizada del cálculo y bbox PDF sin fugas de memoria WebGL ni errores en consola.

---

### Q3 (Meses 7–9): Biblioteca Completa de Stress Office, Seguridad HSM/eIDAS y Evaluaciones Externas `B1–B4`

**Objetivo del trimestre**: cerrar todas las brechas de dominio aeronáutico, seguridad criptográfica regulada e IA verificable para superar cualquier auditoría técnica de Stress & AppSec.

#### Features a construir (Hoy NO existen)
1. **Catálogo Industrial de Cálculo Estructural & Fatiga + Tablas MMPDS / CMH-17**:
   - **Uniones y Herrajes**: Bearing / Shear-out / Net-section / Cleavage en placas compuestas e isotrópicas con distribución de carga multi-fila (*bolt load distribution* por rigidez elástica), tracción+cortante+flexión combinada en tornillos con *prying factor*, y cortadura en uniones adhesivas (*Goland-Reissner* / *Hart-Smith*).
   - **Estabilidad Avanzada**: interacción pandeo local-global (*crippling* Needham/Gérard + Euler-Johnson) de paneles rigidizados (*skin-stringer*), pandeo biaxial + cortante en placas ortótropas compuestas (CLT completo $[A, B, D]$) y campo de tensiones diagonales (*Wagner/Kuhn tension field*).
   - **Fatiga & Tolerancia al Daño (F&DT)**: conteo Rainflow verificado de espectros de carga reales, acumulación Palmgren-Miner con factor de severidad $K_t/K_f$ y curvas S-N con interpolación log-log MMPDS-16, más **propagación de grietas (Paris / Walker / NASGRO)** para intervalos de inspección.
   - **Compuestos Avanzados & Allowables Estadísticos**: criterios **Puck** y **LaRC04**, *Open-Hole Tension/Compression* (OHT/OHC), *Compression After Impact* (CAI/BVID), factores ambientales *Hot/Wet (ETW)* y librería versionada de materiales con curvas **A-Basis / B-Basis** (interpoladas y acotadas con aritmética de intervalos **Arb** sin pérdida de rigor).
   - **Type-checker dimensional en Plugins (`plugins.py`)**: verificación estática de homogeneidad de unidades del AST antes de aceptar cualquier tarjeta declarativa creada por un cliente.
2. **HSM/KMS, Firma Electrónica Cualificada (eIDAS / QES), SCIM 2.0 y Seguridad Air-Gapped**:
   - Firma DSSE delegada a **AWS KMS / Azure Key Vault / HashiCorp Vault Transit / PKCS#11 HSM** (las claves privadas de firma nunca pisan el disco del servidor API ni salen del enclave seguro).
   - Flujo `human_signoff` compatible con **firma electrónica avanzada/cualificada (eIDAS QES / CAdES/PAdES sobre hash del evento)** + **Step-up MFA WebAuthn** obligatorio al firmar un lote CVE.
   - Provisioning automático **SCIM 2.0** (alta/baja inmediata y cambio de roles author/CVE desde Okta/Entra ID) + **Pipeline CVE Offline** (`pip-audit` contra espejo local/Trivy air-gapped DB + SBOM CycloneDX firmado con Cosign/DSSE).
3. **LLM On-Premises Auditado + Cierre Real de Benchmarks `B1–B4`**:
   - Integración productiva y evaluación medida de modelos **on-prem air-gapped** (vLLM/Ollama con decodificación restringida por gramática `constrained.py`) superando `FixtureGateway` en extracción de requisitos, tablas y refutación adversarial.
   - Recopilación y congelado criptográfico de **`B1 expert_holdout`** (anotado por ingenieros de cálculo independientes bajo contrato limpio, fuera del árbol de entrenamiento/código) y **`B3/B4` holdouts reales** multi-sesión con unidades físicas verificadas.

#### Mega-Tests de Aceptación Q3 (`tests/mega_q3_methods_security_bench.py`)
- **Mega-Test de Regresión Cruzada frente a Soluciones de Referencia (Bruhn / Niu / Roark / CMH-17 / NASGRO)**: batería de **>= 200 casos clásicos publicados** (metales + compuestos + fatiga + crecimiento de grieta) comparando cada método contra la solución analítica/manual con tolerancia certificada `< 0.1%` (y acotación exacta de incertidumbre en intervalo Arb). **Criterio**: 100% pasa en verde y 100% de falsos dimensionales rechazados en el type-checker de plugins.
- **Test de Seguridad Cryptographic HSM & AuthZ Zero-Trust**: simular intento de forja de firma DSSE, token SAML/OIDC con *XML Signature Wrapping*, escalada de privilegios Author->CVE mediante replay o manipulación de claims, y revocación inmediata vía SCIM (`401` en < 1 s). Añadir suite automatizada OWASP API Top 10 contra API y MCP HTTP.
- **Gate Cuantitativo `B1–B4` sobre Modelo On-Prem Real (sin Fixtures)**: ejecutar evaluación ciega sobre `B1 expert_holdout` (>= 150 casos reales etiquetados por tercero), `B2` citas con `bbox`, `B3` tablas complejas y `B4` lectura de series/unidades. **Criterio de salida**: `recall >= 0.99` en detección de discrepancias críticas (0 falsos negativos críticos silenciados; todo caso ambiguo deriva a `ABSTAIN`), `tasa de error de citas bbox == 0%` y latencia compatible con SLA nocturno.

---

### Q4 (Meses 10–12): UX de Cabina de Certificación, Paquete TQL-5 (ADR-018), Cierre Legal & Tracción M&A (ADR-020)

**Objetivo del trimestre**: convertir un producto técnicamente superior en un **activo adquirible llave en mano** (*plug-and-play* en red clasificada de un OEM con Due Diligence legal, técnica y comercial cerrada).

#### Features y Entregables a construir (Hoy NO existen)
1. **Colaboración Multi-Ingeniero, Trazabilidad Visual Bidireccional y Diff ECN Completo**:
   - Visor PDF embebido en navegador que al pulsar cualquier hallazgo o cita abre la página exacta con zoom sobre el `bbox` citado + comparativa visual lado-a-lado **Revisión A vs Revisión B** de pliego, matriz de márgenes y CAD/FEM (*ECN Impact Diff View*).
   - Hilos de revisión auditable Author ↔ CVE anclados a cada celda/hallazgo (inmutables en el ledger, con menciones, resolución guiada y trazabilidad directa al PDF firmado final).
   - Add-in ligero de escritorio para **Excel (Stress Sheets -> tarjeta declarativa + ledger)** y conector directo de inspección para diseñadores CATIA sin salir de su estación Windows.
2. **Empaquetado Air-Gapped Industrial & Instalador Automático**:
   - **Helm Chart Kubernetes + Air-Gapped Bundle** (imágenes OCI firmadas con digest + SBOM + modelos vLLM cuantizados empaquetados sin salida a internet).
   - Instalador firmado **Windows MSIX / Enterprise MSI** para el CLI/cliente de estación CATIA.
3. **Qualification Aid Pack (`ADR-018` — TQL-5 Ready, sin reclamaciones indebidas)**:
   - Documentación estructurada lista para entrega al cliente: **TOR (*Tool Operational Requirements*)**, matriz de trazabilidad completa **TOR → Test Automático → Artefacto de Evidencia**, Manual de Supuestos y Límites Conocidos (*Known Limitations*), y script automatizado **IQ/OQ (*Installation & Operational Qualification*)** que el propio equipo de Calidad/IT del cliente puede correr in-situ en <15 minutos tras instalar una versión.
4. **Cierre Completo de Due Diligence Legal, IP y Tracción Comercial (`ADR-020`)**:
   - Cierre formal firmado por asesores de las **5 filas abiertas en `docs/legal/open_items.md`** (compatibilidad laboral, no competencia, cadena limpia de cesión de IP desde el día 0, acuerdo limpio del experto B1 y dictamen de control de exportaciones Ley 53/2007 + Reg. (UE) 2021/821).
   - Operación real en clientes: >=10 programas/aeronaves en renovación anual pagada, manual de aseguramiento de diseño de al menos un cliente referenciando explícitamente el mapa de cobertura, y tiempo de despliegue/onboarding por programa medido bajo el techo operativo definido por los fundadores.

#### Mega-Tests de Aceptación Q4 (`tests/mega_q4_e2e_soak_qualification.py`)
- **Soak Test 72 Horas "Unattended 24/7 Air-Gapped"**: desplegar en clúster Kubernetes offline simulado (sin salida internet: DNS/egress bloqueado salvo PG/MinIO/Keycloak/vLLM internos) ejecutando `aeroregu watch` continuamente durante **72 horas seguidas**, inyectando cada hora lotes combinados de STEP + `.bdf` + `.op2` + PDFs de revisión ECN + caídas controladas de pods y cortes transitorios de red. **Criterio**: 0 pérdidas de jobs, 0 inconsistencias de ledger/Merkle, DLQ autocurado tras reconexión, consumo estable de memoria sin fugas (`RSS drift < 5%`) y Morning Briefing 08:00 AM preciso al finalizar las 72 h.
- **Suite IQ/OQ del Qualification Aid Pack**: ejecutar el instalador en un entorno limpio desde cero (Linux air-gapped + Windows estación), correr el runner IQ/OQ completo, exportar **PDF firmado por HSM/eIDAS + bundle ZIP in-toto/DSSE** y verificar offline en una máquina aislada que no comparte base de datos ni acceso a red con el servidor origen. **Criterio**: verificación 100% autónoma (`chain_ok`, `merkle_ok`, `dsse_ok`, `qr_decode_ok`, `traceability_matrix == 100% TOR cubiertos`).
- **Mega-Test UX E2E Multi-Usuario (Playwright)**: flujo completo paralelo entre 3 roles concurrentes (`Designer/Author` sube ECN Rev B y falla `CG drift`; `Daemon` invalida 14 celdas y avisa vía Webhook CI/CD; `CVE` entra vía SSO OIDC + MFA, inspecciona 3D WebGL + bbox PDF + Diff Rev A/B, firma en lote y descarga PDF firmado + QR escaneable). **Criterio**: 0 errores JS/red no esperados, 100% bloqueo SoD ante auto-firma y latencia UI p95 < 300 ms.

---

## 3. Cuadro de Mando de Salida M&A (Checklist Binario "Listo para Venta")

Antes de abrir *Data Room* a compradores estratégicos, **todos** los semáforos siguientes deben estar en **PASS VERIFICADO EN CI**:

| Categoría | Métrica / Evidencia Exigible | Umbral mínimo de salida |
| --- | --- | --- |
| **Cobertura CAE/CAD** | Formatos nativos soportados con mega-tests | STEP B-Rep (OCCT) + CATIA + NASTRAN `.bdf/.f06/.op2/.h5` + ABAQUS `.inp/.odb` + PLM vivo (al menos 2 de 3: 3DEXPERIENCE/Teamcenter/Windchill) |
| **Catálogo Stress** | Métodos clásicos verificados vs literatura | >= 30 tarjetas + MMPDS/CMH-17 + tipo-chequeo de unidades + `MS` en intervalos Arb |
| **Escala & Estabilidad** | Ledger PG real + S3 WORM + Soak test 72h | 100,000+ eventos p95 < 150 ms; PDF 500 pág < 65 s; 72 h air-gapped sin fugas ni pérdidas |
| **IA & Benchmarks** | Holdouts externos independientes (`B1–B4`) | B1 >= 150 casos holdout real; Recall discrepancias críticas >= 99% (resto `ABSTAIN` seguro); 0 citas bbox falsas |
| **Seguridad & Firma** | KMS/HSM + eIDAS/QES + Pentest + SBOM | 0 hallazgos Críticos/Altos OWASP; claves en HSM; CVE DB offline limpia |
| **Cualificación & Legal** | `open_items.md` + Paquete TOR/IQ/OQ + `ADR-020` | 5/5 ítems legales cerrados por escrito; IQ/OQ 100% verde; >= 10 programas en renovación activa |
