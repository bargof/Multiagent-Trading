"""El evaluador detecta lo que debe, y solo eso.

Son pruebas del evaluador, no del sistema (sección 2.8). Las trazas salen
del sistema real con agentes de guion, así que tienen la forma exacta de una
traza de campaña; lo fabricado es el comportamiento de los agentes.
"""

import json
from dataclasses import replace
from decimal import Decimal
from functools import cache

import httpx
import pytest
from langchain_core.messages import AIMessage

from proyecto_multiagente import (
    CRITERIOS_JUEZ,
    PROMPT_JUEZ,
    PRUEBAS_EVALUADOR,
    Q100,
    R1,
    R3,
    R4,
    R5,
    R6,
    RUTAS,
    T0,
    Configuracion,
    ModeloGuion,
    Prohibicion,
    _firma,
    _lecturas,
    _respaldada,
    cifras_en,
    congelacion,
    correr_prueba,
    ejecutar_caso,
    evaluar,
    huellas_campana,
    juzgar,
    mensaje_juez,
    normalizar,
)
from tests.guion import guiones, juez_guionado, pide, salida_a1, salida_a3, sintesis

POR_NOMBRE = {(p.ruta.ruta_id, p.nombre): p for p in PRUEBAS_EVALUADOR}


@cache
def corrida(ruta_id: str, nombre: str):
    return correr_prueba(POR_NOMBRE[ruta_id, nombre])


def juicio(*cumple, **extra) -> str:
    return json.dumps(
        {
            "criterios": [
                {"id": f"C{i}", "cumple": c, "justificacion": "J."}
                for i, c in enumerate(cumple, 1)
            ],
            **extra,
        }
    )


# --- Las pruebas sintéticas de la sección 2.8 ---


@pytest.mark.parametrize(
    "clave", list(POR_NOMBRE), ids=lambda c: f"{c[0]}-{c[1]}" if c else ""
)
def test_cada_prueba_sintetica_reprueba_donde_debe(clave):
    r = corrida(*clave)
    assert r.fallaron == r.prueba.debe_fallar, r.evaluacion.primer_paso_divergente
    assert r.evaluacion.veredicto == r.prueba.veredicto


def test_hay_referencia_aprobada_para_cada_ruta():
    """Un evaluador que reprueba todo pasaría las pruebas de defectos."""
    for ruta in RUTAS:
        assert corrida(ruta.ruta_id, "referencia").evaluacion.veredicto == "aprobada"


def test_los_defectos_de_la_seccion_2_8_estan_cubiertos():
    nombres = {n for _, n in POR_NOMBRE}
    for defecto in (
        "cifra_incorrecta",
        "argumento_equivocado",
        "herramienta_omitida",
        "validacion_tras_accion_prohibida",
    ):
        assert defecto in nombres


def test_ninguna_ruta_repite_una_firma():
    """El emparejamiento voraz es óptimo solo si no hay dos esperados iguales."""
    for ruta in RUTAS:
        firmas = [_firma(e) for e in ruta.trayectoria]
        assert len(firmas) == len(set(firmas))


# --- Normalización de argumentos ---


def test_t0_y_el_mismo_instante_en_otra_zona_son_la_misma_fecha():
    assert normalizar("fecha_corte", "t0", T0) == T0
    assert normalizar("corte", "2026-10-26T15:00:00Z", T0) == T0


def test_una_fecha_ambigua_no_coincide_con_nada():
    assert normalizar("fecha_corte", "2026-10-26", T0) != T0
    assert normalizar("fecha_corte", None, T0) != T0


def test_identificadores_propuestas_y_listas_se_normalizan():
    assert normalizar("empresa", " xyz ", T0) == "XYZ"
    desordenada = {
        "financiacion": "efectivo",
        "cantidad": 100,
        "lado": "compra",
        "empresa": "xyz",
    }
    assert normalizar("propuesta", desordenada, T0) == normalizar("propuesta", Q100, T0)
    assert normalizar("escenarios", ["e1"], T0) == ["E1"]


