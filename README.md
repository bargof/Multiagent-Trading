# Comité de inversión multiagente

Sistema multiagente que reúne evidencia de noticias y resultados financieros,
analiza movimientos sobre un portafolio y los somete a revisión de riesgo. Se
entrega junto con su evaluación: rutas definidas **antes** de ejecutar el
sistema, que comparan por separado la trayectoria (qué agentes y herramientas
se usaron, con qué argumentos y en qué orden) y el resultado final.

Proyecto final del Módulo 4 · Diplomado en AI & LLMs para Mercados Financieros
· ITAM. La especificación es el documento de trabajo v0.3.

---

## Estado

| Bloque | Contenido | Estado |
|---|---|---|
| 1 | Configuración, contratos, datos simulados, clave del evaluador | Hecho, falta la llamada al modelo |
| 2 | Herramientas deterministas y traza | Hecho |
| 3 | Cinco agentes y grafo de control | Hecho con modelos de guion; falta la prueba con modelos reales |
| 4 | Evaluador, juez y congelación | Hecho y probado con trazas sintéticas; la congelación espera los modelos |
| 5 | Campaña: R1–R5 ×3, R6 ×3 aparte | Hecho: campaña 20261027-145758, 9 de 15 obligatorias y 2 de 3 en R6 |
| 6 | PDF de resultados, diagrama y ZIP | Hecho: entregables en `dist/`; falta la revisión humana |
| 7 | Aplicación sobre el Reto Actinver: datos reales, base de datos, vigía, recomendaciones, ejecución asistida y app | Hecho: ver [la aplicación](#la-aplicación-sobre-el-reto-actinver) |
| 8 | Estrategia validada con el historial del reto, A2 con reporte completo, A3 con escenarios históricos, calendario y monitor | Hecho; falta probar con Gemini que A2 lea la nota y A3 simule los escenarios nuevos |

La campaña oficial es `reports/campanas/20261027-145758`, con
gemini-3.5-flash-lite para los agentes y gemini-3.1-flash-lite para el juez.
Las 23 trazas de `--probar-evaluador` son pruebas del evaluador, no
ejecuciones del sistema. La integración con Gemini y el ejecutor de la
campaña están probados con un cliente falso, sin red ni cuota.

---

## La aplicación sobre el Reto Actinver

El mismo comité, sin cambiar una línea de `proyecto_multiagente.py`, trabaja
sobre mi cuenta del Reto Actinver con datos reales. La huella del archivo
sigue siendo la de la congelación, así que la evaluación de arriba sigue
valiendo para el sistema que usa la app.

```powershell
.venv\Scripts\python -m pip install streamlit==1.66.1 yfinance==1.7.0 feedparser==6.0.14 pandas==3.1.0 openpyxl==3.1.5
.venv\Scripts\streamlit run streamlit_app.py
```

La primera vez importa el universo del reto (214 emisoras con datos), su
historial desde 2024, los benchmarks Conservador, Moderado y Agresivo y el
tipo de cambio. Después se captura la cartera en la página **Cartera**.

```
fuentes gratuitas          vigía (reglas)          comité (A0–A4)         tú
yfinance: precios, FX ─┐   concentración >30% ─┐   noticias, reporte, ─┐  apruebas
Google News: titulares ├─▶ estrés E1, caídas,  ├─▶ cálculo, propuesta  ├─▶ capturas en el reto
yfinance: trimestres, ─┘   noticias, reportes, ┘   y revisión de riesgo┘  registras el folio
  balance, flujo,          calendario, destacadas,
  calendario               rebalanceo de la estrategia
```

| Página | Qué hace |
|---|---|
| Qué hacer | Indicadores contra los benchmarks, el botón **Recorrer todo el proceso** y las compras o ventas por aprobar, con su boleta para el simulador |
| Cartera | Posiciones en pesos, estrés de la cartera, rendimiento en base 100 contra los benchmarks, captura de la cuenta y libro de operaciones |
| Estrategia | Eliges la estrategia; ves su cartera objetivo, las órdenes del ciclo y el backtest de entrenamiento y prueba |
| Situaciones | Lo que detectó el vigía; cada una se puede mandar al comité |
| Comité | Chat con preguntas como las rutas R1–R6; una propuesta conforme se guarda como recomendación |
| Bitácora | Cada caso con su solicitud, los datos que vio el comité, la respuesta y la trayectoria |

**Base de datos** (`data/comite.db`, SQLite). Tres tablas principales:
`operaciones` (la cartera como libro; las posiciones salen de la vista
`posiciones`), `situaciones` (lo que pasa a lo largo del tiempo, en la
cartera y fuera de ella) y `recomendaciones` (qué hacer, de dónde salió y en
qué estado va: propuesta → aprobada → ejecutada). Las apoyan `emisoras`,
`precios`, `benchmarks`, `documentos` y `ejecuciones_comite`.

**Quién decide qué.** Las compras las propone el comité y pasan por A4 y la
validación determinista, igual que en la evaluación. Las ventas salen de
reglas fijas, porque el comité solo sabe proponer compras:
- concentración arriba de 30%;
- noticia negativa con caída de 5% o más;
- el rebalanceo de la estrategia.

Cada recomendación dice si viene del comité o de una regla.

**La estrategia** (D71 y D72). Probé cinco reglas de momentum con el
historial del reto, con candidatos y criterio fijados antes de correr. El
criterio de entrenamiento eligió las 15 emisoras con mayor rendimiento de 120
sesiones que estén arriba de su media de 200, rebalanceando cada 60.

| Del 1 de octubre de 2025 al 23 de octubre de 2026 | Rendimiento | Caída máxima | Volatilidad |
|---|---|---|---|
| Estrategia elegida | +49.2% | −20.1% | 36.9% |
| Igual peso en todo el reto | +13.3% | −6.3% | 15.0% |
| Agresivo | +14.8% | −6.8% | 9.9% |
| La regla que usaba antes | −16.5% | −42.4% | 55.7% |

Rinde más con mucho más riesgo, y el resultado depende de pocas emisoras. Por
eso no se activa sola: la eliges en la página **Estrategia**. Cada ciclo:
- las ventas son de la regla;
- las compras pasan por el comité, con noticias y reporte;
- tú apruebas cada orden.

**A2 ve más del reporte** (D73). Además de ingresos y utilidad operativa, el
reporte trae balance y flujo de efectivo. Una nota con indicadores calculados
lleva márgenes, flujo libre, deuda neta entre EBITDA, rendimiento sobre
capital y valuación. A2 la lee con su herramienta de notas, sin cambiar el
ejecutable.

**A3 simula con la historia del reto** (D76). Además de las caídas planas de
10% (E1 y E2), simula tres escenarios con precios reales del último año:
- E3, el peor mes de tu cartera, con lo que hizo cada emisora en esas fechas;
- E4, la mayor apreciación del peso, que golpea a las del SIC;
- E5, el peor mes de la emisora que compras.

Cada compra muestra cuánto sumaría o restaría a la pérdida en cada uno, y la
página Cartera muestra el estrés de lo que tienes.

**La ejecución.** El reto no tiene API y sus bases no dicen si permiten
operar con un programa. El ejecutor no entra a la cuenta: al aprobar vuelve a
revisar precio (±3%), efectivo, tenencia y concentración, arma la boleta, y
cuando registro el precio y el folio la operación entra al libro.

```powershell
.venv\Scripts\python -m comite recorrer --sin-comite   # solo reglas, sin cuota
.venv\Scripts\python -m comite preguntar "¿Qué dice el reporte de Walmex?"
.venv\Scripts\python -m comite backtest              # la validación de D71
.venv\Scripts\python -m comite estrategia            # muestra o elige la estrategia
.venv\Scripts\python -m comite estado
```

**El monitor** (D74). Repite el recorrido cada 30 minutos, de lunes a viernes
de 7:30 a 15:00. Avisa con una notificación de Windows cuando hay algo por
aprobar y escribe en `data/monitor.log`. Cuida la cuota de dos maneras:
- analiza 2 situaciones por vuelta;
- deja el comité al llegar a 350 llamadas del día.

```powershell
.venv\Scripts\python -m comite vigilar                 # en una terminal abierta
# o con el Programador de tareas, desde la carpeta del repo; fuera de horario
# la vuelta no hace nada:
schtasks /Create /TN ComiteReto /SC MINUTE /MO 30 /F /TR "cmd /c cd /d $PWD && .venv\Scripts\python.exe -m comite vigilar --una-vez"
```

No es day trading:
- Yahoo trae la BMV con unos 20 minutos de retraso;
- Google News tarda de minutos a horas;
- cada caso del comité tarda de 30 a 150 segundos;
- cada orden la capturo yo.

Un caso del comité usa de 4 a 13 llamadas y tarda de 30 a 150 segundos. El
recorrido analiza 4 situaciones por corrida (ajustable en la barra lateral).
Las decisiones de esta parte son D59–D76 en `docs/decisiones.md`.

---

## Configurar la API key

Hay una variable obligatoria, `GOOGLE_API_KEY`, con una key de la API de
Gemini (decisión D47). La usan los agentes A0–A4 (gemini-3.5-flash-lite) y el juez
J1/J2 (gemini-3.1-flash-lite). El juez es otro modelo para no calificar salidas
del suyo, aunque comparte proveedor.

La key se crea gratis en [Google AI Studio](https://aistudio.google.com/apikey)
y va en tu equipo, nunca en el código ni en el chat. Tienes dos opciones:

**Archivo `.env`** (recomendado). Copia la plantilla y escribe la key en
`.env`. Ese archivo está en `.gitignore` y no entra al ZIP de entrega. Si ya
tenías un `.env` de la plantilla anterior, sobrescríbelo: las variables de
OpenAI y Anthropic ya no se usan.

```powershell
Copy-Item .env.example .env
notepad .env
```

**Variable de sesión**, solo para la terminal abierta:

```powershell
$env:GOOGLE_API_KEY = "..."
```

**Cuota.** La capa gratuita limita las llamadas por minuto y por día, por
modelo. Los límites de tu proyecto se ven en AI Studio. El sistema va a 12
llamadas por minuto por modelo (`GEMINI_RPM` lo cambia). En esa capa, Google
usa lo que recibe para mejorar sus productos; los datos del proyecto son
ficticios. Ninguna prueba usa la key: `tests/conftest.py` la borra y corta la
red (decisión D50).

---

## Arranque

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install langchain==1.4.7 langchain-google-genai==4.4.2 google-genai==2.33.0 langgraph==1.2.18 pydantic==2.14.1
.venv\Scripts\python proyecto_multiagente.py --verificar
```

`--verificar` comprueba la versión de Python, las versiones fijadas y las
huellas de la clave del evaluador. Después gasta dos llamadas de la cuota:
- una del modelo de agentes con todos los esquemas del sistema, para que la
  API los valide y el modelo llame una herramienta;
- una de texto del modelo juez.

Un caso de desarrollo, fuera de la campaña oficial:

```powershell
.venv\Scripts\python proyecto_multiagente.py --consulta "Busca noticias de XYZ"
.venv\Scripts\python proyecto_multiagente.py --consulta "..." --falla QERR --traza caso.jsonl
```

El evaluador, comprobado con trazas que llevan un defecto plantado, sin
modelo ni red (sección 2.8 de la especificación):

```powershell
.venv\Scripts\python proyecto_multiagente.py --probar-evaluador
```

Para la congelación, que se hace una vez, antes de la campaña:

```powershell
.venv\Scripts\python proyecto_multiagente.py --congelar
```

Primero corre las mismas pruebas sintéticas. Si todas salen como se espera,
escribe `reports/congelacion.json` con las huellas de datos, expectativas,
juez, agentes, límites y configuración, más el SHA-256 del archivo.

---

## La campaña

```powershell
.venv\Scripts\python proyecto_multiagente.py
```

Sin opciones corre la campaña: R1–R5 tres veces, por rondas, y R6 tres veces
aparte. Al terminar imprime la tabla de las rutas. Si los agentes siguieran
las rutas de referencia serían 123 llamadas a los agentes y 6 al juez; con
modelos reales serán más. A 12 llamadas por minuto, al menos 11 minutos.

Si la cuota se acaba a mitad de campaña, la campaña se detiene. La ejecución
cortada se conserva, no cuenta y se repite. Al volver a correr el mismo
comando con el mismo código, sigue donde quedó sin repetir ninguna ejecución
terminada. Si el código cambió, empieza otra campaña y la anterior se
conserva (decisión D52).

```powershell
.venv\Scripts\python proyecto_multiagente.py --ejecuciones 5   # a lo más 5 hoy
.venv\Scripts\python proyecto_multiagente.py --tabla           # sin llamar a los modelos
.venv\Scripts\python proyecto_multiagente.py --nueva-campana   # otra, a propósito
```

Cada campaña queda en `reports/campanas/<fecha>-<hora>/`:
- `campana.json`: huellas, modelos, versiones, rutas y plan;
- `ejecuciones.jsonl`: un registro por ejecución;
- `trazas.jsonl`: los eventos de cada ejecución;
- `resultados.json`: las tablas, recalculadas de los registros;
- `revision.md`: la plantilla de la revisión humana.

Pruebas deterministas, sin modelo ni red:

```powershell
.venv\Scripts\python -m pip install pytest ruff
.venv\Scripts\python -m pytest
```

---

## Entregables

```powershell
.venv\Scripts\python scripts\diagrama.py    # reports/diagrama_arquitectura.pdf
.venv\Scripts\python scripts\informe.py     # reports/informe_resultados.pdf
.venv\Scripts\python scripts\empacar.py     # dist/: .py, informe, diagrama y ZIP
```

Ninguno llama a los modelos. Necesitan `xelatex` (MiKTeX). El informe toma
todos sus números de `resultados.json` de la campaña completa más reciente. El
análisis de fallas sale de `analisis.json` y la revisión humana de
`revision.md`, los dos en la carpeta de la campaña. Después de llenar la
revisión, se vuelven a correr `informe.py` y `empacar.py`.

---

## Estructura

```
proyecto_multiagente.py   entregable 1: sistema y evaluación en un solo archivo
tests/unit/               pruebas deterministas: contratos, datos, clave,
                          herramientas, Mesa, grafo, evaluador, Gemini y
                          campaña
tests/conftest.py         ninguna prueba sale a la red, usa la key ni escribe
                          en reports/
tests/guion.py            reexporta el modelo de guion del ejecutable, para
                          probar el grafo sin red
tests/gemini_falso.py     cliente falso de Gemini: la conversión real de
                          langchain-google-genai, sin red
docs/decisiones.md        sección 10 para el documento de trabajo: decisiones
                          que completan la especificación v0.3
docs/pruebas.md           registro de lo verificado en cada bloque
comite/                   la aplicación (bloques 7 y 8): base de datos,
                          fuentes, vigía, puente al comité, recomendador,
                          ejecutor, estrategia, backtest, indicadores,
                          escenarios y monitor
streamlit_app.py          la app; sus páginas están en app_pages/
data/precios_reto.csv.gz  historial del reto desde 2024 con USDMXN
tests/app/                pruebas de la aplicación, sin red ni cuota
reports/                  congelación y campañas, JSON y JSONL (Bloque 5)
scripts/                  PDF, diagrama y ZIP de entrega (Bloque 6)
```

La rúbrica pide un solo `.py` ejecutable. Por eso el sistema vive completo en
`proyecto_multiagente.py`, y el repo alrededor aporta pruebas, documentación,
los scripts que generan los entregables y la aplicación, que lo importa sin
modificarlo.

---

## Lo que NO hace

No conecta un intermediario ni ejecuta operaciones: no existe herramienta para
hacerlo. No estima rentabilidad. En la evaluación los datos son ficticios, y
las reglas de POL1 son del proyecto, no del reto Actinver.

La aplicación tampoco opera sola: arma la boleta y yo la capturo. Lee
titulares, no el cuerpo de las notas. La fecha de publicación de los reportes
de yfinance es estimada, y el trimestre se nombra por su mes de cierre
(el trimestre fiscal de NVDA que cierra en julio aparece como 2026Q3).

La estrategia y la regla de reducción son reglas, no predicciones. Que la
estrategia haya funcionado en un año de prueba no garantiza que funcione en
las semanas que quedan del reto. El backtest tiene sesgo de supervivencia,
no incluye dividendos y supone una comisión de 0.25%.
