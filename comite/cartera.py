"""El portafolio del reto, derivado del libro de operaciones.

Posiciones y efectivo no se guardan: se calculan sumando operaciones. Así
cada cambio tiene fecha, origen y, si vino de una recomendación, su liga; y
el historial de valor se puede reconstruir día por día para compararlo con
los benchmarks (decisión D60).
"""

import sqlite3
from dataclasses import dataclass
from typing import Any

import pandas as pd

from comite import config, db, mercado


@dataclass(frozen=True)
class Posicion:
    emisora: str
    clave: str
    cantidad: int
    costo_promedio: float | None
    precio: float | None
    fecha_precio: str | None

    @property
    def valor(self) -> float | None:
        return None if self.precio is None else self.cantidad * self.precio


@dataclass(frozen=True)
class Estado:
    posiciones: list[Posicion]
    efectivo: float

    @property
    def total(self) -> float | None:
        valores = [p.valor for p in self.posiciones]
        if any(v is None for v in valores):
            return None
        return sum(valores) + self.efectivo

    def peso(self, emisora: str) -> float | None:
        total = self.total
        for p in self.posiciones:
            if p.emisora == emisora and total and p.valor is not None:
                return p.valor / total * 100
        return 0.0 if total else None

    def cantidad(self, emisora: str) -> int:
        return next((p.cantidad for p in self.posiciones if p.emisora == emisora), 0)

    @property
    def emisoras(self) -> list[str]:
        return [p.emisora for p in self.posiciones]


def efectivo(conn: sqlite3.Connection) -> float:
    f = db.fila(
        conn,
        """SELECT COALESCE(SUM(CASE WHEN lado IN ('deposito', 'venta') THEN monto
                                    ELSE -monto END), 0) AS efectivo
           FROM operaciones""",
    )
    return round(f["efectivo"], 2)


def estado(conn: sqlite3.Connection) -> Estado:
    posiciones = db.filas(
        conn,
        """SELECT p.emisora, p.cantidad, p.costo_promedio, e.clave
           FROM posiciones p LEFT JOIN emisoras e USING (emisora)
           ORDER BY p.emisora""",
    )
    precios = mercado.ultimos_precios_mxn(conn, [p["emisora"] for p in posiciones])
    return Estado(
        posiciones=[
            Posicion(
                emisora=p["emisora"],
                clave=p["clave"] or mercado.clave_de(p["emisora"]),
                cantidad=int(p["cantidad"]),
                costo_promedio=p["costo_promedio"],
                precio=precios.get(p["emisora"], (None, None))[0],
                fecha_precio=precios.get(p["emisora"], (None, None))[1],
            )
            for p in posiciones
        ],
        efectivo=efectivo(conn),
    )


def tabla_posiciones(est: Estado) -> pd.DataFrame:
    total = est.total
    filas = []
    for p in est.posiciones:
        filas.append(
            {
                "Emisora": p.clave,
                "Títulos": p.cantidad,
                "Costo promedio": p.costo_promedio,
                "Precio": p.precio,
                "Valor": p.valor,
                "Peso %": (p.valor / total * 100) if total and p.valor else None,
                "Rend. %": (
                    (p.precio / p.costo_promedio - 1) * 100
                    if p.precio and p.costo_promedio
                    else None
                ),
                "Precio al": p.fecha_precio,
            }
        )
    filas.append(
        {
            "Emisora": "Efectivo",
            "Valor": est.efectivo,
            "Peso %": est.efectivo / total * 100 if total else None,
        }
    )
    return pd.DataFrame(filas)


# ═══════════════════════════════════════════
# Escritura
# ═══════════════════════════════════════════


