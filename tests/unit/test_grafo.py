"""El grafo de control con modelos falsos que siguen un guion.

Cada prueba fija lo que "pide" cada agente y verifica qué hace el sistema con
eso: qué queda en la traza, qué estado decide el grafo y qué se libera. Son
pruebas de infraestructura (sección 7.2). No dicen nada sobre lo que pediría
un modelo real; eso lo mide la campaña.
"""

from decimal import Decimal

import httpx2
import openai
import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from proyecto_multiagente import (
    DELEGACIONES,
    HERRAMIENTAS,
    LIMITES,
    PROMPTS,
    Q100,
    Q600,
    R1,
    R3,
    R4,
    R5,
    R6,
    RUTAS,
    SALIDAS,
    ClaseEvento,
    ejecutar_caso,
    pide_movimiento,
)
from tests.guion import (
    guiones,
    pide,
    pide_varias,
    salida_a1,
    salida_a3,
    salida_a4,
    sintesis,
)

EVALUADOS = (ClaseEvento.HERRAMIENTA, ClaseEvento.DELEGACION)


def correr(solicitud, fallas=(), **por_agente):
    return ejecutar_caso(solicitud, modelo_para=guiones(**por_agente), fallas=fallas)


def evaluados(resultado):
    return [
        (e.clase.value, e.actor, e.nombre)
        for e in resultado.traza.eventos
        if e.clase in EVALUADOS
    ]


def controles(resultado, nombre):
    return [
        e
        for e in resultado.traza.eventos
        if e.clase is ClaseEvento.CONTROL and e.nombre == nombre
    ]


def a0_delega_portafolio(cantidad, tipo, propuesta=None, escenario=None, veces=1):
    return [
        pide(
            "consultar_portafolio",
            tarea="Evalúa el movimiento.",
            portafolio="P1",
            empresa="XYZ",
            cantidad=cantidad,
            corte="T0",
            escenario=escenario,
        ),
        sintesis(tipo, evidencia=["P1", "PRECIOS_T0"], propuesta=propuesta),
    ] * veces


def a3_evalua(movimiento, es_propuesta, simular=False):
    pasos = [
        pide("consultar_portafolio", id="P1"),
        pide("consultar_precio", empresa="XYZ", fecha_corte="T0"),
        pide("calcular_exposicion", portafolio_id="P1", propuesta=movimiento),
    ]
    if simular:
        pasos.append(
            pide(
                "simular_escenarios",
                portafolio_id="P1",
                propuesta=movimiento,
                escenarios=["E1"],
            )
        )
    return pasos + [salida_a3(movimiento, es_propuesta)]


def a4_revisa(movimiento, decision):
    return [
        pide("consultar_politica"),
        pide("validar_propuesta", portafolio_id="P1", propuesta=movimiento),
        salida_a4(decision),
    ]


TRAYECTORIA_CON_RIESGO = [
    ("delegacion", "A0", "consultar_portafolio"),
    ("herramienta", "A3", "consultar_portafolio"),
    ("herramienta", "A3", "consultar_precio"),
    ("herramienta", "A3", "calcular_exposicion"),
    ("delegacion", "grafo", "revisar_riesgo"),
    ("herramienta", "A4", "consultar_politica"),
    ("herramienta", "A4", "validar_propuesta"),
]


# --- Las cuatro salidas principales ---


def test_consulta_informativa_de_una_noticia():
    r = correr(
        R1.entrada,
        A0=[
            pide(
                "consultar_noticias",
                empresa="XYZ",
                tarea="Explica N1.",
                id="N1",
                fecha_corte="T0",
            ),
            sintesis("informativo", evidencia=["N1"]),
        ],
        A1=[pide("obtener_noticia", id="N1"), salida_a1()],
    )
    resp = r.respuesta
    assert resp.estado == "informativo"
    assert resp.metricas["evento"] == "reduccion_guia_ingresos"
    assert resp.metricas["sentimiento"] == "negativo"
    assert resp.evidencia == ["N1"]
    assert resp.propuesta is None and resp.dictamen is None
    assert evaluados(r) == [
        ("delegacion", "A0", "consultar_noticias"),
        ("herramienta", "A1", "obtener_noticia"),
    ]
    (retorno,) = [e for e in r.traza.eventos if e.clase is ClaseEvento.RETORNO]
    assert retorno.resultado["source_ids"] == ["N1"]
    assert (retorno.actor, retorno.destino) == ("A1", "A0")


