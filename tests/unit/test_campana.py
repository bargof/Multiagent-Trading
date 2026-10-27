"""La campaña del Bloque 5, sin red ni cuota (decisiones D51 a D54).

Los agentes siguen los guiones de referencia de las pruebas sintéticas, y
cada prueba cambia el de alguna ejecución para plantar lo que quiere ver: una
cuota agotada, una excepción, una acción prohibida o un juez sin respuesta.
Así se comprueba qué registra la campaña, qué cuenta, qué repite y dónde se
detiene. Lo que no dice es qué hará el modelo real: eso lo mide la campaña.
"""

import json
from types import SimpleNamespace

import pytest
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import AIMessage

import proyecto_multiagente
from proyecto_multiagente import (
    ESPERA_PROVEEDOR,
    LIMITES,
    MODELO_AGENTES,
    MODELO_JUEZ,
    PRUEBAS_EVALUADOR,
    ClaseEvento,
    CodigoError,
    Configuracion,
    HerramientaError,
    ModeloGuion,
    Presupuesto,
    _Ritmo,
    campanas,
    comparar_con_congelacion,
    congelacion,
    correr_campana,
    main,
    plan_de_campana,
    probar_evaluador,
)
from proyecto_multiagente import pausar_antes_de_reintentar as pausa_real
from tests.gemini_falso import error_de_google, gemini
from tests.guion import guiones, juez_guionado

CONFIG = Configuracion(modelo=MODELO_AGENTES, modelo_juez=MODELO_JUEZ)
PRUEBAS = {(p.ruta.ruta_id, p.nombre): p for p in PRUEBAS_EVALUADOR}
REFERENCIAS = {r: p for (r, nombre), p in PRUEBAS.items() if nombre == "referencia"}


def _cuota():
    return ModelRateLimitError("429 RESOURCE_EXHAUSTED: quota exceeded")


def con_guion(**por_agente):
    """El guion de referencia de una ruta con algunos agentes cambiados."""
    return lambda ruta: {**REFERENCIAS[ruta].guion, **por_agente}


def de_referencia(cambios=None, llamadas=None):
    """modelos_para: la referencia de cada ruta, salvo en las ejecuciones de
    `cambios`, que dan su guion y su juez: {"R3.1": (guion, juez)}."""
    cambios = cambios or {}

    def modelos_para(ruta, repeticion):
        ejecucion = f"{ruta.ruta_id}.{repeticion}"
        if llamadas is not None:
            llamadas.append(ejecucion)
        prueba = REFERENCIAS[ruta.ruta_id]
        guion, juez = cambios.get(ejecucion, (None, None))
        return (
            guiones(**(guion or prueba.guion)),
            juez or juez_guionado(prueba.salida_juez),
        )

    return modelos_para


def correr(modelos_para=None, **opciones):
    return correr_campana(
        CONFIG, modelos_para=modelos_para or de_referencia(), **opciones
    )


def unica():
    (campana,) = campanas(proyecto_multiagente.DIR_CAMPANAS)
    return campana


def por_lugar(campana):
    registros = {}
    for e in campana.ejecuciones():
        registros.setdefault(e.ejecucion, []).append(e)
    return registros


def resultados(campana):
    return json.loads((campana.carpeta / "resultados.json").read_text("utf-8"))


# --- Plan y campaña completa ---


def test_el_plan_va_por_rondas_y_deja_r6_al_final():
    ids = [p["ejecucion"] for p in plan_de_campana()]
    assert ids[:5] == ["R1.1", "R2.1", "R3.1", "R4.1", "R5.1"]
    assert ids[5:10] == ["R1.2", "R2.2", "R3.2", "R4.2", "R5.2"]
    assert ids[15:] == ["R6.1", "R6.2", "R6.3"]
    assert len(ids) == len(set(ids)) == 18


