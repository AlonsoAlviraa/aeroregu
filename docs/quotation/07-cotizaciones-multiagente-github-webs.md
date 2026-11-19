# Investigación Global: Sistemas Multi-Agénticos de Cotización Automática (RFQ/CPQ) y Motores de Suposiciones en GitHub y Webs Comerciales

**Fecha de investigación:** 19 nov 2026  
**Alcance:** Análisis técnico exhaustivo de repositorios open-source en GitHub (32 proyectos) y plataformas web/comerciales globales (18 soluciones) dedicadas a cotización automática, procesamiento de RFQ/RFP, estimación de costes aeroespaciales/industriales (*Should-Costing*), gestión de suposiciones y verificación formal.

---

## 1. Resumen Ejecutivo: El Estado del Arte y la Brecha Real

Tras auditar el ecosistema global en GitHub y las plataformas industriales de cotización automática, se constatan **cuatro hallazgos clave**:

1. **Sí existen prototipos multi-agénticos RFQ/RFP en GitHub, pero están fragmentados**: Proyectos recientes como `Ethan-YS/quotemind`, `aws-samples/sample-rfq-agent-strands-multi-agent`, `naveendas96/presales-copilot-agents`, `Rakif215/ProcuraAI`, `xvanov/truecost` y `braedonsaunders/bidwright` implementan partes de la tubería (ingesta de PDF/email, búsqueda RAG en catálogo, grafos LangGraph/Strands o simulaciones PERT/Monte Carlo P50/P80/P90).
2. **El patrón ganador de la industria es la separación estricta LLM vs. Motor Determinista**: Tanto en open-source (`kpdagrt22/servicequote-ai`, `naveendas96/presales-copilot-agents`, `Ethan-YS/quotemind`) como en nuestro núcleo [`aeroregu`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer), la regla de oro es que **los LLMs jamás calculan precios ni totales**: extraen entidades a esquemas tipados (Pydantic/JSON Schema) y delegan el cálculo a código determinista sobre un *Price-Book / Rate Card* versionado.
3. **Ningún repositorio open-source resuelve de forma conjunta la tríada aeroespacial crítica**:
   - **(a) Taxonomía exhaustiva de suposiciones en 7 dimensiones** con cláusula de salvaguarda (*Change-Order Fallback*), análisis de sensibilidad Tornado y trazabilidad por *span* exacto al RFQ.
   - **(b) Aritmética exacta `Decimal` + cotas de intervalo `FLINT/Arb` + prueba formal SMT (`Z3`) de supervivencia de margen** en todo el hiper-rectángulo de incertidumbre de las suposiciones.
   - **(c) Cadena de custodia criptográfica (`Ledger` SHA-256 + Merkle + DSSE)** con puerta de abstención (`ABSTAIN`) cuando hay conflicto entre agentes o violación de margen.
4. **En el mercado web comercial**, los incumbentes se dividen en tres silos desconectados: *Should-Costing paramétrico aeroespacial* (**Galorath SEER**, **PRICE TruePlanning**, **aPriori**), *Quoting de fabricación/job-shops* (**Paperless Parts**, **Xometry**, **Spanflug**, **Facturee**, **Digifabster**, **Costimator**, **CADDi**) y *Procurement/RFP SaaS* (**Arkestro**, **Keelvar**, **Fairmarkit**, **Responsive**, **Loopio**, **AutoRFP.ai**, **PROS**, **Tacton**). Ninguno combina transparencia matemática verificable *on-premises* con trazabilidad certificable ni demostración formal SMT.

---

## 2. Catálogo Exhaustivo de Repositorios Open-Source en GitHub (32 Analizados)

### 2.1 Pipelines Multi-Agente para RFQ, RFP y Elaboración de Cotizaciones

