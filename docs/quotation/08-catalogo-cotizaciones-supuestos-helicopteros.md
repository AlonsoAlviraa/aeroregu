# Catálogo de Cotizaciones, Tarifas por País, 18 Arquetipos y Supuestos para Ingeniería de Helicópteros

> Documento de referencia técnica para el motor de cotización multiagente y determinista (`rotorcraft_quotation_catalog.py` + `rotorcraft_archetype_quote.json`) orientado a departamentos de diseño, cargas, cálculo estructural, F&DT, dinámica, DOA y ensayos de helicópteros bajo **EASA CS-27 / CS-29 / Part 21J / Part 21G**.
>
> **Regla metodológica:** Toda cifra contractual o paramétrica que no procede de un libro de tarifas firmado ni de una medición auditada se etiqueta explícitamente como `ASSUMPTION` o `ESTIMATE`. El sistema **asiste** al equipo de ingeniería, compras y **CVE (Compliance Verification Engineer)**; **nunca** sustituye el criterio del CVE ni declara cumplimiento normativo por sí solo.

---

## 1. Estudios y Modelos Científicos / Institucionales de Estimación de Costes y Esfuerzo

El motor calibra sus factores paramétricos, intervalos de incertidumbre (`python-flint` / Arb + PERT) y desglose causal WBS mediante seis estudios públicos de referencia en ingeniería aeronáutica y de sistemas:

| ID | Estudio / Fuente | Mecanismo aplicado al presupuesto de helicópteros | Parámetros y restricciones clave (`ASSUMPTION` / `ESTIMATE`) |
|---|---|---|---|
| **MOD-1** | **NASA NDARC** (*NASA Design and Analysis of Rotorcraft*, Ames TP-2015-218751, Johnson / Scott CTM) | **Cost Estimating Relationships (CER)** por subsistema rotatorio y clase de peso vacío (*Weight Empty*, *MTOW*, diámetro de rotor principal, arquitectura single vs. coaxial/compound) | Escalado de ingeniería NRE por complejidad aeromecánica; separa estructura primaria, grupo dinámico (`MRB`/`MRH`/`MGB`) y aviónica/equipos de misión |
| **MOD-2** | **RAND Airframe & Rotary-Wing Cost Models** (Younossi et al., RAND MG-196 / MR-1695; NAFCOM material complexity) | **Multiplicadores por material estructural y nivel de certificación**: aluminio aeronáutico `1.00`, aleaciones Ti `1.65`, laminados **CFRP** híbridos/co-curados `1.45`–`1.85`; prima de complejidad **CS-29** frente a **CS-27** | Explica por qué el *ply-book* compuesto (`Q-DES-03`), la evaluación de delaminación/impacto y el análisis micro-mecánico incrementan horas de cálculo, documentación DOA y revisión CVE |
| **MOD-3** | **USC COSYSMO** (*Constructive Systems Engineering Cost Model*, Valerdi & Boehm, INCOSE) | **Modelado del esfuerzo de ingeniería de sistemas e integración** en función de requisitos, interfaces externas/internas, algoritmos críticos y escenarios operacionales (en lugar de SLOC/planos puros) | Captura el sobrecoste de cambios tardíos en interfaces (**ICD**), integración HEMS/Grúa/Gancho (`Q-DOA-02`) y trazabilidad bidireccional requisito ↔ análisis ↔ ensayo |
| **MOD-4** | **Curran, Scanlan & Roy — Genetic-Causal Design-to-Cost (MDO)** (proyectos DATUM / FLAVIIR, Cranfield / QUB) | **Costeo causal *Feature-Based* unido a árbol WBS**: vincula parámetros de geometría y fabricación (número de nervaduras, *fasteners*, tolerancias, *tooling*, utillaje) directamente con horas CAD/FEM/CNC | Evita la «caja negra» puramente estadística permitiendo auditoría de sensibilidad (*Tornado*) por parámetro geométrico o documental |
| **MOD-5** | **GARTEUR HELIX / FELIX / ASTERIX & Predictive Virtual Testing (PVT)** (*HeliSafe*, AG-14/16/22, Clean Sky / DLR / ONERA) | **Compresión de la pirámide de ensayos** (*Building Block Approach*): el uso de modelos FEM validados, correlación modal/GVT y gemelos virtuales reduce ensayos destructivos/en vuelo a cambio de mayor esfuerzo de correlación y verificación | Ajusta la balanza entre horas de simulación avanzada (`Nastran SOL 103/111/400`, `LS-DYNA`), instrumentación **FTI** (`Q-TST-02`) y campañas en banco (`Q-TST-01`) |
| **MOD-6** | **EASA AI Concept Paper Issue 2 & Part 21.A.239(b) CVE Independence** | **Gobernanza y ratio mínimo de verificación independiente CVE**: ningún algoritmo automático ni herramienta IA puede auto-firmar entregables de aeronavegabilidad; requiere trazabilidad humana Nivel 1/2 y revisión CVE segregada | Impone un piso de **8 % a 15 %** de horas de verificación independiente **CVE** según criticidad CS-27/CS-29 y prohíbe al autor firmar su propio análisis crítico |

