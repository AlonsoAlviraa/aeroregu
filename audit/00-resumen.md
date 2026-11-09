# Resumen de auditoría — aeroregu

Fecha: 9 nov 2026. Auditor: agente de código, papel de auditor independiente. No es asesoramiento jurídico ni una opinión de certificación.

## Conclusión

El repositorio, en `aeroregu`, hace una ayuda al revisor: dos cribados en `Decimal`, un libro con hash y una abstención cuando el chequeo falla. Los tests de esta máquina pasan. Dentro de ese código hay cuentas que ignoran entradas que la propia rejilla presenta como ejes. La altitud no entra en la fuerza. El espesor del tornillo no entra en la tensión. De las 405 celdas, solo 135 cambian el resultado. `POST /calc/run` escribe en el libro sin cookie si el cuerpo pide `record`. El benchmark lo puntúa el mismo paquete que siembra los fallos. Una firma comprueba una frase fija, no la competencia de quien firma. Nada de eso es la envolvente que piden VTOL.2210 o VTOL.2215.

El árbol no tiene ningún commit. No hay hash que citar. El «checkout limpio» que pide el prompt no existe. Las cifras de S1 que los informes llaman VERIFICADO salen del mismo paquete que escribe los fallos. La semilla `20261103` se imprime y no entra en el generador.

Al lado, en `Documents\ALONSOO\AIRBUS`, hay ficheros cuyo nombre apunta a un empleador. No se han abierto. Esa vecindad es el hallazgo crítico de confidencialidad.

## Cinco hallazgos

1. **CRÍTICA.** Material con nombre de empleador en la carpeta hermana `AIRBUS` (páginas y `proyecto-ia-helicopteros.pdf` / `.docx`). No leído. Puerta: abogado laboral y de PI antes de seguir, y ningún fichero de esa carpeta dentro del repo.
2. **CRÍTICA.** Cero commits en `master`. 188 ficheros en el índice y 69 sin seguimiento. No hay congelación real del conjunto reservado. `docs/legal/gate.md` solo registra que el fundador ordenó empezar.
3. **ALTA.** El benchmark lo puntúa quien lo siembra. Dos pasadas de S1, el 9 nov 2026, dieron el mismo informe: 100 000 casos, 7000/7000, falsos positivos 0.000, `llm_numeric_violation` 0. El intervalo que imprime el propio código para esos falsos positivos es 0.000–0.000, porque redondea a tres decimales. La semilla no entra en el generador. No hay experto en el conjunto reservado.
4. **ALTA.** La demo escucha en `0.0.0.0:8000`. `POST /calc/run` con `record` appende eventos y marca celdas como `human` sin cookie. El export del libro tampoco mira la sesión. Contraseñas y secreto de sesión van fijos en el código.
5. **ALTA.** `altitude_m` y `thickness_mm` se validan y no se usan. Las unidades solo se miran si el llamante manda `_input_units`. Un número entero en texto no dispara `llm_numeric_violation`.

## Decisión siguiente

Parar cualquier frase de piloto, valoración o «conforme» hasta que haya un commit, un conjunto escrito por otra persona y un abogado haya visto el empleo y la PI. La ingeniería puede seguir en local, en `127.0.0.1`, sin datos de empleador y sin presentar la rejilla de 405 celdas como cobertura de certificación.

Los informes de esta carpeta no se han publicado, no hay commit y no hay push.

## Lo que el encargo pedía y no se pudo cerrar

- Checkout limpio: no hay ningún commit. No existe un `git worktree` del que repetir los tests. Las dos pytest y las dos pasadas de S1 corrieron en el árbol sucio.
- Otra semilla de S1: `S1_SEED` no entra en el generador. Cambiarla sería editar el código auditado.
- `make bench`: reescribe `docs/benchmarks/`. No se lanzó. El sustituto es `audit/repro/run_audit_metrics.py`.
- `gitleaks`: no está en el PATH. El sustituto es `tools/security/secret_scan.py`, que dijo `secret scan ok`.
- NANDO: ni la página por legislación ni `https://webgate.ec.europa.eu/single-market-compliance-space/notified-bodies` devolvieron filas el 9 nov 2026. No hay lista de organismos.
- ARP4754B: no hay ficha con fecha. La ficha fechada es la de ARP4754A (21 dic 2010).
- Normas ISO y DO-178C, DO-330, DO-254, ED-80: solo ficha pública. El articulado de pago no se ha leído.
