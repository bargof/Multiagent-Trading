"""Bloque 8: estrategia, backtest, rebalanceo, calendario, A2, A3 y monitor.

Igual que test_comite: sin red ni cuota. Los precios son sintéticos salvo en
la prueba del protocolo, que usa el historial del reto que va en el repo.
"""

import json
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import proyecto_multiagente as pm
from comite import (
    backtest,
    cartera,
    config,
    db,
    ejecucion,
    escenarios,
    estrategia,
    finanzas,
    fuentes,
    mercado,
    monitor,
    puente,
    recomendador,
    vigia,
)
from tests.app.test_comite import (
    ESTRATEGIA,
    HOY,
    LECTORES,
    _guion_compra,
    _tabla_precios,
    _titulares,
)


@pytest.fixture
def base(tmp_path):
    conexion = db.conectar(tmp_path / "comite.db")
    mercado.importar_reto(conexion, _tabla_precios())
    inicio = (HOY - timedelta(days=50)).date().isoformat()
    cartera.cargar_posiciones(
        conexion,
        inicio,
        [
            {"emisora": "WALMEX.MX", "cantidad": 1000, "precio": 50.0},
            {"emisora": "AAPL", "cantidad": 60, "precio": 3600.0},
        ],
        efectivo_actual=500_000.0,
    )
    return conexion


def _tendencias(n: int = 260) -> pd.DataFrame:
    """Diez emisoras que suben a ritmos distintos, una que baja y un ETF
    apalancado que sube más que todas."""
    fechas = pd.bdate_range(end="2026-10-23", periods=n)
    datos = {
        f"S{i}.MX": [50 * (1 + 0.001 * i) ** k for k in range(n)] for i in range(10)
    }
    datos["BAJA.MX"] = [100 * 0.999**k for k in range(n)]
    datos["TQQQ"] = [50 * 1.01**k for k in range(n)]
    return pd.DataFrame(datos, index=fechas)


# ═══════════════════════════════════════════
# Estrategia
# ═══════════════════════════════════════════


def test_la_estrategia_toma_las_mejores_y_deja_el_resto_en_efectivo():
    e = estrategia.POR_NOMBRE["momentum_120_top15_tendencia"]
    meta = estrategia.objetivo(_tendencias(), e)
    # S0 no sube (momentum 0), BAJA está bajo su media, TQQQ está excluido:
    # solo 9 de 15 lugares se llenan y 6/15 queda en efectivo.
    assert set(meta) == {f"S{i}.MX" for i in range(1, 10)}
    assert sum(meta.values()) == pytest.approx(9 / 15)


def test_sin_filtro_de_tendencia_entra_la_que_baja_si_hay_lugar():
    e = estrategia.Estrategia("x", "", top=12, ventana=120, rebalanceo=60)
    meta = estrategia.objetivo(_tendencias(), e)
    assert "BAJA.MX" in meta and "TQQQ" not in meta


def test_el_backtest_no_ve_el_cierre_del_dia_en_que_opera():
    fechas = pd.bdate_range("2025-01-01", periods=30)
    precios = pd.DataFrame({"A.MX": [100.0] * 30, "B.MX": [100.0] * 30}, index=fechas)
    # B salta el día 21: si la señal lo viera, compraría B ese mismo día.
    precios.loc[fechas[21] :, "B.MX"] = 200.0
    e = estrategia.Estrategia("x", "", top=1, ventana=20, rebalanceo=1)
    sim = backtest.simular(precios, e, inicio=21, costo_pct=0)
    assert sim.pesos[fechas[21]] == {"A.MX": 1.0}  # empate: el primero
    assert sim.pesos[fechas[22]] == {"B.MX": 1.0}


def test_el_costo_reduce_el_valor():
    precios = _tendencias()
    e = estrategia.POR_NOMBRE["momentum_60_top10_tendencia"]
    sin = backtest.simular(precios, e, 201, costo_pct=0).valor.iloc[-1]
    con = backtest.simular(precios, e, 201, costo_pct=1).valor.iloc[-1]
    assert con < sin