def test_una_campana_completa_con_las_referencias(capsys):
    assert correr() == 0
    campana = unica()
    for archivo in (
        "campana.json",
        "ejecuciones.jsonl",
        "trazas.jsonl",
        "resultados.json",
        "revision.md",
    ):
        assert (campana.carpeta / archivo).is_file(), archivo

    r = resultados(campana)
    assert r["estado"] == "completa" and r["pendientes"] == []
    assert r["obligatorias"] == {
        "planeadas": 15,
        "realizadas": 15,
        "aprobadas": 15,
        "fallidas": 0,
        "no_completadas": 0,
        "errores": 0,
    }
    assert r["complementarias"]["aprobadas"] == r["complementarias"]["planeadas"] == 3
    rutas = {x["ruta"]: x for x in r["rutas"]}
    assert all(x["aprobadas"] == x["realizadas"] == 3 for x in rutas.values())
    assert rutas["R5"]["control"] == {"bloqueadas": 3, "liberadas": 0}
    # El piso de D50: 123 llamadas a los agentes y 6 al juez.
    assert r["uso"]["agentes"]["llamadas"] == 123
    assert r["uso"]["juez"]["llamadas"] == 6

    salida = capsys.readouterr().out
    assert "Obligatorias: 15 de 15 aprobadas" in salida
    for ruta in ("R1", "R2", "R3", "R4", "R5", "R6"):
        assert f"  {ruta}.3 " in salida

    # resultados.json es exactamente lo que se recalcula de los registros.
    sin_fecha = {k: v for k, v in campana.resumen().items() if k != "generado"}
    assert sin_fecha == {k: v for k, v in r.items() if k != "generado"}


def test_cada_ejecucion_empieza_limpia():
    correr()
    campana = unica()
    run_ids = [e.run_id for e in campana.ejecuciones()]
    assert len(run_ids) == len(set(run_ids)) == 18

    eventos = {}
    lineas = (campana.carpeta / "trazas.jsonl").read_text("utf-8").splitlines()
    for linea in lineas:
        evento = json.loads(linea)
        eventos.setdefault(evento["run_id"], []).append(evento)
    assert set(eventos) == set(run_ids)
    for lista in eventos.values():
        assert [e["seq"] for e in lista] == list(range(1, len(lista) + 1))
        assert lista[0]["nombre"] == "iniciar"


def test_el_registro_dice_que_no_hay_cache_ni_key():
    with pytest.MonkeyPatch.context() as entorno:
        entorno.setenv("GOOGLE_API_KEY", "AIza-secreta-de-prueba")
        correr(maximo=2)
    campana = unica()
    assert campana.meta["cache"] is False
    for archivo in campana.carpeta.iterdir():
        assert "AIza-secreta" not in archivo.read_text("utf-8"), archivo.name


# --- Cuota, excepciones e interrupciones ---


def test_la_cuota_agotada_detiene_y_la_campana_sigue_donde_quedo(capsys):
    sin_cuota = {"R3.1": (con_guion(A3=[_cuota(), _cuota()])("R3"), None)}
    assert correr(de_referencia(sin_cuota)) == 2
    campana = unica()
    assert [(e.ejecucion, e.estado) for e in campana.ejecuciones()] == [
        ("R1.1", "evaluada"),
        ("R2.1", "evaluada"),
        ("R3.1", "interrumpida"),
    ]
    salida = capsys.readouterr().out
    assert "El modelo de los agentes no respondió" in salida
    assert "baja GEMINI_RPM" in salida

    llamadas = []
    assert correr(de_referencia(llamadas=llamadas)) == 0
    assert unica().carpeta == campana.carpeta
    # Las terminadas no se vuelven a correr; la interrumpida sí.
    assert llamadas[0] == "R3.1" and "R1.1" not in llamadas and "R2.1" not in llamadas
    registros = por_lugar(campana)
    assert [e.estado for e in registros["R3.1"]] == ["interrumpida", "evaluada"]
    assert all(len(v) == 1 for k, v in registros.items() if k != "R3.1")

    r = resultados(campana)
    assert r["obligatorias"]["aprobadas"] == 15
    # La interrumpida gastó cuota: A0 delegó y A3 lo intentó dos veces.
    assert r["uso"]["agentes"]["llamadas"] == 123 + 3
    (interrumpida,) = r["interrumpidas"]
    assert interrumpida["ejecucion"] == "R3.1"
    assert "RESOURCE_EXHAUSTED" in interrumpida["motivo"]


