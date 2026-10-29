"""El vigía: reglas deterministas que abren situaciones.

No usa el modelo. Detectar que una emisora cayó 6% o que pesa 34% es
aritmética; gastar cuota en eso dejaría menos llamadas para lo que sí
necesita juicio: leer noticias y reportes y revisar riesgo (decisión D64).

Las compras y ventas de la estrategia salen de su ciclo de rebalanceo
(decisión D72). La estrategia es la que elegiste en la app; sin ella el vigía
no propone compras.

Cada situación tiene una clave única (tipo, emisora y día, documento o
ciclo), así que correr el vigía dos veces no la duplica.
"""

import math
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd

from comite import analisis, cartera, db, estrategia, fuentes, mercado
from comite.config import REGLAS


@dataclass
class Situacion:
    clave: str
    emisora: str | None
    en_portafolio: bool
    tipo: str
    severidad: str
    titulo: str
    detalle: str
    datos: dict[str, Any] = field(default_factory=dict)
    evidencia: list[str] = field(default_factory=list)


def _rendimientos(precios: pd.DataFrame, dias: int) -> pd.Series:
    """Cambio % entre el último cierre y el de `dias` sesiones antes."""
    utiles = precios.dropna(how="all")
    if len(utiles) <= dias:
        return pd.Series(dtype=float)
    ultimo = utiles.ffill().iloc[-1]
    base = utiles.ffill().iloc[-1 - dias]
    return ((ultimo / base - 1) * 100).dropna()


# ═══════════════════════════════════════════
# Estrategia: ciclo de rebalanceo y plan
# ═══════════════════════════════════════════


def ciclo_vigente(
    conn: sqlite3.Connection,
    e: estrategia.Estrategia,
    precios: pd.DataFrame,
    hoy,
    est: cartera.Estado,
) -> dict[str, Any]:
    """La cartera objetivo y sus órdenes. Se recalculan cada `rebalanceo`
    sesiones.

    Igual que en el backtest:
    - la señal usa cierres hasta la sesión anterior, porque un cierre de hoy
      a media sesión no decide nada;
    - las órdenes se fijan al empezar el ciclo. Si se recalcularan en cada
      vuelta, un movimiento normal de precio pediría ajustes a media semana
      que la estrategia probada nunca hizo.
    """
    previas = precios[precios.index < pd.Timestamp(hoy.date())]
    ciclo = db.leer_parametro(conn, "ciclo")
    if ciclo and ciclo.get("estrategia") == e.nombre and ciclo.get("senal_al"):
        transcurridas = int((previas.index > pd.Timestamp(ciclo["senal_al"])).sum())
        if transcurridas < e.rebalanceo:
            return ciclo
    # Lo que quedó pendiente del ciclo anterior ya no aplica.
    with db.transaccion(conn):
        conn.execute(
            "UPDATE situaciones SET estado = 'descartada' WHERE estado = 'abierta' "
            "AND tipo IN ('oportunidad', 'salida')"
        )
    senales = estrategia.evaluar(previas, e)
    meta = estrategia.objetivo(previas, e)
    interes = senales.index.isin(list(meta)) | senales.index.isin(est.emisoras)
    detalle = {
        em: {
            "lugar": None if pd.isna(f["lugar"]) else int(f["lugar"]),
            "momentum_pct": None
            if pd.isna(f["momentum_pct"])
            else round(float(f["momentum_pct"]), 2),
            "distancia_media_pct": None
            if pd.isna(f["distancia_media_pct"])
            else round(float(f["distancia_media_pct"]), 2),
            "en_tendencia": bool(f["en_tendencia"]),
        }
        for em, f in senales[interes].iterrows()
    }
    nuevo = {
        "estrategia": e.nombre,
        "inicio": hoy.date().isoformat(),
        "senal_al": previas.index[-1].date().isoformat() if len(previas) else None,
        "objetivo": meta,
        "senales": detalle,
    }
    nuevo["ordenes"] = [asdict(o) for o in plan(conn, nuevo, est)]
    db.guardar_parametro(conn, "ciclo", nuevo)
    return nuevo


@dataclass
class Orden:
    emisora: str
    lado: str  # compra | venta
    cantidad: int
    precio: float
    peso_objetivo_pct: float
    peso_actual_pct: float