def test_el_criterio_de_d71_elige_por_rendimiento_entre_caida():
    tabla = pd.DataFrame(
        [
            ("a", "entrenamiento", 2.0, 10, True),
            ("b", "entrenamiento", 3.0, 50, True),
            ("c", "entrenamiento", 3.0, 20, True),
            ("ref", "entrenamiento", 9.0, 0, False),
            ("a", "prueba", 9.0, 10, True),
        ],
        columns=["estrategia", "periodo", "anual_entre_caida", "ordenes", "candidata"],
    )
    assert backtest.elegir(tabla) == "c"


def test_la_eleccion_del_protocolo_es_la_que_dice_la_configuracion(tmp_path):
    """Con el historial del repo, el criterio de D71 elige lo que dice config."""
    conn = db.conectar(tmp_path / "reto.db")
    mercado.importar_reto(conn, mercado.leer_historia(tmp_path / "no-hay.xlsx"))
    comparacion = backtest.comparar(*backtest.cargar(conn))
    assert comparacion.elegida == config.ESTRATEGIA_PROTOCOLO
    assert comparacion.inicio == pd.Timestamp("2024-10-10")
    # Las del SIC entran: sin tipo de cambio quedarían fuera.
    elegidas = {
        e
        for pesos in comparacion.simulaciones[comparacion.elegida].pesos.values()
        for e in pesos
    }
    assert any(not e.endswith(".MX") for e in elegidas)


def test_sin_tipo_de_cambio_el_backtest_no_corre(tmp_path):
    conn = db.conectar(tmp_path / "sin_fx.db")
    tabla = _tabla_precios().drop(columns=[config.TIPO_CAMBIO])
    mercado.importar_reto(conn, tabla)
    with pytest.raises(ValueError, match="USDMXN"):
        backtest.cargar(conn)


# ═══════════════════════════════════════════
# Rebalanceo en la app
# ═══════════════════════════════════════════