def test_una_accion_prohibida_antes_del_corte_cuenta():
    prohibida = PRUEBAS[("R5", "validacion_tras_accion_prohibida")].guion
    guion = {**prohibida, "A3": [*prohibida["A3"][:4], _cuota(), _cuota()]}
    assert correr(de_referencia({"R5.1": (guion, None)})) == 2
    (r51,) = por_lugar(unica())["R5.1"]
    assert r51.estado == "evaluada" and r51.veredicto == "fallida"
    assert r51.evaluacion.prohibidas
    assert r51.respuesta["error"] == CodigoError.MODEL_UNAVAILABLE

    assert correr() == 0
    assert len(por_lugar(unica())["R5.1"]) == 1  # no se repite


def test_sin_cuota_del_juez_el_juicio_queda_sin_completar_y_se_detiene():
    juez = ModeloGuion(respuestas=[_cuota(), _cuota()])
    assert correr(de_referencia({"R1.1": (None, juez)})) == 2
    (r11,) = por_lugar(unica())["R1.1"]
    assert r11.estado == "evaluada" and r11.veredicto == "no_completada"
    assert r11.evaluacion.resultado.juicio.proveedor_no_respondio

    assert correr() == 0
    revision = (unica().carpeta / "revision.md").read_text("utf-8")
    assert "Juicio sin completar: El juez no respondió" in revision
    r = resultados(unica())
    assert r["obligatorias"]["aprobadas"] == 14
    assert r["obligatorias"]["no_completadas"] == 1


def test_una_excepcion_cuenta_como_error_y_no_se_repite():
    falla = {"R2.1": (con_guion(A1=[ValueError("respuesta imposible")])("R2"), None)}
    assert correr(de_referencia(falla)) == 2
    campana = unica()
    (r21,) = por_lugar(campana)["R2.1"]
    assert r21.estado == "error" and r21.veredicto == "error"
    assert r21.motivo == "ValueError: respuesta imposible"
    # El traceback guarda los marcos más profundos: el que lanzó la excepción.
    assert r21.detalle.startswith("Traceback")
    assert "in _generate" in r21.detalle
    assert "ValueError: respuesta imposible" in r21.detalle
    # La traza parcial se conserva: llegó a delegar en A1.
    assert any("A0→A1" in paso for paso in r21.trayectoria_obtenida)
    assert r21.run_id in (campana.carpeta / "trazas.jsonl").read_text("utf-8")

    assert correr() == 0
    r = resultados(campana)
    assert r["obligatorias"]["errores"] == 1 and r["obligatorias"]["aprobadas"] == 14
    assert {x["ruta"]: x["peor"] for x in r["rutas"]}["R2"] == "R2.1"


def test_un_ctrl_c_interrumpe_y_su_lugar_se_repite(monkeypatch):
    original, veces = proyecto_multiagente.ejecutar_caso, []

    def corta_la_segunda(*args, **kwargs):
        # Las pruebas sintéticas que corren antes de la campaña no cuentan.
        if not kwargs["run_id"].startswith("sintetica"):
            veces.append(1)
            if len(veces) == 2:
                raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(proyecto_multiagente, "ejecutar_caso", corta_la_segunda)
    assert correr() == 2
    monkeypatch.setattr(proyecto_multiagente, "ejecutar_caso", original)
    (r21,) = por_lugar(unica())["R2.1"]
    assert r21.estado == "interrumpida" and "Ctrl+C" in r21.motivo

    assert correr() == 0
    assert [e.estado for e in por_lugar(unica())["R2.1"]] == [
        "interrumpida",
        "evaluada",
    ]


# --- Cuándo se sigue una campaña ---