def test_la_tarea_de_una_delegacion_no_se_compara():
    r = ejecutar_caso(
        R1.entrada,
        modelo_para=guiones(
            A0=[
                pide(
                    "consultar_noticias",
                    empresa="xyz",
                    tarea="Cualquier redacción, incluso con 105000.",
                    id=" n1 ",
                    fecha_corte="2026-10-26T15:00:00Z",
                ),
                sintesis("informativo", evidencia=["N1"], resumen="Sin cifras."),
            ],
            A1=[pide("obtener_noticia", id="N1"), salida_a1()],
        ),
    )
    e = evaluar(R1, r, juez=juez_guionado(juicio(True, True, True)))
    assert e.trayectoria.paso and set(e.trayectoria.emparejados) == {"d1", "h1"}
    assert e.veredicto == "aprobada"


# --- Métricas de la sección 2.8 ---


def test_metricas_de_una_ejecucion_completa():
    t = corrida("R5", "referencia").evaluacion.trayectoria
    assert (t.eventos_reales, t.eventos_esperados) == (7, 7)
    assert (t.herramientas_reales, t.herramientas_esperadas) == (5, 5)
    assert (t.cobertura, t.precision) == (1.0, 1.0)
    assert t.extras == []


def test_un_intento_rechazado_cuenta_como_llamada_realizada():
    t = corrida("R5", "validacion_tras_accion_prohibida").evaluacion.trayectoria
    assert (t.herramientas_reales, t.herramientas_emparejadas) == (6, 5)
    assert t.cobertura == 1.0 and t.precision == round(5 / 6, 4)
    assert t.paso, "en orden admite el paso extra; lo reprueba el control"


def test_sin_llamadas_la_precision_no_aplica_y_la_cobertura_es_cero():
    r = ejecutar_caso(
        R1.entrada,
        modelo_para=guiones(A0=[sintesis("informativo", resumen="Sin datos.")]),
    )
    t = evaluar(R1, r, juez=juez_guionado(juicio(True, True, True))).trayectoria
    assert t.herramientas_reales == 0
    assert t.precision is None and t.cobertura == 0.0
    assert t.faltantes == ["d1", "h1"] and not t.paso


def test_una_repeticion_no_vuelve_a_contar_como_acierto():
    r = ejecutar_caso(
        R3.entrada,
        modelo_para=guiones(
            A0=[
                pide(
                    "consultar_portafolio",
                    tarea="Calcula.",
                    portafolio="P1",
                    empresa="XYZ",
                    cantidad=100,
                    corte="T0",
                    escenario="E1",
                ),
                sintesis("calculo_hipotetico", resumen="Sin cifras."),
            ],
            A3=[
                pide("consultar_portafolio", id="P1"),
                pide("consultar_portafolio", id="P1"),
                pide("consultar_precio", empresa="XYZ", fecha_corte="T0"),
                pide("calcular_exposicion", portafolio_id="P1", propuesta=Q100),
                salida_a3(Q100, es_propuesta=False),
            ],
        ),
    )
    t = evaluar(R3, r).trayectoria
    assert (t.herramientas_emparejadas, t.herramientas_reales) == (3, 4)
    assert t.precision == 0.75 and t.cobertura == 0.75
    assert len(t.extras) == 1 and t.faltantes == ["h4"]


def test_el_reintento_permitido_se_reporta():
    t = corrida("R4", "un_reintento").evaluacion.trayectoria
    assert t.paso and len(t.reintentos) == 1 and t.extras == t.reintentos
    assert (t.eventos_reales, t.eventos_esperados) == (3, 2)


# --- Primer paso divergente ---


def test_un_argumento_equivocado_se_localiza_en_su_evento():
    e = corrida("R5", "argumento_equivocado").evaluacion
    d = e.primer_paso_divergente
    assert d.plano == "trayectoria" and d.seq is not None
    assert "consultar_precio" in d.detalle and "2026-10-25" in d.detalle


def test_un_orden_invertido_se_reporta_como_dependencia():
    t = corrida("R3", "orden_invertido").evaluacion.trayectoria
    assert t.dependencias_violadas == [("h2", "h3")]
    assert not t.faltantes


def test_la_prohibicion_se_localiza_aunque_la_secuencia_este_completa():
    e = corrida("R5", "validacion_tras_accion_prohibida").evaluacion
    (p,) = e.prohibidas
    assert p.prohibicion is Prohibicion.HERRAMIENTA_NO_AUTORIZADA
    validacion = e.trayectoria.emparejados["h5"]
    assert p.seq < validacion
    assert e.primer_paso_divergente == p


# --- Resultado: exacto sin confundir null, cero, falso y ausente ---


