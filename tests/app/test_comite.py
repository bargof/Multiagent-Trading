"""La aplicación sobre datos reales, probada sin red ni cuota.

Los precios, titulares y estados financieros son sintéticos y entran por los
mismos lectores inyectables que en producción usan yfinance y Google News.
El comité corre con el modelo de guion del ejecutable: así se prueba que el
puente arma un `DatosSimulados` que las herramientas reales del comité
aceptan, con los identificadores que A0 recibe en el contexto.
"""

from datetime import timedelta

import pandas as pd
import pytest

import proyecto_multiagente as pm
from comite import (
    cartera,
    config,
    db,
    ejecucion,
    estrategia,
    finanzas,
    fuentes,
    mercado,
    proceso,
    puente,
    recomendador,
    vigia,
)

HOY = db.ahora()


# La que se usa en las pruebas del rebalanceo. Con estos precios solo CAT
# sube y está arriba de su media de 200 sesiones.
ESTRATEGIA = "momentum_120_top10_tendencia"


def _tabla_precios() -> pd.DataFrame:
    # 260 sesiones: la estrategia necesita la media de 200.
    fechas = pd.bdate_range(end=HOY.date(), periods=260)
    n = len(fechas)
    walmex = [50.0] * (n - 5) + [48.0, 47.0, 46.0, 45.0, 44.0]  # -12% en 5
    aapl = [200.0] * n  # USD
    cat = [100.0 + i for i in range(n)]  # sube todo el periodo
    return pd.DataFrame(
        {
            "WALMEX.MX": walmex,
            "AAPL": aapl,
            "CAT": cat,
            "TAN": [40.0] * n,
            "Conservador": [100.0 + i * 0.1 for i in range(n)],
            "Moderado": [100.0 + i * 0.2 for i in range(n)],
            "Agresivo": [100.0 + i * 0.3 for i in range(n)],
            "USDMXN": [18.0] * n,
        },
        index=fechas,
    )


def _titulares(consulta: str, idioma: str) -> list[dict]:
    if idioma != "es" or "(" not in consulta:
        return []
    nombre = consulta.split('"')[1]
    return [
        {
            "titulo": f"{nombre}: titular {i}",
            "fuente": f"Medio {i}",
            "url": f"https://ejemplo.mx/{nombre}/{i}",
            "fecha": HOY - timedelta(hours=10 + i),
        }
        for i in range(3)
    ]


def _estados(emisora: str) -> dict | None:
    fin = (pd.Timestamp(HOY.date()) - pd.offsets.QuarterEnd(1)).date()
    anterior = (pd.Timestamp(fin) - pd.DateOffset(years=1)).date()
    return {
        "moneda": "MXN",
        "trimestres": {
            fin.isoformat(): {
                "ingresos": 120e6,
                "utilidad_operativa": 12e6,
                "utilidad_neta": 8e6,
            },
            anterior.isoformat(): {
                "ingresos": 100e6,
                "utilidad_operativa": 15e6,
                "utilidad_neta": 9e6,
            },
        },
    }


LECTORES = proceso.Fuentes(
    descargar=lambda tickers, desde: pd.DataFrame(),
    titulares=_titulares,
    estados=_estados,
    nombre=lambda emisora: None,
    calendario=lambda emisora: None,
)


@pytest.fixture
def conn(tmp_path):
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


def _concentrar(conn):
    """40 AAPL más: 100 × 3,600 = 360k de 904k, arriba del 30%."""
    cartera.registrar(
        conn,
        fecha=HOY.date().isoformat(),
        lado="compra",
        emisora="AAPL",
        cantidad=40,
        precio=3600,
        monto=144_000,
    )


# ═══════════════════════════════════════════
# Mercado y cartera
# ═══════════════════════════════════════════


def test_el_sic_se_valua_en_pesos(conn):
    est = cartera.estado(conn)
    aapl = next(p for p in est.posiciones if p.emisora == "AAPL")
    assert aapl.precio == pytest.approx(200 * 18)
    assert est.total == pytest.approx(1000 * 44 + 60 * 3600 + 500_000)