def test_ejecuciones_limita_y_la_siguiente_vez_sigue(capsys):
    assert correr(maximo=4) == 2
    assert len(unica().ejecuciones()) == 4
    assert "Quedan 14 ejecuciones" in capsys.readouterr().out
    assert correr() == 0
    assert len(unica().ejecuciones()) == 18


def test_si_cambia_el_codigo_empieza_otra_y_la_anterior_se_conserva(monkeypatch):
    correr(maximo=2)
    (anterior,) = campanas(proyecto_multiagente.DIR_CAMPANAS)
    monkeypatch.setattr(proyecto_multiagente, "huella_archivo", lambda: "otro")
    correr(maximo=1)
    assert len(campanas(proyecto_multiagente.DIR_CAMPANAS)) == 2
    assert len(anterior.ejecuciones()) == 2


def test_otro_modelo_es_otra_campana():
    correr(maximo=1)
    correr_campana(
        Configuracion(modelo="gemini-otro", modelo_juez=MODELO_JUEZ),
        modelos_para=de_referencia(),
        maximo=1,
    )
    assert len(campanas(proyecto_multiagente.DIR_CAMPANAS)) == 2


def test_nueva_campana_no_sigue_la_anterior():
    correr(maximo=1)
    correr(maximo=1, nueva=True)
    assert len(campanas(proyecto_multiagente.DIR_CAMPANAS)) == 2


def test_sin_pruebas_sinteticas_no_se_corre_nada(monkeypatch, capsys):
    pruebas = probar_evaluador()
    pruebas[0] = SimpleNamespace(**{**vars(pruebas[0]), "como_se_esperaba": False})
    monkeypatch.setattr(proyecto_multiagente, "probar_evaluador", lambda: pruebas)
    monkeypatch.setattr(
        proyecto_multiagente, "imprimir_pruebas_evaluador", lambda _: None
    )
    llamadas = []
    assert correr(de_referencia(llamadas=llamadas)) == 1
    assert llamadas == [] and campanas(proyecto_multiagente.DIR_CAMPANAS) == []
    assert "no se corre la campaña" in capsys.readouterr().out


# --- Resultados ---


def test_la_peor_ejecucion_y_su_primer_paso_divergente(capsys):
    cambios = {
        "R4.2": (PRUEBAS[("R4", "dos_reintentos")].guion, None),
        "R5.2": (PRUEBAS[("R5", "validacion_tras_accion_prohibida")].guion, None),
        "R5.3": (PRUEBAS[("R5", "argumento_equivocado")].guion, None),
    }
    assert correr(de_referencia(cambios)) == 0
    rutas = {x["ruta"]: x for x in resultados(unica())["rutas"]}
    assert (rutas["R4"]["aprobadas"], rutas["R4"]["peor"]) == (2, "R4.2")
    # Una acción prohibida es peor que una trayectoria equivocada.
    assert (rutas["R5"]["aprobadas"], rutas["R5"]["peor"]) == (1, "R5.2")
    # El intento se bloqueó: R5 no liberó nada, aunque la ejecución reprueba.
    assert rutas["R5"]["control"] == {"bloqueadas": 3, "liberadas": 0}
    filas = {f["ejecucion"]: f for f in rutas["R4"]["ejecuciones"]}
    assert filas["R4.2"]["primer_paso_divergente"]["plano"] == "trayectoria"
    assert filas["R4.1"]["primer_paso_divergente"] is None

    salida = capsys.readouterr().out
    assert "R4.2 fallida" in salida and "primer paso divergente" in salida
    assert "Obligatorias: 12 de 15 aprobadas · fallidas 3" in salida


def test_la_revision_humana_tiene_un_lugar_por_ejecucion():
    cambios = {"R4.2": (PRUEBAS[("R4", "dos_reintentos")].guion, None)}
    correr(de_referencia(cambios))
    revision = (unica().carpeta / "revision.md").read_text("utf-8")
    for ruta in ("R1", "R2", "R3", "R4", "R5", "R6"):
        for n in (1, 2, 3):
            assert f"### {ruta}.{n} · " in revision
    assert revision.count("[ ] de acuerdo  [ ] en desacuerdo") == 18  # R1 y R2
    assert revision.count("Bloquea sin liberar la propuesta") == 3  # R5
    assert revision.count("Primer paso divergente") == 1
    assert "- Causa probable:" in revision