| # | Repositorio | URL | Stack Principal | Qué resuelve | Cómo trata suposiciones / cálculos | Brecha frente a `aeroregu` |
|---|---|---|---|---|---|---|
| 1 | `Ethan-YS/quotemind` | https://github.com/Ethan-YS/quotemind | State-machine estilo LangGraph, Python | Pipeline RFQ-a-cotización con tarjetas de características de pieza, recuperación de comparables, BOM borrador, enrutamiento y puerta HITL en cada etapa | Puntuación de transferibilidad de costes y revisión humana por etapa | Sin aritmética `Decimal`/Arb, sin Z3 SMT, sin taxonomía formal en 7 dimensiones |
| 2 | `aws-samples/sample-rfq-agent-strands-multi-agent` | https://github.com/aws-samples/sample-rfq-agent-strands-multi-agent | AWS Bedrock, Strands Agents SDK | Sistema multi-agente para creación automática de RFQ, integración ERP/SAP, rendimiento de proveedores y chequeo REACH/RoHS | Verificación de cumplimiento normativo mediante agentes especializados | Acoplado a nube AWS Bedrock; no es *air-gapped* ni tiene Ledger SHA-256 |
| 3 | `naveendas96/presales-copilot-agents` | https://github.com/naveendas96/presales-copilot-agents | LangGraph, máquina de estados tipada | Copiloto multi-agente RFP/RFQ con trazabilidad de requisitos, estimación explicable de esfuerzo/coste y registro de riesgos con bucle crítico acotado | Estimación explicable y registro de riesgos mediante grafo cíclico | No usa intervalos rigurosos Arb ni demostración SMT de margen |
| 4 | `Rakif215/ProcuraAI` | https://github.com/Rakif215/ProcuraAI | FastAPI, Python, LangGraph, Supabase (PostgreSQL+RLS), React 19 | Plataforma de automatización RFQ: ingesta de emails con LLM, cruce con inventario, pipeline multi-agente y PDF de cotización | Cruce directo contra catálogo de inventario en PostgreSQL | Orientado a compras estándar, sin WBS de ingeniería ni análisis PERT |
| 5 | `vanshjain271/B2B-RFP-Project` | https://github.com/vanshjain271/B2B-RFP-Project | Multi-agente con Gemini/OpenAI, Python | Procesamiento automatizado B2B de RFQ/RFP industriales (cables/manufactura), mapeo de especificaciones a catálogo y cálculo de precios | Mapeo paramétrico desde especificaciones extraídas | Sin agente refutador adversarial ni abstención formal |
| 6 | `killyx/ai-rfp-triage-agent` | https://github.com/killyx/ai-rfp-triage-agent | n8n, FastAPI, OpenAI Structured Outputs | Triaje autónomo de RFP/leads con *model cascading*, vector store de tarifas (*rate cards*) y bloqueo HITL vía Slack | *Rate cards* y propuestas previas en almacén vectorial | Falta motor de suposiciones implícitas con impacto económico Tornado |
| 7 | `tolgadur/rfx-email-agent` | https://github.com/tolgadur/rfx-email-agent | Python, PostgreSQL + pgvector RAG | Monitoriza buzones para RFX, cuestionarios y Excel/CSV adjuntos, fundamentando respuestas en documentación corporativa | RAG sobre documentación de precios y cumplimiento | Sin trazabilidad de *spans* exactos ni cálculo paramétrico de manufactura |
| 8 | `weitzu-com/first-principles-rfq-robot` | https://github.com/weitzu-com/first-principles-rfq-robot | LangGraph, Python | Robot automatizado de consultas a proveedores y RFQ inspirado en razonamiento *first-principles* de manufactura | Descomposición desde primeros principios de cadena de suministro | Prototipo ligero sin auditoría criptográfica |
| 9 | `A2CN-protocol/A2CN` | https://github.com/A2CN-protocol/A2CN | Protocolo SDK compatible LangGraph / CrewAI | Protocolo abierto Agent-to-Agent (A2A) para negociación B2B: RFQ canónico, BAFO (*Best and Final Offer*) y subasta inversa | Mensajería estructurada para rondas de negociación comercial | Define el protocolo A2A, no el motor interno de costes y suposiciones |
| 10 | `SAP-samples/btp-joule-a2a-pro-code-agent` | https://github.com/SAP-samples/btp-joule-a2a-pro-code-agent | SAP Cloud SDK, LangGraph, React | Copiloto empresarial A2A que analiza, puntúa y genera alternativas optimizadas de cotización comercial sobre SAP | Optimización de alternativas de cotización conectadas a ERP | Dependiente del ecosistema SAP BTP |
| 11 | `banthevaishnavi/rfqflow-ai` | https://github.com/banthevaishnavi/rfqflow-ai | Python, Streamlit, SQLite | Procesamiento de emails RFQ, extracción de campos, detección de duplicados y enrutamiento a ERP simulado | Validación de esquema básico en SQLite | Sin motor multi-agente adversarial ni cálculo de ingeniería |

