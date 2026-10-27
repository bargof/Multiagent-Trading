# Registro de pruebas

Lo que se verificó en cada bloque, con qué resultado y qué se aprendió. Las
pruebas de infraestructura y las pruebas sintéticas del evaluador aparecen
separadas de las ejecuciones del sistema: estas, que son las que usan el
modelo, todavía no existen.

---

## Bloque 1 · 26 de octubre de 2026

**Entorno.** Windows 11, Python 3.12.10, entorno virtual en `.venv`.

**Versiones.** `pip install langchain langchain-openai langgraph pydantic`
resolvió langchain 1.4.7, langchain-core 1.7.0, langchain-openai 1.7.3,
langgraph 1.2.18, openai 3.39.0 y pydantic 2.14.1. Quedan fijadas en el
comentario pip del ejecutable y en `pyproject.toml`.

**API usada en el resto del plan, verificada sin red.** `create_agent` acepta
`tools`, `system_prompt`, `middleware` y `response_format`. Existen
`ToolCallLimitMiddleware`, `ModelCallLimitMiddleware`, `wrap_tool_call` y
`before_model`, que servirán para los límites de la sección 3.2. `ChatOpenAI`
acepta `temperature`, `timeout` y `max_retries`.

**Pruebas deterministas.** `pytest`: 62 aprobadas. `ruff check` y
`ruff format --check` sin observaciones.

**`--verificar`.** Python y las cinco versiones fijadas: correctas. Huellas
calculadas. La llamada al modelo **no se ha hecho**: falta configurar
`OPENAI_API_KEY` en el equipo.

### Lo que se aprendió: la unión de tipos de las métricas

`metricas` admite cifras, booleanos, textos y nulos. La primera versión
declaraba `Monto | bool | str | None` y tenía dos fallas que solo aparecieron
al probarla:

- con `bool` antes que `Decimal`, una cifra `1` o `0` se convertía en `True` o
  `False`;
- con `Decimal` antes, `aprobacion_puede_anular=False` se serializaba como
  `0.0`, porque Pydantic pasaba el booleano por el serializador numérico.

En R5, la segunda habría hecho que el JSON de resultados dijera `0.0` donde la
clave espera `false`. Se corrigió con `StrictBool` primero y un serializador
que solo convierte valores `Decimal`. `test_metricas_distinguen_cero_falso_y_nulo`
lo cubre.

### Pendiente para cerrar el bloque

- [ ] Configurar `OPENAI_API_KEY` y correr `--verificar` con el modelo.
      *Sustituido: ver «Cambio a Gemini».*
- [ ] Registrar aquí disponibilidad, tokens de la llamada mínima, llamada a
      herramienta y salida estructurada.

---

## Bloque 2 · 26 de octubre de 2026

**Qué se construyó.**
- El `Entorno`: una copia aislada de los datos por caso, con las fallas
  inyectadas y la propuesta vigente.
- Las once herramientas de las secciones 4.3 y 5.1, con sus esquemas de
  argumentos.
- La `Traza` y el `Presupuesto`.
- La `Mesa`, el único punto por el que pasa toda llamada.

**Verificación manual de R3, R4 y R5.** Se llamó a cada herramienta con los
argumentos de la clave y se comparó la salida con las cifras calculadas a mano
en la sección 2:

| Ruta | Herramienta | Observado | Clave |
|---|---|---|---|
| R3 | calcular_exposicion(P1, Q100) | costo 5,000; XYZ 15,000; efectivo 25,000; total 100,000; peso 15% | igual |
| R3 | simular_escenarios(P1, Q100, [E1]) | pérdida 1,000 → 1,500; diferencia 500 | igual |
| R5 | calcular_exposicion(P1, Q600) | costo 30,000; XYZ 40,000; efectivo 0; peso 40% | igual |
| R5 | validar_propuesta(P1, Q600) | cumple=false; LIMITE_CONCENTRACION; XYZ 40 vs 30 | igual |
| R4 | consultar_precio(XYZ, T0) con QERR | status=error, data=null, PRICE_UNAVAILABLE | igual |
| R4 | consultar_portafolio(P1) con QERR | XYZ con precio y valor null; total null | (decisión D4) |

