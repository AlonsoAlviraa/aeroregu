# Parte C — Barrido regulatorio

Fuente de verdad previa: vault `obsidian-regulacion` (zip del 8 nov 2026, 52 ficheros). Esta sección no lo edita. Las propuestas están en `audit/vault-propuestas/`. No es asesoramiento jurídico.

Fecha de las comprobaciones nuevas: 9 nov 2026. Una propuesta, una NPA o un concept paper no es ley.

## Lo que se abrió hoy en fuente oficial

| Instrumento | Qué se vio | Etiqueta |
|---|---|---|
| Reglamento (UE) 2026/1744 | EUR-Lex, CELEX 32026R1744. Firmado el 8 jul 2026. Publicación 24 jul 2026. Efecto 27 jul 2026. Modifica 2024/1689, 2018/1139 y 2023/1230 | VERIFICADO |
| Consolidado 2024/1689 a 27 jul 2026 | CELEX 02024R1689-20260727. M1 = 2026/1744 | VERIFICADO |
| Anexo I, sección B, punto 20 | Solo 2018/1139 en la parte de aeronaves no tripuladas y sus motores, hélices, piezas y equipo de control remoto | VERIFICADO |
| Plazos de alto riesgo en el consolidado | 2 dic 2027 (art. 6(2) y anexo III); 2 ago 2028 (art. 6(1) y anexo I) | VERIFICADO |
| Art. 4 sustituido | Obligación de medidas de alfabetización. No exige garantizar un nivel individual | VERIFICADO |
| Proyecto 121/000096 | Ficha del Congreso: resultado Caducado. Enmiendas hasta 06/10/2026. Concluido (Caducado) desde 06/10/2026 | VERIFICADO. HTML en `audit/fuentes/congreso-121-000096.html` |
| RD 806/2026 | BOE-A-2026-20742. Disolución de las Cortes. Elecciones 29 nov 2026. Constitución de las Cámaras 23 dic 2026 | VERIFICADO. https://www.boe.es/eli/es/rd/2026/10/05/806 |

EUR-Lex devolvió 403 y luego un HTTP 202 vacío al descargarlo con el cliente de esta máquina. El texto usado es el que el recuperador de páginas guardó el mismo día desde la URL oficial. No se ha guardado un PDF del DOUE en `audit/fuentes/` para el 2026/1744. Ese fichero falta.

## Añadido al cerrar pip-audit, mismo 9 nov 2026

Parte 21. EUR-Lex muestra el consolidado CELEX 02012R0748-20260807. El índice sigue llamando «Part 21» al anexo I y conserva el punto 21.A.239 (sistema de gestión del diseño) y 21.A.239A (seguridad de la información). El Reglamento delegado (UE) 2026/56 y el de ejecución (UE) 2026/100 modifican ese anexo y, en el texto leído, se aplican desde el 7 de agosto de 2026. VERIFICADO como existencia del consolidado y de esos dos modificadores. No se ha leído 21.A.239 entero ni se ha mapeado cada cambio de 2026 al producto.

NPA 2025-07. La ficha de EASA, vista en el resultado de búsqueda de hoy, sigue publicada: fecha 10 nov 2025, plazo de comentarios 10 feb 2026, ampliado al 10 mar 2026. Esos plazos ya han pasado. La descarga directa de la ficha se abortó. No se ha visto una decisión de adopción ni un CRD en esa lectura. Sigue siendo propuesta. PARCIAL.

NIS2 en España. El buscador de legislación del BOE rechazó la consulta automática. Dos textos del propio BOE, abiertos hoy, llaman a la transposición «anteproyecto en tramitación»: la Orden PJC/522/2025 (BOE-A-2025-10371, 23 may 2025) y un documento de Puertos del Estado publicado el 9 ene 2026 (BOE-A-2026-511). Eso no prueba que entre enero y el 9 nov 2026 no se haya publicado una ley. El estado de la transposición sigue NO VERIFICADO como ausencia. Lo que sí queda VERIFICADO es que, en esas dos publicaciones, el Gobierno aún hablaba de anteproyecto.