### 2.2 Motores CPQ, *Price-Book* Determinista y Estimación Cuantitativa (PERT / Monte Carlo)

| # | Repositorio | URL | Stack Principal | Qué resuelve | Cómo trata suposiciones / cálculos | Brecha frente a `aeroregu` |
|---|---|---|---|---|---|---|
| 12 | `kpdagrt22/servicequote-ai` | https://github.com/kpdagrt22/servicequote-ai | Next.js, Supabase RLS | Convierte notas técnicas en presupuestos por partidas y PDF de propuesta; prohíbe al LLM inventar precios | Libro de precios explícito (*price-book*) como única fuente de verdad | Solo servicios simples; sin sensibilidad ni verificación SMT |
| 13 | `braedonsaunders/bidwright` | https://github.com/braedonsaunders/bidwright | Python, pgvector híbrido, servidor MCP | Plataforma nativa de estimación/pujas con mediciones 2D/3D, parametrización de conjuntos y servidor MCP para IDEs | Orquestación unificada con parametrización de conjuntos | Orientado a construcción; no cubre tolerancias/materiales aeroespaciales |
| 14 | `xvanov/truecost` | https://github.com/xvanov/truecost | Python, pipeline profundo de 7 agentes | Análisis de planos CAD/PDF, alcance, simulaciones Monte Carlo P50/P80/P90 y comparativa multi-proveedor | Distribución probabilística de riesgo P50/P80/P90 | Dominio construcción; sin aritmética `Decimal`/Arb ni Z3 |
| 15 | `IAmTomShaw/quotation-agent` | https://github.com/IAmTomShaw/quotation-agent | Python, FastAPI WebSockets, OpenAI, Notion DB | Agente conversacional de presupuestos con conversión de divisas en vivo y búsqueda web de tarifas de mercado | Lee tarifas desde base Notion y tasas FX externas | Usa `float` estándar y carece de refutador adversarial o Ledger |
| 16 | `vybetechlabs-blip/enquiry-to-quote` | https://github.com/vybetechlabs-blip/enquiry-to-quote | Python, HITL workflow | Transforma consultas crudas de clientes en borradores cotizados aplicando un *rate card* estructurado | *Rate card* fijo con revisión humana previa al envío | Sin descomposición WBS ni matriz de suposiciones |
| 17 | `shantiNaser/RFQ_system` | https://github.com/shantiNaser/RFQ_system | Python, Django | Aplicación web RFQ para gestionar listas de ítems, generación de RFQ y envío de ofertas entre cliente y proveedor | Flujo transaccional clásico sin agentes IA | Carece de extracción documental, agentes y análisis de riesgo |
| 18 | `paigecew/Simple-Product-Quoting-System-in-Python` | https://github.com/paigecew/Simple-Product-Quoting-System-in-Python | Python | Utilidad ligera para generar cotizaciones estructuradas de productos y cálculo de costes de pedidos | Fórmulas deterministas básicas en Python | Sin ingesta de RFQ ni gestión de suposiciones |

### 2.3 Agentes de Licitaciones (*Tender/RFP*), Cumplimiento y Evidencia Verificable