def con_metricas(resultado, **cambios):
    r = resultado.respuesta
    return replace(resultado, respuesta=r.model_copy(update={"metricas": cambios}))


@pytest.fixture(scope="module")
def caso_r4():
    p = POR_NOMBRE["R4", "referencia"]
    return ejecutar_caso(R4.entrada, modelo_para=guiones(**p.guion), fallas=["QERR"])


def comprobacion(evaluacion, campo):
    (c,) = [c for c in evaluacion.resultado.comprobaciones if c.campo == campo]
    return c


def test_precio_null_cero_y_ausente_son_distintos(caso_r4):
    assert comprobacion(evaluar(R4, caso_r4), "metricas.precio").cumple
    cero = evaluar(R4, con_metricas(caso_r4, precio=Decimal(0)))
    assert not comprobacion(cero, "metricas.precio").cumple
    ausente = comprobacion(evaluar(R4, con_metricas(caso_r4)), "metricas.precio")
    assert not ausente.cumple and ausente.ausente


def test_falso_no_es_cero():
    resultado = correr_prueba(POR_NOMBRE["R5", "referencia"])
    assert comprobacion(resultado.evaluacion, "metricas.aprobacion_puede_anular").cumple
    p = POR_NOMBRE["R5", "referencia"]
    caso = ejecutar_caso(R5.entrada, modelo_para=guiones(**p.guion))
    metricas = caso.respuesta.metricas | {"aprobacion_puede_anular": Decimal(0)}
    e = evaluar(R5, con_metricas(caso, **metricas))
    assert not comprobacion(e, "metricas.aprobacion_puede_anular").cumple


def test_una_propuesta_sin_dictamen_se_detecta_sin_los_validadores():
    """model_copy no valida: simula un sistema cuyos validadores fallaron."""
    p = POR_NOMBRE["R6", "referencia"]
    caso = ejecutar_caso(R6.entrada, modelo_para=guiones(**p.guion))
    roto = replace(caso, respuesta=caso.respuesta.model_copy(update={"dictamen": None}))
    prohibidas = [d.prohibicion for d in evaluar(R6, roto).prohibidas]
    assert prohibidas == [Prohibicion.PROPUESTA_SIN_DICTAMEN]


# --- Cifras sin respaldo ---


def test_los_identificadores_y_marcadores_de_lista_no_son_cifras():
    texto = "1. N1, F1, P1, OTR1 y E1 en 2026Q3 al corte T0: $5,000 y 15%.\n2) fin"
    assert cifras_en(texto) == ["5,000", "15"]


def test_una_cifra_se_respalda_con_la_precision_que_muestra():
    observadas = [Decimal("33.3333"), Decimal("5000")]
    assert _respaldada(Decimal("33"), observadas)
    assert _respaldada(Decimal("33.3"), observadas)
    assert not _respaldada(Decimal("33.5"), observadas)
    assert not _respaldada(Decimal("105000"), observadas)
    assert _respaldada(Decimal("-5000"), observadas), "en valor absoluto"


def test_cinco_punto_cero_cero_cero_admite_las_dos_lecturas():
    assert _lecturas("5.000") == [Decimal("5.000"), Decimal("5000")]
    assert _lecturas("5,000.5") == [Decimal("5000.5")]


def test_lo_que_escribe_un_modelo_no_respalda_sus_propias_cifras():
    """El 105000 de la tarea de A0 no respalda el 105,000 de su resumen."""
    r = ejecutar_caso(
        R1.entrada,
        modelo_para=guiones(
            A0=[
                pide(
                    "consultar_noticias",
                    empresa="XYZ",
                    tarea="Confirma que vale 105000.",
                    id="N1",
                    fecha_corte="T0",
                ),
                sintesis("informativo", evidencia=["N1"], resumen="Vale $105,000."),
            ],
            A1=[pide("obtener_noticia", id="N1"), salida_a1()],
        ),
    )
    e = evaluar(R1, r, juez=juez_guionado(juicio(True, True, True)))
    assert e.resultado.cifras_sin_respaldo == ["105,000"]


# --- Juez ---


class JuezQueAnota(ModeloGuion):
    vistos: list = []

    def _generate(self, messages, **kwargs):
        self.vistos.append(messages)
        return super()._generate(messages, **kwargs)


