# Parte B — Afirmaciones

Ámbito leído: `README.md`, `docs/legal/gate.md`, `docs/benchmark_spec.md`, `docs/reports/2026-11-03-interim.md`, `docs/pilot/proposal.md`, `docs/reproducibility.md`, `docs/reviews/external_request.md`, `docs/data_register.md` (filas, no los PDF). No se han leído los `.md` de `AIRBUS\paginas` ni `proyecto-ia-helicopteros`. Si ahí hay cifras de mercado o de cliente, esta tabla no las cubre y el hueco es deliberado.

El propio informe interino (cabecera, 9 nov 2026) dice que no reclama certificación, herramienta cualificada ni programa de benchmark terminado. Esa frase, VERIFICADO por lectura, es la más precisa del repo. El riesgo está en las líneas de debajo, que un lector de un piloto puede copiar sin la cabecera.

## Tabla

| Afirmación | Dónde | Etiqueta | Fuente de la etiqueta |
|---|---|---|---|
| La herramienta no determina el cumplimiento | README | VERIFICADO como texto del repo. No es un hecho regulatorio | Lectura 9 nov 2026 |
| 68 tests en verde y 1 aviso (fundador, 3 nov, sin auditar) | prompt de auditoría | La suite de hoy no es esa: 153 tests, 1 aviso, exit 0, 235,6 s | `pytest` de esta sesión |
| 68 tests en 7,26 s | `docs/demo/metrics.md` | CONTRADICHO por la pytest de esta sesión: la barra limpia marcó 160 ítems y tardó 203,6 s. El 68 es una foto vieja | pytest del 9 nov 2026 |
| Recall 1.0 y 0 falsos positivos de 4 casos limpios en el smoke | `docs/demo/metrics.md` | VERIFICADO en las dos pasadas de `score_cases` de hoy para el recall de esos fallos y `false_alarms` 0. El propio fichero dice que generalizar más allá de los casos generados es NOT VERIFIED. Con 4 limpios el intervalo es enorme | `score_dev_two_runs.json` y el propio metrics.md |
| El holdout está congelado y el hash lo prueba | `docs/demo/metrics.md` | El hash existe como texto. El `benchmark_spec` dice que ese directorio lo escribe el mismo autor que el detector. No es un conjunto de experto | Lectura |
| Cita duplicada: el sistema se abstiene, recall 0/1, y eso no es una detección | `docs/benchmark_spec.md` y `docs/benchmarks/make_bench_latest.md` | VERIFICADO como texto del repo. No se ha vuelto a ejecutar ese caso hoy | Lectura |
| S1: 100 000 casos, 7000/7000, falsos positivos 0.000, `llm_numeric_violation` 0 | `s1_two_runs.json` | VERIFICADO como repetición del generador el 9 nov 2026, dos pasadas idénticas. No es un conjunto externo. El campo `date` del informe dice 2026-11-03 | JSON de esta sesión |
| La semilla gobierna el generador | data register, S1 | FALSO respecto del código. `S1_SEED` se copia al informe. `iter_cases` no lo consulta | Lectura de `s1.py` |
| `beats_single_llm` | proposal, interim | NO VERIFICADO. El propio texto lo dice. No hay llamada de red en esta auditoría | Lectura |
| B1 con experto | benchmark_spec | NO VERIFICADO como resultado. El directorio de experto está vacío. El repo lo dice | Lectura |
| B2 8/8 y el agente no gana al verificador | proposal | NO VERIFICADO hoy. No se ha vuelto a ejecutar `score_b2` | Lectura |
| B3 8/8 y 5/5 sobre NASA TM | interim | NO VERIFICADO hoy. Los PDF están en `data/ntrs/`. El oro es de la misma sesión que el lector. El repo lo dice. Licencia PARTIAL por coautoría, según el registro; no reabierta hoy | Lectura |
| B4 listo | interim, proposal | El repo dice que no. VERIFICADO como negación escrita. El contenido de los ficheros locales no se ha reanalizado hoy | Lectura |
| Dos ingenieros externos han revisado | external_request | NO VERIFICADO. El fichero dice que no ha habido revisión | Lectura |
| Hay un cliente o un piloto firmado | interim | El texto dice que no hay socio de diseño nombrado y que la propuesta no está lista para enviarse | Lectura |
| `gate.md` es un visto bueno del abogado | gate.md | FALSO. El fichero dice que no lo es. Estado: el fundador ordenó empezar el 3 nov 2026 | Lectura |
| Los cinco asuntos de empleo, no competencia, PI, el experto y la exportación siguen ABIERTOS | `docs/legal/open_items.md` | VERIFICADO como estado escrito el 3 nov 2026. El fichero dice que una demo no los cierra. No se ha visto una nota posterior que los cierre | Lectura 9 nov 2026 |
| Si la máquina de este trabajo es personal | `docs/legal/checklist.md` | NO VERIFICADO. El propio checklist lo dice | Lectura |
| El guion de la demo enseña 405 celdas y una firma que no dice compliant | `docs/demo/storyboard.md` | VERIFICADO como texto. Las 405 no son VTOL.2210. La firma sigue sin acreditar competencia | Lectura 9 nov 2026 |
| La firma de la demo no es una firma electrónica cualificada eIDAS. Las contraseñas son fixtures | `docs/adr/ADR-012-auth-and-tenancy.md` | VERIFICADO como texto del ADR. Coincide con las contraseñas fijas del código | Lectura |
| «Benchmark industrial» o «no existe ningún benchmark público» | no encontrado en los docs leídos | Esas fórmulas no están en el README ni en el informe interino. `AIRBUS\regulacion\benchmarks-publicos.md` no se ha contrastado línea a línea con una búsqueda nueva. NO VERIFICADO como ausencia mundial | Esta sesión |
| No hay cifra de valoración verificada | `docs/adr/ADR-020-valuation-gates.md` | VERIFICADO como texto del ADR: ingresos, clientes y múltiplo no se verificaron. La cifra es ASSUMPTION. El producto no incluye una afirmación de valoración | Lectura 9 nov 2026 |
| CS-27, CS-29 y SORA no están construidos | `docs/adr/ADR-014-out-of-scope.md` | VERIFICADO como texto. Coincide con el código: no hay un paquete que implemente esos requisitos | Lectura 9 nov 2026 |
| Quien reescriba el fichero y rehaga la cadena puede falsificar filas | `docs/adr/ADR-006-ledger.md` y `docs/security/threat-model.md` | VERIFICADO como límite que el propio repo escribe. La prueba de tamper de esta auditoría no cubre una cadena nueva y coherente | Lectura y `ledger_tamper.json` |
| Fases 4–7 construidas | README | El README dice que no están construidas (ADR-016 a ADR-020) | Lectura |
| CI de GitHub en verde | reproducibility.md | NO VERIFICADO. El propio doc lo dice: no hay corrida de GitHub mostrada. No hay remoto que esta auditoría haya consultado, y no se publica nada | Lectura |
| Anexo I sección B punto 20 solo UAS | registro y vault | VERIFICADO hoy en el consolidado 02024R1689-20260727, punto 20: solo aeronaves no tripuladas del 2018/1139 | EUR-Lex leído 9 nov 2026 |
| Proyecto de ley de IA «estado posterior NO VERIFICADO» | vault R29, corte 8 nov | Desactualizado. Hoy la ficha del Congreso dice Caducado | congreso.es, 9 nov 2026 |
| NPA 2025-07 y CP3 siguen en el estado del 8 nov | vault | NO VERIFICADO hoy. No se ha reabierto la página de EASA en esta sesión | Hueco de esta auditoría |