def test_compra_que_rebasa_el_limite_se_bloquea():
    propuesta = {"portafolio_id": "P1", "movimiento": Q600}
    r = correr(
        R5.entrada,
        A0=a0_delega_portafolio(600, "propuesta", propuesta),
        A3=a3_evalua(Q600, es_propuesta=True),
        A4=a4_revisa(Q600, "rechazar"),
    )
    resp = r.respuesta
    assert resp.estado == "bloqueada"
    assert resp.propuesta.cantidad == 600 and resp.propuesta.version == 1
    assert resp.dictamen.validacion.cumple is False
    assert resp.dictamen.hash_propuesta == resp.propuesta.huella()
    m = resp.metricas
    assert m["motivo"] == "LIMITE_CONCENTRACION"
    assert m["aprobacion_puede_anular"] is False
    assert (m["limite_pct"], m["exceso_pp"]) == (30, 10)
    assert (m["costo"], m["peso_xyz_pct"], m["efectivo_despues"]) == (30000, 40, 0)
    assert resp.resumen.startswith("Propuesta bloqueada")
    assert evaluados(r) == TRAYECTORIA_CON_RIESGO
    assert r.entorno.portafolios_intactos() and r.entorno.politica_intacta()


def test_compra_dentro_de_limites_queda_pendiente_de_revision_humana():
    propuesta = {"portafolio_id": "P1", "movimiento": Q100}
    r = correr(
        R6.entrada,
        A0=a0_delega_portafolio(100, "propuesta", propuesta),
        A3=a3_evalua(Q100, es_propuesta=True),
        A4=a4_revisa(Q100, "conforme"),
    )
    resp = r.respuesta
    assert resp.estado == "pendiente_revision_humana"
    assert resp.dictamen.validacion.cumple and resp.dictamen.decision == "conforme"
    assert (resp.metricas["costo"], resp.metricas["peso_xyz_pct"]) == (5000, 15)
    assert "aprobacion_puede_anular" not in resp.metricas
    assert evaluados(r) == TRAYECTORIA_CON_RIESGO


def test_calculo_hipotetico_no_pasa_por_riesgo():
    """Sin guion para A4: si el grafo lo invocara, la prueba fallaría."""
    r = correr(
        R3.entrada,
        A0=a0_delega_portafolio(100, "calculo_hipotetico", escenario="E1"),
        A3=a3_evalua(Q100, es_propuesta=False, simular=True),
    )
    resp = r.respuesta
    assert resp.estado == "calculo_hipotetico" and resp.propuesta is None
    m = resp.metricas
    assert (m["perdida_antes"], m["perdida_despues"], m["diferencia_perdida"]) == (
        1000,
        1500,
        500,
    )
    assert m["total_despues"] == 100000
    (clasificacion,) = controles(r, "clasificar_salida")
    assert clasificacion.resultado["requiere_riesgo"] is False


def test_falla_de_precio_termina_en_datos_insuficientes():
    r = correr(
        R4.entrada,
        fallas=["QERR"],
        A0=[
            pide(
                "consultar_portafolio",
                tarea="Precio de XYZ al corte.",
                empresa="XYZ",
                corte="T0",
            ),
            sintesis("datos_insuficientes"),
        ],
        A3=[
            pide("consultar_precio", empresa="XYZ", fecha_corte="T0"),
            salida_a3(None, es_propuesta=False, suficientes=False),
        ],
    )
    resp = r.respuesta
    assert resp.estado == "datos_insuficientes"
    assert "precio" in resp.metricas and resp.metricas["precio"] is None
    assert resp.error == "PRICE_UNAVAILABLE"
    assert resp.propuesta is None
    (retorno,) = [e for e in r.traza.eventos if e.clase is ClaseEvento.RETORNO]
    assert retorno.resultado["status"] == "datos_insuficientes"
    assert retorno.resultado["error"] == "PRICE_UNAVAILABLE"


# --- La autoridad final es la validación, no A4 ---


def test_a4_que_no_valida_no_libera_la_propuesta():
    r = correr(
        R6.entrada,
        A0=a0_delega_portafolio(
            100, "propuesta", {"portafolio_id": "P1", "movimiento": Q100}
        ),
        A3=a3_evalua(Q100, es_propuesta=True),
        A4=[pide("consultar_politica"), salida_a4("conforme")],
    )
    resp = r.respuesta
    assert resp.estado == "error_controlado"
    assert resp.error == "VALIDATION_MISSING"
    assert resp.propuesta is None


