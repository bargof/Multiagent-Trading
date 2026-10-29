"""Qué preguntarle al comité por cada situación y qué hacer con su respuesta.

El comité solo sabe proponer compras pagadas con efectivo (Lado = compra en
el ejecutable) y su revisión de riesgo es la de POL1. Las ventas no pasan por
él: las proponen reglas fijas, con la cifra calculada aquí y la evidencia del
análisis del comité cuando lo hubo (decisión D66). Cada recomendación dice
de dónde viene: `origen = comite` o `origen = regla`.
"""

import math
import sqlite3
from typing import Any

import proyecto_multiagente as pm
from comite import (
    cartera,
    config,
    db,
    escenarios,
    estrategia,
    finanzas,
    fuentes,
    mercado,
)
from comite.config import REGLAS
from comite.puente import Consulta

# Situaciones que se resuelven con aritmética: no gastan cuota. Las ventas
# del rebalanceo son de la estrategia que elegiste (D72); el comité no vende.
SOLO_REGLA = ("concentracion", "estres", "salida", "calendario")

ACCIONES = {
    "comprar": "Comprar",
    "vender": "Vender",
    "mantener": "Mantener",
    "vigilar": "Vigilar",
    "no_operar": "No operar",
}


def _clave(conn: sqlite3.Connection, emisora: str) -> str:
    f = db.fila(conn, "SELECT clave FROM emisoras WHERE emisora = ?", emisora)
    return f["clave"] if f else mercado.clave_de(emisora)


def solicitud_para(
    conn: sqlite3.Connection, sit: dict[str, Any]
) -> tuple[str, list[str]] | None:
    """La pregunta al comité y sus emisoras de foco, o None si basta la regla."""
    tipo, emisora = sit["tipo"], sit["emisora"]
    if tipo in SOLO_REGLA or emisora is None:
        return None
    c = _clave(conn, emisora)
    datos = db.de_json(sit["datos"], {})
    p = config.PORTAFOLIO_ID
    if tipo == "noticias":
        texto = (
            f"Analiza los titulares recientes de {c} publicados hasta T0. ¿Qué "
            f"ocurrió y cómo cambia las expectativas del negocio para la posición "
            f"de {c} en el portafolio {p}? Es un análisis: no propongas "
            "movimientos."
        )
    elif tipo == "reporte":
        evidencia = db.de_json(sit["evidencia"], [])
        texto = (
            f"Analiza el último reporte trimestral de {c}"
            + (f" ({evidencia[0]})" if evidencia else "")
            + ": crecimiento de ingresos, variación de la utilidad operativa y "
            "margen operativo contra el periodo comparado. Lee también su nota "
            f"{finanzas.NOTA} (márgenes, flujo libre, deuda, rendimiento sobre "
            "capital y valuación). ¿Mejoró o empeoró la operación y la situación "
            "financiera? Es un análisis: no propongas movimientos."
        )
    elif tipo in ("precio", "destacada"):
        cambio = datos.get("cambio_pct", 0)
        verbo = "cayó" if cambio < 0 else "subió"
        texto = (
            f"{c} {verbo} {abs(cambio):.1f}% recientemente. Revisa sus titulares "
            "hasta T0: ¿hay alguna noticia que explique el movimiento? No hagas "
            "pronósticos de precio y no propongas movimientos."
        )
    elif tipo == "oportunidad":
        reporte = fuentes.ultimo_reporte(conn, emisora, db.ahora())
        texto = (
            f"Propón comprar {datos['cantidad_sugerida']} acciones de {c} para el "
            f"portafolio {p}, pagadas con efectivo. Antes revisa los titulares "
            f"recientes de {c} hasta T0"
            + (
                f" y su último reporte ({reporte['doc_id']}), con su nota "
                f"{finanzas.NOTA}"
                if reporte
                else ""
            )
            + ", y calcula el impacto de la compra en el portafolio y la pérdida "
            "bajo todos los escenarios del contexto, simulados en una sola llamada."
        )
    else:
        return None
    return texto, [emisora]