### Reglas de escalado paramétrico incorporadas al cálculo
- **Base CS-27 vs CS-29:** Los programas **CS-29** (categoría A/B > 3 175 kg o > 9 plazas) aplican factor estructural y documental superior (`1.35x` respecto a base CS-27 en certificaciones completas).
- **Complejidad de material:** Factor `1.00` (Al-2024/7075 metálico), `1.45` (híbrido metal-CFRP), `1.75` (primario CFRP / sándwich nido de abeja), `1.65` (Ti-6Al-4V / aceros especiales de transmisión).
- **Madurez de datos de entrada (IDP):** Un **Input Data Package (IDP)** completo baja el buffer de contingencia/riesgo al tramo mínimo; IDP incompleto o sin cargas congeladas dispara prima de incertidumbre y/o Split **Fixed-Price + Capped T&M** o estado `ABSTAIN`.

---

## 2. Tarifario Regional: Base Europea por Defecto (`EU_DEFAULT`) + 8 Perfiles por País

Todos los importes se expresan en **EUR/hora** (`ASSUMPTION`, tarifas B2B de mercado externo de ingeniería aeroespacial completamente cargadas / *fully burdened* antes de IVA, convertidas a EUR equivalente para comparación homogénea). Cada cotización incluye el cálculo del país seleccionado **y** la tabla comparativa automática de los **9 perfiles**, además de la opción híbrida **Onshore CVE + Nearshore Stress Execution**.

| Código | Perfil / País | CAD Diseño | Cargas / Aeroel. | Cálculo Senior FEM | F&DT / Crash / Din. | Sist. / Rayo / Firewall | Ensayos / FTI | CVE Indep. | Taller Proto / CNC | HPC Solver (€/h) | Overhead (%) | Conting. (%) | Notas contractuales / export / fiscales |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **`EU_DEFAULT`** | Base Europea (Referencia PO) | 88 | 108 | 112 | 122 | 115 | 102 | 138 | 85 | 18 | 12 | 10 | Referencia neutra pan-europea EASA Part 21J/G |
| **`FR`** | Francia (Toulouse / Marignane) | 96 | 118 | 124 | 134 | 125 | 112 | 150 | 95 | 18 | 14 | 10 | Derecho laboral francés, seguridad DGA/ITAR-free, tarifa senior Toulouse/Marignane |
| **`DE`** | Alemania (Donauwörth / Ottobrunn) | 104 | 126 | 132 | 144 | 135 | 120 | 160 | 105 | 19 | 15 | 10 | Convenios IG Metall / AÜG subcontratación, sobrecoste de documentación BfL |
| **`ES`** | España (Albacete / Madrid / Sevilla) | 74 | 92 | 95 | 104 | 98 | 88 | 122 | 72 | 17 | 11 | 9 | Hubs Albacete/Getafe/Sevilla; alta competitividad coste-calidad DOA CS-29/NH90/H135 |
| **`IT`** | Italia (Cascina Costa / Brindisi) | 82 | 100 | 105 | 114 | 108 | 96 | 130 | 80 | 18 | 12 | 10 | Clúster Lombardía-Piamonte; sólida experiencia en transmisiones y rotores |
| **`UK`** | Reino Unido (Yeovil / Bristol) | 94 | 114 | 118 | 128 | 122 | 108 | 146 | 92 | 19 | 13 | 11 | **IR35** (*off-payroll working*), doble marcaje CAA UK + EASA post-Brexit, riesgo FX GBP/EUR |
| **`US`** | Estados Unidos (TX / CT / AZ) | 128 | 152 | 158 | 172 | 162 | 145 | 195 | 130 | 22 | 16 | 12 | Regulación **ITAR / EAR** (TAA requerido), seguro de responsabilidad USA elevado, riesgo FX USD/EUR |
| **`PL`** | Polonia (Mielec / Świdnik / Rzeszów) | 58 | 72 | 76 | 84 | 78 | 70 | 102 | 56 | 16 | 10 | 10 | Aviation Valley; fuerte capacidad estructural y aeroespacial competitiva dentro de la UE |
| **`IN`** | India (Bengaluru / Hyderabad) | 42 | 54 | 58 | 66 | 60 | 52 | 90 | 44 | 15 | 10 | 14 | GCCs offshore; requiere restricción ITAR/EAR/EU-Export, coordinación horaria y **CVE Onshore obligatorio** |