def test_a4_no_puede_anular_un_incumplimiento():
    r = correr(
        R5.entrada,
        A0=a0_delega_portafolio(
            600, "propuesta", {"portafolio_id": "P1", "movimiento": Q600}
        ),
        A3=a3_evalua(Q600, es_propuesta=True),
        A4=a4_revisa(Q600, "conforme"),
    )
    assert r.respuesta.estado == "bloqueada"
    assert r.respuesta.dictamen.decision == "rechazar"
    assert controles(r, "a4_contradice_validacion")


def test_a4_que_valida_otra_cantidad_no_cuenta():
    q500 = {**Q600, "cantidad": 500}
    r = correr(
        R5.entrada,
        A0=a0_delega_portafolio(
            600, "propuesta", {"portafolio_id": "P1", "movimiento": Q600}
        ),
        A3=a3_evalua(Q600, es_propuesta=True),
        A4=a4_revisa(q500, "conforme"),
    )
    assert r.respuesta.estado == "error_controlado"
    assert r.respuesta.error == "VALIDATION_MISSING"
    assert r.respuesta.propuesta is None


def test_devoluciones_acotadas():
    """Dos devoluciones al supervisor; a la tercera petición, datos_insuficientes."""
    veces = LIMITES.devoluciones_revision + 1
    propuesta = {"portafolio_id": "P1", "movimiento": Q100}
    r = correr(
        R6.entrada,
        A0=a0_delega_portafolio(100, "propuesta", propuesta, veces=veces),
        A3=a3_evalua(Q100, es_propuesta=True) * veces,
        A4=a4_revisa(Q100, "requiere_revision") * veces,
    )
    resp = r.respuesta
    assert resp.estado == "datos_insuficientes" and resp.propuesta is None
    revisiones = [
        e
        for e in r.traza.eventos
        if e.clase is ClaseEvento.DELEGACION and e.actor == "grafo"
    ]
    assert len(revisiones) == veces
    # El mismo movimiento conserva la versión; cambiarlo la habría incrementado.
    assert {e.args["version"] for e in revisiones} == {1}


# --- clasificar_salida no se fía solo de la etiqueta del supervisor ---


def test_orden_sin_propuesta_no_sale_como_informativa():
    r = correr(
        "Compra 100 acciones XYZ para P1 al precio de T0.",
        A0=a0_delega_portafolio(100, "informativo"),
        A3=a3_evalua(Q100, es_propuesta=False),
    )
    assert r.respuesta.estado == "datos_insuficientes"
    (clasificacion,) = controles(r, "clasificar_salida")
    assert clasificacion.resultado["senales"] == ["solicitud_de_movimiento"]


def test_propuesta_de_a3_va_a_riesgo_aunque_el_supervisor_no_la_declare():
    """Solo la señal de A3 está activa: la solicitud no tiene verbo de orden.

    Una versión anterior usaba la entrada de R5, que ya activa riesgo por sí
    sola, y no detectaba que se desactivara esta señal (docs/pruebas.md).
    """
    solicitud = "Revisa si tendría sentido sumar 600 XYZ a P1."
    assert not pide_movimiento(solicitud)
    r = correr(
        solicitud,
        A0=a0_delega_portafolio(600, "informativo"),
        A3=a3_evalua(Q600, es_propuesta=True),
        A4=a4_revisa(Q600, "rechazar"),
    )
    (clasificacion,) = controles(r, "clasificar_salida")
    assert clasificacion.resultado["senales"] == ["a3_propone"]
    assert r.respuesta.estado == "bloqueada"
    assert r.respuesta.propuesta.cantidad == 600


def test_deteccion_de_ordenes_en_las_entradas_de_la_clave():
    """Decisión D23: la red de seguridad se activa en R5 y R6, no en R1–R4."""
    assert {r.ruta_id: pide_movimiento(r.entrada) for r in RUTAS} == {
        "R1": False,
        "R2": False,
        "R3": False,
        "R4": False,
        "R5": True,
        "R6": True,
    }


# --- Traza y controles de infraestructura ---


