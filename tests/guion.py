"""Un modelo falso que sigue un guion: las respuestas se fijan de antemano.

Sirve para probar el grafo y los controles sin red ni API key. Lo que se
verifica con él es la infraestructura, es decir, qué hace el sistema con lo
que un modelo pida. No dice nada sobre lo que un modelo real pediría: eso solo
lo mide la campaña.
"""

import uuid
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ModeloGuion(BaseChatModel):
    respuestas: list[Any]
    model_name: str = "guion"

    @property
    def _llm_type(self) -> str:
        return "guion"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.respuestas:
            raise AssertionError("El guion se agotó: el agente pidió más turnos.")
        siguiente = self.respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return ChatResult(generations=[ChatGeneration(message=_copia(siguiente))])


def _copia(mensaje: AIMessage) -> AIMessage:
    """Un mensaje nuevo con ids nuevos en cada turno.

    `[pide(...)] * 5` repite el mismo objeto. LangGraph fusiona los mensajes
    que comparten id, así que sin copia el agente vería una sola llamada donde
    el guion pedía cinco.
    """
    return AIMessage(
        content=mensaje.content,
        tool_calls=[
            {**c, "id": f"call_{uuid.uuid4().hex[:8]}"} for c in mensaje.tool_calls
        ],
        usage_metadata=mensaje.usage_metadata,
    )


def pide(nombre: str, **args: Any) -> AIMessage:
    """Un turno del modelo que pide una herramienta."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": nombre, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}
        ],
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )


def pide_varias(*llamadas: tuple[str, dict]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": n, "args": a, "id": f"call_{uuid.uuid4().hex[:8]}"}
            for n, a in llamadas
        ],
    )


def guiones(**por_agente: list[Any]):
    """modelo_para(agente) con un guion propio por agente."""
    modelos = {a: ModeloGuion(respuestas=list(r)) for a, r in por_agente.items()}

    def modelo_para(agente: str) -> ModeloGuion:
        if agente not in modelos:
            raise AssertionError(f"{agente} no tenía guion y fue invocado.")
        return modelos[agente]

    modelo_para.modelos = modelos
    return modelo_para


# --- Salidas estructuradas frecuentes ---


def sintesis(tipo: str, evidencia=(), propuesta=None, resumen="Resumen.") -> AIMessage:
    return pide(
        "SintesisSupervisor",
        tipo_salida=tipo,
        resumen=resumen,
        evidencia=list(evidencia),
        limitaciones=[],
        propuesta=propuesta,
    )


def salida_a1(
    noticia_id="N1", evento="reduccion_guia_ingresos", sentimiento="negativo"
):
    return pide(
        "SalidaNoticias",
        analisis=[
            {
                "noticia_id": noticia_id,
                "tipo_evento": evento,
                "sentimiento": sentimiento,
                "novedad": "nueva",
                "incertidumbre": "media",
                "explicacion": "Explicación.",
            }
        ],
        hallazgos=["Hallazgo."],
        limitaciones=[],
        datos_suficientes=True,
    )


def salida_a3(movimiento, es_propuesta, suficientes=True, portafolio="P1"):
    return pide(
        "SalidaPortafolio",
        hallazgos=["Hallazgo."],
        supuestos=[],
        limitaciones=[],
        portafolio_id=portafolio,
        movimiento=movimiento,
        es_propuesta=es_propuesta,
        datos_suficientes=suficientes,
    )


def salida_a4(decision, motivos=("Motivo.",)):
    return pide("SalidaRiesgo", decision=decision, motivos=list(motivos))