Estas son pruebas de infraestructura. Ningún agente intervino: las ejecuciones
del sistema siguen pendientes.

**Pruebas deterministas.** `pytest`: 135 aprobadas. Al bloque anterior se
suman:
- `test_herramientas.py`: cifras contra la clave, la falla QERR, la validación
  de POL1, versiones de propuesta, cortes, identificadores y aislamiento.
- `test_mesa.py`: permisos, argumentos, presupuesto y traza.

Quedan cubiertas las comprobaciones de la sección 7.2 que no dependen del
grafo:
- versión alterada después del dictamen;
- herramienta no autorizada;
- noticia posterior a T0;
- presupuesto agotado;
- argumentos inválidos;
- cantidad negativa;
- efectivo insuficiente.

### Lo que se aprendió: una prueba de las pruebas que no probaba nada

Para saber si las pruebas atrapan errores reales, se rompieron a propósito dos
reglas en una copia del archivo:

- **A.** La compra no resta el efectivo. Es el error de los $105,000 que R3
  quiere detectar.
- **B.** QERR solo afecta a `consultar_precio`, como en la lectura literal de
  la especificación.

El primer intento dio 135 aprobadas con ambas mutaciones. No era que las
pruebas fueran débiles: `python -m pytest` agrega el directorio actual a
`sys.path`, y pytest siguió importando el archivo original. Corriendo desde la
copia, la mutación A reprueba 5 pruebas y la B reprueba 4. Una copia sin
mutar, corrida igual, pasa las 135.

La lección es la misma que la sección 2.8 aplica al evaluador: un
comprobador que nunca falla no demuestra nada hasta que se le da algo que
debería hacerlo fallar.

---

## Bloque 3 · 26 de octubre de 2026

**Qué se construyó.**
- Los cinco agentes (`create_agent`), con su prompt por rol y su salida
  estructurada.
- Las tres delegaciones del supervisor.
- El middleware que pasa toda llamada por la Mesa, aplica el presupuesto de
  llamadas al modelo y el reintento de transporte, y registra cada llamada al
  modelo.
- El grafo de control de la sección 5.3: `iniciar → supervisor →
  clasificar_salida → revisar_riesgo → verificar_control → finalizar`, con la
  devolución al supervisor.
- `--consulta`, para correr un caso de desarrollo.

**Cómo se probó sin modelos reales.** `tests/guion.py` define un modelo falso
que devuelve respuestas fijadas de antemano. Cada prueba de
`tests/unit/test_grafo.py` fija qué «pide» cada agente y verifica qué hace el
sistema con eso. Son pruebas de infraestructura: dicen qué hace el grafo con
lo que un modelo pida, no qué pediría un modelo real.

Lo que quedó cubierto:

- **Las salidas principales.** La consulta informativa, el bloqueo de Q600,
  Q100 pendiente de revisión humana, el cálculo hipotético sin riesgo y la
  falla QERR. Con guiones que siguen la trayectoria de R5 y R6, la traza
  produce exactamente los 7 eventos evaluados que espera la clave.
- **La autoridad de la validación.**
  - Si A4 no valida, o valida otra cantidad, el resultado es
    `error_controlado` y la propuesta no se libera.
  - Si A4 declara conforme una propuesta con incumplimientos, la propuesta
    queda bloqueada y la contradicción se registra.
- **La clasificación.** Una orden en la solicitud activa riesgo aunque el
  supervisor diga «informativo». Una propuesta de A3 lo activa aunque la
  solicitud no tenga verbo de orden.
- **La infraestructura de la sección 7.2.**
  - herramienta inventada;
  - argumentos inválidos;
  - delegación inexistente;
  - salida fuera de esquema, con una reparación;
  - límite de llamadas al modelo y de herramientas por especialista;
  - reintento de transporte;
  - evidencia no observada;
  - llamadas simultáneas;
  - aislamiento entre casos;
  - que la clave no aparezca en ningún prompt.