| # | Repositorio | URL | Stack Principal | Qué resuelve | Cómo trata suposiciones / cálculos | Brecha frente a `aeroregu` |
|---|---|---|---|---|---|---|
| 19 | `GiorgosPanagopoulos/bidpilot` | https://github.com/GiorgosPanagopoulos/bidpilot | Python, agente ReAct, búsqueda semántica | Plataforma de inteligencia de licitaciones: evalúa elegibilidad declarativa, extrae requisitos y redacta propuestas por sección | Reglas declarativas de elegibilidad | Enfocado a texto de licitación, no a escandallo cuantitativo |
| 20 | `Mohamed934789/TenderProof-Core` | https://github.com/Mohamed934789/TenderProof-Core | Python, FastAPI, Streamlit | Sistema multi-agente orientado a revisión de contratos y licitaciones basada en evidencias con citas PDF verificables | Citas verificables a PDF y chequeo de cumplimiento | Sin motor paramétrico de costes ni pruebas Z3 de margen |
| 21 | `aadrikasingh/AI-Powered-RFP-Analyzer` | https://github.com/aadrikasingh/AI-Powered-RFP-Analyzer | Semantic Kernel, Azure | Evaluación automatizada de propuestas de proveedores, puntuación de cumplimiento y análisis de riesgo legal/regulatorio | *Scoring* ponderado contra criterios estrictos | Evaluador comprador (*buy-side*), no elabora cotizaciones con suposiciones |
| 22 | `Start-With-AI/autonomous-rfp-agent` | https://github.com/Autonomous-RFP-Response-System | Multi-agente modular Python | Simula un equipo de ofertas: lector de PDFs, recuperador de contexto, redactor de propuestas y gestor de cumplimiento | Separación por roles de equipo de licitación | Sin aritmética `Decimal` ni motor de suposiciones con sensibilidad |
| 23 | `ishandutta2007/Awesome-RFP-Response-Management` | https://github.com/ishandutta2007/Awesome-RFP-Response-Management | LangGraph, AutoGen, CrewAI | Guía arquitectónica y colección de referencia multi-agente (Estimador de Precios, Redactor Técnico, Revisor Legal, Cumplimiento) | Patrones de coordinación entre roles de oferta | Repositorio de arquitectura/referencia, no un motor productivo ejecutable |
| 24 | `ZainAhmed9/bidengine-ai-showcase` | https://github.com/ZainAhmed9/bidengine-ai-showcase | Python, agentes LLM | Motor de análisis RFP, *compliance scoring* y generación automática de borradores de licitación | Plantillas de respuesta por sección | No calcula márgenes ni acota incertidumbres |
| 25 | `charithmadhuranga/CrewAI-Langgraph-Projects` | https://github.com/charithmadhuranga/CrewAI-Langgraph-Projects | CrewAI + LangGraph, Python | Patrones híbridos que combinan máquinas de estado LangGraph con ejecución autónoma CrewAI y aprobación HITL | Enrutamiento condicional hacia sub-equipos | Patrones genéricos sin dominio ni trazabilidad criptográfica |
| 26 | `Ionio-io/langgraph-with-crewai` | https://github.com/Ionio-io/langgraph-with-crewai | LangGraph + CrewAI, Python | Enrutamiento por grafo de consultas entrantes hacia sub-equipos especializados | Delegación de tareas mediante bordes condicionales | Arquitectura de ejemplo |

### 2.4 Estimación Paramétrica de Esfuerzo, PERT y Costes de Flujos Agénticos

| # | Repositorio | URL | Stack Principal | Qué resuelve | Cómo trata suposiciones / cálculos | Brecha frente a `aeroregu` |
|---|---|---|---|---|---|---|
| 27 | `kiloloop/agent-estimate` | https://github.com/kiloloop/agent-estimate | CLI, GitHub Action | Estima cronogramas PERT, duraciones, horizontes de fiabilidad y costes equivalentes de flotas de agentes IA | Configuración explícita de cargas, *overhead* de revisión y tasas de fallo | Modela costes de ejecución de agentes, no cotizaciones de ingeniería/manufactura |
| 28 | `abhimanyupallavisudhir/costly` | https://github.com/abhimanyupallavisudhir/costly | Python (`@costly()`) | Estima tiempo y coste monetario de *pipelines* LLM antes de ejecutarlos mediante simulación | Simulación paramétrica de tokens y tarifas API | Complementario (presupuesto de inferencia), no motor de cotización B2B |
| 29 | `pydantic/genai-prices` | https://github.com/pydantic/genai-prices | Python / multi-lenguaje | Registro determinista de tarifas de inferencia LLM por proveedor (tokens cacheados, niveles, contexto) | Cálculo exacto por catálogo de precios actualizado | Útil para presupuestar costes de cómputo de IA dentro del RFQ |
| 30 | `RightNow-AI/inference-cost-truth` | https://github.com/RightNow-AI/inference-cost-truth | Python | Modela supuestos de hardware (GPU, utilización, *throughput*) para comparar costes *on-prem* vs. API | Supuestos explícitos de infraestructura de inferencia | Específico de economía GPU |
| 31 | `franbonafina/llm-pricing-analytic` | https://github.com/franbonafina/llm-pricing-analytic | Python, LLMs | Ingesta requisitos software y mapea alternativas cloud (AWS/Azure/GCP) con datos de precios | Comparativa multi-nube de requisitos | Dominio exclusivamente *cloud infrastructure* |