### Modelo híbrido recomendado (*Onshore CVE + Nearshore Execution*)
- En trabajos de cálculo masivo o malla FEM (`Q-STR-02`, `Q-STR-03`, `Q-FDT-01`), combinar ejecución *nearshore* UE (`ES` o `PL`) con dirección técnica, verificación **CVE** y firma **Part 21J** *onshore* (`EU_DEFAULT`, `FR`, `DE` o `UK`) mantiene la soberanía de datos **EASA/ITAR-free** sin fricción aduanera de exportación de tecnología de defensa fuera de la UE.

---

## 3. Catálogo de 18 Arquetipos Profesionales del Departamento de Helicópteros

Cada arquetipo agrupa puestos reales del departamento (de los 28 perfiles identificados en `paginas/05-departamento-puestos-tesis-30m-llm.md`), cadena de herramientas (*CATIA V5/3DEXPERIENCE*, *Patran/Apex*, *MSC Nastran*, *Altair HyperMesh/OptiStruct*, *Abaqus*, *LS-DYNA*, *NASGRO/AFGROW*, *CAMRAD II / FLIGHTLAB*), IDP obligatorio, entregables certificables, estimación PERT `(O, M, P)` de horas base y reparto contractual (`Fixed-Price %` vs `Capped T&M %`).