def plan(
    conn: sqlite3.Connection, ciclo: dict[str, Any], est: cartera.Estado
) -> list[Orden]:
    """Lo que falta para llegar a la cartera objetivo, a precios de hoy.

    Como en el backtest: cada emisora del objetivo vale su peso del total, lo
    que no está en el objetivo se vende y una orden menor al mínimo no se
    hace. Primero las ventas, que liberan efectivo.
    """
    total = est.total
    if not total:
        return []
    meta = ciclo.get("objetivo", {})
    precios = mercado.ultimos_precios_mxn(conn, [*meta, *est.emisoras])
    minimo = REGLAS.orden_minima_pct / 100 * total
    ordenes = []
    for emisora in dict.fromkeys([*est.emisoras, *meta]):
        if emisora not in precios:
            continue
        precio = precios[emisora][0]
        tenencia = est.cantidad(emisora)
        actual = tenencia * precio
        deseado = meta.get(emisora, 0.0) * total
        diferencia = deseado - actual
        if abs(diferencia) < minimo:
            continue
        if diferencia > 0:
            lado, q = "compra", int(diferencia // precio)
        elif deseado == 0:
            lado, q = "venta", tenencia
        else:
            lado, q = "venta", min(tenencia, math.ceil(-diferencia / precio))
        if q >= 1:
            ordenes.append(
                Orden(
                    emisora,
                    lado,
                    q,
                    precio,
                    round(meta.get(emisora, 0.0) * 100, 2),
                    round(actual / total * 100, 2),
                )
            )
    return sorted(ordenes, key=lambda o: (o.lado != "venta", -o.peso_objetivo_pct))


def _situaciones_estrategia(
    conn: sqlite3.Connection,
    e: estrategia.Estrategia,
    ciclo: dict[str, Any],
    est: cartera.Estado,
    excedida: bool,
    c,
) -> list[Situacion]:
    situaciones = []
    efectivo = est.efectivo
    senales = ciclo.get("senales", {})
    for o in (Orden(**x) for x in ciclo.get("ordenes", [])):
        s = senales.get(o.emisora, {})
        datos = {
            "estrategia": e.nombre,
            "ciclo": ciclo["inicio"],
            "cantidad_sugerida": o.cantidad,
            "precio": round(o.precio, 4),
            "peso_objetivo_pct": o.peso_objetivo_pct,
            "peso_actual_pct": o.peso_actual_pct,
            "lugar": s.get("lugar"),
            "momentum_pct": s.get("momentum_pct"),
            "distancia_media_pct": s.get("distancia_media_pct"),
        }
        if o.lado == "venta":
            fuera = o.peso_objetivo_pct == 0
            if fuera and s.get("lugar") is None:
                motivo = (
                    "no cumple el filtro de la estrategia (tendencia, momentum o "
                    "precio mínimo)"
                )
            elif fuera:
                motivo = f"quedó en el lugar {s['lugar']} y la estrategia toma {e.top}"
            else:
                motivo = (
                    f"pesa {o.peso_actual_pct:.1f}% y su objetivo es "
                    f"{o.peso_objetivo_pct:.1f}%"
                )
            situaciones.append(
                Situacion(
                    clave=f"salida:{o.emisora}:{ciclo['inicio']}",
                    emisora=o.emisora,
                    en_portafolio=True,
                    tipo="salida",
                    severidad="media",
                    titulo=(
                        f"Rebalanceo: vender {o.cantidad} {c(o.emisora)}"
                        + (" (toda la posición)" if fuera else "")
                    ),
                    detalle=f"{c(o.emisora)} {motivo}.",
                    datos=datos | {"vender_todo": fuera, "motivo": motivo},
                )
            )
            continue
        # Con una posición arriba del límite, validar_propuesta bloquea toda
        # compra (mide la cartera resultante completa): proponer una solo
        # gastaría cuota. Primero se corrige la concentración (decisión D64).
        if excedida:
            continue
        # Solo con efectivo para la orden completa, sin contar ventas que aún
        # no registras. Si falta, la compra se propone en una vuelta posterior
        # del mismo ciclo; una compra parcial no se completaría después.
        costo = o.cantidad * o.precio * 1.005
        if costo > efectivo:
            continue
        efectivo -= costo
        situaciones.append(
            Situacion(
                clave=f"oportunidad:{o.emisora}:{ciclo['inicio']}",
                emisora=o.emisora,
                en_portafolio=est.cantidad(o.emisora) > 0,
                tipo="oportunidad",
                severidad="media",
                titulo=(
                    f"Rebalanceo: comprar {o.cantidad} {c(o.emisora)} "
                    f"(lugar {s.get('lugar')})"
                ),
                detalle=(
                    f"Su objetivo es {o.peso_objetivo_pct:.1f}% y hoy pesa "
                    f"{o.peso_actual_pct:.1f}%. Rendimiento de {e.ventana} sesiones: "
                    f"{s.get('momentum_pct') or 0:+.1f}%. Es la regla de la "
                    "estrategia, no una predicción; el comité la revisa."
                ),
                datos=datos,
            )
        )
    return situaciones


# ═══════════════════════════════════════════
# Detección
# ═══════════════════════════════════════════


def detectar(conn: sqlite3.Connection, reglas=REGLAS) -> list[Situacion]:
    hoy = db.ahora()
    dia = hoy.date().isoformat()
    est = cartera.estado(conn)
    total = est.total
    en_cartera = set(est.emisoras)
    claves = {
        f["emisora"]: f["clave"]
        for f in db.filas(conn, "SELECT emisora, clave FROM emisoras")
    }
    universo = [
        f["emisora"]
        for f in db.filas(conn, "SELECT emisora FROM emisoras WHERE con_datos = 1")
    ]
    elegida = estrategia.vigente(conn)
    # La estrategia necesita 200 sesiones para la media; sin ella bastan 60 días.
    dias_historia = 400 if elegida else 60
    desde = (hoy - timedelta(days=dias_historia)).date().isoformat()
    precios = mercado.cierres_mxn(conn, universo, desde)
    r1 = _rendimientos(precios, 1)
    r5 = _rendimientos(precios, 5)
    situaciones: list[Situacion] = []

    def c(e: str) -> str:
        return claves.get(e, mercado.clave_de(e))

    # --- Cartera: concentración y estrés tipo E1 ---
    for p in est.posiciones:
        peso = est.peso(p.emisora)
        if peso is None or total is None:
            continue
        perdida = p.valor * -reglas.choque_e1_pct / 100
        datos = {
            "peso_pct": round(peso, 2),
            "valor": round(p.valor, 2),
            "total": round(total, 2),
            "perdida_e1": round(perdida, 2),
            "perdida_e1_pct_total": round(perdida / total * 100, 2),
        }
        if peso > reglas.concentracion_max_pct:
            exceso = p.valor - total * reglas.concentracion_max_pct / 100
            vender = int(-(-exceso // p.precio))  # hacia arriba: quedar ≤ límite
            situaciones.append(
                Situacion(
                    clave=f"concentracion:{p.emisora}:{dia}",
                    emisora=p.emisora,
                    en_portafolio=True,
                    tipo="concentracion",
                    severidad="alta",
                    titulo=f"{c(p.emisora)} pesa {peso:.1f}% del portafolio",
                    detalle=(
                        f"Supera el límite de {reglas.concentracion_max_pct:.0f}%. "
                        f"Vender {vender} títulos la regresa al límite."
                    ),
                    datos=datos | {"vender_para_limite": vender},
                )
            )
        elif peso > reglas.alerta_concentracion_pct:
            situaciones.append(
                Situacion(
                    clave=f"estres:{p.emisora}:{dia}",
                    emisora=p.emisora,
                    en_portafolio=True,
                    tipo="estres",
                    severidad="media",
                    titulo=(
                        f"E1: una caída de {-reglas.choque_e1_pct:.0f}% en "
                        f"{c(p.emisora)} costaría ${perdida:,.0f}"
                    ),
                    detalle=(
                        f"{c(p.emisora)} pesa {peso:.1f}%; la pérdida sería "
                        f"{datos['perdida_e1_pct_total']:.2f}% del total. Es un "
                        "supuesto, no una predicción."
                    ),
                    datos=datos,
                )
            )

    # --- Cartera: movimientos de precio ---
    for e in en_cartera:
        d1, d5 = r1.get(e), r5.get(e)
        if d1 is not None and abs(d1) >= reglas.movimiento_dia_pct:
            movimiento, dias = d1, 1
        elif d5 is not None and abs(d5) >= reglas.movimiento_semana_pct:
            movimiento, dias = d5, 5
        else:
            continue
        situaciones.append(
            Situacion(
                clave=f"precio:{e}:{dia}",
                emisora=e,
                en_portafolio=True,
                tipo="precio",
                severidad="alta"
                if movimiento <= -reglas.movimiento_semana_pct
                else "media",
                titulo=(
                    f"{c(e)} {'cayó' if movimiento < 0 else 'subió'} "
                    f"{abs(movimiento):.1f}% en {dias} "
                    f"{'sesión' if dias == 1 else 'sesiones'}"
                ),
                detalle="Movimiento de precio de una posición de la cartera.",
                datos={"cambio_pct": round(movimiento, 2), "sesiones": dias},
            )
        )

    # --- Cartera: noticias, reportes y calendario ---
    for e in en_cartera:
        titulares = fuentes.titulares_recientes(conn, e, hoy, dias=3)
        if titulares:
            situaciones.append(
                Situacion(
                    clave=f"noticias:{e}:{dia}",
                    emisora=e,
                    en_portafolio=True,
                    tipo="noticias",
                    severidad="media",
                    titulo=f"{len(titulares)} titulares recientes de {c(e)}",
                    detalle=titulares[0]["titulo"],
                    evidencia=[t["doc_id"] for t in titulares],
                )
            )
        reporte = fuentes.ultimo_reporte(conn, e, hoy)
        if reporte:
            fin = pd.Timestamp(reporte["reporte"]["fin_periodo"])
            if (pd.Timestamp(dia) - fin).days <= 75:
                situaciones.append(
                    Situacion(
                        clave=f"reporte:{reporte['doc_id']}",
                        emisora=e,
                        en_portafolio=True,
                        tipo="reporte",
                        severidad="media",
                        titulo=f"Reporte {reporte['reporte']['periodo']} de {c(e)}",
                        detalle=(
                            "Comparado contra "
                            f"{reporte['reporte']['periodo_comparado']} "
                            f"({reporte['reporte']['comparacion']})."
                        ),
                        evidencia=[reporte["doc_id"]],
                    )
                )
        fecha = analisis.proximo_reporte(conn, e)
        if total and analisis.reporta_pronto(
            fecha, hoy.date(), reglas.dias_aviso_reporte
        ):
            p = next(x for x in est.posiciones if x.emisora == e)
            perdida = (p.valor or 0) * -reglas.choque_e1_pct / 100
            situaciones.append(
                Situacion(
                    clave=f"calendario:{e}:{fecha}",
                    emisora=e,
                    en_portafolio=True,
                    tipo="calendario",
                    severidad="media",
                    titulo=f"{c(e)} reporta resultados el {fecha}",
                    detalle=(
                        f"Pesa {est.peso(e) or 0:.1f}%. Si cae "
                        f"{-reglas.choque_e1_pct:.0f}% (E1) perderías "
                        f"${perdida:,.0f}."
                    ),
                    datos={
                        "fecha_reporte": fecha,
                        "peso_pct": round(est.peso(e) or 0, 2),
                        "perdida_e1": round(perdida, 2),
                        "perdida_e1_pct_total": round(perdida / total * 100, 2),
                    },
                )
            )

    # --- Fuera de la cartera: destacadas ---
    for e, d1 in r1.items():
        if e in en_cartera or abs(d1) < reglas.destacada_dia_pct:
            continue
        situaciones.append(
            Situacion(
                clave=f"destacada:{e}:{dia}",
                emisora=e,
                en_portafolio=False,
                tipo="destacada",
                severidad="baja",
                titulo=f"{c(e)} {'cayó' if d1 < 0 else 'subió'} {abs(d1):.1f}% hoy",
                detalle="Movimiento fuerte de una emisora del reto que no tienes.",
                datos={"cambio_pct": round(d1, 2)},
            )
        )

    # --- Estrategia: el rebalanceo del ciclo ---
    if elegida is not None and total:
        excedida = any(
            (est.peso(p.emisora) or 0) > reglas.concentracion_max_pct
            for p in est.posiciones
        )
        ciclo = ciclo_vigente(conn, elegida, precios, hoy, est)
        situaciones += _situaciones_estrategia(conn, elegida, ciclo, est, excedida, c)
    return situaciones


def guardar(conn: sqlite3.Connection, situaciones: list[Situacion]) -> int:
    """Inserta las nuevas; las que ya existen (misma clave) se ignoran."""
    nuevas = 0
    with db.transaccion(conn):
        for s in situaciones:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO situaciones
                   (clave, detectada, emisora, en_portafolio, tipo, severidad,
                    titulo, detalle, datos, evidencia)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    s.clave,
                    db.ahora_iso(),
                    s.emisora,
                    int(s.en_portafolio),
                    s.tipo,
                    s.severidad,
                    s.titulo,
                    s.detalle,
                    db.a_json(s.datos),
                    db.a_json(s.evidencia),
                ),
            )
            nuevas += cursor.rowcount
    return nuevas


def abiertas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Por severidad y, dentro de ella, primero la cartera y lo más reciente."""
    return db.filas(
        conn,
        """SELECT * FROM situaciones WHERE estado = 'abierta'
           ORDER BY CASE severidad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END,
                    en_portafolio DESC, detectada DESC, id DESC""",
    )


def descartar_viejas(conn: sqlite3.Connection, dias: int = 3) -> int:
    """Una situación de precio de hace días ya no describe el mercado de hoy.

    Las del rebalanceo valen mientras dure su ciclo: la compra que esperaba
    efectivo no debe perderse porque tardaste en registrar una venta.
    """
    limite = (db.ahora() - timedelta(days=dias)).isoformat()
    with db.transaccion(conn):
        cursor = conn.execute(
            "UPDATE situaciones SET estado = 'descartada' "
            "WHERE estado = 'abierta' AND detectada < ? "
            "AND tipo NOT IN ('oportunidad', 'salida')",
            (limite,),
        )
    return cursor.rowcount