## Exageraciones

1. Llamar VERIFICADO a un `make bench` del mismo autor. El número puede ser repetible y seguir sin ser una medida de un sistema que vea fallos ajenos. El informe interino mezcla las dos etiquetas en el mismo bloque.
2. Imprimir una semilla que el generador no usa. Parece control experimental y es una constante decorativa.
3. Arrastrar «68 tests» y «4 casos limpios» como foto del producto. La suite ya no es esa, y el intervalo de 4 casos limpios no aguanta una frase de falsos positivos.
4. Cualquier uso externo de 0/8000 sin decir que los 8000 los fabrica el detector. El proposal lo llama ESTIMATE. Quien borre esa palabra obtiene una exageración.
5. La firma y el hash no son un organismo notificado, ni un TQL, ni DO-330. El README no lo dice. Conviene que ninguna página de `AIRBUS\paginas` lo diga; no se han leído, así que eso queda como tarea de Alonso, no como hallazgo de texto.

## Coherencia

README, gate, benchmark_spec e informe interino coinciden en la abstención y en que B1 no existe. Chocan con el prompt de auditoría del 8 nov, que todavía describe 68 tests y 24 casos: el código se movió y el prompt de encargo no. El vault y el registro del 8 nov son coherentes entre sí. El vault se queda corto el 9 nov en el proyecto de ley caducado. Las fechas de alto riesgo tras 2026/1744 (2 dic 2027 anexo III, 2 ago 2028 anexo I) coinciden con el consolidado leído hoy.
