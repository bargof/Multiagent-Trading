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
| 4 | Evaluador, juez y congelación | Pendiente |
| 5 | Campaña: R1–R5 ×3, R6 ×3 aparte | Pendiente |
| 6 | PDF de resultados, diagrama y ZIP | Pendiente |

Ninguna ruta se ha ejecutado todavía. No hay resultados observados.

---

## Configurar las API keys

Hay dos variables obligatorias, una por proveedor (decisión D22):

- `OPENAI_API_KEY`, para los agentes A0–A4 (gpt-4.1-mini);
- `ANTHROPIC_API_KEY`, para el juez J1/J2 (claude-sonnet-5-5).

Juez y agentes son de proveedores distintos para que el juez no comparta los
sesgos del modelo que evalúa. Las keys van en tu equipo, nunca en el código
ni en el chat. Tienes dos opciones:

**Archivo `.env`** (recomendado). Copia la plantilla y escribe las keys en
`.env`. Ese archivo está en `.gitignore` y no entra al ZIP de entrega.

```powershell
Copy-Item .env.example .env
notepad .env
```

**Variables de sesión**, solo para la terminal abierta:

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

---

## Arranque

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install langchain==1.4.7 langchain-openai==1.7.3 langchain-anthropic==1.7.6 langgraph==1.2.18 openai==3.39.0 anthropic==1.17.0 pydantic==2.14.1
.venv\Scripts\python proyecto_multiagente.py --verificar
```

`--verificar` comprueba la versión de Python, las versiones fijadas, las
huellas de la clave del evaluador y, para cada modelo, su disponibilidad,
una llamada de texto, una llamada a herramienta y una salida estructurada.

Un caso de desarrollo, fuera de la campaña oficial:

```powershell
.venv\Scripts\python proyecto_multiagente.py --consulta "Busca noticias de XYZ"
.venv\Scripts\python proyecto_multiagente.py --consulta "..." --falla QERR --traza caso.jsonl
```

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
                          herramientas, Mesa y grafo
tests/guion.py            modelo falso con guion, para probar el grafo sin red
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
