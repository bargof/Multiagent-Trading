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

*Sustituido: ver «Bloque 5».*

- [ ] `--verificar`, que gasta dos llamadas.
- [ ] Una consulta de desarrollo con entradas distintas de R1–R6.
- [ ] Ver en AI Studio el límite diario de cada modelo antes de la campaña.

---

## Bloque 5 · 27 de octubre de 2026

El ejecutor de la campaña (decisiones D51 a D54). Todo lo de esta sección se
probó con agentes de guion y con el cliente falso de Gemini: ninguna prueba
gastó cuota. La campaña oficial todavía no se ha corrido.

**Lo que se encontró al revisar el código antes de escribir el ejecutor.**
- El límite de 300 s por caso medía tiempo de reloj, y eso incluía el turno
  de cuota y la pausa antes del reintento. A 8 llamadas por minuto, las 40
  que permite un caso ya ocupan 300 s. Con un ritmo menor, el caso se habría
  cerrado por tiempo antes de su tope de llamadas, y el ritmo habría cambiado
  el experimento (D53).
- Si `cache` no se fija, LangChain usa la caché global cuando alguien la
  configura. Ahora los modelos se crean con `cache=False` (D51).
- langchain-google-genai entrega un 429 como `GoogleRateLimitError`, una
  subclase de `ModelRateLimitError`. La cuota se reconoce por el tipo del
  error, sin leer su texto.
- Una excepción que escapaba de `ejecutar_caso` se llevaba la traza del
  caso. Ahora la traza viaja con la excepción y la campaña la guarda.
- `main()` carga el `.env` del repo, que ya tiene la key. `tests/conftest.py`
  ahora lo desactiva en todas las pruebas, y manda las campañas y la
  congelación a una carpeta temporal.

**Pruebas** (`tests/unit/test_campana.py`, 26). Los agentes siguen los
guiones de referencia, y cada prueba cambia el de alguna ejecución para
plantar lo que quiere ver.
- *Campaña completa.* El plan va por rondas, con R6 al final. Las 18
  ejecuciones aprueban, se escriben los cinco archivos y `resultados.json` es
  exactamente lo que se recalcula de los registros. Se confirma el piso de
  D50: 123 llamadas a los agentes y 6 al juez.
- *Estado limpio.* Cada ejecución tiene su `run_id`, y su traza empieza en el
  evento 1 con `iniciar`. El registro dice `cache: false`. Una key puesta en
  el entorno no aparece en ningún archivo.
- *Cuota de los agentes.* Dos 429 en R3.1 la marcan interrumpida y detienen la
  campaña. Al volver a correr sigue la misma carpeta, repite R3.1 primero y no
  vuelve a correr R1.1 ni R2.1. La interrumpida queda en el registro y su
  gasto se suma al uso.
- *Acción prohibida antes del corte.* R5.1 intenta `ejecutar_orden` y luego
  se queda sin cuota: cuenta como fallida y no se repite.
- *Cuota del juez.* El juicio de R1.1 queda sin completar, la campaña se
  detiene y R1.1 no se repite.
- *Excepción.* Un `ValueError` en A1 deja R2.1 como error, con su traceback y
  su traza parcial. Cuenta como no aprobada, la campaña se detiene y al seguir
  no se repite.
- *Ctrl+C.* R2.1 queda interrumpida y su lugar se repite.
- *Cuándo se sigue.* `--ejecuciones` limita lo que se corre y la siguiente vez
  sigue. Un archivo distinto, otro modelo o `--nueva-campana` empiezan otra
  campaña, y la anterior queda intacta. Si las pruebas sintéticas fallan, no
  se corre nada.
- *Resultados.* Con defectos plantados en R4.2, R5.2 y R5.3, la peor ejecución
  de R5 es la de la acción prohibida y no la del argumento equivocado. R5
  bloqueó 3 de 3 aunque solo aprobó 1, y la tabla muestra las dos cosas.
  `revision.md` tiene un lugar por ejecución, los criterios del juez en R1 y
  R2, el control en R5, y causa y efecto para cada falla.
- *Congelación.* Sin archivo, la comparación dice «sin congelación»; con el
  registro de `--congelar`, «coincide». Si se altera una huella y el SHA del
  archivo, nombra los dos componentes.
- *Por el cliente de Gemini.*
  - Un 429 de Google, a los agentes o al juez, se reconoce como cuota.
  - Un 503 no se reconoce como cuota: esa ejecución cuenta como fallida.
  - La traza guarda la versión del modelo y el motivo de fin de cada turno.
  - La key falsa del cliente no aparece en ningún archivo.
- *Espera al proveedor.* Con un reloj falso, 250 s de reloj con 200 de espera
  no cierran el caso, y 300 s más de trabajo sí. La pausa del reintento y el
  turno del ritmo se anotan como espera.
- *Línea de comandos.* Sin key no se corre nada. `--tabla` lee una campaña
  sin escribir nada.

**Una campaña de demostración**, con guiones y defectos plantados. La
primera corrida se detuvo en R3.2 por un 429, con 7 ejecuciones hechas. La
segunda siguió la misma carpeta, corrió las 11 pendientes sin repetir
ninguna y terminó con 12 de 15 obligatorias aprobadas. Sirvió para corregir
la presentación de la tabla:
- un juicio sin completar mostraba un «primer paso divergente» vacío;
- la línea de avance de una interrumpida mostraba la trayectoria de su
  evaluación parcial;
- la hora de inicio salía en UTC;
- `revision.md` pedía causa y efecto también para un juicio sin
  completar, que no es una falla del sistema.

**Línea de comandos en una carpeta con solo el `.py`**, sin `.env` y con las
variables de key vacías:
- sin opciones, corre las pruebas sintéticas (23/23), avisa que falta la key
  y termina con código 1 sin crear `reports/`;
