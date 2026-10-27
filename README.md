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
| 5 | Campaña: R1–R5 ×3, R6 ×3 aparte | Pendiente |
| 6 | PDF de resultados, diagrama y ZIP | Pendiente |

Ninguna ruta se ha ejecutado todavía con modelos reales. No hay resultados
observados: las 23 trazas de `--probar-evaluador` son pruebas del evaluador,
no ejecuciones del sistema. La integración con Gemini está probada con un
cliente falso, sin red ni cuota.

---

## Configurar la API key

Hay una variable obligatoria, `GOOGLE_API_KEY`, con una key de la API de
Gemini (decisión D47). La usan los agentes A0–A4 (gemini-3.6-flash) y el juez
J1/J2 (gemini-3.8-flash). El juez es otro modelo para no calificar salidas
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
modelo. Los límites de tu proyecto se ven en AI Studio. El sistema va a 8
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

Pruebas deterministas, sin modelo ni red:

```powershell
.venv\Scripts\python -m pip install pytest ruff
.venv\Scripts\python -m pytest
```

---

## Estructura

```
proyecto_multiagente.py   entregable 1: sistema y evaluación en un solo archivo
tests/unit/               pruebas deterministas: contratos, datos, clave,
                          herramientas, Mesa, grafo, evaluador y Gemini
tests/conftest.py         ninguna prueba sale a la red ni usa la key
tests/guion.py            reexporta el modelo de guion del ejecutable, para
                          probar el grafo sin red
docs/decisiones.md        sección 10 para el documento de trabajo: decisiones
                          que completan la especificación v0.3
docs/pruebas.md           registro de lo verificado en cada bloque
reports/                  resultados de campaña, JSON y JSONL (Bloque 5)
scripts/                  PDF, diagrama y ZIP de entrega (Bloque 6)
```

La rúbrica pide un solo `.py` ejecutable. Por eso el sistema vive completo en
`proyecto_multiagente.py`, y el repo alrededor solo aporta pruebas,
documentación y los scripts que generan los entregables.

---

## Lo que NO hace

No conecta un intermediario ni ejecuta operaciones: no existe herramienta para
hacerlo. No estima rentabilidad. Los datos son ficticios, y las reglas de POL1
son del proyecto, no del reto Actinver.