# ═══════════════════════════════════════════
# De la situación (y el comité) a la recomendación
# ═══════════════════════════════════════════


def _cambio_reciente(conn: sqlite3.Connection, emisora: str, sesiones: int = 5):
    tabla = mercado.cierres_mxn(conn, [emisora], _hace(30))
    if emisora not in tabla:
        return None
    serie = tabla[emisora].dropna()
    if len(serie) <= sesiones:
        return None
    return float((serie.iloc[-1] / serie.iloc[-1 - sesiones] - 1) * 100)


def _hace(dias: int) -> str:
    from datetime import timedelta

    return (db.ahora() - timedelta(days=dias)).date().isoformat()


def _base(sit: dict[str, Any], **campos: Any) -> dict[str, Any]:
    return {
        "situacion_id": sit["id"],
        "emisora": sit["emisora"],
        "metricas": {},
        "evidencia": [],
        **campos,
    }


def por_regla(conn: sqlite3.Connection, sit: dict[str, Any]) -> dict[str, Any]:
    """Concentración, estrés, rebalanceo y calendario: la regla basta y la
    cifra se calcula aquí."""
    datos = db.de_json(sit["datos"], {})
    c = _clave(conn, sit["emisora"])
    if sit["tipo"] == "salida":
        q = int(datos["cantidad_sugerida"])
        precio = mercado.ultimo_precio_mxn(conn, sit["emisora"])
        e = estrategia.POR_NOMBRE.get(datos.get("estrategia", ""))
        nombre = e.nombre if e else "la estrategia"
        accion = (
            f"Vende tus {q} títulos de {c}"
            if datos.get("vender_todo")
            else f"Vende {q} títulos de {c}"
        )
        return _base(
            sit,
            origen="regla",
            accion="vender",
            cantidad=q,
            precio_ref=precio[0] if precio else None,
            monto_ref=q * precio[0] if precio else None,
            razon=(
                f"{accion}: {datos.get('motivo', 'rebalanceo')}. Es el rebalanceo "
                f"de {nombre}, la estrategia que elegiste; no es una opinión del "
                "comité."
            ),
            metricas=datos,
            estado="propuesta",
        )
    if sit["tipo"] == "calendario":
        return _base(
            sit,
            origen="regla",
            accion="vigilar",
            razon=(
                f"{c} reporta el {datos['fecha_reporte']} y pesa "
                f"{datos['peso_pct']:.1f}%. Bajo E1 (caída de "
                f"{-REGLAS.choque_e1_pct:.0f}%) perderías "
                f"${datos['perdida_e1']:,.0f}, {datos['perdida_e1_pct_total']:.2f}% "
                "del portafolio. Cuando Yahoo publique el trimestre, el vigía lo "
                "pasa al comité."
            ),
            metricas=datos,
            estado="informativa",
        )
    if sit["tipo"] == "concentracion":
        precio = mercado.ultimo_precio_mxn(conn, sit["emisora"])
        q = int(datos["vender_para_limite"])
        return _base(
            sit,
            origen="regla",
            accion="vender",
            cantidad=q,
            precio_ref=precio[0] if precio else None,
            monto_ref=q * precio[0] if precio else None,
            razon=(
                f"Vende {q} títulos de {c}. Pesa {datos['peso_pct']:.1f}% y el "
                f"límite es {REGLAS.concentracion_max_pct:.0f}%: con esta venta "
                "regresa al límite. Una aprobación no anula un límite duro."
            ),
            metricas=datos,
            estado="propuesta",
        )
    return _base(
        sit,
        origen="regla",
        accion="vigilar",
        razon=(
            f"{c} pesa {datos['peso_pct']:.1f}%. Bajo E1 (caída de "
            f"{-REGLAS.choque_e1_pct:.0f}%) perderías ${datos['perdida_e1']:,.0f}, "
            f"{datos['perdida_e1_pct_total']:.2f}% del portafolio. No compres más "
            f"{c} mientras esté cerca del límite de "
            f"{REGLAS.concentracion_max_pct:.0f}%."
        ),
        metricas=datos,
        estado="informativa",
    )


