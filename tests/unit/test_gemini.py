"""La integración con Gemini, sin red ni cuota (decisión D50).

Un cliente falso ocupa el lugar de google.genai.Client: guarda cada petición
que arma langchain-google-genai y contesta con el turno siguiente de un
guion, convertido al formato de la API. Así las rutas de referencia pasan por
la conversión real de mensajes, esquemas, firmas de pensamiento y errores,
que el modelo de guion se salta. Lo que no prueba es lo que contestaría el
modelo real: eso lo mide la campaña.
"""

import json
from decimal import Decimal
from functools import cache
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types
from langchain_core.exceptions import ModelInvalidRequestError
from langchain_core.messages import AIMessage
from pydantic import BaseModel

import proyecto_multiagente
from proyecto_multiagente import (
    MODELO_AGENTES,
    MODELO_JUEZ,
    PROMPT_JUEZ,
    PROMPTS,
    PRUEBAS_EVALUADOR,
    SALIDAS,
    ClaseEvento,
    Configuracion,
    _disponible,
    _probar_agentes,
    _probar_juez,
    crear_modelo,
    ejecutar_caso,
    esquemas_del_sistema,
    evaluar,
    herramientas_para,
    verificar_entorno,
)
from tests.guion import pide

CONFIG = Configuracion(modelo=MODELO_AGENTES, modelo_juez=MODELO_JUEZ)
REFERENCIAS = {p.ruta.ruta_id: p for p in PRUEBAS_EVALUADOR if p.nombre == "referencia"}


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


def correr(prueba, guion=None):
    guion = guion or prueba.guion
    modelos = {a: gemini(MODELO_AGENTES, turnos) for a, turnos in guion.items()}
    caso = ejecutar_caso(
        prueba.ruta.entrada,
        modelo_para=lambda agente: modelos[agente],
        fallas=[prueba.ruta.falla] if prueba.ruta.falla else [],
    )
    return caso, modelos


@cache
def corrida(ruta_id):
    prueba = REFERENCIAS[ruta_id]
    caso, modelos = correr(prueba)
    juez = gemini(MODELO_JUEZ, [AIMessage(content=prueba.salida_juez)])
    return SimpleNamespace(
        caso=caso,
        modelos=modelos,
        juez=juez,
        evaluacion=evaluar(prueba.ruta, caso, juez=juez),
    )


def peticiones(corrida_):
    for agente, llm in corrida_.modelos.items():
        for peticion in llm.client.peticiones:
            yield agente, peticion


def texto(contenido) -> str:
    return "".join(p.text or "" for p in contenido.parts)


# --- Las rutas de referencia, por la conversión real ---


@pytest.mark.parametrize("ruta_id", sorted(REFERENCIAS))
def test_las_referencias_aprueban_pasando_por_gemini(ruta_id):
    """Mismo veredicto que con el modelo de guion: la conversión de ida y
    vuelta no cambia argumentos, salidas ni orden."""
    assert corrida(ruta_id).evaluacion.veredicto == "aprobada"


@pytest.mark.parametrize("ruta_id", sorted(REFERENCIAS))
def test_cada_peticion_cumple_lo_que_pide_gemini_3(ruta_id):
    """Decisiones D48 y D30: sin temperature, razonamiento fijo, timeout de
    la sección 3.2 y ningún reintento dentro del SDK."""
    for agente, p in peticiones(corrida(ruta_id)):
        assert p.model == MODELO_AGENTES
        assert p.config.temperature is None
        assert p.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
        assert p.config.http_options.timeout == 60_000
        assert p.config.http_options.retry_options.attempts in (0, 1)
        assert texto(p.config.system_instruction) == PROMPTS[agente]
        declaradas = {
            d.name for t in p.config.tools for d in t.function_declarations or []
        }
        esperadas = {h.name for h in herramientas_para(agente)}
        assert declaradas == esperadas | {SALIDAS[agente].__name__}


def test_las_firmas_de_pensamiento_vuelven_al_modelo():
    """Gemini 3 exige reenviar la firma de cada turno con llamadas. Si se
    perdiera, la librería pondría un comodín y el modelo razonaría sin su
    contexto anterior."""
    revisadas = 0
    for _, p in peticiones(corrida("R5")):
        for contenido in p.contents:
            llamadas = [x for x in contenido.parts if x.function_call]
            if contenido.role != "model" or not llamadas:
                continue
            firma = llamadas[0].thought_signature
            assert isinstance(firma, bytes) and firma.startswith(b"firma-")
            revisadas += 1
    assert revisadas >= 5


def test_cada_llamada_recibe_su_respuesta_con_nombre():
    for _, p in peticiones(corrida("R5")):
        for anterior, siguiente in zip(p.contents, p.contents[1:], strict=False):
            llamadas = [x.function_call for x in anterior.parts if x.function_call]
            if anterior.role != "model" or not llamadas:
                continue
            respuestas = [
                x.function_response for x in siguiente.parts if x.function_response
            ]
            assert [r.name for r in respuestas] == [c.name for c in llamadas]
            assert all(isinstance(r.response, dict) for r in respuestas)


def test_la_traza_registra_el_modelo_y_los_tokens():
    c = corrida("R1")
    llamadas = c.caso.traza.de_clase(ClaseEvento.MODELO)
    assert llamadas and {e.nombre for e in llamadas} == {MODELO_AGENTES}
    # Las firmas son del proveedor y no aportan nada a la traza.
    assert "firma" not in c.caso.traza.a_jsonl()
    assert c.caso.tokens["input_tokens"] == 100 * len(llamadas)


