"""La Mesa: permisos, presupuesto, argumentos y traza.

Lo que se prueba aquí es lo que el evaluador va a leer. Si la traza perdiera
un intento bloqueado, o registrara los argumentos después de que alguien los
modificara, la evaluación de trayectoria mediría una historia distinta de la
que ocurrió.
"""

import dataclasses
import json

import pytest

from proyecto_multiagente import (
    HERRAMIENTAS,
    LIMITES,
    Q100,
    ClaseEvento,
    Entorno,
    Mesa,
    Presupuesto,
    Traza,
)


def mesa(**kwargs):
    return Mesa(Entorno(), **kwargs)


# --- Permisos ---


@pytest.mark.parametrize(
    "actor,nombre",
    [
        ("A1", "validar_propuesta"),  # herramienta de otro agente
        ("A0", "consultar_precio"),  # el supervisor no consulta datos
        ("A4", "calcular_exposicion"),
        ("A3", "ejecutar_orden"),  # no existe
        ("A4", "modificar_politica"),  # no existe
    ],
)
def test_fuera_de_catalogo_se_bloquea_y_se_registra(actor, nombre):
    m = mesa()
    r = m.llamar(actor, nombre, {"portafolio_id": "P1", "propuesta": Q100})
    assert r.error.code == "TOOL_NOT_ALLOWED"
    (evento,) = m.traza.eventos
    assert evento.bloqueado and evento.status == "error"
    assert (evento.actor, evento.nombre) == (actor, nombre)
    assert m.presupuesto.herramientas_por_invocacion.total() == 0


# --- Argumentos ---


@pytest.mark.parametrize(
    "args",
    [
        {},  # falta el id
        {"id": "N1", "fecha_corte": "T0"},  # campo de más
        {"id": 1},  # tipo equivocado
    ],
)
def test_argumentos_invalidos(args):
    m = mesa()
    r = m.llamar("A1", "obtener_noticia", args)
    assert r.error.code == "INVALID_ARGUMENTS"
    assert not m.traza.eventos[0].bloqueado


@pytest.mark.parametrize("cantidad", [-1, 0, 2.5, "100"])
def test_cantidad_invalida_en_un_calculo(cantidad):
    r = mesa().llamar(
        "A3",
        "calcular_exposicion",
        {"portafolio_id": "P1", "propuesta": {**Q100, "cantidad": cantidad}},
    )
    assert r.error.code == "INVALID_ARGUMENTS"


def test_venta_en_corto_no_tiene_representacion():
    r = mesa().llamar(
        "A3",
        "calcular_exposicion",
        {"portafolio_id": "P1", "propuesta": {**Q100, "lado": "venta"}},
    )
    assert r.error.code == "INVALID_ARGUMENTS"


# --- Presupuesto ---


def test_quinta_herramienta_de_una_invocacion_agota_el_caso():
    m = mesa()
    limite = LIMITES.herramientas_por_especialista
    for _ in range(limite):
        r = m.llamar("A1", "obtener_noticia", {"id": "N1"}, invocacion="inv-1")
        assert r.status == "ok"
    r = m.llamar("A1", "obtener_noticia", {"id": "N1"}, invocacion="inv-1")
    assert r.error.code == "BUDGET_EXCEEDED" and m.traza.eventos[-1].bloqueado
    assert m.presupuesto.agotado == "BUDGET_EXCEEDED"

    # Agotado un límite, el caso queda cerrado también para otros agentes.
    r = m.llamar("A3", "consultar_portafolio", {"id": "P1"}, invocacion="inv-2")
    assert r.error.code == "BUDGET_EXCEEDED"


def test_argumentos_invalidos_consumen_presupuesto():
    m = mesa()
    m.llamar("A1", "obtener_noticia", {}, invocacion="inv-1")
    assert m.presupuesto.herramientas_por_invocacion["inv-1"] == 1


def test_invocaciones_separadas_tienen_contadores_separados():
    m = mesa()
    for invocacion in ("inv-1", "inv-2"):
        for _ in range(LIMITES.herramientas_por_especialista):
            m.llamar("A1", "obtener_noticia", {"id": "N1"}, invocacion=invocacion)
    assert m.presupuesto.agotado is None


def test_tiempo_por_caso():
    ahora = [0.0]
    presupuesto = Presupuesto(reloj=lambda: ahora[0])
    m = mesa(presupuesto=presupuesto)
    assert m.llamar("A1", "obtener_noticia", {"id": "N1"}).status == "ok"
    ahora[0] = LIMITES.timeout_caso_s + 1
    r = m.llamar("A1", "obtener_noticia", {"id": "N1"})
    assert r.error.code == "TIMEOUT" and presupuesto.agotado == "TIMEOUT"


@pytest.mark.parametrize(
    "consumir,limite",
    [
        ("consumir_invocacion", LIMITES.invocaciones_especialistas),
        ("consumir_llamada_modelo", LIMITES.llamadas_modelo),
    ],
)
def test_limites_del_grafo(consumir, limite):
    presupuesto = Presupuesto()
    for _ in range(limite):
        getattr(presupuesto, consumir)()
    with pytest.raises(Exception, match="Más de"):
        getattr(presupuesto, consumir)()
    assert presupuesto.agotado == "BUDGET_EXCEEDED"


# --- Traza ---


def test_el_evento_se_abre_antes_de_ejecutar(monkeypatch):
    """Si la herramienta revienta, el intento no desaparece de la traza."""

    def revienta(entorno, args):
        raise RuntimeError("falla inesperada")

    rota = dataclasses.replace(HERRAMIENTAS["obtener_noticia"], funcion=revienta)
    monkeypatch.setitem(HERRAMIENTAS, "obtener_noticia", rota)
    m = mesa()
    with pytest.raises(RuntimeError):
        m.llamar("A1", "obtener_noticia", {"id": "N1"})
    (evento,) = m.traza.eventos
    assert evento.status == "en_curso" and evento.fin is None


def test_los_argumentos_se_copian_por_valor():
    m = mesa()
    args = {"portafolio_id": "P1", "propuesta": dict(Q100)}
    m.llamar("A3", "calcular_exposicion", args)
    args["propuesta"]["cantidad"] = 600
    assert m.traza.eventos[0].args["propuesta"]["cantidad"] == 100


def test_la_traza_es_jsonl_con_numeros():
    m = Mesa(Entorno(), traza=Traza(run_id="R3-1"))
    m.llamar("A3", "calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q100})
    m.llamar("A3", "consultar_precio", {"empresa": "XYZ", "fecha_corte": "ayer"})
    lineas = [json.loads(linea) for linea in m.traza.a_jsonl().splitlines()]
    assert [linea["seq"] for linea in lineas] == [1, 2]
    assert all(linea["run_id"] == "R3-1" for linea in lineas)
    assert lineas[0]["resultado"]["data"]["costo"] == 5000
    assert isinstance(lineas[0]["resultado"]["data"]["costo"], float)
    assert lineas[1]["status"] == "error"
    assert lineas[1]["resultado"]["error"]["code"] == "INVALID_ARGUMENTS"
    assert lineas[0]["inicio"] <= lineas[0]["fin"]


def test_solo_herramientas_en_esta_capa():
    m = mesa()
    m.llamar("A1", "obtener_noticia", {"id": "N1"})
    assert m.traza.de_clase(ClaseEvento.HERRAMIENTA) == m.traza.eventos
    assert m.traza.de_clase(ClaseEvento.DELEGACION) == []