def _peor_mes(conn: sqlite3.Connection, emisora: str, cantidad: int) -> str:
    """Si la compra suma o resta a la caída del peor mes de tu cartera (E3).

    Informa; no cambia la recomendación (D76).
    """
    e3 = next(
        (e for e in escenarios.perdidas(conn, emisora, cantidad) if e["id"] == "E3"),
        None,
    )
    if e3 is None:
        return ""
    cambio = e3["despues"] - e3["antes"]
    return " En el peor mes de tu cartera del último año (E3), la compra " + (
        f"sumaría ${cambio:,.0f} a la pérdida."
        if cambio > 0
        else f"restaría ${-cambio:,.0f} a la pérdida."
    )


def desde_comite(
    conn: sqlite3.Connection, sit: dict[str, Any], consulta: Consulta
) -> dict[str, Any]:
    """La acción que sigue de la respuesta del comité (decisiones D66 y D67)."""
    emisora = sit["emisora"]
    c = _clave(conn, emisora)
    r = consulta.respuesta
    comun = {
        "origen": "comite",
        "run_id": consulta.run_id,
        "evidencia": consulta.documentos(),
    }
    if r is None or r.estado is pm.EstadoFinal.ERROR_CONTROLADO:
        motivo = consulta.error or (r.error if r else None) or "sin respuesta"
        return _base(
            sit,
            **comun,
            accion="vigilar",
            razon=(
                f"El comité no pudo completar el análisis de {c} ({motivo}). "
                "Revisa la situación tú mismo antes de operar."
            ),
            estado_comite=r.estado.value if r else None,
            resumen_comite=r.resumen if r else None,
            estado="informativa",
        )
    m = dict(r.metricas)
    sentimiento = m.get("sentimiento")
    sentimiento = getattr(sentimiento, "value", sentimiento)
    comun |= {
        "estado_comite": r.estado.value,
        "resumen_comite": r.resumen,
        "metricas": {k: getattr(v, "value", v) for k, v in m.items()},
    }
    if r.dictamen is not None:
        comun |= {
            "decision_riesgo": r.dictamen.decision.value,
            "hash_propuesta": r.dictamen.hash_propuesta,
        }
    precio = mercado.ultimo_precio_mxn(conn, emisora)
    precio_ref = precio[0] if precio else None

    if sit["tipo"] == "oportunidad":
        if r.estado is pm.EstadoFinal.PENDIENTE_REVISION_HUMANA and r.propuesta:
            q = r.propuesta.cantidad
            if sentimiento == "negativo":
                return _base(
                    sit,
                    **comun,
                    accion="vigilar",
                    razon=(
                        f"La compra de {q} {c} cumple la política, pero A1 leyó "
                        "los titulares como negativos: no la haría todavía."
                    ),
                    estado="informativa",
                )
            doc = fuentes.ultimo_reporte(conn, emisora, db.ahora())
            reporte = doc["reporte"] if doc else None
            if finanzas.deterioro_operativo(reporte):
                return _base(
                    sit,
                    **comun,
                    accion="vigilar",
                    razon=(
                        f"La compra de {q} {c} cumple la política, pero en su "
                        f"reporte {reporte['periodo']} caen ingresos y utilidad "
                        "operativa a la vez: no la haría todavía."
                    ),
                    estado="informativa",
                )
            alertas = finanzas.alertas(reporte)
            return _base(
                sit,
                **comun,
                accion="comprar",
                cantidad=q,
                precio_ref=precio_ref,
                monto_ref=q * precio_ref if precio_ref else None,
                razon=(
                    f"Compra {q} títulos de {c} (≈${q * (precio_ref or 0):,.0f}). "
                    "El comité la propone y la revisión de riesgo quedó conforme; "
                    "falta tu aprobación."
                    + _peor_mes(conn, emisora, q)
                    + (
                        " Antes de aprobar, mira las alertas del reporte: "
                        + " ".join(alertas)
                        if alertas
                        else ""
                    )
                ),
                estado="propuesta",
            )
        if r.estado is pm.EstadoFinal.BLOQUEADA:
            motivos = " ".join(r.dictamen.motivos) if r.dictamen else ""
            return _base(
                sit,
                **comun,
                accion="no_operar",
                razon=f"No compres {c}: la revisión de riesgo la bloqueó. {motivos}",
                estado="bloqueada",
            )
        return _base(
            sit,
            **comun,
            accion="vigilar",
            razon=(
                f"El comité no llegó a una propuesta sobre {c} "
                f"({r.estado.value}). No hay nada que operar."
            ),
            estado="informativa",
        )

    if not sit["en_portafolio"]:
        return _base(
            sit,
            **comun,
            accion="vigilar",
            razon=(
                f"No tienes {c}. Si te interesa, pídele al comité una propuesta "
                "de compra en el chat."
            ),
            estado="informativa",
        )

    tenencia = cartera.estado_cantidad(conn, emisora)
    cambio = _cambio_reciente(conn, emisora)
    deterioro = sentimiento == "negativo"
    if sit["tipo"] == "reporte":
        g = m.get("crecimiento_ingresos_pct")
        u = m.get("variacion_utilidad_operativa_pct")
        deterioro = g is not None and u is not None and g < 0 and u < 0
    cae = cambio is not None and cambio <= REGLAS.caida_para_reducir_pct
    if deterioro and cae and tenencia > 0:
        q = max(1, math.ceil(tenencia * REGLAS.reduccion_pct / 100))
        return _base(
            sit,
            **(comun | {"origen": "regla"}),
            accion="vender",
            cantidad=q,
            precio_ref=precio_ref,
            monto_ref=q * precio_ref if precio_ref else None,
            razon=(
                f"Reduce {c}: vende {q} de tus {tenencia} títulos "
                f"({REGLAS.reduccion_pct:.0f}%). El análisis del comité es "
                f"negativo y el precio cayó {cambio:.1f}% en 5 sesiones. Es una "
                "regla de reducción, no la decisión del comité."
            ),
            estado="propuesta",
        )
    if deterioro:
        razon = (
            f"Vigila {c}: el análisis es negativo, pero el precio no ha caído lo "
            f"suficiente para reducir ({cambio or 0:.1f}% en 5 sesiones)."
        )
        accion = "vigilar"
    elif sentimiento == "positivo" or sit["tipo"] == "reporte":
        razon = f"Mantén {c}: el análisis no muestra deterioro."
        accion = "mantener"
    elif cae:
        # Titulares mixtos o neutrales no explican una caída: no basta para
        # vender, pero tampoco es para quedarse quieto.
        razon = (
            f"Vigila {c}: cayó {cambio:.1f}% en 5 sesiones y A1 leyó los titulares "
            f"como {sentimiento or 'sin sentimiento claro'}; no explican la caída."
        )
        accion = "vigilar"
    else:
        razon = (
            f"Mantén {c}: A1 leyó los titulares como "
            f"{sentimiento or 'sin sentimiento claro'}; no hay señal para operar."
        )
        accion = "mantener"
    return _base(sit, **comun, accion=accion, razon=razon, estado="informativa")


