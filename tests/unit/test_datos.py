"""Los datos simulados dicen exactamente lo que fija la sección 2.1.

Un error de captura aquí —un precio de 5 en vez de 50— no lo detectaría
ninguna otra prueba: el sistema calcularía con coherencia sobre un dato
equivocado y la clave del evaluador parecería mal hecha.
"""

from decimal import Decimal

from proyecto_multiagente import DATOS, T0


def valor(empresa):
    p1 = DATOS.portafolios["P1"]
    cantidad = next(p.cantidad for p in p1.posiciones if p.empresa == empresa)
    return cantidad * DATOS.precios_t0[empresa]


def test_t0():
    assert T0.isoformat() == "2026-10-26T09:00:00-06:00"
    assert DATOS.t0 == T0


def test_p1_vale_cien_mil():
    p1 = DATOS.portafolios["P1"]
    assert p1.moneda == "MXN"
    assert valor("XYZ") == Decimal("10000")
    assert [valor(e) for e in ("OTR1", "OTR2", "OTR3")] == [Decimal("20000")] * 3
    assert p1.efectivo == Decimal("30000")
    total = sum(valor(p.empresa) for p in p1.posiciones) + p1.efectivo
    assert total == Decimal("100000")


def test_pol1():
    pol = DATOS.politica
    assert pol.policy_id == "POL1"
    assert pol.concentracion_max_pct == Decimal("30")
    assert set(pol.universo) == {"XYZ", "OTR1", "OTR2", "OTR3"}
    assert pol.efectivo_final_minimo == 0
    assert not pol.ventas_en_corto and not pol.apalancamiento


def test_todo_se_publico_antes_del_corte():
    for noticia in DATOS.noticias.values():
        assert noticia.fecha_publicacion < T0
    for reporte in DATOS.reportes.values():
        assert reporte.fecha_publicacion < T0


def test_f1_solo_trae_ingresos_y_utilidad_operativa():
    f1 = DATOS.reportes["F1"]
    assert (f1.empresa, f1.periodo, f1.periodo_comparado) == ("XYZ", "2026Q3", "2025Q3")
    assert f1.partidas == {
        "ingresos": {"2026Q3": 120, "2025Q3": 100},
        "utilidad_operativa": {"2026Q3": 12, "2025Q3": 15},
    }
    assert f1.notas == {}


def test_noticias_sin_pronostico_de_precio():
    for noticia in DATOS.noticias.values():
        assert "precio" not in noticia.texto.lower()


def test_e1_y_qerr():
    assert DATOS.escenarios["E1"].choques_pct == {"XYZ": Decimal("-10")}
    qerr = DATOS.fallas["QERR"]
    assert (qerr.empresa, qerr.code) == ("XYZ", "PRICE_UNAVAILABLE")


def test_cuentas_a_mano_de_r3_y_r5():
    """La referencia independiente: la aritmética de la sección 2, sin herramientas.

    Cuando existan las herramientas (Bloque 2), sus resultados se compararán
    contra la clave, no contra esta prueba; esta solo confirma que la clave y
    los datos describen el mismo portafolio.
    """
    precio = DATOS.precios_t0["XYZ"]
    efectivo = DATOS.portafolios["P1"].efectivo
    total = Decimal("100000")

    for compra, peso, perdida_despues in ((100, 15, 1500), (600, 40, None)):
        costo = compra * precio
        xyz_despues = valor("XYZ") + costo
        assert efectivo - costo >= 0
        assert xyz_despues / total * 100 == peso
        if perdida_despues is not None:
            assert xyz_despues * Decimal("0.10") == perdida_despues