### 2.5 Motores Aeroespaciales, Confinamiento de Salidas y Verificación Formal Integrables

| # | Repositorio | URL | Rol en nuestro Sistema Multi-Agéntico de Cotizaciones |
|---|---|---|---|
| 32 | `OpenMDAO/OpenMDAO` & `fast-aircraft-design/FAST-OAD` | https://github.com/OpenMDAO/OpenMDAO / https://github.com/fast-aircraft-design/FAST-OAD | Dimensionamiento paramétrico preliminar (masas, horas de ingeniería, envolvente) acoplable a cotizaciones de diseño conceptual |
| — | `dottxt-ai/outlines` / `llguidance` | https://github.com/dottxt-ai/outlines | Decodificación restringida por gramática/JSON Schema para impedir que modelos locales emitan números inventados fuera de esquema |
| — | `Z3Prover/z3` | https://github.com/Z3Prover/z3 | Demostración formal SMT de que ninguna perturbación dentro del rango acotado de las suposiciones rompe el margen mínimo de la cotización |
| — | `strictdoc-project/strictdoc` & `oscal-compass/compliance-trestle` | https://github.com/strictdoc-project/strictdoc / https://github.com/oscal-compass/compliance-trestle | Exportación auditable de trazabilidad de requisitos y cumplimiento dentro del dosier de oferta |

---

## 3. Catálogo de Plataformas Web y Comerciales a Nivel Mundial (18 Soluciones Analizadas)

### 3.1 Estimación Paramétrica y *Should-Costing* Aeroespacial / Defensa

| Plataforma | Web Oficial | Modelo de Negocio / Público | Motor Técnico y Gestión de Suposiciones | Limitaciones frente a nuestro enfoque |
|---|---|---|---|---|
| **Galorath SEER** (`SEER-H`, `SEER-Aero`, `SEER-DFM`, `SEER Ply`) | https://galorath.com | OEMs aeroespaciales, NASA, Defensa | Modelos paramétricos históricos de hardware, compuestos (*ply*), electrónica, software, riesgo y calendario cuando aún no existe BOM detallado | Caja negra propietaria de alto coste de licencia; sin agentes LLM auditables sobre RFQ ni cadena Merkle |
| **PRICE Systems TruePlanning** | https://www.pricesystems.com | Programas espaciales (ESA), defensa, grandes contratistas | Predicción de costes de ciclo de vida, desarrollo y fabricación basada en impulsores de complejidad y *TRL* | Requiere parametrización manual experta; no ingesta pliegos heterogéneos con citas por *bbox* |
| **aPriori Digital Factory** | https://www.apriori.com | OEMs Aeroespacial, Automoción, VAVE | Reconocimiento geométrico sobre CAD 3D + simulación de *Digital Factory* (tasas regionales, máquina 5 ejes, fundición, forja, DFM) | Orientado a *should-cost* interno de OEM; no redacta paquetes completos de suposiciones contractuales multi-disciplinares ni pruebas SMT |

### 3.2 Cotización Automática para Proveedores Aeroespaciales, CNC y Job-Shops