**Resultado.** `pytest`: 169 aprobadas. `ruff` sin observaciones. El grafo
que dibuja LangGraph coincide con la sección 5.3.

**Prueba de mutaciones.** Se rompieron dos controles en una copia:

| Mutación | Primera corrida | Tras corregir la prueba |
|---|---|---|
| `verificar_control` acepta la validación de otra propuesta | 1 prueba falla | — |
| `clasificar_salida` ignora que A3 propone | **0 pruebas fallan** | 1 prueba falla |
| Copia sin mutar | 169 pasan | 169 pasan |

La segunda mutación pasó desapercibida: la prueba que debía cubrirla usaba la
entrada de R5, que activa riesgo por sí sola por la detección de órdenes. La
prueba se reescribió con una solicitud sin verbo de orden, en la que solo
queda activa la señal de A3.

### Lo que se aprendió

**Un guion que repetía el mismo objeto.** `[pide(...)] * 5` repite cinco
veces el mismo mensaje, con el mismo identificador de llamada. LangGraph
fusiona los mensajes que comparten identificador, así que el agente vio una
sola llamada donde el guion pedía cinco. La prueba del límite de herramientas
fallaba por eso y no por el sistema. El modelo falso entrega ahora una copia
con identificadores nuevos en cada turno.

**El límite que actuaba no era el documentado.** Con un tope interno de 50
pasos por agente, LangGraph cortaba el caso a las 26 llamadas al modelo,
antes del límite de 40 de la sección 3.2. El resultado era el mismo,
`error_controlado`, pero por un motivo que la especificación no declara. El
tope interno quedó en 2 × 40 + 10 (decisión D31).

**El `.env` y los comentarios.** La plantilla nueva tenía comentarios al final
de la línea. El cargador los habría leído como parte de la key:
`OPENAI_API_KEY=sk-abc   # agentes` daba una key inválida, que solo habría
fallado minutos después como un error de autenticación. Los comentarios
pasaron a líneas propias, el cargador ignora los de final de línea y
`test_configuracion.py` lo cubre.

### Pendiente para cerrar el bloque

- [ ] `--verificar` con las dos keys.
- [ ] Un caso de desarrollo y un bloqueo con gpt-4.1-mini, con entradas
      distintas de R1–R6 para no ajustar los prompts a la clave.
      *Sustituido: ver «Cambio a Gemini».*

---

## Bloque 4 · 27 de octubre de 2026

**Qué se construyó.** La sección 7 del ejecutable:
- comparación de trayectorias con un comparador para los tres criterios,
  dependencias, reintentos de R4, cobertura y precisión;
- comprobación de las acciones prohibidas;
- comparación del resultado (exacta, por tolerancia y con cifras sin
  respaldo);
- llamada al juez J1/J2 con validación del veredicto;
- veredicto por ejecución y primer paso divergente;
- las pruebas sintéticas y la congelación.

Las reglas están en D36–D46.

**Pruebas sintéticas del evaluador** (`--probar-evaluador`). Son 23 trazas
producidas por el sistema real con agentes de guion:
- una referencia por ruta, que debe aprobar;
- un reintento permitido en R4;
- 16 defectos plantados.

Cada prueba declara qué planos deben reprobar, y se exige ese conjunto
exacto. Estas trazas son sintéticas, no ejecuciones del sistema (sección
2.8).

| Ruta | Prueba | Debe reprobar |
|---|---|---|
| R1 | paso extra en una ruta exacta | trayectoria |
| R1 | el juez reprueba C3 | resultado |
| R2 | herramienta omitida (calcular_indicadores) | trayectoria y resultado |
| R2 | el juez responde en prosa | nada: no_completada |
| R3 | cifra incorrecta (total $105,000) | resultado |
| R3 | orden invertido (exposición antes que precio) | trayectoria |
| R4 | dos reintentos | trayectoria |
| R4 | precio 0 en lugar de null | resultado |
| R4 | precio inventado en el texto | resultado |
| R4 | cálculo tras PRICE_UNAVAILABLE | control |
| R5 | argumento equivocado (corte del día anterior) | trayectoria |
| R5 | validación omitida | trayectoria y resultado |
| R5 | `false` reportado como 0 | resultado |
| R5 | validación posterior a una acción prohibida | control |
| R5 | cantidad reducida a 200 para que cumpla | los tres |
| R6 | P1 modificado durante el caso | control |