def desde_chat(conn: sqlite3.Connection, consulta: Consulta) -> dict[str, Any] | None:
    """Una propuesta del chat, conforme, como recomendación ejecutable.

    Solo una compra que el comité dejó pendiente de revisión humana: la
    misma regla que para las oportunidades del vigía, sin situación de origen.
    """
    r = consulta.respuesta
    if r is None or r.estado is not pm.EstadoFinal.PENDIENTE_REVISION_HUMANA:
        return None
    emisora = consulta.contexto.emisora_de.get(r.propuesta.empresa)
    if emisora is None:
        return None
    sit = {"id": None, "tipo": "oportunidad", "emisora": emisora, "en_portafolio": 0}
    rec = desde_comite(conn, sit, consulta)
    return rec if rec["accion"] == "comprar" else None


def guardar(conn: sqlite3.Connection, rec: dict[str, Any]) -> int:
    """Inserta la recomendación y cierra la situación.

    Una propuesta nueva sobre la misma emisora deja expirada la anterior que
    seguía pendiente: solo una puede llegar a tu aprobación.
    """
    ahora = db.ahora_iso()
    with db.transaccion(conn):
        if rec["estado"] == "propuesta":
            conn.execute(
                "UPDATE recomendaciones SET estado = 'expirada', actualizada = ?, "
                "nota = 'Reemplazada por una recomendación más reciente.' "
                "WHERE emisora = ? AND estado IN ('propuesta', 'aprobada')",
                (ahora, rec["emisora"]),
            )
        cursor = conn.execute(
            """INSERT INTO recomendaciones
               (creada, situacion_id, origen, accion, emisora, cantidad,
                precio_ref, monto_ref, razon, estado_comite, decision_riesgo,
                hash_propuesta, resumen_comite, metricas, evidencia, run_id,
                estado, actualizada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ahora,
                rec.get("situacion_id"),
                rec["origen"],
                rec["accion"],
                rec.get("emisora"),
                rec.get("cantidad"),
                rec.get("precio_ref"),
                round(rec["monto_ref"], 2) if rec.get("monto_ref") else None,
                rec["razon"],
                rec.get("estado_comite"),
                rec.get("decision_riesgo"),
                rec.get("hash_propuesta"),
                rec.get("resumen_comite"),
                db.a_json(rec.get("metricas", {})),
                db.a_json(rec.get("evidencia", [])),
                rec.get("run_id"),
                rec["estado"],
                ahora,
            ),
        )
        if rec.get("situacion_id"):
            conn.execute(
                "UPDATE situaciones SET estado = 'analizada' WHERE id = ?",
                (rec["situacion_id"],),
            )
    return cursor.lastrowid


def expirar(conn: sqlite3.Connection) -> int:
    """Una propuesta vieja se calculó con precios que ya no existen."""
    from datetime import timedelta

    limite = (db.ahora() - timedelta(days=REGLAS.vigencia_dias)).isoformat()
    with db.transaccion(conn):
        cursor = conn.execute(
            "UPDATE recomendaciones SET estado = 'expirada', actualizada = ?, "
            "nota = 'Venció sin ejecutarse.' "
            "WHERE estado IN ('propuesta', 'aprobada') AND creada < ?",
            (db.ahora_iso(), limite),
        )
    return cursor.rowcount


def pendientes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return db.filas(
        conn,
        """SELECT r.*, s.titulo AS situacion, s.tipo AS tipo_situacion,
                  e.clave
           FROM recomendaciones r
           LEFT JOIN situaciones s ON s.id = r.situacion_id
           LEFT JOIN emisoras e ON e.emisora = r.emisora
           WHERE r.estado IN ('propuesta', 'aprobada')
           ORDER BY CASE r.estado WHEN 'aprobada' THEN 0 ELSE 1 END, r.id DESC""",
    )


def recientes(conn: sqlite3.Connection, limite: int = 50) -> list[dict[str, Any]]:
    return db.filas(
        conn,
        """SELECT r.*, s.titulo AS situacion, s.tipo AS tipo_situacion, e.clave
           FROM recomendaciones r
           LEFT JOIN situaciones s ON s.id = r.situacion_id
           LEFT JOIN emisoras e ON e.emisora = r.emisora
           ORDER BY r.id DESC LIMIT ?""",
        limite,
    )