| Plataforma | Web Oficial | Público | Cómo automatiza cotización y suposiciones | Limitaciones |
|---|---|---|---|---|
| **Paperless Parts** (*Wingman AI*) | https://www.paperlessparts.com | Talleres de mecanizado y proveedores sub-tier Aeroespacial/Defensa (EE.UU.) | IA especializada que extrae BOMs, revisiones, notas GD&T y paquetes ZIP heredados; aplica reglas de taller sobre ERP e ITAR/CMMC | Cloud propietario EE.UU. (GovCloud); cálculo basado en reglas comerciales sin prueba formal SMT ni paquetes de cálculo estructural |
| **Xometry** (*Instant Quoting Engine*) | https://www.xometry.com / https://www.xometry.eu | Compradores industriales y red de talleres | Motor IQE entrenado en millones de piezas para precios instantáneos, DFM y plazos en CNC, chapa, impresión 3D e inyección | Marketplace cerrado; opacidad sobre las suposiciones internas de margen y sin trazabilidad certificable por *span* |
| **Spanflug** (*Spanflug MAKE*) | https://www.spanflug.de | Talleres CNC europeos (torneado/fresado) | Analiza modelos CAD 3D y planos 2D con IA para calcular tiempos de mecanizado y generar cotizaciones en minutos | Limitado a mecanizado discreto; no cotiza paquetes de ingeniería/certificación ni evalúa riesgo PERT/Z3 |
| **Facturee** | https://www.facturee.de | Ingeniería mecánica y compras industriales en Europa | Plataforma digital de fabricación bajo demanda que unifica cotización y red de producción | Orientada a compra/subcontratación de piezas estándar y mecanizadas |
| **Digifabster** | https://www.digifabster.com | Pymes de mecanizado, chapa e impresión 3D | Reconocimiento de características, DFM y calibración IA sobre matrices de precios para *widgets* web 24/7 | Orientado a e-commerce rápido de piezas comerciales; insuficiente para pliegos complejos CS-27/CS-29 |
| **Costimator** (MTI Systems) | https://www.mtisystems.com | Proveedores de precisión aeroespacial | Estimación asistida por ordenador (ACE) con bibliotecas de velocidades, avances, aleaciones (titanio, Inconel) y tasas de taller | Herramienta clásica de estimación manual/semi-asistida sin pipeline multi-agente LLM |
| **CADDi** (*Drawer / Quote*) | https://us.caddi.com | Compras e ingeniería de manufactura | Visión por computador sobre planos 2D heredados y CAD 3D para extraer cotas, tolerancias y piezas similares | Fuerte en búsqueda visual de planos 2D, no en orquestación multi-agente de suposiciones contractuales |
| **Tacton CPQ** | https://www.tacton.com | Fabricantes de maquinaria y equipos configurables | Configurador basado en restricciones (*constraint-based CPQ*) + venta guiada | Requiere modelado previo rígido de reglas de producto; no procesa RFQ de ingeniería no estructurados |

### 3.3 Plataformas SaaS de Compras Autónomas, RFQ Predictivo y Respuesta RFP

| Plataforma | Web Oficial | Lado del Mercado | Función Principal | Limitaciones |
|---|---|---|---|---|
| **Arkestro** | https://www.arkestro.com | *Buy-side* (Compras) | Orquestación predictiva de compras con ML para lanzar RFPs autónomos y predecir precios de mercado | Enfocada en negociación comercial de proveedores, no en física/coste de ingeniería ni suposiciones técnicas |
| **Keelvar** | https://www.keelvar.com | *Buy-side* (Sourcing Enterprise) | Bots inteligentes de *sourcing* para automatizar eventos RFQ complejos y adjudicación óptima multi-criterio | Optimización de licitaciones para compradores |
| **Fairmarkit** | https://www.fairmarkit.com | *Buy-side* (*Tail Spend*) | Automatiza selección de proveedores, envío de RFQs y comparación de ofertas | Cola de gasto general, sin análisis técnico de planos ni ingeniería |
| **Responsive** (antes RFPIO) | https://www.responsive.io | *Sell-side* (Equipos RFP) | Gestión estratégica de RFx y cuestionarios de seguridad con biblioteca semántica de respuestas | Gestión documental de texto; no calcula costes ni verifica márgenes en `Decimal`/Z3 |
| **Loopio** | https://www.loopio.com | *Sell-side* (Equipos RFP) | Plataforma de respuesta a RFPs y DDQs con flujos de colaboración y aprobación | Sin motor de estimación de costes o suposiciones de ingeniería |
| **AutoRFP.ai** | https://autorfp.ai | *Sell-side* (RFPs/Cuestionarios) | Búsqueda semántica y autocompletado automático de RFPs/RFQs con base de conocimiento | Orientado a texto comercial/seguridad, sin verificación matemática determinista |
| **PROS Smart CPQ** | https://pros.com | *Sell-side* (Enterprise) | Optimización dinámica de precios y CPQ empresarial con ML | Enfoque SaaS comercial de tarifas, sin auditoría criptográfica ni ingesta de pliegos técnicos |

---

## 4. Comparativa Técnica: Por Qué Nuestro Sistema Multi-Agéntico Supera el Estado del Arte