def test_sin_tipo_de_cambio_el_precio_queda_vacio_no_en_cero(conn):
    conn.execute("DELETE FROM precios WHERE emisora = 'USDMXN'")
    est = cartera.estado(conn)
    assert next(p for p in est.posiciones if p.emisora == "AAPL").precio is None
    assert est.total is None


def test_la_clave_del_comite_no_lleva_sufijo(conn):
    assert mercado.mapa_claves(conn)["WALMEX"] == "WALMEX.MX"


def test_el_libro_no_permite_corto_ni_apalancamiento(conn):
    with pytest.raises(ValueError, match="solo tienes"):
        cartera.registrar(
            conn,
            fecha="2026-10-29",
            lado="venta",
            emisora="WALMEX.MX",
            cantidad=1001,
            precio=44,
            monto=1001 * 44,
        )
    with pytest.raises(ValueError, match="Efectivo insuficiente"):
        cartera.registrar(
            conn,
            fecha="2026-10-29",
            lado="compra",
            emisora="CAT",
            cantidad=10_000,
            precio=2000,
            monto=20_000_000,
        )


def test_historial_en_base_100_con_benchmarks(conn):
    tabla = cartera.historial(conn)
    assert {"Mi portafolio", "Conservador", "Moderado", "Agresivo"} <= set(tabla)
    assert tabla["Conservador"].dropna().iloc[0] == pytest.approx(100)


# ═══════════════════════════════════════════
# Fuentes
# ═══════════════════════════════════════════


def test_reporte_compara_contra_el_mismo_trimestre_del_anio_anterior():
    reporte = fuentes.reporte_desde_estados("WALMEX.MX", _estados("x"), HOY)
    assert reporte["comparacion"] == "anual"
    assert reporte["partidas"]["ingresos"][reporte["periodo"]] == 120.0
    assert reporte["fecha_publicacion"] <= HOY.isoformat()


def test_sin_el_anio_anterior_compara_contra_el_trimestre_previo():
    estados = {
        "moneda": "MXN",
        "trimestres": {
            "2026-09-30": {"ingresos": 10e6},
            "2026-06-30": {"ingresos": 9e6},
        },
    }
    reporte = fuentes.reporte_desde_estados("X.MX", estados, HOY)
    assert (reporte["periodo"], reporte["periodo_comparado"]) == ("2026Q3", "2026Q2")
    assert reporte["comparacion"] == "trimestral"


def test_titulares_sin_duplicados_y_los_que_nombran_primero(conn):
    fuentes.actualizar_noticias(conn, ["WALMEX.MX"], _titulares, lambda e: None)
    conn.execute(
        """INSERT INTO documentos (doc_id, tipo, emisora, titulo, fuente,
           fecha_publicacion, obtenido) VALUES ('N-OTRO', 'noticia', 'WALMEX.MX',
           'Otro tema sin relación', 'X', ?, ?)""",
        (HOY.isoformat(), HOY.isoformat()),
    )
    titulares = fuentes.titulares_recientes(conn, "WALMEX.MX", HOY)
    assert titulares[-1]["doc_id"] == "N-OTRO"
    assert len({t["titulo"] for t in titulares}) == len(titulares)


# ═══════════════════════════════════════════
# Vigía
# ═══════════════════════════════════════════


def test_vigia_detecta_y_no_duplica(conn):
    fuentes.actualizar_noticias(conn, ["WALMEX.MX"], _titulares, lambda e: None)
    fuentes.actualizar_reportes(conn, ["WALMEX.MX"], _estados)
    situaciones = vigia.detectar(conn)
    tipos = {(s.tipo, s.emisora) for s in situaciones}
    # AAPL pesa 216k de 760k: 28%, cerca del límite.
    assert ("estres", "AAPL") in tipos
    assert ("precio", "WALMEX.MX") in tipos
    assert ("noticias", "WALMEX.MX") in tipos
    assert ("reporte", "WALMEX.MX") in tipos
    # Sin estrategia elegida, el vigía no propone compras ni rebalanceo.
    assert not {t for t, _ in tipos} & {"oportunidad", "salida"}
    assert vigia.guardar(conn, situaciones) == len(situaciones)
    assert vigia.guardar(conn, vigia.detectar(conn)) == 0