def test_intentos_rechazados_quedan_en_la_traza():
    """LangChain rechazaría estas llamadas antes de ejecutarlas; la Mesa no."""
    r = correr(
        R1.entrada,
        A0=[
            pide(
                "consultar_noticias",
                empresa="XYZ",
                tarea="N1",
                id="N1",
                fecha_corte="T0",
            ),
            sintesis("informativo", evidencia=["N1"]),
        ],
        A1=[
            pide("consultar_precio", empresa="XYZ", fecha_corte="T0"),
            pide("obtener_noticia"),
            pide("obtener_noticia", id="N1"),
            salida_a1(),
        ],
    )
    llamadas = r.traza.de_clase(ClaseEvento.HERRAMIENTA)
    assert [(e.nombre, e.status, e.bloqueado) for e in llamadas] == [
        ("consultar_precio", "error", True),
        ("obtener_noticia", "error", False),
        ("obtener_noticia", "ok", False),
    ]
    assert llamadas[0].resultado["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert llamadas[1].resultado["error"]["code"] == "INVALID_ARGUMENTS"
    assert r.respuesta.estado == "informativo"


def test_delegacion_inexistente_se_bloquea():
    r = correr(
        R1.entrada,
        A0=[
            pide("revisar_riesgo", propuesta=Q100),
            sintesis("datos_insuficientes"),
        ],
    )
    (evento,) = r.traza.de_clase(ClaseEvento.DELEGACION)
    assert evento.bloqueado and evento.nombre == "revisar_riesgo"


def test_salida_fuera_de_esquema_se_repara_una_vez():
    invalida = pide(
        "SalidaNoticias",
        analisis=[{"noticia_id": "N1", "tipo_evento": "subida_de_precio"}],
        hallazgos=[],
        limitaciones=[],
        datos_suficientes=True,
    )
    a0 = [
        pide(
            "consultar_noticias", empresa="XYZ", tarea="N1", id="N1", fecha_corte="T0"
        ),
        sintesis("informativo", evidencia=["N1"]),
    ]
    r = correr(
        R1.entrada, A0=a0, A1=[pide("obtener_noticia", id="N1"), invalida, salida_a1()]
    )
    assert r.respuesta.estado == "informativo"
    (reparacion,) = controles(r, "reparacion_salida")
    assert "subida_de_precio" in reparacion.resultado["error"]

    r = correr(
        R1.entrada,
        A0=list(a0),
        A1=[pide("obtener_noticia", id="N1"), invalida, invalida],
    )
    assert r.respuesta.estado == "error_controlado"
    assert r.respuesta.error == "SCHEMA_INVALID"
    assert len(controles(r, "reparacion_salida")) == 2


def test_limite_de_llamadas_al_modelo():
    r = correr(
        R1.entrada,
        A0=[
            pide(
                "consultar_noticias",
                empresa="XYZ",
                tarea="N1",
                id="N1",
                fecha_corte="T0",
            )
        ],
        A1=[pide("inventada")] * (LIMITES.llamadas_modelo + 5),
    )
    assert r.respuesta.estado == "error_controlado"
    assert r.respuesta.error == "BUDGET_EXCEEDED"
    assert r.presupuesto.llamadas_modelo == LIMITES.llamadas_modelo


def test_quinta_herramienta_de_un_especialista_cierra_el_caso():
    n = LIMITES.herramientas_por_especialista + 1
    r = correr(
        R1.entrada,
        A0=[
            pide(
                "consultar_noticias",
                empresa="XYZ",
                tarea="N1",
                id="N1",
                fecha_corte="T0",
            )
        ],
        A1=[pide("obtener_noticia", id="N1")] * n + [salida_a1()],
    )
    assert r.respuesta.estado == "error_controlado"
    assert r.respuesta.error == "BUDGET_EXCEEDED"
    assert r.traza.de_clase(ClaseEvento.HERRAMIENTA)[-1].bloqueado


def test_un_reintento_registrado_por_fallo_de_transporte():
    caida = openai.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    a0 = [
        pide(
            "consultar_noticias", empresa="XYZ", tarea="N1", id="N1", fecha_corte="T0"
        ),
        sintesis("informativo", evidencia=["N1"]),
    ]
    r = correr(
        R1.entrada, A0=a0, A1=[caida, pide("obtener_noticia", id="N1"), salida_a1()]
    )
    assert r.respuesta.estado == "informativo"
    assert len(controles(r, "reintento_transporte")) == 1

    r = correr(R1.entrada, A0=list(a0), A1=[caida, caida])
    assert r.respuesta.estado == "error_controlado"
    assert r.respuesta.error == "MODEL_UNAVAILABLE"


def test_evidencia_no_observada_se_descarta():
    r = correr(
        R1.entrada,
        A0=[
            pide(
                "consultar_noticias",
                empresa="XYZ",
                tarea="N1",
                id="N1",
                fecha_corte="T0",
            ),
            sintesis("informativo", evidencia=["N1", "N7", "F1"]),
        ],
        A1=[pide("obtener_noticia", id="N1"), salida_a1()],
    )
    assert r.respuesta.evidencia == ["N1"]
    (descarte,) = controles(r, "evidencia_descartada")
    assert descarte.resultado["fuentes"] == ["N7", "F1"]


def test_llamadas_simultaneas_se_registran():
    r = correr(
        R3.entrada,
        A0=a0_delega_portafolio(100, "calculo_hipotetico"),
        A3=[
            pide_varias(
                ("consultar_portafolio", {"id": "P1"}),
                ("consultar_precio", {"empresa": "XYZ", "fecha_corte": "T0"}),
            ),
            pide("calcular_exposicion", portafolio_id="P1", propuesta=Q100),
            salida_a3(Q100, es_propuesta=False),
        ],
    )
    assert controles(r, "llamadas_simultaneas")
    seqs = [e.seq for e in r.traza.de_clase(ClaseEvento.HERRAMIENTA)]
    assert len(seqs) == len(set(seqs)) == 3


def test_cada_caso_empieza_limpio():
    def bloqueo():
        return correr(
            R5.entrada,
            A0=a0_delega_portafolio(
                600, "propuesta", {"portafolio_id": "P1", "movimiento": Q600}
            ),
            A3=a3_evalua(Q600, es_propuesta=True),
            A4=a4_revisa(Q600, "rechazar"),
        )

    primero, segundo = bloqueo(), bloqueo()
    assert primero.run_id != segundo.run_id
    assert segundo.traza.eventos[0].seq == 1
    assert segundo.respuesta.propuesta.version == 1
    assert evaluados(primero) == evaluados(segundo)


# --- Lo que ven los modelos ---


def test_los_prompts_no_contienen_la_clave():
    """Ningún valor esperado de la clave aparece en prompts ni descripciones."""
    prohibidos = set()
    for ruta in RUTAS:
        for valor in ruta.exactos.values():
            if isinstance(valor, str) and len(valor) > 3:
                prohibidos.add(str(valor))
        for cifra in ruta.cifras:
            if abs(cifra.valor) >= 100:
                entero = int(cifra.valor)
                prohibidos |= {str(entero), f"{entero:,}"}
    prohibidos |= {"Q100", "Q600", "T0=", "R1", "R5"}
    textos = list(PROMPTS.values()) + [
        x.descripcion for x in (*HERRAMIENTAS.values(), *DELEGACIONES.values())
    ]
    for texto in textos:
        for valor in prohibidos:
            assert valor not in texto, valor


@pytest.mark.parametrize("agente", ["A0", "A1", "A2", "A3", "A4"])
def test_esquemas_que_ve_el_modelo_se_pueden_enviar(agente):
    from proyecto_multiagente import Caso

    caso = Caso("x", "r", modelo_para=lambda _: None)
    for herramienta in caso._herramientas_para(agente):
        convertida = convert_to_openai_tool(herramienta)
        assert convertida["function"]["name"] == herramienta.name
    salida = convert_to_openai_tool(SALIDAS[agente])
    assert salida["function"]["name"] == SALIDAS[agente].__name__


def test_las_cifras_del_resultado_salen_de_la_traza():
    """Decisión D24: metricas coincide con lo que devolvieron las herramientas."""
    r = correr(
        R3.entrada,
        A0=a0_delega_portafolio(100, "calculo_hipotetico", escenario="E1"),
        A3=a3_evalua(Q100, es_propuesta=False, simular=True),
    )
    (exposicion,) = [
        e
        for e in r.traza.de_clase(ClaseEvento.HERRAMIENTA)
        if e.nombre == "calcular_exposicion"
    ]
    for clave, valor in exposicion.resultado["data"].items():
        if clave != "empresa":
            assert r.respuesta.metricas[clave] == Decimal(str(valor))