def registrar(
    conn: sqlite3.Connection,
    *,
    fecha: str,
    lado: str,
    monto: float,
    origen: str = "manual",
    emisora: str | None = None,
    cantidad: int | None = None,
    precio: float | None = None,
    recomendacion_id: int | None = None,
    folio: str | None = None,
    nota: str | None = None,
) -> int:
    """Agrega una operación. Una venta no puede dejar la posición negativa y
    una compra no puede dejar el efectivo negativo: el reto no permite corto
    ni apalancamiento."""
    if lado == "venta" and cantidad > estado_cantidad(conn, emisora):
        raise ValueError(
            f"No puedes vender {cantidad} {emisora}: solo tienes "
            f"{estado_cantidad(conn, emisora)}."
        )
    if lado in ("compra", "retiro") and monto > efectivo(conn) + 0.005:
        raise ValueError(
            f"Efectivo insuficiente: la operación cuesta ${monto:,.2f} y hay "
            f"${efectivo(conn):,.2f}."
        )
    with db.transaccion(conn):
        cursor = conn.execute(
            """INSERT INTO operaciones
               (fecha, lado, emisora, cantidad, precio, monto, origen,
                recomendacion_id, folio, nota, creada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fecha,
                lado,
                emisora,
                cantidad,
                precio,
                round(monto, 2),
                origen,
                recomendacion_id,
                folio,
                nota,
                db.ahora_iso(),
            ),
        )
    return cursor.lastrowid


def estado_cantidad(conn: sqlite3.Connection, emisora: str | None) -> int:
    f = db.fila(conn, "SELECT cantidad FROM posiciones WHERE emisora = ?", emisora)
    return int(f["cantidad"]) if f else 0


def cargar_posiciones(
    conn: sqlite3.Connection,
    fecha: str,
    posiciones: list[dict[str, Any]],
    efectivo_actual: float,
) -> None:
    """Reemplaza la carga inicial: posiciones con su costo y el efectivo de hoy.

    Es la forma rápida de capturar la cuenta del reto sin teclear cada
    operación. El depósito se calcula para que el efectivo quede exactamente
    en el valor capturado.
    """
    costo = sum(p["cantidad"] * p["precio"] for p in posiciones)
    with db.transaccion(conn):
        conn.execute("DELETE FROM operaciones WHERE origen = 'inicial'")
        conn.execute(
            """INSERT INTO operaciones (fecha, lado, monto, origen, nota, creada)
               VALUES (?, 'deposito', ?, 'inicial', 'Carga inicial', ?)""",
            (fecha, round(costo + efectivo_actual, 2), db.ahora_iso()),
        )
        for p in posiciones:
            conn.execute(
                """INSERT INTO operaciones
                   (fecha, lado, emisora, cantidad, precio, monto, origen, nota,
                    creada)
                   VALUES (?, 'compra', ?, ?, ?, ?, 'inicial', 'Carga inicial', ?)""",
                (
                    fecha,
                    p["emisora"],
                    int(p["cantidad"]),
                    float(p["precio"]),
                    round(p["cantidad"] * p["precio"], 2),
                    db.ahora_iso(),
                ),
            )


def operaciones(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.DataFrame(db.filas(conn, "SELECT * FROM operaciones ORDER BY fecha, id"))


# ═══════════════════════════════════════════
# Historial contra benchmarks
# ═══════════════════════════════════════════


def historial(conn: sqlite3.Connection) -> pd.DataFrame:
    """Valor diario del portafolio y de los benchmarks, en base 100.

    Empieza el día de la primera operación. Los benchmarks del reto se
    reescalan a 100 ese mismo día para que la comparación sea de rendimiento.
    """
    ops = operaciones(conn)
    if ops.empty:
        return pd.DataFrame()
    inicio = ops["fecha"].min()
    emisoras = sorted(ops["emisora"].dropna().unique())
    precios = mercado.cierres_mxn(conn, emisoras, inicio) if emisoras else None
    fechas = pd.bdate_range(inicio, db.ahora().date().isoformat())
    if precios is not None and not precios.empty:
        fechas = fechas.union(precios.index)
        precios = precios.reindex(fechas).ffill()
    ops["fecha"] = pd.to_datetime(ops["fecha"])
    valores = []
    for dia in fechas:
        hasta = ops[ops["fecha"] <= dia]
        caja = (
            hasta.loc[hasta["lado"].isin(["deposito", "venta"]), "monto"].sum()
            - hasta.loc[hasta["lado"].isin(["compra", "retiro"]), "monto"].sum()
        )
        valor = caja
        for emisora in emisoras:
            de_ella = hasta[hasta["emisora"] == emisora]
            q = (
                de_ella.loc[de_ella["lado"] == "compra", "cantidad"].sum()
                - de_ella.loc[de_ella["lado"] == "venta", "cantidad"].sum()
            )
            if q:
                precio = precios.at[dia, emisora] if emisora in precios else None
                if precio is None or pd.isna(precio):
                    valor = None
                    break
                valor += q * precio
        valores.append(valor)
    tabla = pd.DataFrame({"Mi portafolio": valores}, index=fechas).dropna()
    # Los depósitos posteriores al primero no son rendimiento: se compara el
    # valor contra el capital aportado hasta ese día.
    aportado = pd.Series(
        [
            ops.loc[(ops["fecha"] <= d) & (ops["lado"] == "deposito"), "monto"].sum()
            - ops.loc[(ops["fecha"] <= d) & (ops["lado"] == "retiro"), "monto"].sum()
            for d in tabla.index
        ],
        index=tabla.index,
    )
    tabla["Mi portafolio"] = tabla["Mi portafolio"] / aportado * 100
    bench = mercado.benchmarks(conn)
    if not bench.empty:
        # El reto publica los benchmarks con retraso: después de su último
        # dato la línea se corta en vez de seguir plana.
        ultimo = bench.index.max()
        bench = bench.reindex(bench.index.union(tabla.index)).ffill()
        bench.loc[bench.index > ultimo] = None
        bench = bench.loc[tabla.index.min() :]
        base = bench.iloc[0]
        for nombre in config.BENCHMARKS:
            if nombre in bench:
                tabla[nombre] = bench[nombre] / base[nombre] * 100
    return tabla