def test_con_una_posicion_excedida_no_propone_compras(conn):
    estrategia.elegir(conn, ESTRATEGIA)
    _concentrar(conn)
    tipos = {(s.tipo, s.emisora) for s in vigia.detectar(conn)}
    assert ("concentracion", "AAPL") in tipos
    assert not any(t == "oportunidad" for t, _ in tipos)


def test_concentracion_vende_lo_justo_para_volver_al_limite(conn):
    _concentrar(conn)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "concentracion")
    rec = recomendador.por_regla(conn, sit)
    est = cartera.estado(conn)
    despues = (100 - rec["cantidad"]) * 3600 / est.total * 100
    antes = (100 - rec["cantidad"] + 1) * 3600 / est.total * 100
    assert despues <= config.REGLAS.concentracion_max_pct < antes


# ═══════════════════════════════════════════
# Puente al comité
# ═══════════════════════════════════════════


def test_emisoras_mencionadas(conn):
    conn.execute("UPDATE emisoras SET nombre = 'Walmex' WHERE emisora = 'WALMEX.MX'")
    texto = "¿Qué tan bien va walmex comparada con AAPL?"
    assert puente.emisoras_mencionadas(conn, texto) == ["WALMEX.MX", "AAPL"]
    assert puente.emisoras_mencionadas(conn, "Compra TAN") == ["TAN"]


def test_contexto_arma_datos_que_el_comite_acepta(conn):
    fuentes.actualizar_noticias(conn, ["WALMEX.MX"], _titulares, lambda e: None)
    fuentes.actualizar_reportes(conn, ["WALMEX.MX"], _estados)
    ctx = puente.construir_contexto(conn, ["WALMEX.MX"])
    d = ctx.datos
    assert set(d.noticias) == {"N-WALMEX"}
    assert d.noticias["N-WALMEX"].texto.count("\n- ") == 3
    assert list(d.reportes)[0].startswith("F-WALMEX-")
    assert finanzas.NOTA in ctx.descripcion()
    assert d.escenarios["E1"].choques_pct == {"WALMEX": -10}
    assert set(d.escenarios["E2"].choques_pct) == {"WALMEX", "AAPL"}
    assert d.precios_t0["AAPL"] == 3600
    assert "N-WALMEX" in ctx.descripcion() and "RETO" in ctx.descripcion()
    # Las herramientas reales del comité leen estos datos sin error.
    mesa = pm.Mesa(pm.Entorno(d))
    r = mesa.llamar("A3", "consultar_portafolio", {"id": "RETO"}, invocacion="A3-1")
    assert r.status == "ok" and r.data["total"] == pytest.approx(760_000)
    r = mesa.llamar(
        "A2", "calcular_indicadores", {"datos_id": list(d.reportes)[0]}, "A2-1"
    )
    assert r.data["crecimiento_ingresos_pct"] == 20
    # A2 lee los indicadores calculados con su herramienta de notas.
    r = mesa.llamar(
        "A2",
        "consultar_nota",
        {"reporte_id": list(d.reportes)[0], "seccion": finanzas.NOTA},
        "A2-1",
    )
    assert r.status == "ok" and "Margen neto: 6.67% contra 9.00%" in r.data["texto"]


def _guion_noticias(sentimiento: str):
    return pm.guiones(
        A0=[
            pm.pide(
                "consultar_noticias",
                empresa="WALMEX",
                tarea="Analiza los titulares.",
                id="N-WALMEX",
                fecha_corte="T0",
            ),
            pm.sintesis("informativo", evidencia=["N-WALMEX"], resumen="Análisis."),
        ],
        A1=[
            pm.pide("obtener_noticia", id="N-WALMEX"),
            pm.salida_a1("N-WALMEX", "otro", sentimiento),
        ],
    )


