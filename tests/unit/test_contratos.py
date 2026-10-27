"""Los contratos como guardrail: lo que no debe ocurrir no se puede construir.

Cada prueba intenta fabricar un objeto que viola una regla de la
especificación. Si la construcción tiene éxito, la regla depende de que el
grafo o el modelo la respeten, y eso es justo lo que el diseño quiere evitar.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from proyecto_multiagente import (
    T0,
    CodigoError,
    DecisionRiesgo,
    Dictamen,
    EstadoFinal,
    Incumplimiento,
    Movimiento,
    Propuesta,
    RespuestaFinal,
    ResultadoHerramienta,
    Validacion,
)


def propuesta(cantidad=100, version=1):
    return Propuesta(
        propuesta_id="PR-1",
        version=version,
        portafolio_id="P1",
        empresa="XYZ",
        lado="compra",
        cantidad=cantidad,
        financiacion="efectivo",
        fecha_corte=T0,
    )


def validacion(p, cumple=True):
    return Validacion(
        cumple=cumple,
        controles=[],
        incumplimientos=[] if cumple else [Incumplimiento.LIMITE_CONCENTRACION],
        propuesta_id=p.propuesta_id,
        version=p.version,
        policy_id="POL1",
        hash_propuesta=p.huella(),
    )


def dictamen(p, cumple=True, decision=DecisionRiesgo.CONFORME):
    return Dictamen(
        propuesta_id=p.propuesta_id,
        version=p.version,
        hash_propuesta=p.huella(),
        validacion=validacion(p, cumple),
        decision=decision,
    )


# --- ResultadoHerramienta ---


def test_error_no_lleva_cifra_de_reemplazo():
    with pytest.raises(ValidationError):
        ResultadoHerramienta(
            status="error",
            data={"precio": 0},
            fecha_corte=T0,
            error={"code": "PRICE_UNAVAILABLE", "message": "", "retryable": False},
        )


def test_error_exige_codigo():
    with pytest.raises(ValidationError):
        ResultadoHerramienta(status="error", data=None, fecha_corte=T0)


def test_fecha_sin_zona_horaria_se_rechaza():
    with pytest.raises(ValidationError):
        ResultadoHerramienta(status="ok", data={}, fecha_corte="2026-10-26T09:00:00")


# --- Movimiento y Propuesta ---


@pytest.mark.parametrize("cantidad", [0, -5, 10.5, "100", True])
def test_cantidad_es_entero_positivo(cantidad):
    with pytest.raises(ValidationError):
        Movimiento(
            empresa="XYZ", lado="compra", cantidad=cantidad, financiacion="efectivo"
        )


def test_no_hay_ventas_ni_apalancamiento():
    for campo, valor in (("lado", "venta"), ("financiacion", "margen")):
        datos = {
            "empresa": "XYZ",
            "lado": "compra",
            "cantidad": 1,
            "financiacion": "efectivo",
        }
        datos[campo] = valor
        with pytest.raises(ValidationError):
            Movimiento(**datos)


def test_campos_adicionales_se_rechazan():
    with pytest.raises(ValidationError):
        Movimiento(
            empresa="XYZ",
            lado="compra",
            cantidad=1,
            financiacion="efectivo",
            aprobado=True,
        )


def test_huella_cambia_con_cualquier_campo():
    base = propuesta()
    assert base.huella() == propuesta().huella()
    assert base.huella() != propuesta(cantidad=101).huella()
    assert base.huella() != propuesta(version=2).huella()


# --- Dictamen ---


def test_validacion_coherente_con_incumplimientos():
    p = propuesta()
    with pytest.raises(ValidationError):
        Validacion(
            cumple=True,
            controles=[],
            incumplimientos=[Incumplimiento.LIMITE_CONCENTRACION],
            propuesta_id=p.propuesta_id,
            version=1,
            policy_id="POL1",
            hash_propuesta=p.huella(),
        )


def test_a4_no_puede_declarar_conforme_un_incumplimiento():
    with pytest.raises(ValidationError, match="conforme"):
        dictamen(propuesta(), cumple=False, decision=DecisionRiesgo.CONFORME)


def test_a4_no_puede_declarar_conforme_sin_validacion():
    p = propuesta()
    with pytest.raises(ValidationError, match="conforme"):
        Dictamen(
            propuesta_id=p.propuesta_id,
            version=1,
            hash_propuesta=p.huella(),
            validacion=None,
            decision=DecisionRiesgo.CONFORME,
        )


def test_a4_si_puede_ser_mas_estricto_que_la_validacion():
    d = dictamen(propuesta(), cumple=True, decision=DecisionRiesgo.RECHAZAR)
    assert d.decision is DecisionRiesgo.RECHAZAR


# --- RespuestaFinal: reglas de autoridad ---


def test_propuesta_sin_dictamen_no_sale():
    with pytest.raises(ValidationError, match="sin dictamen"):
        RespuestaFinal(estado=EstadoFinal.BLOQUEADA, resumen="", propuesta=propuesta())


def test_dictamen_de_otra_version_no_sirve():
    vieja = propuesta(version=1)
    nueva = propuesta(version=2)
    with pytest.raises(ValidationError, match="otra versión"):
        RespuestaFinal(
            estado=EstadoFinal.PENDIENTE_REVISION_HUMANA,
            resumen="",
            propuesta=nueva,
            dictamen=dictamen(vieja),
        )


def test_revision_humana_exige_dictamen_conforme():
    p = propuesta()
    with pytest.raises(ValidationError, match="revisión humana"):
        RespuestaFinal(
            estado=EstadoFinal.PENDIENTE_REVISION_HUMANA,
            resumen="",
            propuesta=p,
            dictamen=dictamen(p, decision=DecisionRiesgo.RECHAZAR),
        )


def test_revision_humana_valida():
    p = propuesta()
    r = RespuestaFinal(
        estado=EstadoFinal.PENDIENTE_REVISION_HUMANA,
        resumen="",
        propuesta=p,
        dictamen=dictamen(p),
    )
    assert r.dictamen.validacion.cumple


@pytest.mark.parametrize(
    "estado", [EstadoFinal.INFORMATIVO, EstadoFinal.CALCULO_HIPOTETICO]
)
def test_respuesta_informativa_no_lleva_propuesta(estado):
    p = propuesta()
    with pytest.raises(ValidationError):
        RespuestaFinal(estado=estado, resumen="", propuesta=p, dictamen=dictamen(p))


def test_error_controlado_no_libera_propuesta():
    p = propuesta()
    with pytest.raises(ValidationError, match="no libera"):
        RespuestaFinal(
            estado=EstadoFinal.ERROR_CONTROLADO,
            resumen="",
            propuesta=p,
            dictamen=dictamen(p),
            error=CodigoError.VALIDATION_MISSING,
        )


def test_metricas_distinguen_cero_falso_y_nulo():
    """Un 0 es una cifra, False es un booleano y None es un dato ausente."""
    r = RespuestaFinal(
        estado=EstadoFinal.INFORMATIVO,
        resumen="",
        metricas={"efectivo": 0, "anular": False, "precio": None, "uno": 1},
    )
    assert r.metricas["efectivo"] == Decimal("0")
    assert r.metricas["anular"] is False
    assert r.metricas["uno"] == Decimal("1") and r.metricas["uno"] is not True

    json = r.model_dump(mode="json")["metricas"]
    assert json == {"efectivo": 0.0, "anular": False, "precio": None, "uno": 1.0}
    assert json["anular"] is False