Siguen sin poder cerrarse, y no pasan a VERIFICADO: la lista de organismos notificados del AI Act en NANDO (la página por legislación se abrió y no devolvió filas), el texto de pago de ARP4754B (la ficha fechada que sí se abrió es la de ARP4754A, diciembre 2010; una página de curso nombra la B y no trae fecha), y el articulado de las normas ISO. De 42001 solo consta la ficha: publicada, edición 1, 2023-12, 51 páginas.

Reabiertos en esta pasada, solo metadatos: ARP4754A/B y ISO/IEC 42001:2023 más la mención de catálogo de 23894:2023.

Reabiertos en esta pasada: AMC 20-152A (noticia del 29 jul 2020, ED Decision 2020/010/R; ED-80 y DO-254 no se han leído) y ED-324 (la ficha de EUROCAE WG-114 lo marca Draft, objetivo 31 dic 2026).

Reabiertos en esta pasada: Concept Paper Issue 2 (6 mar 2024) y Proposed Issue 03 (consulta cerrada el 12 ago 2026, sin adopción leída), ED Decision 2025/018/R sobre SORA 2.5 (AMC; SORA 2.0 sigue en vigor según el artículo 2 del PDF), e informe MLEAP de 28 may 2024 (investigación, no regla).

Reabiertos en esta pasada: Ley 1/2019 artículo 1, Ley 24/2015 artículos 15 y 16, artículo 28 del RGPD en el consolidado con cabecera de 4 may 2016, y la ficha de EASA de AMC 20-115D (24 oct 2017).

Reabiertos en esta pasada: Reglamento de Ejecución (UE) 2023/203 (aplicación general el 22 feb 2026), artículo 21 del ET en la edición del BOE que declara última modificación el 21 oct 2026, artículo 97.4 de la LPI en la ficha BOE-A-1996-8930 (no contrastada con un consolidado de fecha posterior), y el estatuto de AESA, cuya ficha consolidada declara última actualización el 12 jun 2026.

Reabiertos en esta pasada: Part-IS 2022/1645 (ámbito DOA/POA y aeródromos, aplicación 16 oct 2025), doble uso 2025/2003 (anexo sustituido, efecto 15 nov 2025; la categoría 9 está en el índice y este producto no se ha clasificado), 2019/945 consolidado a 24 jun 2025.

Reabiertos en esta pasada y escritos en `audit/vault-propuestas/`: SC-VTOL Issue 2 (10 jun 2024; VTOL.2210 y VTOL.2215 existen; el MOC-5 Issue 2 se publicó como final el 5 nov 2026 y no se ha leído), CS-29 Enmienda 12 (ED Decision 2024/009/R), CRA artículo 2 (la exclusión del 2018/1139 es para productos ya certificados), Data Act artículo 50 (aplicación general el 12 sep 2025, con fechas parciales posteriores).

Reabiertos el 9 nov 2026 y escritos en `audit/vault-propuestas/`: CS-27 Enmienda 10 (PARCIAL, ficha y documento de cambios, no el PDF de la CS), 2019/947 consolidado a 1 may 2025 (el artículo 11 es la evaluación de riesgo operacional), Directiva 2024/2853 con corrección del 7 may 2026 (el ámbito del artículo 2.1 pasa a «después del 8 dic 2026»), Ley 53/2007 (consolidado BOE sin modificaciones publicadas, valor informativo).

Las notas de bufete sobre NIS2 no cuentan como fuente. La búsqueda negativa en el formulario del BOE no llegó a ejecutarse.

Las notas de bufete sobre NIS2 no cuentan como fuente. La búsqueda negativa en el formulario del BOE no llegó a ejecutarse.

FAA y Reino Unido: el vault los deja fuera de alcance. No se han descargado.

Normas de pago: no se ha copiado su texto.

## Por capas, y si el repo puede apoyar algo

### IA horizontal

El producto, tal como el README lo describe, propone texto y recalcula números. No es, por ese solo hecho, el sistema de alto riesgo del anexo III ni el componente de una aeronave no tripulada del punto 20. Si el caso de uso es C (IA embarcada) o D (UAS) y se pide crédito, el encaje puede cambiar. SUPUESTO de producto, no una clasificación.

Puede apoyar: un registro de qué modelo y qué prompt se usaron, una abstención, un hash del evento, y un humano que pulsa firmar.