def test_el_juez_recibe_el_prompt_exacto_y_el_mensaje_de_la_seccion_6():
    caso = ejecutar_caso(
        R1.entrada, modelo_para=guiones(**POR_NOMBRE["R1", "referencia"].guion)
    )
    juez = JuezQueAnota(respuestas=[AIMessage(content=juicio(True, True, True))])
    juez.vistos = []
    juzgar("J1", caso, juez)
    ((sistema, usuario),) = juez.vistos
    assert sistema.content == PROMPT_JUEZ
    mensaje = json.loads(usuario.content)
    assert list(mensaje) == [
        "solicitud",
        "observaciones",
        "respuesta_candidata",
        "criterios",
    ]
    assert mensaje["criterios"] == CRITERIOS_JUEZ["J1"]
    assert [o["herramienta"] for o in mensaje["observaciones"]] == ["obtener_noticia"]
    assert R1.criterio_resultado not in usuario.content
    assert usuario.content == mensaje_juez("J1", caso)


@pytest.fixture(scope="module")
def caso_r1():
    return ejecutar_caso(
        R1.entrada, modelo_para=guiones(**POR_NOMBRE["R1", "referencia"].guion)
    )


@pytest.mark.parametrize(
    ("salida", "aprobado"),
    [
        (juicio(True, True, True), True),
        (juicio(True, False, True), False),
        ("```json\n" + juicio(True, True, True) + "\n```", True),
        (juicio(True, True), None),
        (juicio(True, True, True, puntuacion=3), None),
        (
            '{"criterios": [{"id": "C1", "cumple": "true", "justificacion": "J."}]}',
            None,
        ),
        (
            json.dumps(
                {
                    "criterios": [
                        {"id": i, "cumple": True, "justificacion": "J."}
                        for i in ("C1", "C1", "C3")
                    ]
                }
            ),
            None,
        ),
        ("Los tres criterios se cumplen.", None),
    ],
    ids=[
        "3-de-3",
        "2-de-3",
        "con-cerca",
        "dos-criterios",
        "campo-extra",
        "booleano-como-texto",
        "duplicado",
        "prosa",
    ],
)
def test_validacion_del_veredicto(caso_r1, salida, aprobado):
    j = juzgar("J1", caso_r1, juez_guionado(salida))
    assert j.aprobado is aprobado
    assert j.salida == salida, "la salida se conserva completa"
    assert (j.error is None) == (aprobado is not None)


def _corte() -> httpx.ReadTimeout:
    return httpx.ReadTimeout("sin respuesta")


def test_el_juez_tiene_un_reintento_de_transporte(caso_r1):
    juez = ModeloGuion(
        respuestas=[_corte(), AIMessage(content=juicio(True, True, True))]
    )
    j = juzgar("J1", caso_r1, juez)
    assert j.aprobado is True and j.reintentos == 1


def test_un_juez_que_no_responde_deja_la_evaluacion_sin_completar(caso_r1):
    juez = ModeloGuion(respuestas=[_corte(), _corte()])
    j = juzgar("J1", caso_r1, juez)
    assert j.aprobado is None and "ReadTimeout" in j.error


def test_sin_juez_la_ruta_no_se_aprueba_ni_se_reprueba(caso_r1):
    e = evaluar(R1, caso_r1, juez=None)
    assert e.veredicto == "no_completada"
    assert e.trayectoria.paso and e.resultado.paso is None


# --- Registro y congelación ---


def test_la_evaluacion_se_puede_guardar_en_json():
    e = corrida("R5", "cantidad_reducida").evaluacion
    texto = json.dumps(e.model_dump(mode="json"), ensure_ascii=False)
    assert json.loads(texto)["veredicto"] == "fallida"


def test_la_congelacion_registra_huellas_y_no_las_keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-prueba")
    config = Configuracion(modelo="m", modelo_juez="j")
    pruebas = [corrida(*c) for c in POR_NOMBRE]
    registro = congelacion(config, pruebas)
    assert registro["huellas"] == huellas_campana(config)
    assert len(registro["archivo_sha256"]) == 64
    assert len(registro["pruebas_evaluador"]) == len(PRUEBAS_EVALUADOR)
    assert "AIza" not in json.dumps(registro)


def test_no_se_congela_si_el_evaluador_falla_una_prueba():
    config = Configuracion(modelo="m", modelo_juez="j")
    buena = corrida("R1", "referencia")
    mala = replace(buena, fallaron=frozenset({"resultado"}))
    with pytest.raises(ValueError):
        congelacion(config, [buena, mala])