def test_noticia_negativa_y_caida_reducen_la_posicion(conn):
    fuentes.actualizar_noticias(conn, ["WALMEX.MX"], _titulares, lambda e: None)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "noticias")
    solicitud, foco = recomendador.solicitud_para(conn, sit)
    consulta = puente.consultar(
        conn,
        solicitud,
        foco,
        origen="vigia",
        situacion_id=sit["id"],
        modelo_para=_guion_noticias("negativo"),
    )
    assert consulta.respuesta.estado is pm.EstadoFinal.INFORMATIVO
    assert len(consulta.documentos()) == 3
    rec = recomendador.desde_comite(conn, sit, consulta)
    # -12% en 5 sesiones y análisis negativo: la regla reduce 25% de 1000.
    assert (rec["accion"], rec["cantidad"], rec["origen"]) == ("vender", 250, "regla")
    recomendador.guardar(conn, rec)
    registro = db.fila(conn, "SELECT * FROM ejecuciones_comite")
    assert registro["estado"] == "informativo" and registro["traza"]


def test_noticia_positiva_mantiene(conn):
    fuentes.actualizar_noticias(conn, ["WALMEX.MX"], _titulares, lambda e: None)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "noticias")
    solicitud, foco = recomendador.solicitud_para(conn, sit)
    consulta = puente.consultar(
        conn, solicitud, foco, origen="vigia", modelo_para=_guion_noticias("positivo")
    )
    rec = recomendador.desde_comite(conn, sit, consulta)
    assert rec["accion"] == "mantener" and rec["estado"] == "informativa"


def test_titulares_mixtos_con_caida_piden_vigilar(conn):
    fuentes.actualizar_noticias(conn, ["WALMEX.MX"], _titulares, lambda e: None)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "noticias")
    solicitud, foco = recomendador.solicitud_para(conn, sit)
    consulta = puente.consultar(
        conn, solicitud, foco, origen="vigia", modelo_para=_guion_noticias("mixto")
    )
    rec = recomendador.desde_comite(conn, sit, consulta)
    assert rec["accion"] == "vigilar" and "mixto" in rec["razon"]


def _guion_compra(cantidad: int, decision: str = "conforme"):
    mov = {
        "empresa": "CAT",
        "lado": "compra",
        "cantidad": cantidad,
        "financiacion": "efectivo",
    }
    return pm.guiones(
        A0=[
            pm.pide(
                "consultar_noticias",
                empresa="CAT",
                tarea="Titulares.",
                fecha_corte="T0",
            ),
            pm.pide(
                "consultar_portafolio",
                tarea="Evalúa la compra.",
                portafolio="RETO",
                empresa="CAT",
                cantidad=cantidad,
                escenario="E1",
            ),
            pm.sintesis(
                "propuesta",
                evidencia=["N-CAT", "RETO"],
                propuesta={"portafolio_id": "RETO", "movimiento": mov},
            ),
        ],
        A1=[
            pm.pide("buscar_noticias", empresa="CAT", fecha_corte="T0"),
            pm.pide("obtener_noticia", id="N-CAT"),
            pm.salida_a1("N-CAT", "otro", "positivo"),
        ],
        A3=[
            pm.pide("consultar_portafolio", id="RETO"),
            pm.pide("consultar_precio", empresa="CAT", fecha_corte="T0"),
            pm.pide("calcular_exposicion", portafolio_id="RETO", propuesta=mov),
            pm.pide(
                "simular_escenarios",
                portafolio_id="RETO",
                propuesta=mov,
                escenarios=["E1"],
            ),
            pm.salida_a3(mov, True, portafolio="RETO"),
        ],
        A4=[
            pm.pide("consultar_politica"),
            pm.pide("validar_propuesta", portafolio_id="RETO", propuesta=mov),
            pm.salida_a4(decision),
        ],
    )


def _oportunidad(conn):
    estrategia.elegir(conn, ESTRATEGIA)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "oportunidad")
    fuentes.actualizar_noticias(conn, ["CAT"], _titulares, lambda e: None)
    return sit, db.de_json(sit["datos"])["cantidad_sugerida"]