| ID | Arquetipo Profesional | Cláusulas EASA CS-27/CS-29 | Roles principales | Entregables clave | Split contractual (FP / Capped T&M) | PERT Base (O / M / P h) |
|---|---|---|---|---|---|---|
| **`Q-DES-01`** | Concepto & Arquitectura Preliminar de Fuselaje/Cabina | CS 27/29.301, 29.771, 29.803 | Arquitecto Aeronáutico, Ergonomía, Pesos | Layout 3D, envolvente espacial, DMU preliminar, Trade-off | 70 % / 30 % | 220 / 320 / 480 |
| **`Q-DES-02`** | Diseño Detallado Metálico (Mecanizados, Chapa, Herrajes) | CS 27/29.603, 29.607, 29.611 | Proyectista Mecánico, Materiales, M&P, DFM | Modelos CATIA 3D PMI/GD&T, planos 2D, BOM, Stack-up | 80 % / 20 % | 260 / 380 / 540 |
| **`Q-DES-03`** | Diseño Compuestos & *Ply-Book* Laminado (CFRP/Sandwich) | CS 27/29.573, AMC 20-29 | Proyectista Composites, M&P, Laminación | Catia CPD *Ply-Book*, tablas de caída (*drop-off*), utillaje | 75 % / 25 % | 300 / 440 / 640 |
| **`Q-DES-04`** | Gestión de Configuración, Pesos & Centrado (W&B) y BOM | CS 27/29.25, 29.27, 29.1519 | Ingeniero W&B, Configuración PLM/EBOM | Informe W&B, envolvente CG longitudinal/lateral, árbol EBOM | 85 % / 15 % | 140 / 210 / 310 |
| **`Q-STR-01`** | Generación y Envolvente de Cargas (Vuelo, Tierra, Rotor) | CS 27/29 Subpart C (29.321–29.511) | Ingeniero Cargas, Aerodinámica Rotatoria | Matrices de casos límite/últimos, diagramas V-n, espectros | 60 % / 40 % | 320 / 460 / 700 |
| **`Q-STR-02`** | GFEM Global de Fuselaje Completo & Balanceo Inercial | CS 27/29.305, 29.307 | Analista FEM Global, Cargas | GFEM `.bdf`, auditoría `.f06` GPWG/OLOAD/SPCFORCE/EPSILON | 70 % / 30 % | 380 / 560 / 820 |
| **`Q-STR-03`** | DFEM Detallado & Dosier Completo de Cálculo Estático | CS 27/29.305, 29.307, 29.625 | Calculista Estructural Senior, CVE | DFEM submodelo, cálculo clásico+FEM (Huth, *buckling*, `MS_min`), Stress Report | 75 % / 25 % | 340 / 500 / 740 |
| **`Q-STR-04`** | Verificación de Proveedores / *Sub-Tier Stress Gatekeeper* | Part 21.A.239, 21.A.131 | CVE Estructural, Gatekeeper Proveedor | Lista de hallazgos, auditoría CAD↔BDF↔F06↔PDF, nota CVE | 65 % / 35 % | 160 / 240 / 380 |
| **`Q-FDT-01`** | Fatiga & Tolerancia al Daño (F&DT) de Estructura Primaria | CS 29.571, 29.573 (AC 29-2C / AMC 20-29) | Especialista F&DT, Fractura, Materiales | Análisis Miner + propagación `da/dN`, intervalos inspección (ALS/ICA) | 55 % / 45 % | 420 / 640 / 980 |
| **`Q-FDT-02`** | Vida Segura (*Safe-Life*) de Componentes Dinámicos (`MRB`/`MRH`/`MGB`) | CS 29.571(e), 29.547, 29.917 | Especialista Rotores y Transmisión, F&DT | Curvas S-N reducidas, espectros piloto-esfuerzo, límites de retiro | 50 % / 50 % | 480 / 720 / 1100 |
| **`Q-DYN-01`** | Dinámica Estructural, Modos vs `N·b·Ω`, *Ground Resonance* & Flutter | CS 29.241, 29.629, 29.631 | Ingeniero Dinámica, Aeroelasticidad, GVT | Diagrama Campbell / Fan Plot vs `1Ω`/`N·b·Ω`, correlación GVT, estabilidad | 55 % / 45 % | 360 / 540 / 840 |
| **`Q-DYN-02`** | Crashworthiness, Energía de Impacto & Retención de Masa/Asientos | CS 29.561, 29.562, 29.785 | Especialista Impacto Explícito (`LS-DYNA`) | Simulación no lineal explícita, deceleraciones HIC/lumbar, fusible de tren | 50 % / 50 % | 440 / 680 / 1040 |
| **`Q-DYN-03`** | Impacto de Ave (*Bird Strike*), Granizo y Amaraje (*Ditching*) | CS 29.631, 29.801, 29.802 | Especialista ALE/SPH (`LS-DYNA` / `Pam-Crash`) | Modelo FSI/SPH parabrisas-nariz, presiones hidrodinámicas, flotación | 50 % / 50 % | 400 / 600 / 920 |
| **`Q-DOA-01`** | Reparaciones, Concesiones MRB & Boletines de Servicio (SB) | Part 21J Subpart D/E, 21.A.435 | Ingeniero MRB/Sustainment, CVE | Clasificación Minor/Major, cálculo reparación en FEM congelado, SB | 45 % / 55 % | 90 / 140 / 240 |
| **`Q-DOA-02`** | Integración Equipos de Misión & STC (HEMS, Grúa HEC, Gancho, EO/IR) | CS 29.865, 29.785, Part 21 Subpart E | Ingeniero Integración STC, Diseño, Cálculo | Diseño soportes, interfaz ICD, cálculo estático/F&DT, suplemento RFM | 65 % / 35 % | 300 / 460 / 700 |
| **`Q-DOA-03`** | Propulsión, Soportes Motor/APU, *Firewall* y Rayo / HIRF | CS 29.1191, 29.1316, 29.1317, DO-160G | Especialista Termo-mecánico, EMC/Rayo, CVE | Verificación zona fuego 1100 °C 15 min, rutas retorno rayo/HIRF, soportes | 60 % / 40 % | 320 / 480 / 740 |
| **`Q-TST-01`** | Diseño de Bancos de Ensayo Estructurales, Utillaje & Correlación | CS 29.307, AMC 20-29 | Ingeniero Ensayos Tierra, Proyectista Utillaje | Diseño utillaje carga/reacción, Test Plan, correlación FEM-galgas (±%) | 65 % / 35 % | 280 / 420 / 660 |
| **`Q-TST-02`** | Instrumentación **FTI**, Ensayos en Vuelo & *Permit to Fly* (PtF) | Part 21J Subpart P (PtF), CS 29.307(d) | Ingeniero FTI, Mecánica de Vuelo, CVE | Soportes FTI sin interferencia de modos/seguridad, Flight Test Conditions, PtF | 55 % / 45 % | 310 / 470 / 720 |

