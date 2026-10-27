"""Un modelo falso que sigue un guion: las respuestas se fijan de antemano.

Sirve para probar el grafo y los controles sin red ni API key. Lo que se
verifica con él es la infraestructura, es decir, qué hace el sistema con lo
que un modelo pida. No dice nada sobre lo que un modelo real pediría: eso solo
lo mide la campaña.

El modelo y los ayudantes viven en el ejecutable (sección 7), porque también
los usan las pruebas sintéticas del evaluador. Aquí se reexportan para las
pruebas, junto con un ayudante que solo usan ellas.
"""

import uuid

from langchain_core.messages import AIMessage

from proyecto_multiagente import (
    ModeloGuion,
    guiones,
    juez_guionado,
    pide,
    salida_a1,
    salida_a2,
    salida_a3,
    salida_a4,
    sintesis,
)

__all__ = [
    "ModeloGuion",
    "guiones",
    "juez_guionado",
    "pide",
    "pide_varias",
    "salida_a1",
    "salida_a2",
    "salida_a3",
    "salida_a4",
    "sintesis",
]


def pide_varias(*llamadas: tuple[str, dict]) -> AIMessage:
    """Un turno que pide varias herramientas a la vez (decisión D28)."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": n, "args": a, "id": f"call_{uuid.uuid4().hex[:8]}"}
            for n, a in llamadas
        ],
    )