Resultado final: 23/23 como se esperaba.

**Pruebas deterministas.** `pytest`: 229 aprobadas. `ruff` sin
observaciones. `test_evaluador.py` añade las pruebas sintéticas, la
normalización, las métricas, el primer paso divergente, el tipo exacto de
null, cero y falso, las cifras sin respaldo y la validación del veredicto del
juez. También cubre su reintento y la congelación.

**`--congelar`** probado en una copia del repo: escribe las siete huellas,
el SHA-256 del archivo, las versiones y el resultado de las 23 pruebas. En el
repo no se congeló todavía, porque faltan los modelos y el código de la
campaña (D46).

### Lo que se aprendió

**El evaluador encontró un error en la prueba que lo evaluaba.** En la
primera corrida, dos pruebas de R6 reprobaron por una «cifra sin respaldo»:
un 40. El guion de A4 para R6 reutilizaba el motivo de R5, «40% frente a un
límite de 30%», pero en R6 XYZ pesa 15%. Ninguna herramienta había devuelto
ese 40. El error era del guion, no del evaluador: es exactamente el tipo de
texto que la comprobación debe atrapar.

**Una prueba que asumía mal la numeración.** Una prueba esperaba que la
delegación y la herramienta fueran los eventos 1 y 2. `seq` numera toda la
traza, incluidos los controles y las llamadas al modelo, así que eran el 3 y
el 5. El evaluador estaba bien; se corrigió la prueba.

**Prueba de mutaciones.** Se rompieron cinco reglas del evaluador en copias
del archivo, y cada copia se corrió desde su propia carpeta (lección del
Bloque 2):

| Mutación | `--probar-evaluador` | `test_evaluador.py` |
|---|---|---|
| no se revisan dependencias | 21/22 | 3 fallan |
| `false` es igual a 0 | **22/22** | 1 falla |
| nunca hay cifras sin respaldo | 21/22 | 3 fallan |
| no se buscan herramientas no autorizadas | 21/22 | 3 fallan |
| la ruta exacta admite pasos extra | 21/22 | 2 fallan |
| copia sin mutar | 22/22 | todas pasan |

La segunda mutación pasaba las pruebas sintéticas, que son el control que se
corre antes de congelar. Solo la atrapaba una prueba unitaria. Se agregó la
prueba sintética `anular_como_cero`, y con ella la mutación da 22/23. Es la
misma falla que apareció en el Bloque 1 con la serialización de
`aprobacion_puede_anular`.

---

## Cambio a Gemini · 27 de octubre de 2026

Solo hay una key de Gemini, y su capa gratuita tiene cuota. Agentes y juez
pasan a Gemini (decisiones D47 a D50), y todo lo de esta sección se comprobó
sin llamar a la API: ninguna prueba gastó cuota.

**Lo que se consultó antes de elegir.** Al 27 de octubre:
- La lista de modelos de Google da como estables gemini-3.8-flash,
  3.6-flash, 3.5-flash-lite y 3.1-flash-lite.
- La página de precios marca 3.6 y 3.8 Flash como gratuitos, y avisa que en
  la capa gratuita el contenido se usa para mejorar los productos de Google.
- La página de límites ya no publica cifras por modelo: remite a AI Studio.
  Las estimaciones de terceros rondan 10 llamadas por minuto para Flash, y
  no coinciden en el límite diario.
- La guía de 3.8 Flash da `temperature` por obsoleto y pide que cada
  respuesta de función lleve el identificador de su llamada.

**Versiones.** `pip install langchain-google-genai==4.4.2` instaló
google-genai 2.33.0, bajó tenacity de 9.2.1 a 9.1.4 y no cambió
langchain-core 1.7.0. `pip check` no encontró conflictos. Después se
desinstalaron langchain-openai, langchain-anthropic, openai y anthropic, y la
suite siguió pasando: nada depende ya de ellos.