No puede probar: alfabetización del art. 4, un sistema de gestión de la calidad, datos de entrenamiento gobernados, robustez, un organismo notificado, ni que el sistema sea o no de alto riesgo. El art. 4a (datos especiales para sesgo) no tiene implementación vista; el producto no declara ese tratamiento.

### Aviación (2018/1139, Parte 21, CS, SC-VTOL, AMC)

La rejilla de 405 celdas y los dos métodos (`rigid_body_point_mass`, `bolt_screen`) son ilustraciones con masas inventadas. Pueden apoyar una traza de una cuenta hecha con una tarjeta nombrada. No pueden probar learning assurance, ODD, una línea base de requisitos de CS-27 o CS-29, cualificación DO-330, ni el juicio que pide VTOL.2210. Ese párrafo, leído hoy en el PDF de la Issue 2, obliga al solicitante a determinar las cargas de diseño en las combinaciones críticas, con magnitud y distribución basadas en principios físicos. La rejilla no hace eso. El consolidado de la Parte 21 existe a 7 ago 2026 y conserva 21.A.239. El código no cita ese punto.

NPA 2025-07 y el Concept Paper propuesto Issue 03 son propuesta. No se usan como obligación.

### UAS

Solo entra si el caso es D. El repo no arma un dossier SORA. Punto 20, arriba, es el único gancho de anexo I leído hoy, y es solo no tripulado.

### Ciberseguridad y datos

Part-IS, en el vault, obliga a la organización aprobada, y al proveedor solo si el contrato lo arrastra. El repo no tiene gestión de incidentes ni un registro de accesos digno de eso. La demo guarda un SQLite local y lo exporta sin autenticación.

CRA: el vault dice que el art. 2(3) excluye productos certificados bajo 2018/1139 y que esta herramienta no lo está. No reabierto hoy. Un servicio sin producto conectado puede quedar fuera; un software instalable con conexión de datos puede quedar dentro. Abogado. El repo no tiene SBOM generado en esta sesión (`tools/sbom.py` existe; no se ha ejecutado) ni aviso de vulnerabilidad.

RGPD y LOPDGDD: no se ha visto un contrato de encargado. Los informes de ingeniería pueden traer nombres de autores. No hay minimización implementada como política ejecutable.

Data Act, capítulo de cambio de proveedor: NO VERIFICADO el detalle, igual que el vault.

NIS2: directiva, no reglamento. Sin transposición comprobada en el BOE hoy.

### Responsabilidad por productos (Directiva (UE) 2024/2853)

Sigue siendo directiva, transposición pendiente según el vault (límite 9 dic 2026). No reabierto hoy. El software puede ser producto cuando el Estado la trasponga. El ledger ayuda a saber qué versión corrió. No es un seguro ni un aviso a clientes. La propuesta de directiva de responsabilidad por IA figura en el vault como retirada (DO C/2025/5423). No reabierta hoy. No citarla como vigente.

### Exportación

2021/821 y la Ley 53/2007 están PARCIAL en el vault. Un informe técnico de cargas puede ser dato técnico. El repo no clasifica exportaciones. Abogado antes de sacar el disco de la UE. No es una prohibición general escrita en el código.

### PI, laboral, secretos

`gate.md` no sustituye al art. 21 del ET ni al art. 97.4 de la LPI. Dos fundadores y un empleador en el nombre de la carpeta hermana: prioridad de abogado. No se copia aquí ningún método de esa carpeta.

### España

AESIA existe por el RD 729/2023 según el vault (no reabierto hoy). El proyecto de ley que designaría vigilantes del AI Act está caducado. Hasta que haya otro texto, no hay régimen sancionador español nuevo que este repo pueda «cumplir».

### Lo que el software no prueba, en una lista

Learning assurance, ODD, línea base de requisitos oficiales, extracción trazable sobre un informe que no sea el oro de la misma sesión, procedencia de un PDF de cliente, configuración de un DOA, V&V independiente, investigación de incidentes, registros de Part-IS, supervisión humana con competencia acreditada.

## Descarga de «todas» las regulaciones

No se ha volcado el DOUE entero ni los regímenes de otros países. El encargo del prompt limita FAA y Reino Unido a marcadores, y las normas de pago a metadatos. Descargar el resto del derecho europeo no cabe en una auditoría honesta y produciría texto que nadie ha leído. Lo leído hoy está en la tabla de arriba y en `audit/vault-propuestas/`.
