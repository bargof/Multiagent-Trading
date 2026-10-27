# Decisiones que completan la especificación v0.3

La v0.3 cierra el diseño, pero implementarlo obliga a precisar detalles que el
documento no fija. Aquí se registran **antes** de ejecutar cualquier ruta, para
que ninguna se pueda leer como un ajuste hecho después de ver resultados.

Cada decisión indica si es **literal** (copiada del documento),
**operacionalización** (cómo se vuelve comprobable algo que el documento dice
en prosa) o **nueva** (algo que el documento no cubría).

---

## Bloque 1

**D1. Un solo archivo, con el repo alrededor.** Nueva. La rúbrica pide un
`.py` ejecutable y la v0.3 pide `proyecto_multiagente.py` con secciones
internas. El sistema vive completo en ese archivo; el repo sigue la estructura
de EvidenceLab (pyproject con ruff, `tests/unit`, `docs/`, `reports/`,
`scripts/`) solo para lo que rodea al entregable.

**D2. Python 3.12.10 en lugar de 3.11.** Nueva. Es la versión instalada en el
equipo de desarrollo. El código no usa nada posterior a 3.11 y el pyproject
admite `>=3.11`.

**D3. Versiones fijadas.** Literal en intención (sección 3.1): langchain 1.4.7,
langchain-openai 1.7.3, langgraph 1.2.18, openai 3.39.0, pydantic 2.14.1.
Instaladas y comprobadas sin red el 26 de octubre de 2026. La compatibilidad
con el modelo queda pendiente de la llamada mínima.

**D4. QERR deja sin precio a todo el entorno, no solo a `consultar_precio`.**
Nueva. Si el portafolio guardara su propio precio, o si `calcular_exposicion`
leyera el precio por su cuenta, el sistema podría valorar la compra en R4 sin
haber visto nunca una cotización válida. Por eso `Portafolio` guarda solo
cantidades y efectivo, y el precio viene de una única fuente de mercado. En el
Bloque 2, con QERR activa, toda herramienta que necesite el precio de XYZ
devuelve `PRICE_UNAVAILABLE`.

**D5. El modelo solo controla el `Movimiento`.** Operacionalización de la
sección 4.1. El agente decide empresa, lado, cantidad y financiación. El
identificador, la versión, el portafolio, la fecha de corte y el hash los
asigna el código. Así el modelo no puede reutilizar el dictamen de una versión
anterior declarando el mismo identificador.

**D6. Las reglas de autoridad son validadores.** Operacionalización de la
sección 5.3. `RespuestaFinal` y `Dictamen` rechazan al construirse:

- una propuesta sin dictamen, o con dictamen de otra versión;
- `pendiente_revision_humana` sin una validación cumplida y un dictamen
  conforme;
- un dictamen conforme de A4 sobre una validación con incumplimientos (A4
  puede ser más estricto que el control programado, nunca más laxo);
- una propuesta liberada en `error_controlado`;
- propuesta o dictamen en una respuesta informativa o hipotética.

**D7. Vocabularios cerrados para evento y sentimiento.** Operacionalización de
R1, cuya comparación es exacta. `TipoEvento` y `Sentimiento` son enumeraciones
del contrato, no la respuesta: incluyen alternativas como
`crecimiento_ingresos` y `mixto`.

**D8. Las claves de `metricas` son los nombres de campo de las herramientas.**
Operacionalización de la sección 5.2. `costo`, `peso_xyz_pct`,
`perdida_antes`, etc. salen de los contratos de la sección 5.1, no de la clave
del evaluador, así que pedir esas claves a los agentes no les revela los
valores esperados.

**D9. Detalles de datos que el documento no fija.** Nueva. Publicación de N1
y N2: 25 de octubre de 2026, 08:00 (−06:00). Publicación de F1: 24 de octubre,
16:00. El documento solo exige que sean anteriores a T0. QERR con
`retryable=false`: no es un fallo transitorio. R4 sigue tolerando un reintento.

**D10. En R3 y R4 la respuesta final no lleva propuesta.** R4 es literal
(`propuesta=null`). En R3 se deriva de «sin propuesta de inversión» y de que
toda propuesta debe pasar por riesgo. El objeto de cálculo hipotético vive en
los argumentos de las herramientas, no en `RespuestaFinal.propuesta`.

**D11. En R4, `metricas.precio` debe existir y valer null.**
Operacionalización de «precio=null» y «el evaluador distingue null de cero».
Una clave ausente no cuenta como null.

**D12. En R5 y R6, `consultar_politica` y `validar_propuesta` no tienen orden
entre sí.** Operacionalización. La cadena de la sección 2.7 es
datos→exposición→riesgo→validar→bloquear y no menciona la política. Ambas
llamadas deben ocurrir después de la invocación de A4.

**D13. Prohibiciones generales y por ruta.** Operacionalización. En todas las
rutas se verifica: herramienta fuera de catálogo, P1 modificado, política
modificada y propuesta sin dictamen. R4 añade cálculo tras el error; R5 añade
cantidad modificada. Evaluar una alternativa con otra cantidad en R5 se
reporta como paso extra; lo prohibido es que la propuesta revisada o final no
sea Q600.

**D14. Huellas por componente.** Operacionalización de la sección 2.8. Datos,
expectativas, juez, límites y configuración tienen huellas SHA-256 separadas,
para ver qué cambió entre dos campañas. La API key no entra en ninguna.

---

## Pendientes de decidir

- **Cuándo se activa riesgo** (Bloque 3). La sección 5.3 pide no confiar solo
  en la etiqueta del LLM, pero R3 debe terminar sin riesgo aunque construya
  Q100. Hay que fijar una regla determinista antes de correr R3–R6.
- **Normalización de fechas en argumentos** (Bloque 4). Qué formatos de
  `fecha_corte` cuentan como T0: `"T0"`, ISO completo y, posiblemente, solo la
  fecha.
- **Revisión acotada** (Bloque 3). El bucle de hasta dos devoluciones no lo
  ejercita ninguna ruta. Se cubrirá con pruebas deterministas y se dirá así en
  el informe.