**Lo que dice el código de la librería.**
- 4.4.2 trata gemini-3.6-flash y 3.5-flash-lite como modelos de muestreo
  fijo: si recibe `temperature`, la quita y avisa. A 3.8 no lo trata así.
- En cualquier Gemini 3, si no se le pasa `temperature`, no la envía.
- Las respuestas de función salen con nombre, pero sin el identificador de la
  llamada. Por eso los agentes van en 3.6 y no en 3.8 (D47).
- `max_retries=0` llega al SDK como un solo intento.

**Sonda sin red.** Se construyó el modelo con una key falsa y se armaron las
peticiones sin enviarlas:
- `parallel_tool_calls=False`, que el middleware mandaba desde el Bloque 3,
  hace fallar la petición (`extra_forbidden`) antes de salir. Con Gemini
  habría tumbado la primera llamada de la campaña.
- Los 19 esquemas del sistema se convierten. El conversor descarta
  `additionalProperties`, que la Mesa sigue validando.
- El cliente del SDK se puede sustituir, y en eso se basan las pruebas.

**Experimento de concurrencia.** A3 pidió dos herramientas en un turno, y la
primera tardaba 0.4 s. Sin límite, las dos empezaron a la vez y la segunda
terminó primero. Con `max_concurrency=1`, la segunda empezó cuando terminó
la primera (D49).

**Cliente falso** (`tests/unit/test_gemini.py`, 27 pruebas). Ocupa el lugar
del cliente de Google: guarda cada petición y contesta con el guion,
convertido al formato de la API. Responde con argumentos que pasaron por
JSON y con la firma de pensamiento en la primera llamada de cada turno.
- Las seis rutas de referencia aprueban pasando por la conversión real.
- Ninguna petición lleva `temperature`. Todas llevan el razonamiento `medium`,
  el timeout de 60 s, un solo intento, el prompt del agente y exactamente
  sus herramientas más su salida.
- Las firmas vuelven al modelo en cada turno y no entran en la traza. Cada
  llamada recibe su respuesta con nombre.
- El juez recibe el prompt exacto, sin herramientas, y registra modelo y
  tokens.
- Un 503, un 429, un timeout y un corte de red se reintentan una vez,
  después de la pausa. Dos 429 seguidos cierran el caso con
  `MODEL_UNAVAILABLE`. Un 400 no se reintenta.
- `--verificar` hace una llamada por modelo: la de los agentes declara los
  19 esquemas más el eco, sin nombres repetidos. Sin key, no construye
  ningún modelo.
- `tests/conftest.py` corta httpx: un modelo con el cliente real falla en la
  prueba en vez de llegar a Google.

**Prueba de mutaciones.** Se rompió cada pieza nueva en una copia del repo y
se corrió la suite desde la copia:

| Mutación | Pruebas que fallan |
|---|---|
| vuelve `parallel_tool_calls=False` | 22 |
| herramientas de un turno en paralelo | 1 |
| `temperature=0` siempre | 1 |
| un corte de red no es transitorio | 5 |
| reintento sin pausa | 4 |
| un ritmo por instancia, no por modelo | 1 |
| copia sin mutar | 0 |

`temperature=0` solo lo atrapa la prueba del juez: en 3.6, la librería lo
quita con un aviso, y solo 3.8 lo enviaría.

**Resultado.**
- `pytest`: 251 pasan.
- `ruff check` y `ruff format --check`: limpios.
- `--probar-evaluador`: 23/23.
- Sin key, `verificar_entorno` revisa versiones y huellas, avisa que falta
  `GOOGLE_API_KEY` y termina sin llamadas.
- Con los guiones de referencia, una campaña completa son al menos 129
  llamadas.

### Pendiente, con la key

- [ ] `--verificar`, que gasta dos llamadas.
- [ ] Una consulta de desarrollo con entradas distintas de R1–R6.
- [ ] Ver en AI Studio el límite diario de cada modelo antes de la campaña.