---

## 4. Taxonomía de Supuestos en 10 Dimensiones (40+ Supuestos Estandarizados)

Toda cotización clasifica y bloquea sus hipótesis en **10 dimensiones auditables**. Si el cliente modifica cualquiera de ellas tras la oferta, se dispara una **Orden de Cambio (Change Order)** o un bloqueo **fail-closed (`ABSTAIN`)**:

1. **`TECHNICAL_SCOPE`** (Alcance técnico y frontera del paquete): Congelación de configuración CAD/DMU/PDM, exclusión de rediseño por fallo estructural detectado, alcance de entregables por revisión (A/B/C), número de variantes geométricas.
2. **`ROTORCRAFT_LOADS_SPECTRA`** (*Específica de helicópteros*): Disponibilidad y congelación del libro de cargas CS-27/CS-29 (vuelo estacionario, autorrotación, maniobras asimétricas, aterrizaje duro), factores de carga límites/últimos y espectros de uso de misión (HEMS, Offshore O&G, SAR, Utility).
3. **`DYNAMICS_VIBRATION_AEROELASTIC`** (*Específica de helicópteros*): Frecuencias de paso de pala (`1Ω`, `b·Ω`, `2·b·Ω`), amortiguamiento estructural asumido, necesidad de correlación GVT/Whirl Tower y exclusión de inestabilidad aeromecánica salvo contratación explícita.
4. **`DOA_CERTIFICATION_PRIVILEGES`** (*Específica de helicópteros*): Titularidad del privilegio **Part 21J DOA**, separación funcional autor vs **CVE independiente**, idioma de dosieres (EN/ES/FR), tasa de rondas de preguntas **CRI / CAI** de la Autoridad (EASA/FAA).
5. **`DATA_AND_IDP`** (Madurez del *Input Data Package*): Completitud de planos 2D/STEP/CATIA, propiedades de materiales certificadas (MMPDS / CMH-17 / especificaciones OEM), malla FEM existente sin geometría corrupta (`EPSILON` / penetraciones).
6. **`SCHEDULE_AND_ITERATIONS`** (Plazo y ciclos de iteración): Límite máximo de ciclos CAD↔FEM incluidos (típico 2 ciclos), SLA de respuesta del cliente a RFD/RFIs (5 días laborables), restricción de paralelismo ante ausencia de *freeze*.
7. **`COMMERCIAL_AND_RATES`** (Tarifario y estructura contractual): País de tarifa seleccionado + perfil de referencia, validez de la oferta (60 días), desglose **Fixed-Price vs Capped T&M**, exclusión de costes de licencia física o tiempo de túnel/banco externo salvo partida explícita.
8. **`LEGAL_IP_AND_EXPORT`** (Propiedad intelectual y control de exportación): Clasificación **ITAR / EAR / Dual-Use UE (Reg. 2021/821)**, soberanía del repositorio de cálculo (EU-only cuando sea aplicable), limitación de responsabilidad por uso no autorizado fuera del espectro declarado.
9. **`TOOLING_AND_COMPUTE`** (Cómputo HPC y cadena de herramientas): Versión exacta de solver (*MSC Nastran*, *CATIA*, *Abaqus*, *LS-DYNA*), horas HPC incluidas por corrida no lineal, disponibilidad de licencias del cliente o propias.
10. **`RISK_AND_ABSTAIN_TRIGGERS`** (Gatillos de `ABSTAIN` y cambio de alcance): Falta de base de certificación CS-27 vs CS-29, ausencia de espectros de carga en F&DT, solicitud de asumir margen estructural positivo sin datos de material trazables, o petición de auto-certificación sin CVE.

