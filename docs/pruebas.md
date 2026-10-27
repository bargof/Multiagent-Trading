# Registro de pruebas

Lo que se verificó en cada bloque, con qué resultado y qué se aprendió. Las
pruebas de infraestructura aparecen separadas de las ejecuciones del sistema:
estas, que son las que usan el modelo, todavía no existen.

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
- [ ] Registrar aquí disponibilidad, tokens de la llamada mínima, llamada a
      herramienta y salida estructurada.
