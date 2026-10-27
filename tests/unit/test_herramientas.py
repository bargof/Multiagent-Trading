"""Las herramientas producen las cifras de la clave y fallan sin inventar.

La referencia es siempre la clave del evaluador (R2, R3, R5, R6), que se
calculó a mano en la sección 2 de la especificación, no una segunda cuenta
hecha aquí. Si una herramienta y la clave discrepan, una de las dos está mal y
hay que averiguar cuál antes de correr agentes.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from proyecto_multiagente import (
    CATALOGO,
    DATOS,
    HERRAMIENTAS,
    Q100,
    Q600,
    R2,
    R3,
    R5,
    R6,
    RUTAS,
    ZONA_MX,
    DecisionRiesgo,
    Dictamen,
    Entorno,
    EstadoFinal,
    Mesa,
    Movimiento,
    Noticia,
    RespuestaFinal,
    Validacion,
)


def mesa(*fallas, datos=DATOS):
    return Mesa(Entorno(datos=datos, fallas=fallas))


def data(resultado):
    assert resultado.status == "ok", resultado.error
    return resultado.data


def codigo(resultado):
    assert resultado.status == "error"
    assert resultado.data is None
    return resultado.error.code


def cerca(observado, cifra):
    return abs(Decimal(str(observado)) - cifra.valor) <= cifra.tolerancia


def cifras(ruta):
    return {c.clave.removeprefix("metricas."): c for c in ruta.cifras}


def validar(m, movimiento):
    m.entorno.registrar_propuesta("P1", Movimiento(**movimiento))
    resultado = m.llamar(
        "A4", "validar_propuesta", {"portafolio_id": "P1", "propuesta": movimiento}
    )
    return Validacion.model_validate(data(resultado))


def concentracion(validacion, empresa):
    return next(
        c for c in validacion.controles if c.nombre == f"concentracion_{empresa}"
    )


# --- Catálogo ---


def test_catalogo_coincide_con_las_fichas_de_los_agentes():
    assert CATALOGO == {
        "A1": ("buscar_noticias", "obtener_noticia"),
        "A2": ("obtener_reporte", "consultar_nota", "calcular_indicadores"),
        "A3": (
            "consultar_portafolio",
            "consultar_precio",
            "calcular_exposicion",
            "simular_escenarios",
        ),
        "A4": ("consultar_politica", "validar_propuesta"),
    }


def test_no_existen_herramientas_sensibles():
    for nombre in HERRAMIENTAS:
        assert not any(
            p in nombre for p in ("ejecutar", "orden", "modificar", "aprobar")
        )


def test_la_clave_solo_espera_herramientas_del_catalogo_de_cada_actor():
    """Si la clave esperara una herramienta inexistente, ninguna ruta pasaría."""
    for ruta in RUTAS:
        for evento in ruta.trayectoria:
            if not evento.es_delegacion:
                assert evento.nombre in CATALOGO[evento.actor], (ruta.ruta_id, evento)


# --- R2: indicadores de F1 ---


def test_indicadores_de_f1_coinciden_con_r2():
    d = data(mesa().llamar("A2", "calcular_indicadores", {"datos_id": "F1"}))
    for clave, cifra in cifras(R2).items():
        assert cerca(d[clave], cifra), clave
    assert d["limitaciones"] == []
    assert (d["moneda"], d["unidades"]) == ("MXN", "millones")


def test_margen_cae_cinco_puntos_no_cinco_por_ciento():
    d = data(mesa().llamar("A2", "calcular_indicadores", {"datos_id": "F1"}))
    caida_relativa = (
        (d["margen_operativo_actual_pct"] - d["margen_operativo_anterior_pct"])
        / d["margen_operativo_anterior_pct"]
        * 100
    )
    assert d["cambio_margen_pp"] == -5
    assert round(caida_relativa, 2) == Decimal("-33.33")


def test_base_cero_da_null_y_limitacion():
    f1 = DATOS.reportes["F1"]
    sin_base = f1.model_copy(
        update={
            "partidas": {
                "ingresos": {"2026Q3": Decimal("120"), "2025Q3": Decimal("0")},
                "utilidad_operativa": {"2026Q3": Decimal("12")},
            }
        }
    )
    datos = DATOS.model_copy(update={"reportes": {"F1": sin_base}})
    d = data(mesa(datos=datos).llamar("A2", "calcular_indicadores", {"datos_id": "F1"}))
    assert d["crecimiento_ingresos_pct"] is None
    assert d["margen_operativo_anterior_pct"] is None
    assert d["variacion_utilidad_operativa_pct"] is None
    assert d["cambio_margen_pp"] is None
    assert d["margen_operativo_actual_pct"] == 10
    assert len(d["limitaciones"]) == 2


def test_f1_no_tiene_notas():
    m = mesa()
    r = m.llamar("A2", "consultar_nota", {"reporte_id": "F1", "seccion": "deuda"})
    assert codigo(r) == "DATA_NOT_AVAILABLE"


def test_reporte_de_otro_periodo_no_existe():
    r = mesa().llamar("A2", "obtener_reporte", {"empresa": "XYZ", "periodo": "2026Q2"})
    assert codigo(r) == "DATA_NOT_AVAILABLE"


def test_periodo_mal_escrito_es_argumento_invalido():
    r = mesa().llamar("A2", "obtener_reporte", {"empresa": "XYZ", "periodo": "Q3-2026"})
    assert codigo(r) == "INVALID_ARGUMENTS"


# --- R3: cálculo verificable ---


def test_exposicion_y_escenario_coinciden_con_r3():
    m = mesa()
    exp = data(
        m.llamar(
            "A3", "calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q100}
        )
    )
    sim = data(
        m.llamar(
            "A3",
            "simular_escenarios",
            {"portafolio_id": "P1", "propuesta": Q100, "escenarios": ["E1"]},
        )
    )
    (e1,) = sim["escenarios"]
    observado = {**exp, **e1}
    for clave, cifra in cifras(R3).items():
        assert cerca(observado[clave], cifra), clave


def test_comprar_con_efectivo_no_infla_el_total():
    """El error que R3 quiere atrapar: sumar la compra sin restar el efectivo."""
    d = data(
        mesa().llamar(
            "A3", "calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q100}
        )
    )
    assert d["total_despues"] == Decimal("100000")
    assert d["total_despues"] != Decimal("105000")


def test_escenario_desconocido():
    r = mesa().llamar(
        "A3",
        "simular_escenarios",
        {"portafolio_id": "P1", "propuesta": Q100, "escenarios": ["E9"]},
    )
    assert codigo(r) == "UNKNOWN_ID"


# --- R4: falla QERR ---


def test_qerr_precio_es_error_sin_cifra():
    r = mesa("QERR").llamar(
        "A3", "consultar_precio", {"empresa": "XYZ", "fecha_corte": "T0"}
    )
    assert codigo(r) == "PRICE_UNAVAILABLE"
    assert r.error.retryable is False


def test_qerr_portafolio_muestra_null_y_no_cero():
    d = data(mesa("QERR").llamar("A3", "consultar_portafolio", {"id": "P1"}))
    xyz = next(p for p in d["posiciones"] if p["empresa"] == "XYZ")
    assert xyz["precio"] is None and xyz["valor"] is None
    assert d["total"] is None
    assert d["limitaciones"]
    otr1 = next(p for p in d["posiciones"] if p["empresa"] == "OTR1")
    assert otr1["valor"] == Decimal("20000")


@pytest.mark.parametrize(
    "nombre,args",
    [
        ("calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q100}),
        (
            "simular_escenarios",
            {"portafolio_id": "P1", "propuesta": Q100, "escenarios": ["E1"]},
        ),
    ],
)
def test_qerr_no_hay_otro_camino_al_precio(nombre, args):
    """Decisión D4: ninguna herramienta de cálculo filtra la cotización."""
    assert codigo(mesa("QERR").llamar("A3", nombre, args)) == "PRICE_UNAVAILABLE"


def test_qerr_tampoco_permite_validar():
    m = mesa("QERR")
    m.entorno.registrar_propuesta("P1", Movimiento(**Q100))
    r = m.llamar("A4", "validar_propuesta", {"portafolio_id": "P1", "propuesta": Q100})
    assert codigo(r) == "PRICE_UNAVAILABLE"


def test_qerr_solo_afecta_a_xyz():
    r = mesa("QERR").llamar(
        "A3", "consultar_precio", {"empresa": "OTR1", "fecha_corte": "T0"}
    )
    assert data(r)["precio"] == Decimal("100")


# --- R5 y R6: validación de POL1 ---


def test_q600_se_bloquea_por_concentracion_como_en_r5():
    m = mesa()
    exp = data(
        m.llamar(
            "A3", "calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q600}
        )
    )
    v = validar(m, Q600)
    xyz = concentracion(v, "XYZ")
    observado = {**exp, "limite_pct": xyz.limite, "exceso_pp": xyz.valor - xyz.limite}
    for clave, cifra in cifras(R5).items():
        assert cerca(observado[clave], cifra), clave
    assert v.cumple is False
    assert v.incumplimientos == ["LIMITE_CONCENTRACION"]


def test_q100_cumple_como_en_r6():
    m = mesa()
    exp = data(
        m.llamar(
            "A3", "calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q100}
        )
    )
    for clave, cifra in cifras(R6).items():
        assert cerca(exp[clave], cifra), clave
    v = validar(m, Q100)
    assert v.cumple and v.incumplimientos == []


def test_efectivo_insuficiente_y_concentracion_a_la_vez():
    q1000 = {**Q100, "cantidad": 1000}
    v = validar(mesa(), q1000)
    assert set(v.incumplimientos) == {"EFECTIVO_INSUFICIENTE", "LIMITE_CONCENTRACION"}


def test_cantidad_negativa_es_incumplimiento_no_error_de_formato():
    m = mesa()
    m.entorno.registrar_propuesta("P1", Movimiento(**Q100))
    r = m.llamar(
        "A4",
        "validar_propuesta",
        {"portafolio_id": "P1", "propuesta": {**Q100, "cantidad": -5}},
    )
    v = Validacion.model_validate(data(r))
    assert v.incumplimientos == ["CANTIDAD_INVALIDA"]


def test_instrumento_fuera_del_universo():
    m = mesa()
    m.entorno.registrar_propuesta("P1", Movimiento(**Q100))
    r = m.llamar(
        "A4",
        "validar_propuesta",
        {"portafolio_id": "P1", "propuesta": {**Q100, "empresa": "ABC"}},
    )
    assert Validacion.model_validate(data(r)).incumplimientos == [
        "INSTRUMENTO_NO_AUTORIZADO"
    ]


def test_validar_sin_propuesta_registrada():
    r = mesa().llamar(
        "A4", "validar_propuesta", {"portafolio_id": "P1", "propuesta": Q100}
    )
    assert codigo(r) == "INVALID_ARGUMENTS"


def test_politica_completa():
    d = data(mesa().llamar("A4", "consultar_politica", {}))
    assert d["policy_id"] == "POL1" and d["concentracion_max_pct"] == 30


# --- Versiones e identidad de la propuesta ---


def test_huella_de_la_validacion_es_la_de_la_propuesta_vigente():
    m = mesa()
    v = validar(m, Q600)
    assert v.hash_propuesta == m.entorno.propuesta_vigente.huella()


def test_a4_no_puede_revisar_otra_cantidad_y_reclamar_el_dictamen():
    """Si A4 valida 500 en vez de 600, el dictamen no casa con la propuesta."""
    m = mesa()
    vigente = m.entorno.registrar_propuesta("P1", Movimiento(**Q600))
    r = m.llamar(
        "A4",
        "validar_propuesta",
        {"portafolio_id": "P1", "propuesta": {**Q600, "cantidad": 500}},
    )
    v = Validacion.model_validate(data(r))
    assert v.hash_propuesta != vigente.huella()
    with pytest.raises(ValidationError, match="otra propuesta"):
        Dictamen(
            propuesta_id=vigente.propuesta_id,
            version=vigente.version,
            hash_propuesta=vigente.huella(),
            validacion=v,
            decision=DecisionRiesgo.CONFORME,
        )


def test_cambiar_la_propuesta_invalida_el_dictamen_anterior():
    """Sección 7.2: versión alterada después del dictamen."""
    entorno = Entorno()
    v1 = entorno.registrar_propuesta("P1", Movimiento(**Q100))
    assert entorno.registrar_propuesta("P1", Movimiento(**Q100)) is v1
    m = Mesa(entorno)
    validacion = Validacion.model_validate(
        data(
            m.llamar(
                "A4", "validar_propuesta", {"portafolio_id": "P1", "propuesta": Q100}
            )
        )
    )
    dictamen = Dictamen(
        propuesta_id=v1.propuesta_id,
        version=v1.version,
        hash_propuesta=v1.huella(),
        validacion=validacion,
        decision=DecisionRiesgo.CONFORME,
    )
    v2 = entorno.registrar_propuesta("P1", Movimiento(**{**Q100, "cantidad": 120}))
    assert (v2.propuesta_id, v2.version) == (v1.propuesta_id, 2)
    with pytest.raises(ValidationError, match="otra versión"):
        RespuestaFinal(
            estado=EstadoFinal.PENDIENTE_REVISION_HUMANA,
            resumen="",
            propuesta=v2,
            dictamen=dictamen,
        )


# --- Noticias y fechas de corte ---


def test_buscar_noticias_al_corte():
    d = data(
        mesa().llamar("A1", "buscar_noticias", {"empresa": "XYZ", "fecha_corte": "T0"})
    )
    assert [n["noticia_id"] for n in d["noticias"]] == ["N1", "N2"]
    assert "texto" not in d["noticias"][0]


def test_obtener_noticia_n1():
    d = data(mesa().llamar("A1", "obtener_noticia", {"id": "N1"}))
    assert "de 8% a 3%" in d["texto"]
    assert d["fecha_publicacion"] < DATOS.t0


def test_noticia_posterior_al_corte_no_existe_para_el_sistema():
    """Sección 7.2. N3 solo existe en este entorno de prueba, no en DATOS."""
    n3 = Noticia(
        noticia_id="N3",
        empresa="XYZ",
        titulo="Noticia del futuro",
        texto="Publicada después de T0.",
        fuente="prueba",
        fecha_publicacion=datetime(2026, 10, 27, 8, 0, tzinfo=ZONA_MX),
    )
    datos = DATOS.model_copy(update={"noticias": {**DATOS.noticias, "N3": n3}})
    m = mesa(datos=datos)
    d = data(m.llamar("A1", "buscar_noticias", {"empresa": "XYZ", "fecha_corte": "T0"}))
    assert "N3" not in [n["noticia_id"] for n in d["noticias"]]
    assert codigo(m.llamar("A1", "obtener_noticia", {"id": "N3"})) == "AFTER_CUTOFF"


@pytest.mark.parametrize(
    "corte",
    ["T0", "t0", "2026-10-26T09:00:00-06:00", "2026-10-26T15:00:00Z"],
)
def test_formas_validas_de_t0(corte):
    r = mesa().llamar(
        "A3", "consultar_precio", {"empresa": "XYZ", "fecha_corte": corte}
    )
    assert data(r)["precio"] == Decimal("50")


@pytest.mark.parametrize(
    "corte,esperado",
    [
        ("2026-10-26", "INVALID_ARGUMENTS"),  # sin hora ni zona: ambigua
        ("2026-10-26T09:00:00", "INVALID_ARGUMENTS"),  # sin zona
        ("ayer", "INVALID_ARGUMENTS"),
        ("2026-10-27T09:00:00-06:00", "AFTER_CUTOFF"),
        ("2026-10-25T09:00:00-06:00", "DATA_NOT_AVAILABLE"),
    ],
)
def test_cortes_invalidos(corte, esperado):
    r = mesa().llamar(
        "A3", "consultar_precio", {"empresa": "XYZ", "fecha_corte": corte}
    )
    assert codigo(r) == esperado


def test_buscar_noticias_futuras():
    r = mesa().llamar(
        "A1",
        "buscar_noticias",
        {"empresa": "XYZ", "fecha_corte": "2026-12-01T00:00:00-06:00"},
    )
    assert codigo(r) == "AFTER_CUTOFF"


@pytest.mark.parametrize(
    "actor,nombre,args",
    [
        ("A1", "obtener_noticia", {"id": "N9"}),
        ("A1", "buscar_noticias", {"empresa": "ABC", "fecha_corte": "T0"}),
        ("A2", "calcular_indicadores", {"datos_id": "F9"}),
        ("A3", "consultar_portafolio", {"id": "P9"}),
        ("A3", "consultar_precio", {"empresa": "ABC", "fecha_corte": "T0"}),
    ],
)
def test_identificadores_desconocidos(actor, nombre, args):
    assert codigo(mesa().llamar(actor, nombre, args)) == "UNKNOWN_ID"


def test_identificadores_sin_importar_mayusculas():
    d = data(mesa().llamar("A3", "consultar_portafolio", {"id": " p1 "}))
    assert d["portafolio_id"] == "P1"


# --- Aislamiento y ausencia de mutaciones ---


def test_ninguna_herramienta_muta_los_datos():
    m = mesa()
    llamadas = [
        ("A1", "buscar_noticias", {"empresa": "XYZ", "fecha_corte": "T0"}),
        ("A1", "obtener_noticia", {"id": "N1"}),
        ("A2", "obtener_reporte", {"empresa": "XYZ", "periodo": "2026Q3"}),
        ("A2", "calcular_indicadores", {"datos_id": "F1"}),
        ("A3", "consultar_portafolio", {"id": "P1"}),
        ("A3", "calcular_exposicion", {"portafolio_id": "P1", "propuesta": Q600}),
        (
            "A3",
            "simular_escenarios",
            {"portafolio_id": "P1", "propuesta": Q600, "escenarios": ["E1"]},
        ),
        ("A4", "consultar_politica", {}),
    ]
    for actor, nombre, args in llamadas:
        data(m.llamar(actor, nombre, args, invocacion=f"{actor}-{nombre}"))
    validar(m, Q600)
    assert m.entorno.portafolios_intactos() and m.entorno.politica_intacta()
    assert m.entorno.datos == DATOS


def test_los_entornos_no_comparten_estado():
    a, b = Entorno(), Entorno()
    a.registrar_propuesta("P1", Movimiento(**Q600))
    a.datos.portafolios["P1"] = a.datos.portafolios["P1"].model_copy(
        update={"efectivo": Decimal("0")}
    )
    assert not a.portafolios_intactos()
    assert b.portafolios_intactos() and b.propuesta_vigente is None
    assert DATOS.portafolios["P1"].efectivo == Decimal("30000")


def test_los_datos_son_inmutables():
    with pytest.raises(ValidationError):
        Entorno().datos.portafolios["P1"].efectivo = Decimal("0")