def test_rebalanceo_vende_lo_que_sobra_y_compra_el_objetivo(base):
    estrategia.elegir(base, ESTRATEGIA)
    situaciones = vigia.detectar(base)
    por_tipo = {(s.tipo, s.emisora): s for s in situaciones}
    # Solo CAT sube y está en tendencia: WALMEX y AAPL salen completas.
    assert por_tipo[("salida", "WALMEX.MX")].datos["cantidad_sugerida"] == 1000
    assert por_tipo[("salida", "AAPL")].datos["vender_todo"]
    compra = por_tipo[("oportunidad", "CAT")]
    total = cartera.estado(base).total
    precio = compra.datos["precio"]
    assert compra.datos["cantidad_sugerida"] == int(0.1 * total // precio)
    assert vigia.guardar(base, situaciones) == len(situaciones)
    assert vigia.guardar(base, vigia.detectar(base)) == 0


def test_las_ordenes_del_ciclo_no_cambian_con_el_precio(base):
    estrategia.elegir(base, ESTRATEGIA)
    vigia.detectar(base)
    antes = db.leer_parametro(base, "ciclo")
    base.execute(
        "UPDATE precios SET cierre = cierre * 1.05 WHERE emisora = 'CAT' AND fecha = ?",
        (HOY.date().isoformat(),),
    )
    vigia.detectar(base)
    assert db.leer_parametro(base, "ciclo")["ordenes"] == antes["ordenes"]


def test_la_venta_del_rebalanceo_es_de_regla_y_se_ejecuta(base):
    estrategia.elegir(base, ESTRATEGIA)
    vigia.guardar(base, vigia.detectar(base))
    sit = next(s for s in vigia.abiertas(base) if s["tipo"] == "salida")
    assert recomendador.solicitud_para(base, sit) is None
    rec = recomendador.por_regla(base, sit)
    assert (rec["accion"], rec["origen"], rec["estado"]) == (
        "vender",
        "regla",
        "propuesta",
    )
    boleta = ejecucion.aprobar(base, recomendador.guardar(base, rec))
    assert boleta.operacion == "VENTA"


def test_sin_efectivo_la_compra_espera_a_que_registres_las_ventas(base):
    cartera.registrar(
        base,
        fecha=HOY.date().isoformat(),
        lado="retiro",
        emisora=None,
        cantidad=None,
        precio=None,
        monto=499_000,
    )
    estrategia.elegir(base, ESTRATEGIA)
    tipos = {(s.tipo, s.emisora) for s in vigia.detectar(base)}
    assert ("salida", "AAPL") in tipos and ("oportunidad", "CAT") not in tipos
    cartera.registrar(
        base,
        fecha=HOY.date().isoformat(),
        lado="venta",
        emisora="AAPL",
        cantidad=60,
        precio=3600,
        monto=216_000,
    )
    tipos = {(s.tipo, s.emisora) for s in vigia.detectar(base)}
    assert ("oportunidad", "CAT") in tipos


def test_cambiar_de_estrategia_descarta_lo_pendiente(base):
    estrategia.elegir(base, ESTRATEGIA)
    vigia.guardar(base, vigia.detectar(base))
    estrategia.elegir(base, None)
    abiertas = {s["tipo"] for s in vigia.abiertas(base)}
    assert not abiertas & {"oportunidad", "salida"}
    assert estrategia.vigente(base) is None


# ═══════════════════════════════════════════
# A2: reporte completo y nota de indicadores
# ═══════════════════════════════════════════


# Trimestres relativos a hoy, para que la prueba no caduque.
_FIN = pd.Timestamp(HOY.date()) - pd.offsets.QuarterEnd(1)
_TRIMESTRES = [(_FIN - pd.offsets.QuarterEnd(i)).date().isoformat() for i in range(5)]
PERIODO = fuentes.periodo_de(_TRIMESTRES[0])


def _estados_completos(emisora: str) -> dict:
    trimestres = {}
    for i, fin in enumerate(_TRIMESTRES[:4]):
        trimestres[fin] = {
            "ingresos": 1000e6 - i * 10e6,
            "utilidad_bruta": 300e6,
            "utilidad_operativa": 150e6,
            "ebitda": 200e6,
            "utilidad_neta": 100e6,
            "efectivo": 500e6,
            "deuda_total": 1300e6,
            "capital_contable": 2000e6,
            "flujo_operativo": 180e6,
            "capex": -60e6,
        }
    trimestres[_TRIMESTRES[4]] = {
        "ingresos": 900e6,
        "utilidad_operativa": 160e6,
        "utilidad_neta": 110e6,
        "utilidad_bruta": 260e6,
    }
    return {
        "moneda": "MXN",
        "trimestres": trimestres,
        "valuacion": {"per": 15.0, "precio_valor_libros": 2.5, "dividendo_pct": 3.1},
    }


def test_indicadores_y_nota_para_a2():
    r = fuentes.reporte_desde_estados("X.MX", _estados_completos("X.MX"), HOY)
    ind = r["indicadores"]
    assert ind["flujo_libre"] == 120  # 180 − 60, en millones
    assert ind["deuda_neta"] == 800
    assert ind["ebitda_12m"] == 800
    assert ind["deuda_neta_entre_ebitda_12m"] == 1.0
    assert ind["rendimiento_sobre_capital_pct"] == 20.0
    texto = finanzas.nota(r)
    assert "Margen bruto: 30.00% contra 28.89% (+1.11 puntos porcentuales)" in texto
    assert "precio entre utilidad 15.00 veces" in texto
    assert "capex" in r["partidas"] and "deuda_total" in r["partidas"]


def test_una_variacion_atipica_se_marca():
    estados = _estados_completos("X.MX")
    estados["trimestres"][_TRIMESTRES[4]]["utilidad_neta"] = 1e6
    texto = finanzas.nota(fuentes.reporte_desde_estados("X.MX", estados, HOY))
    assert "Es atípica" in texto


def test_alertas_del_reporte():
    estados = _estados_completos("X.MX")
    actual = estados["trimestres"][_TRIMESTRES[0]]
    actual.update(ingresos=800e6, utilidad_operativa=100e6, capex=-400e6)
    r = fuentes.reporte_desde_estados("X.MX", estados, HOY)
    alertas = finanzas.alertas(r)
    assert any(a.startswith("Caen ingresos") for a in alertas)
    assert any("Flujo libre negativo" in a for a in alertas)
    assert finanzas.deterioro_operativo(r)


def test_a2_lee_la_nota_dentro_de_su_limite_de_herramientas(base):
    fuentes.actualizar_reportes(base, ["WALMEX.MX"], _estados_completos)
    vigia.guardar(base, vigia.detectar(base))
    sit = next(s for s in vigia.abiertas(base) if s["tipo"] == "reporte")
    solicitud, foco = recomendador.solicitud_para(base, sit)
    assert finanzas.NOTA in solicitud
    doc = f"F-WALMEX-{PERIODO}"
    guion = pm.guiones(
        A0=[
            pm.pide(
                "consultar_finanzas",
                empresa="WALMEX",
                tarea="Analiza el reporte y su nota de indicadores.",
                periodo=PERIODO,
                reporte=doc,
                fecha_corte="T0",
            ),
            pm.sintesis("informativo", evidencia=[doc], resumen="Análisis."),
        ],
        A2=[
            pm.pide("obtener_reporte", empresa="WALMEX", periodo=PERIODO),
            pm.pide("calcular_indicadores", datos_id=doc),
            pm.pide("consultar_nota", reporte_id=doc, seccion=finanzas.NOTA),
            pm.salida_a2(),
        ],
    )
    consulta = puente.consultar(
        base, solicitud, foco, origen="vigia", modelo_para=guion
    )
    assert consulta.respuesta.estado is pm.EstadoFinal.INFORMATIVO
    pasos = [
        json.loads(linea) for linea in consulta.resultado.traza.a_jsonl().splitlines()
    ]
    vistos = [(p["actor"], p["nombre"], p["status"]) for p in pasos]
    assert ("A2", "consultar_nota", "ok") in vistos, vistos


def test_no_compra_si_el_reporte_muestra_deterioro(base):
    estados = _estados_completos("CAT")
    estados["trimestres"][_TRIMESTRES[0]].update(
        ingresos=800e6, utilidad_operativa=100e6
    )
    fuentes.actualizar_reportes(base, ["CAT"], lambda e: estados)
    fuentes.actualizar_noticias(base, ["CAT"], _titulares, lambda e: None)
    estrategia.elegir(base, ESTRATEGIA)
    vigia.guardar(base, vigia.detectar(base))
    sit = next(s for s in vigia.abiertas(base) if s["tipo"] == "oportunidad")
    q = db.de_json(sit["datos"])["cantidad_sugerida"]
    solicitud, foco = recomendador.solicitud_para(base, sit)
    assert f"F-CAT-{PERIODO}" in solicitud
    consulta = puente.consultar(
        base, solicitud, foco, origen="vigia", modelo_para=_guion_compra(q)
    )
    rec = recomendador.desde_comite(base, sit, consulta)
    assert rec["accion"] == "vigilar" and "caen ingresos" in rec["razon"]


# ═══════════════════════════════════════════
# Calendario
# ═══════════════════════════════════════════


def test_calendario_avisa_antes_del_reporte(base):
    manana = (HOY + timedelta(days=1)).date().isoformat()
    lejos = (HOY + timedelta(days=30)).date().isoformat()
    fechas = {"WALMEX.MX": manana, "AAPL": lejos}
    fuentes.actualizar_calendario(base, ["WALMEX.MX", "AAPL"], fechas.get)
    vigia.guardar(base, vigia.detectar(base))
    cal = [s for s in vigia.abiertas(base) if s["tipo"] == "calendario"]
    assert [s["emisora"] for s in cal] == ["WALMEX.MX"]
    rec = recomendador.por_regla(base, cal[0])
    assert rec["accion"] == "vigilar" and manana in rec["razon"]


def test_una_lectura_que_no_responde_no_detiene_nada():
    import threading

    detenido = threading.Event()
    with pytest.raises(TimeoutError):
        fuentes.con_limite(detenido.wait, 5, segundos=0.1)


# ═══════════════════════════════════════════
# Base y monitor
# ═══════════════════════════════════════════


def test_una_base_del_bloque_7_se_migra_sin_perder_situaciones(tmp_path):
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    esquema = (
        db.ESQUEMA.replace(
            "'oportunidad', 'salida',\n                      'calendario'",
            "'oportunidad'",
        )
        .replace(",\n    proximo_reporte TEXT", "")
        .replace(
            "CREATE TABLE IF NOT EXISTS parametros", "CREATE TABLE IF NOT EXISTS p"
        )
    )
    assert "'salida'" not in esquema and "proximo_reporte" not in esquema
    vieja.executescript(esquema)
    vieja.execute(
        "INSERT INTO situaciones (clave, detectada, en_portafolio, tipo, severidad, "
        "titulo, detalle) VALUES ('x', '2026-10-28', 1, 'precio', 'alta', 't', 'd')"
    )
    vieja.commit()
    vieja.close()
    conn = db.conectar(ruta)
    assert db.fila(conn, "SELECT clave FROM situaciones")["clave"] == "x"
    conn.execute(
        "INSERT INTO situaciones (clave, detectada, en_portafolio, tipo, "
        "severidad, titulo, detalle) "
        "VALUES ('y', '2026-10-29', 1, 'calendario', 'media', 't', 'd')"
    )
    columnas = {f["name"] for f in conn.execute("PRAGMA table_info(emisoras)")}
    assert "proximo_reporte" in columnas


def test_horario_del_monitor():
    jueves = datetime(2026, 10, 29, 10, 0, tzinfo=config.ZONA)
    assert monitor.en_horario(jueves)
    assert not monitor.en_horario(jueves.replace(hour=16))
    assert not monitor.en_horario(jueves + timedelta(days=2))  # sábado


def test_vuelta_del_monitor_registra_y_cuenta_propuestas(base):
    estrategia.elegir(base, ESTRATEGIA)
    v = monitor.vuelta(base, usar_comite=False, lectores=LECTORES)
    assert {r["accion"] for r in v.nuevas} == {"vender"}
    registro = db.leer_parametro(base, "monitor")
    assert registro["propuestas_nuevas"] == len(v.nuevas) == 2
    assert db.leer_parametro(base, "fundamentales_al")
    # La siguiente vuelta, antes de 6 horas, no vuelve a pedir reportes.
    assert not monitor.toca_fundamentales(base, db.ahora())


def test_el_monitor_deja_cuota_para_el_chat(base):
    base.execute(
        "INSERT INTO ejecuciones_comite (run_id, inicio, origen, solicitud, "
        "llamadas_modelo) VALUES ('r', ?, 'chat', 's', ?)",
        (db.ahora_iso(), config.REGLAS.llamadas_monitor_max),
    )
    v = monitor.vuelta(base, usar_comite=True, lectores=LECTORES)
    assert not v.con_comite
    assert "cuota al chat" in v.resumen.avisos[0]


def test_correr_una_vez_fuera_de_horario_no_hace_nada(base, monkeypatch):
    sabado = datetime(2026, 10, 31, 10, 0, tzinfo=config.ZONA)
    monkeypatch.setattr(db, "ahora", lambda: sabado)
    monkeypatch.setattr(monitor, "_anotar", lambda texto: None)
    monitor.correr(base, una_vez=True, notificar=False)
    assert db.leer_parametro(base, "monitor") is None


def test_la_serie_del_backtest_empieza_en_100():
    e = estrategia.POR_NOMBRE[ESTRATEGIA]
    sim = backtest.simular(_tendencias(), e, 201)
    assert sim.valor.iloc[0] == pytest.approx(100)
    assert np.isfinite(sim.valor).all()


# ═══════════════════════════════════════════
# Escenarios históricos de A3 (D76)
# ═══════════════════════════════════════════


def _tramos() -> pd.DataFrame:
    """A.MX, la posición, cae 20% de la sesión 30 a la 50. B (SIC) sube 10%
    en dólares en esas mismas fechas. C.MX cae 20% de la 5 a la 25. El
    dólar baja 5% de la 10 a la 30."""
    n = 60
    fechas = pd.bdate_range(end=HOY.date(), periods=n)

    def rampa(antes: float, despues: float, i: int, j: int) -> list[float]:
        return [
            antes
            if k <= i
            else despues
            if k >= j
            else antes + (despues - antes) * (k - i) / (j - i)
            for k in range(n)
        ]

    return pd.DataFrame(
        {
            "A.MX": rampa(100, 80, 30, 50),
            "B": rampa(10, 11, 30, 50),
            "C.MX": rampa(50, 40, 5, 25),
            "USDMXN": rampa(20, 19, 10, 30),
        },
        index=fechas,
    )


@pytest.fixture
def tramos(tmp_path):
    conexion = db.conectar(tmp_path / "tramos.db")
    mercado.importar_reto(conexion, _tramos())
    inicio = (HOY - timedelta(days=100)).date().isoformat()
    cartera.cargar_posiciones(
        conexion,
        inicio,
        [{"emisora": "A.MX", "cantidad": 1000, "precio": 100.0}],
        efectivo_actual=100_000.0,
    )
    return conexion


def test_peor_tramo_da_fechas_y_cambio():
    serie = _tramos()["C.MX"]
    inicio, fin, cambio = escenarios.peor_tramo(serie)
    assert (inicio, fin) == (serie.index[5], serie.index[25])
    assert cambio == pytest.approx(-20)


def test_e3_usa_el_peor_mes_de_tu_cartera(tramos):
    est = cartera.estado(tramos)
    por_id = {e.id: e for e in escenarios.todos(tramos, est, "B")}
    e3 = por_id["E3"]
    assert e3.choques["A.MX"] == pytest.approx(-20)
    # En esas fechas B subió 10% en dólares con el dólar quieto en 19.
    assert e3.choques["B"] == pytest.approx(10)
    assert "B cambió +10.00% en esas fechas" in e3.descripcion
    # E4: solo cae lo del SIC; A.MX es de la BMV.
    assert por_id["E4"].choques == {"B": pytest.approx(-5)}
    assert set(por_id) == {"E1", "E2", "E3", "E4", "E5"}


def test_e5_es_el_peor_mes_de_la_emisora(tramos):
    est = cartera.estado(tramos)
    e5 = next(e for e in escenarios.todos(tramos, est, "C.MX") if e.id == "E5")
    assert e5.choques == {"C.MX": pytest.approx(-20)}
    # Sin emisoras del SIC no hay escenario de tipo de cambio.
    assert "E4" not in {e.id for e in escenarios.todos(tramos, est, "C.MX")}


def test_una_compra_que_sube_en_el_peor_mes_resta_perdida(tramos):
    filas = {f["id"]: f for f in escenarios.perdidas(tramos, "B", 100)}
    valor_b = 100 * 11 * 19
    assert filas["E3"]["antes"] == pytest.approx(16_000)
    assert filas["E3"]["despues"] == pytest.approx(16_000 - valor_b * 0.10)
    assert filas["E4"]["antes"] == 0
    assert filas["E4"]["despues"] == pytest.approx(valor_b * 0.05)
    assert "restaría $2,090" in recomendador._peor_mes(tramos, "B", 100)


def test_a3_simula_los_cinco_en_una_llamada_con_la_misma_cuenta(tramos):
    ctx = puente.construir_contexto(tramos, ["B"])
    texto = ctx.descripcion()
    # A0 ve los históricos por título, sin fechas ni cifras (D65).
    for linea in texto.splitlines():
        if linea.startswith(("- Escenario E3", "- Escenario E4", "- Escenario E5")):
            assert not any(ch.isdigit() for ch in linea.split(":", 1)[1])
    assert "varios escenarios en una sola llamada" in texto
    mesa = pm.Mesa(pm.Entorno(ctx.datos))
    r = mesa.llamar(
        "A3",
        "simular_escenarios",
        {
            "portafolio_id": "RETO",
            "propuesta": {
                "empresa": "B",
                "lado": "compra",
                "cantidad": 100,
                "financiacion": "efectivo",
            },
            "escenarios": ["E1", "E2", "E3", "E4", "E5"],
        },
        invocacion="A3-1",
    )
    assert r.status == "ok"
    propias = {f["id"]: f for f in escenarios.perdidas(tramos, "B", 100)}
    for e in r.data["escenarios"]:
        f = propias[e["escenario_id"]]
        assert float(e["perdida_antes"]) == pytest.approx(f["antes"], abs=0.05)
        assert float(e["perdida_despues"]) == pytest.approx(f["despues"], abs=0.05)
        assert e["descripcion"]


def test_sin_historia_no_hay_escenarios_historicos(tmp_path):
    conn = db.conectar(tmp_path / "corta.db")
    mercado.importar_reto(conn, _tramos().iloc[-10:])
    cartera.cargar_posiciones(
        conn,
        (HOY - timedelta(days=30)).date().isoformat(),
        [{"emisora": "A.MX", "cantidad": 10, "precio": 80.0}],
        efectivo_actual=0.0,
    )
    est = cartera.estado(conn)
    assert [e.id for e in escenarios.todos(conn, est, "B")] == ["E1", "E2"]
