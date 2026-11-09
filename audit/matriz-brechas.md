# Matriz de brechas

Orden: CRÍTICA, ALTA, MEDIA, BAJA. El CSV hermano tiene las mismas filas. Fecha de la evidencia de código: 9 nov 2026.

| id | área | hallazgo | gravedad | puerta |
|---|---|---|---|---|
| B-01 | repo | Carpeta hermana con nombres de empleador, no abierta | CRÍTICA | No copiar nada de `AIRBUS` salvo el encargo regulatorio. Abogado antes de seguir |
| B-02 | repo | Cero commits. No hay checkout limpio ni freeze | CRÍTICA | No citar un hash. No tratar `bench/holdout` como congelado |
| B-03 | repo | El detector puntúa fallos que siembra el mismo paquete. La semilla no entra en el generador | ALTA | No usar S1 como rendimiento externo |
| B-04 | repo | Demo en 0.0.0.0, secreto y contraseñas fijos, export del ledger sin cookie | ALTA | No exponer el puerto. Atar el export a la sesión |
| B-05 | regulatorio | 405 celdas no son VTOL.2210 ni VTOL.2215 | ALTA | No llamar cobertura de certificación a la rejilla |
| B-06 | docs | «VERIFICADO from make bench» y «ESTIMATE» en el mismo bloque. S1 se repitió y sigue siendo el mismo generador | ALTA | Separar repetible de independiente |
| B-07 | regulatorio | Vault: estado del proyecto de ley de IA atrasado. Hoy está caducado | ALTA | Copiar la propuesta de `audit/vault-propuestas/` cuando Alonso lo decida. No editar el vault desde aquí |
| B-08 | repo | La firma comprueba una frase, no la competencia | ALTA | No decir que la firma es verificación independiente |
| B-09 | repo | Los cuatro agentes comparten un gateway | MEDIA | No decir que hay revisión de modelos distintos |
| B-10 | repo | pip-audit sin avisos en PyPI; paquetes locales fuera; certifi es MPL-2.0; gitleaks ausente | MEDIA | No llamar limpio al código propio |
| B-11 | repo | Git sin user.name ni user.email | MEDIA | Configurarlos el día que haya un commit pedido |
| B-12 | regulatorio | Parte 21 consolidada a 7 ago 2026. NPA 2025-07 con plazo vencido y sin decisión leída. NIS2 sigue sin búsqueda negativa en el BOE | MEDIA | No citar la NPA como regla ni afirmar que no hay ley NIS2 |
| B-13 | repo | El hash no prueba el dato de origen ni impide sustituir el fichero entero | MEDIA | Decirlo al lado de cualquier demo del ledger |
| B-14 | repo | Un aviso de Starlette en la suite | BAJA | No bloquea |
| B-15 | repo | El guardián solo busca el texto `ledger.append`. `app.py` escribe con `record(` | MEDIA | No fiarse de ese test como cierre de la regla |
| B-16 | repo | El intervalo de falsos positivos de S1 se imprime 0.000–0.000 y la fecha del informe se queda en 2026-11-03 | ALTA | No citar ese JSON como prueba de cero falsos positivos |
| B-17 | repo | La altitud se valida y no entra en la fuerza. 135 resultados distintos dentro de 405 ids | ALTA | No llamar cobertura a la rejilla |
| B-18 | repo | El espesor del tornillo es obligatorio y la fórmula no lo usa | ALTA | No presentar bolt_screen como cribado de espesor |
| B-19 | repo | Pint no corre si el llamante no manda `_input_units` | ALTA | No decir que cada magnitud lleva la unidad verificada |
| B-20 | repo | Un entero en texto no cuenta como violación numérica del modelo | ALTA | No decir que ningún número del modelo se cuela |
| B-21 | repo | `POST /calc/run` con `record` escribe el libro como humano, sin cookie | ALTA | No exponer el puerto |
| B-22 | repo | La sal de la contraseña sale del tenant y del actor, y no se rota | MEDIA | No tratar el login como autenticación |
| B-23 | docs | `docs/demo/metrics.md` dice 68 tests en 7,26 s. La pytest de hoy marcó 160 ítems en 203,6 s | MEDIA | No citar esa página como ficha de la suite |

El detalle de evidencia, acción, responsable y etiqueta está en `matriz-brechas.csv`.