def test_compra_conforme_se_aprueba_y_se_registra(conn):
    sit, q = _oportunidad(conn)
    solicitud, foco = recomendador.solicitud_para(conn, sit)
    consulta = puente.consultar(
        conn,
        solicitud,
        foco,
        origen="vigia",
        situacion_id=sit["id"],
        modelo_para=_guion_compra(q),
    )
    assert consulta.respuesta.estado is pm.EstadoFinal.PENDIENTE_REVISION_HUMANA
    rec = recomendador.desde_comite(conn, sit, consulta)
    assert (rec["accion"], rec["cantidad"], rec["estado"]) == (
        "comprar",
        q,
        "propuesta",
    )
    rec_id = recomendador.guardar(conn, rec)
    assert (
        db.fila(conn, "SELECT estado FROM situaciones WHERE id = ?", sit["id"])[
            "estado"
        ]
        == "analizada"
    )

    boleta = ejecucion.aprobar(conn, rec_id)
    assert boleta.operacion == "COMPRA" and boleta.titulos == q
    assert "CAT" in boleta.texto()
    efectivo_antes = cartera.efectivo(conn)
    ejecucion.registrar(conn, rec_id, precio=boleta.precio_actual, folio="F-123")
    assert cartera.estado_cantidad(conn, "CAT") == q
    assert cartera.efectivo(conn) == pytest.approx(
        efectivo_antes - q * boleta.precio_actual, abs=0.01
    )
    estado = db.fila(conn, "SELECT estado FROM recomendaciones WHERE id = ?", rec_id)
    assert estado["estado"] == "ejecutada"


def test_compra_que_rompe_el_limite_queda_bloqueada(conn):
    sit, _ = _oportunidad(conn)
    solicitud, foco = recomendador.solicitud_para(conn, sit)
    # 3,000 CAT a ~6,500 MXN superan el efectivo y el 30%.
    consulta = puente.consultar(
        conn, solicitud, foco, origen="vigia", modelo_para=_guion_compra(3000)
    )
    assert consulta.respuesta.estado is pm.EstadoFinal.BLOQUEADA
    rec = recomendador.desde_comite(conn, sit, consulta)
    assert rec["accion"] == "no_operar" and rec["estado"] == "bloqueada"


def test_el_ejecutor_rechaza_si_el_precio_se_movio(conn):
    sit, q = _oportunidad(conn)
    solicitud, foco = recomendador.solicitud_para(conn, sit)
    consulta = puente.consultar(
        conn, solicitud, foco, origen="vigia", modelo_para=_guion_compra(q)
    )
    rec = recomendador.desde_comite(conn, sit, consulta)
    assert rec["accion"] == "comprar"
    rec["precio_ref"] *= 0.9
    rec_id = recomendador.guardar(conn, rec)
    with pytest.raises(ejecucion.OrdenInvalida, match="El precio se movió"):
        ejecucion.aprobar(conn, rec_id)


def test_una_venta_de_regla_no_pasa_de_la_tenencia(conn):
    _concentrar(conn)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "concentracion")
    rec = recomendador.por_regla(conn, sit)
    rec["cantidad"] = 500
    rec_id = recomendador.guardar(conn, rec)
    with pytest.raises(ejecucion.OrdenInvalida, match="tienes 100"):
        ejecucion.aprobar(conn, rec_id)


def test_una_propuesta_nueva_expira_la_anterior(conn):
    _concentrar(conn)
    vigia.guardar(conn, vigia.detectar(conn))
    sit = next(s for s in vigia.abiertas(conn) if s["tipo"] == "concentracion")
    primera = recomendador.guardar(conn, recomendador.por_regla(conn, sit))
    recomendador.guardar(conn, recomendador.por_regla(conn, sit))
    estado = db.fila(conn, "SELECT estado FROM recomendaciones WHERE id = ?", primera)
    assert estado["estado"] == "expirada"


def test_recorrer_sin_comite_resuelve_las_reglas_y_deja_lo_demas(conn):
    _concentrar(conn)
    resumen = proceso.recorrer(conn, usar_comite=False, lectores=LECTORES)
    assert resumen.por_regla and resumen.sin_analizar > 0
    assert recomendador.pendientes(conn)


def test_recorrer_sin_key_avisa_y_no_falla(conn):
    resumen = proceso.recorrer(conn, lectores=LECTORES)
    assert any("GOOGLE_API_KEY" in a for a in resumen.avisos)