def test_el_juez_recibe_el_prompt_exacto_sin_herramientas():
    c = corrida("R1")
    juicio = c.evaluacion.resultado.juicio
    (peticion,) = c.juez.client.peticiones
    assert texto(peticion.config.system_instruction) == PROMPT_JUEZ
    (usuario,) = peticion.contents
    assert texto(usuario) == juicio.mensaje
    assert peticion.config.tools is None
    assert peticion.config.temperature is None
    assert juicio.modelo == juicio.modelo_respuesta == MODELO_JUEZ
    assert juicio.tokens == {"input_tokens": 100, "output_tokens": 15}


# --- Errores del proveedor ---


def _error(codigo, estado):
    cuerpo = {"error": {"code": codigo, "status": estado, "message": estado}}
    if codigo >= 500:
        return genai_errors.ServerError(codigo, cuerpo)
    return genai_errors.ClientError(codigo, cuerpo)


TRANSITORIOS = {
    "503_saturado": lambda: _error(503, "UNAVAILABLE"),
    "429_cuota": lambda: _error(429, "RESOURCE_EXHAUSTED"),
    "timeout": lambda: httpx.ReadTimeout("sin respuesta"),
    "sin_red": lambda: httpx.ConnectError("sin red"),
}


def _con_falla_en_a1(*fallas):
    prueba = REFERENCIAS["R1"]
    guion = dict(prueba.guion)
    guion["A1"] = [*fallas, *guion["A1"]]
    return prueba, guion


@pytest.mark.parametrize("falla", sorted(TRANSITORIOS))
def test_un_fallo_transitorio_tiene_un_reintento_tras_una_pausa(falla, monkeypatch):
    pausas = []
    monkeypatch.setattr(
        proyecto_multiagente, "pausar_antes_de_reintentar", lambda: pausas.append(1)
    )
    prueba, guion = _con_falla_en_a1(TRANSITORIOS[falla]())
    caso, _ = correr(prueba, guion)
    assert caso.respuesta.estado == "informativo"
    controles = [e.nombre for e in caso.traza.de_clase(ClaseEvento.CONTROL)]
    assert controles.count("reintento_transporte") == 1
    assert pausas == [1]


def test_dos_fallos_seguidos_cierran_el_caso():
    prueba, guion = _con_falla_en_a1(
        TRANSITORIOS["429_cuota"](), TRANSITORIOS["429_cuota"]()
    )
    caso, _ = correr(prueba, guion)
    assert caso.respuesta.estado == "error_controlado"
    assert caso.respuesta.error == "MODEL_UNAVAILABLE"


def test_una_peticion_invalida_no_se_reintenta():
    """Un 400 es un error del programa, no del modelo: se ve en vez de
    esconderse detrás de un reintento."""
    prueba, guion = _con_falla_en_a1(_error(400, "INVALID_ARGUMENT"))
    with pytest.raises(ModelInvalidRequestError):
        correr(prueba, guion)


# --- Ritmo y verificación ---


def test_el_ritmo_se_comparte_por_modelo(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-sin-red")
    monkeypatch.setattr(proyecto_multiagente, "_RITMOS", {})
    a, b = crear_modelo(MODELO_AGENTES, CONFIG), crear_modelo(MODELO_AGENTES, CONFIG)
    juez = crear_modelo(MODELO_JUEZ, CONFIG)
    assert a.rate_limiter is b.rate_limiter
    assert juez.rate_limiter is not a.rate_limiter
    assert a.rate_limiter.requests_per_second == pytest.approx(8 / 60)


def test_verificar_gasta_una_llamada_por_modelo():
    agentes = gemini(MODELO_AGENTES, [pide("eco", texto="hola")])
    assert _disponible(agentes) and _probar_agentes(agentes)
    (peticion,) = agentes.client.peticiones
    nombres = [d.name for t in peticion.config.tools for d in t.function_declarations]
    assert len(nombres) == len(set(nombres)) == len(esquemas_del_sistema()) + 1
    for agente, salida in SALIDAS.items():
        assert salida.__name__ in nombres
        for h in herramientas_para(agente):
            assert h.name in nombres or f"{h.name}_{agente}" in nombres

    juez = gemini(MODELO_JUEZ, [AIMessage(content="ok")])
    assert _disponible(juez) and _probar_juez(juez)
    assert len(juez.client.peticiones) == 1


def test_verificar_avisa_si_el_modelo_no_existe(capsys):
    assert not _disponible(gemini(MODELO_AGENTES, existe=False))
    assert "no está disponible" in capsys.readouterr().out


def test_sin_key_verificar_no_construye_modelos(capsys):
    assert not verificar_entorno(Configuracion.desde_entorno())
    assert "Falta GOOGLE_API_KEY" in capsys.readouterr().out


def test_las_pruebas_no_pueden_salir_a_la_red(monkeypatch):
    """La guarda de conftest.py: un modelo con el cliente real no llega a Google."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-sin-red")
    llm = crear_modelo(MODELO_AGENTES, CONFIG)
    llm.rate_limiter = None
    with pytest.raises(AssertionError, match="salir a la red"):
        llm.invoke("hola")