### Reglas de bloqueo obligatorio (`ABSTAIN`)
El motor se detiene en modo `ABSTAIN` (sin emitir precio vinculante ni números físicos inventados) si ocurre cualquiera de las condiciones siguientes:
- Descripción del RFQ vacía o fuera de dominio sin parámetros mínimos.
- País solicitado inexistente en el tarifario oficial (`EU_DEFAULT`, `FR`, `DE`, `ES`, `IT`, `UK`, `US`, `PL`, `IN`).
- Arquetipo incompatible o base de certificación no especificada en trabajos críticos de aeronavegabilidad cuando falta información contractual mínima.
- Solicitud explícita de omitir verificación independiente CVE en entregables Part 21J o de «garantizar cumplimiento» sin datos de ensayo/materiales.

---

## 5. Escalado a 2.000+ Cotizaciones Históricas, Extracción Física IDP y k-NN

Para resolver el cuello de botella empírico sin introducir subjetividad humana ni errores de punto flotante, el motor incorpora tres subsistemas integrados (`historical_quotation_calibrator.py` + `rotorcraft_historical_calibration.json`):

1. **Ingesta Masiva de Cotizaciones Históricas (*As-Bid vs. As-Burned*):**
   - Admite lotes CSV, JSON o JSONL de **2.000+ cotizaciones pasadas** con sello SHA-256 por registro y digest completo del dataset (`dataset_sha256`), más un corpus sintético de referencia reproducible de **2.160 registros** (`SYNTHETIC_BENCHMARK_ASSUMPTION`) para validación previa a la entrega del histórico real.
   - Ejecuta validación temporal **80/20** (*Pre-Calibration MAPE* vs. *Post-Calibration MAPE*) y mezcla las ternas PERT previas con los cuantiles empíricos reales `P10 / P50 / P90` mediante credibilidad determinista de Bühlmann (`w = min(1, n / n_full)`) e intervalos `FLINT/Arb` a 50 dígitos.
2. **Extractor Objetivo de Complejidad Física desde Adjuntos IDP (`.bdf`, `.f06`, `.stp`, `.dxf`):**
   - Inspecciona mazos Nastran `.bdf` (`GRID`, `CQUAD4`/`CHEXA`, `CBUSH`/`PBUSH`/`RBE2`/`RBE3`, `PCOMP`, `SUBCASE`), salidas `.f06` (`GPWG`, `OLOAD`/`SPCFORCE`, `EPSILON > 1e-6`, `FATAL MESSAGE`), sólidos STEP y entidades DXF.
   - Fija automáticamente `idp_maturity`, `cosysmo_complexity` y `idp_feature_complexity_factor` (`0.850`–`1.650`).
3. **Recuperación Determinista *k-NN* de Ofertas Pasadas Similares:**
   - Compara cada nuevo RFQ frente a las **2.000+ ofertas** mediante distancia ponderada exacta en `Decimal` (arquetipo, familia, base CS-27/29, material, país, madurez IDP y métricas geométricas FEM/CAD) devolviendo las **$k$ ofertas más cercanas** con su desviación real de horas y los supuestos históricamente rotos.
