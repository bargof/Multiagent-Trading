"""Un cliente falso de Gemini, para probar la integración sin red ni cuota.

Ocupa el lugar de google.genai.Client: guarda cada petición que arma
langchain-google-genai y contesta con el turno siguiente de un guion,
convertido al formato de la API. Así las rutas pasan por la conversión real
de mensajes, esquemas, firmas de pensamiento y errores, que el modelo de
guion se salta. Lo que no prueba es lo que contestaría el modelo real: eso lo
mide la campaña.
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from google.genai import types
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from proyecto_multiagente import (
    MODELO_AGENTES,
    MODELO_JUEZ,
    Configuracion,
    crear_modelo,
)

CONFIG = Configuracion(modelo=MODELO_AGENTES, modelo_juez=MODELO_JUEZ)


def _a_json(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, BaseModel):
        return valor.model_dump(mode="json")
    raise TypeError(type(valor))


def respuesta_de_la_api(mensaje: AIMessage, modelo: str, turno: int):
    """Un AIMessage del guion, como lo devolvería la API de Gemini."""
    partes = [types.Part(text=mensaje.text)] if mensaje.text else []
    for i, llamada in enumerate(mensaje.tool_calls):
        partes.append(
            types.Part(
                function_call=types.FunctionCall(
                    id=f"fc-{turno}-{i}",
                    name=llamada["name"],
                    # Ida y vuelta por JSON: los argumentos llegan así de la API.
                    args=json.loads(json.dumps(llamada["args"], default=_a_json)),
                ),
                # Gemini firma solo la primera llamada de cada turno.
                thought_signature=f"firma-{turno}".encode() if i == 0 else None,
            )
        )
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=partes),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100,
            candidates_token_count=10,
            thoughts_token_count=5,
            total_token_count=115,
        ),
        model_version=modelo,
    )


class ClienteFalso:
    """Ocupa el lugar de google.genai.Client. `models` es él mismo."""

    def __init__(self, guion=(), existe=True):
        self.models = self
        self.guion = list(guion)
        self.peticiones = []
        self.existe = existe

    def generate_content(self, *, model, contents, config):
        self.peticiones.append(
            SimpleNamespace(model=model, contents=contents, config=config)
        )
        if not self.guion:
            raise AssertionError("El guion se agotó: el agente pidió más turnos.")
        turno = self.guion.pop(0)
        if isinstance(turno, Exception):
            raise turno
        return respuesta_de_la_api(turno, model, len(self.peticiones))

    def get(self, *, model):
        if not self.existe:
            raise genai_errors.ClientError(
                404, {"error": {"code": 404, "status": "NOT_FOUND"}}
            )
        return types.Model(name=f"models/{model}")


def gemini(nombre, guion=(), existe=True):
    """El modelo que usa el sistema, con el cliente falso en lugar del real."""
    with pytest.MonkeyPatch.context() as entorno:
        # Una key cualquiera: construir el cliente no sale a la red.
        entorno.setenv("GOOGLE_API_KEY", "AIza-sin-red")
        llm = crear_modelo(nombre, CONFIG)
    llm.client = ClienteFalso(guion, existe)
    llm.rate_limiter = None  # el ritmo se prueba aparte; aquí solo haría esperar
    return llm


def error_de_google(codigo, estado):
    """El error que lanza el SDK de Google con ese código HTTP."""
    cuerpo = {"error": {"code": codigo, "status": estado, "message": estado}}
    if codigo >= 500:
        return genai_errors.ServerError(codigo, cuerpo)
    return genai_errors.ClientError(codigo, cuerpo)