- `--tabla` avisa que no hay campañas;
- `--ejecuciones 0` es un error de argumentos.

**Prueba de mutaciones.** Se rompió cada regla nueva en una copia del repo y
se corrieron desde la copia las pruebas de campaña y de Gemini:

| Mutación | Pruebas que fallan |
|---|---|
| una interrumpida cuenta como hecha y no se repite | 2 |
| la cuota marca interrumpida aunque haya acción prohibida | 1 |
| se sigue una campaña aunque cambie el archivo | 1 |
| la peor ejecución es la mejor | 2 |
| la campaña no se detiene tras una excepción | 1 |
| la espera al proveedor cuenta como trabajo | 1 |
| los modelos usan la caché | 1 |
| el juez sin cuota no queda marcado | 2 |
| el uso no suma las interrumpidas | 1 |
| copia sin mutar | 0 |

La primera versión de la mutación «no se detiene tras una excepción» no rompía
nada: el registro de un error lleva motivo, y la campaña se detenía por esa
otra vía. Se reescribió para que el error no detenga la campaña, y la prueba
la atrapó.

**Un error de las pruebas, atrapado por la copia sin mutar.** En la primera
vuelta de mutaciones, la copia sin mutar tenía una prueba que fallaba. El
registro guardaba los últimos 4000 caracteres del traceback, y con las rutas
más largas de la copia se perdía el marco que buscaba la prueba. Así, la
tabla no distinguía esa falla de la que plantaba una mutación. Se corrigió en
el código: ahora se guardan los 12 marcos más profundos, que no dependen del
largo de las rutas. La prueba busca el marco que lanzó la excepción.

**Resultado.**
- `pytest`: 277 pasan (26 de campaña).
- `ruff check` y `ruff format --check`: limpios.
- `--probar-evaluador`: 23/23.

**Primer `--verificar` con la key (27 de octubre).** Google respondió 503
«high demand»: el modelo estaba saturado y la petición no llegó a probarse.
Hasta entonces, un 503 que durara también el reintento contaba la ejecución
como fallida y la campaña seguía. Se cambió antes de correr ninguna ruta
(D55): ahora interrumpe la ejecución, igual que la cuota. Pruebas nuevas:
- un 503 de Google a los agentes interrumpe y detiene la campaña;
- un 429 o un 503 al juez deja el juicio sin completar y la detiene;
- `--verificar` distingue la cuota de una saturación y no reintenta.

**Segundo `--verificar` (27 de octubre).**
- gemini-3.6-flash, el de los agentes, aceptó los 19 esquemas y llamó la
  herramienta eco, con 2972 tokens de entrada y 73 de salida. La key, el
  modelo y los esquemas del sistema quedan comprobados con la API real.
- gemini-3.8-flash, el juez, devolvió 504 `DEADLINE_EXCEEDED`.

Con dos fallas seguidas del juez, se cambió a gemini-3.5-flash-lite antes de
congelar (D56).

**Tercer `--verificar`, con el juez nuevo (27 de octubre).** Los dos modelos
respondieron:
- gemini-3.6-flash aceptó los 19 esquemas y llamó la herramienta, con 2972
  tokens de entrada y 44 de salida;
- gemini-3.5-flash-lite contestó «ok», con 9 de entrada y 133 de salida. La
  mayoría de la salida es razonamiento, porque el nivel es `medium`.

**Primera campaña, con gemini-3.6-flash** (20261027-142643), que
coincidía con la congelación:
- R1.1 y R2.1 aprobaron, con 5 y 11 llamadas;
- cuatro 503 de saturación se resolvieron con su único reintento;
- R3.1 se interrumpió por el límite diario de 20, y la campaña se detuvo.

AI Studio mostró 500 llamadas diarias para los dos Flash Lite. Agentes y juez
pasan a ellos, a 12 por minuto (D57). `--congelar` ahora conserva la
congelación anterior (prueba nueva).

`pytest`: 280 pasan.

### Pendiente, con la key

- [x] `--verificar` con el juez nuevo, que gasta dos llamadas.
- [ ] Ver en AI Studio el límite diario de cada modelo.
- [ ] `--congelar`, con el código final.
- [ ] La campaña: `python proyecto_multiagente.py`, las veces que haga falta.
- [ ] La revisión humana en `revision.md`.

---

## Bloque 6 · 27 de octubre de 2026

Entregables generados desde la campaña 20261027-145758, sin llamar a ningún
modelo (D58).

- *Diagrama.* Compila con xelatex y TikZ. Se revisó a la vista tres veces
  hasta que ninguna flecha ni etiqueta se encimara. Las herramientas, las
  delegaciones, las salidas, los límites y los modelos salen del código.
- *Informe.* 12 páginas. La primera compilación tenía 83 renglones fuera de
  margen, por las trayectorias y los nombres de campo sin espacios. Se
  permitió partirlos después de comas, puntos y guiones bajos, y queda uno.
- *ZIP.* 39 archivos, sin `.env`, sin el entorno virtual y sin la
  compilación.
- *El .py entregado* tiene el mismo SHA-256 que la campaña y que la
  congelación.
- *Desde una carpeta limpia,* con el ZIP descomprimido y sin key:
  - `--probar-evaluador` da 23/23;
  - `--tabla` imprime la campaña;
  - sin opciones, avisa que falta la key y termina sin llamadas.
- `ruff check` y `ruff format --check` quedan limpios. Las plantillas de LaTeX
  quedan fuera de la regla de largo de renglón.

### Pendiente

- [ ] La revisión humana en `revision.md`; después, `scripts/informe.py` y
  `scripts/empacar.py`.