def test_la_comparacion_con_la_congelacion():
    assert comparar_con_congelacion(CONFIG)["estado"] == "sin_congelacion"
    registro = congelacion(CONFIG, probar_evaluador())
    ruta = proyecto_multiagente.RUTA_CONGELACION
    ruta.write_text(json.dumps(registro), encoding="utf-8")
    assert comparar_con_congelacion(CONFIG) == {
        "estado": "coincide",
        "difieren": [],
        "fecha": registro["fecha"],
    }
    correr(maximo=1)
    assert unica().meta["congelacion"]["estado"] == "coincide"

    registro["huellas"]["expectativas"] = "cambiada"
    registro["archivo_sha256"] = "otro"
    ruta.write_text(json.dumps(registro), encoding="utf-8")
    comparacion = comparar_con_congelacion(CONFIG)
    assert comparacion["estado"] == "difiere"
    assert comparacion["difieren"] == ["expectativas", "archivo"]


# --- Por el cliente de Gemini ---


def _por_gemini(cambiar_a1=(), juez_contesta=None):
    """modelos_para con el cliente falso de Gemini: la conversión real de
    langchain-google-genai, también la de sus errores."""

    def modelos_para(ruta, _repeticion):
        prueba = REFERENCIAS[ruta.ruta_id]
        guion = dict(prueba.guion)
        if "A1" in guion:
            guion["A1"] = [*cambiar_a1, *guion["A1"]]
        modelos = {a: gemini(MODELO_AGENTES, turnos) for a, turnos in guion.items()}
        juez = gemini(
            MODELO_JUEZ, juez_contesta or [AIMessage(content=prueba.salida_juez)]
        )
        return (lambda agente: modelos[agente]), juez

    return modelos_para


def test_un_429_de_google_se_reconoce_como_cuota():
    cuota = [error_de_google(429, "RESOURCE_EXHAUSTED")] * 2
    assert correr(_por_gemini(cambiar_a1=cuota)) == 2
    campana = unica()
    (r11,) = campana.ejecuciones()
    assert r11.estado == "interrumpida" and "RESOURCE_EXHAUSTED" in r11.motivo
    for archivo in campana.carpeta.iterdir():
        assert "AIza" not in archivo.read_text("utf-8"), archivo.name


@pytest.mark.parametrize(
    "codigo,estado", [(429, "RESOURCE_EXHAUSTED"), (503, "UNAVAILABLE")]
)
def test_si_google_no_responde_al_juez_se_detiene(codigo, estado):
    sin_respuesta = [error_de_google(codigo, estado)] * 2
    assert correr(_por_gemini(juez_contesta=sin_respuesta)) == 2
    (r11,) = unica().ejecuciones()
    assert r11.veredicto == "no_completada"
    assert r11.evaluacion.resultado.juicio.proveedor_no_respondio


def test_un_503_de_google_interrumpe_como_la_cuota(capsys):
    """Decisión D55: un modelo saturado no mide al sistema. Se conserva, no
    cuenta, la campaña se detiene y al seguir se repite."""
    saturado = [error_de_google(503, "UNAVAILABLE")] * 2
    assert correr(_por_gemini(cambiar_a1=saturado)) == 2
    (r11,) = unica().ejecuciones()
    assert r11.estado == "interrumpida" and "UNAVAILABLE" in r11.motivo
    assert r11.respuesta["error"] == CodigoError.MODEL_UNAVAILABLE
    assert "Un 503 es saturación" in capsys.readouterr().out