| Capacidad Técnica | Repositorios GitHub típicos (`quotemind`, `ProcuraAI`, `truecost`) | Plataformas Web Comerciales (`Paperless Parts`, `aPriori`, `SEER`) | **`aeroregu` Multi-Agent Quotation Engine** |
|---|---|---|---|
| **Separación LLM vs. Cálculo Matemático** | Parcial (algunos delegan aritmética o usan `float`) | Motores propietarios en `float` | **100% Determinista (`decimal.Decimal` + `FLINT/Arb`)**, prohibido `float` y cero cálculo por LLM |
| **Generación Automática de Suposiciones** | Lista plana informal o inexistente | Implícitas dentro del modelo paramétrico | **Taxonomía exhaustiva en 7 dimensiones** (`TECH`, `MAT`, `MFG`, `REG`, `COM`, `SCH`, `EXC`) con etiqueta, razón, impacto Tornado y cláusula de *Change Order* |
| **Trazabilidad al Pliego Original (RFQ)** | Referencias de texto o sin offsets | N/A o propietario | **Citas verificadas con `[span_start, span_end]`** comprobadas en código determinista |
| **Incertidumbre y Riesgo Cuantitativo** | Puntual (salvo `truecost` Monte Carlo en construcción) | Rangos paramétricos propietarios | **PERT 3 puntos ($P_{50}/P_{80}/P_{90}$) + intervalos `Arb` + análisis Tornado por suposición** |
| **Garantía Formal de Viabilidad de Margen** | Inexistente | Inexistente | **Prueba formal Z3 SMT** sobre todo el hiper-rectángulo continuo de incertidumbre de las suposiciones |
| **Control Adversarial y Puerta de Abstención** | Crítico LLM simple o nulo | Ninguna (siempre emite cifra o alerta UI) | **Agente Refutador Adversarial + `DecisionGate`**: fuerza `ABSTAIN` (`human_engineer`) ante conflicto, dato ausente crítico o colapso de margen |
| **Inmutabilidad y Operación *Air-Gapped*** | Dependen de APIs cloud (OpenAI/Bedrock) y BD estándar | SaaS cloud (salvo despliegues especiales) | **On-premise / Air-gapped**, Ledger SHA-256 + Merkle Tree + atestaciones DSSE Ed25519 |

---

## 5. Arquitectura Implementada en `aeroregu`

1. **Motor de Tarjetas Deterministas (`packages/calc`)**:
   - [`quotation_costing.py`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer/packages/calc/src/evidence_calc/quotation_costing.py) con tarjetas [`aerospace_quotation_costing.json`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer/packages/calc/cards/aerospace_quotation_costing.json) y [`engineering_workpackage_quote.json`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer/packages/calc/cards/engineering_workpackage_quote.json), integradas con intervalos `FLINT/Arb` en [`intervals.py`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer/packages/calc/src/evidence_calc/intervals.py).
2. **Motor Multi-Agéntico de 8 Agentes (`packages/coverage`)**:
   - [`quotation_multiagent.py`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer/packages/coverage/src/evidence_coverage/quotation_multiagent.py): ejecuta secuencialmente bajo supervisión determinista a `rfq_intake_agent` → `scope_wbs_agent` → `assumption_generator_agent` → `deterministic_cost_engine` → `compliance_export_agent` → `adversarial_quote_refuter` (+ Z3 SMT) → `decision_gate_agent` → `quotation_scribe_agent`, sellando cada turno y cálculo en el `Ledger`.
3. **Scraper & Inteligencia Global (`packages/coverage`)**:
   - [`repo_web_scraper.py`](file:///c:/Users/Mariano/Documents/ALONSOO/AIRBUS/evidence-layer/packages/coverage/src/evidence_coverage/repo_web_scraper.py): consolida los 32 repositorios GitHub y 18 webs comerciales con soporte de scraping HTTP en vivo (`api.github.com`, PyPI, HN Algolia, cabeceras web) y respaldo determinista *air-gapped*.
4. **Exposición API, CLI y MCP (`apps/api`)**:
   - Rutas REST `/quotations/*`, comandos CLI `aeroregu quote {generate,assumptions,scrape}` y herramientas MCP `generate_multiagent_quotation` y `scrape_global_quotation_repos`.
