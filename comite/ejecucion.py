"""El ejecutor: de una recomendación aprobada a una orden en el Reto Actinver.

El reto no tiene API y sus bases no dicen si permiten operar con un
programa. Por eso el ejecutor no entra a tu cuenta: revisa que la orden siga
siendo válida, arma la boleta que capturas en el simulador y, cuando le das
el precio y el folio, la registra en el libro (decisión D68).

Las comprobaciones se repiten al aprobar aunque el comité ya las hizo: la
validación del comité es al corte T0 y entre T0 y tu aprobación el precio,
el efectivo y la cartera pueden haber cambiado.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from comite import cartera, db, mercado
from comite.config import REGLAS


class OrdenInvalida(ValueError):  # noqa: N818 — es un rechazo, no un fallo
    """La recomendación no puede avanzar; el mensaje dice por qué."""


@dataclass(frozen=True)
class Boleta:
    recomendacion_id: int
    operacion: str  # COMPRA | VENTA
    emisora: str
    clave: str
    titulos: int
    precio_actual: float
    precio_limite: float
    importe: float
    fecha_precio: str

    def texto(self) -> str:
        return (
            f"Operación: {self.operacion}\n"
            f"Emisora: {self.clave}  (Yahoo: {self.emisora})\n"
            f"Títulos: {self.titulos:,}\n"
            f"Tipo de orden: limitada, vigencia del día\n"
            f"Precio límite: ${self.precio_limite:,.2f}  "
            f"(último ${self.precio_actual:,.2f} al {self.fecha_precio})\n"
            f"Importe estimado: ${self.importe:,.2f}"
        )


def _recomendacion(conn: sqlite3.Connection, rec_id: int) -> dict[str, Any]:
    rec = db.fila(
        conn,
        """SELECT r.*, e.clave FROM recomendaciones r
           LEFT JOIN emisoras e ON e.emisora = r.emisora WHERE r.id = ?""",
        rec_id,
    )
    if rec is None:
        raise OrdenInvalida(f"No existe la recomendación {rec_id}.")
    return rec


def _cambiar(conn, rec_id: int, estado: str, nota: str | None = None) -> None:
    with db.transaccion(conn):
        conn.execute(
            "UPDATE recomendaciones SET estado = ?, actualizada = ?, "
            "nota = COALESCE(?, nota) WHERE id = ?",
            (estado, db.ahora_iso(), nota, rec_id),
        )


def revisar(conn: sqlite3.Connection, rec: dict[str, Any]) -> Boleta:
    """Las condiciones para operar hoy, recalculadas. Lanza OrdenInvalida."""
    if rec["accion"] not in ("comprar", "vender"):
        raise OrdenInvalida("Solo una compra o una venta se ejecutan.")
    if rec["origen"] == "comite" and not (
        rec["decision_riesgo"] == "conforme"
        and rec["hash_propuesta"]
        and rec["estado_comite"] == "pendiente_revision_humana"
    ):
        raise OrdenInvalida(
            "La propuesta del comité no tiene un dictamen conforme de su versión."
        )
    creada = datetime.fromisoformat(rec["creada"])
    if db.ahora() - creada > timedelta(days=REGLAS.vigencia_dias):
        raise OrdenInvalida(
            f"La recomendación tiene más de {REGLAS.vigencia_dias} días: vuelve a "
            "analizar."
        )
    precio = mercado.ultimo_precio_mxn(conn, rec["emisora"])
    if precio is None:
        raise OrdenInvalida(f"No hay precio de {rec['clave']}: no se puede operar.")
    actual, fecha = precio
    if rec["precio_ref"]:
        deriva = (actual / rec["precio_ref"] - 1) * 100
        if abs(deriva) > REGLAS.deriva_precio_max_pct:
            raise OrdenInvalida(
                f"El precio se movió {deriva:+.1f}% desde la recomendación (límite "
                f"±{REGLAS.deriva_precio_max_pct:.0f}%): vuelve a analizar."
            )
    q = int(rec["cantidad"])
    est = cartera.estado(conn)
    if rec["accion"] == "comprar":
        limite = round(actual * 1.005, 2)
        importe = q * limite
        if importe > est.efectivo:
            raise OrdenInvalida(
                f"La compra cuesta hasta ${importe:,.2f} y tienes "
                f"${est.efectivo:,.2f} de efectivo."
            )
        total = est.total
        if total:
            valor = (est.cantidad(rec["emisora"]) + q) * actual
            peso = valor / total * 100
            if peso > REGLAS.concentracion_max_pct:
                raise OrdenInvalida(
                    f"Con la compra, {rec['clave']} pesaría {peso:.1f}%: pasa el "
                    f"límite de {REGLAS.concentracion_max_pct:.0f}%."
                )
    else:
        limite = round(actual * 0.995, 2)
        importe = q * limite
        tenencia = est.cantidad(rec["emisora"])
        if q > tenencia:
            raise OrdenInvalida(
                f"Quieres vender {q} {rec['clave']} y tienes {tenencia}."
            )
    return Boleta(
        recomendacion_id=rec["id"],
        operacion="COMPRA" if rec["accion"] == "comprar" else "VENTA",
        emisora=rec["emisora"],
        clave=rec["clave"] or mercado.clave_de(rec["emisora"]),
        titulos=q,
        precio_actual=round(actual, 4),
        precio_limite=limite,
        importe=round(importe, 2),
        fecha_precio=fecha,
    )


def aprobar(conn: sqlite3.Connection, rec_id: int) -> Boleta:
    rec = _recomendacion(conn, rec_id)
    if rec["estado"] != "propuesta":
        raise OrdenInvalida(f"La recomendación está {rec['estado']}, no propuesta.")
    boleta = revisar(conn, rec)
    _cambiar(conn, rec_id, "aprobada", "Aprobada por ti; falta capturarla en el reto.")
    return boleta


def boleta(conn: sqlite3.Connection, rec_id: int) -> Boleta:
    """La boleta de una recomendación aprobada, con el precio de ahora."""
    return revisar(conn, _recomendacion(conn, rec_id))


def rechazar(conn: sqlite3.Connection, rec_id: int, nota: str | None = None) -> None:
    rec = _recomendacion(conn, rec_id)
    if rec["estado"] not in ("propuesta", "aprobada"):
        raise OrdenInvalida(f"La recomendación ya está {rec['estado']}.")
    _cambiar(conn, rec_id, "rechazada", nota or "Rechazada por ti.")


def registrar(
    conn: sqlite3.Connection,
    rec_id: int,
    precio: float,
    cantidad: int | None = None,
    folio: str | None = None,
    fecha: str | None = None,
) -> int:
    """La orden ya se ejecutó en el reto: entra al libro y la cartera cambia."""
    rec = _recomendacion(conn, rec_id)
    if rec["estado"] != "aprobada":
        raise OrdenInvalida("Solo se registra una recomendación aprobada.")
    q = int(cantidad or rec["cantidad"])
    if not 0 < q <= rec["cantidad"]:
        raise OrdenInvalida(
            f"Los títulos ejecutados deben estar entre 1 y {rec['cantidad']}."
        )
    if precio <= 0:
        raise OrdenInvalida("El precio de ejecución debe ser positivo.")
    try:
        op_id = cartera.registrar(
            conn,
            fecha=fecha or db.ahora().date().isoformat(),
            lado="compra" if rec["accion"] == "comprar" else "venta",
            emisora=rec["emisora"],
            cantidad=q,
            precio=precio,
            monto=q * precio,
            origen="recomendacion",
            recomendacion_id=rec_id,
            folio=folio,
        )
    except ValueError as error:
        raise OrdenInvalida(str(error)) from error
    _cambiar(
        conn,
        rec_id,
        "ejecutada",
        f"Ejecutada: {q} a ${precio:,.2f}" + (f", folio {folio}" if folio else ""),
    )
    return op_id