def test_la_traza_guarda_la_version_y_el_fin_de_cada_turno():
    correr(_por_gemini(), maximo=1)
    lineas = (unica().carpeta / "trazas.jsonl").read_text("utf-8").splitlines()
    turnos = [
        json.loads(x)["resultado"]
        for x in lineas
        if json.loads(x)["clase"] == ClaseEvento.MODELO
    ]
    assert turnos
    assert {(t["modelo_respuesta"], t["fin"]) for t in turnos} == {
        (MODELO_AGENTES, "STOP")
    }


# --- La espera al proveedor no cuenta como trabajo (D53) ---


@pytest.fixture
def reloj_falso(monkeypatch):
    ahora = [1000.0]
    monkeypatch.setattr(ESPERA_PROVEEDOR, "segundos", 0.0)
    monkeypatch.setattr(
        proyecto_multiagente,
        "time",
        SimpleNamespace(
            monotonic=lambda: ahora[0],
            sleep=lambda s: ahora.__setitem__(0, ahora[0] + s),
        ),
    )
    return ahora


def test_el_tiempo_del_caso_descuenta_la_espera_al_proveedor(reloj_falso):
    presupuesto = Presupuesto()
    reloj_falso[0] += 250
    ESPERA_PROVEEDOR.sumar(200)
    presupuesto.verificar()  # 250 s de reloj, 50 s de trabajo
    reloj_falso[0] += LIMITES.timeout_caso_s
    with pytest.raises(HerramientaError) as error:
        presupuesto.verificar()
    assert error.value.code == CodigoError.TIMEOUT


def test_la_pausa_antes_del_reintento_es_espera(reloj_falso):
    pausa_real()
    assert ESPERA_PROVEEDOR.segundos == LIMITES.pausa_reintento_s


def test_el_ritmo_anota_lo_que_espera(monkeypatch):
    monkeypatch.setattr(ESPERA_PROVEEDOR, "segundos", 0.0)
    ritmo = _Ritmo(requests_per_second=20, check_every_n_seconds=0.01)
    ritmo.acquire()
    ritmo.acquire()
    # Empieza sin turnos: dos llamadas a 20 por segundo esperan ~0.1 s.
    assert ESPERA_PROVEEDOR.segundos >= 0.08


# --- Línea de comandos ---


def test_sin_opciones_y_sin_key_no_se_corre_nada(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["proyecto_multiagente.py"])
    assert main() == 1
    assert "Falta GOOGLE_API_KEY" in capsys.readouterr().out
    assert campanas(proyecto_multiagente.DIR_CAMPANAS) == []


def test_congelar_no_borra_la_congelacion_anterior(monkeypatch):
    """Una campaña ya corrida depende de su congelación: se conserva."""
    ruta = proyecto_multiagente.RUTA_CONGELACION
    anterior = {"fecha": "2026-10-27T14:20:31-06:00", "huellas": {"datos": "x"}}
    ruta.write_text(json.dumps(anterior), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["proyecto_multiagente.py", "--congelar"])
    assert main() == 0
    guardada = ruta.with_name("congelacion-2026-10-27T142031.json")
    assert json.loads(guardada.read_text("utf-8")) == anterior
    assert json.loads(ruta.read_text("utf-8"))["huellas"]["datos"] != "x"
    assert main() == 0  # una segunda vez no pisa a la primera guardada
    assert len(list(ruta.parent.glob("congelacion-*.json"))) == 2


def test_tabla_lee_la_campana_sin_escribir(monkeypatch, capsys):
    correr(maximo=3)
    campana = unica()
    antes = {a.name: a.read_bytes() for a in campana.carpeta.iterdir()}
    capsys.readouterr()

    monkeypatch.setattr("sys.argv", ["proyecto_multiagente.py", "--tabla"])
    assert main() == 0
    salida = capsys.readouterr().out
    assert f"Campaña {campana.id} · incompleta" in salida
    assert "Pendientes: R4.1" in salida
    assert {a.name: a.read_bytes() for a in campana.carpeta.iterdir()} == antes

    monkeypatch.setattr("sys.argv", ["proyecto_multiagente.py", "--tabla", "no-existe"])
    assert main() == 1
