"""Los escenarios de estrés que simula A3, con la historia del reto (D76).

Antes A3 solo tenía dos caídas planas de 10%: E1 en la emisora de la
consulta y E2 en toda la cartera. Sus herramientas no cambian, pero
`simular_escenarios` aplica los choques que le demos, así que aquí se arman
tres más con precios reales hasta hoy:

    E3  tu cartera repite su peor mes del último año, y cada emisora lo que
        hizo en esas mismas fechas. Dice si la compra suma o resta a la
        caída que ya tienes.
    E4  el peso repite su mayor apreciación del último año: las del SIC
        caen eso en pesos.
    E5  la emisora de la consulta repite su peor mes del último año.

Son supuestos históricos, no predicciones. La misma cuenta de A3 se hace aquí
sin el modelo para mostrarla en la app.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd

from comite import cartera, db, mercado
from comite.config import REGLAS


@dataclass(frozen=True)
class Escenario:
    id: str
    # Sin cifras: es lo que A0 ve en el contexto (D65). Las fechas y cifras
    # van en la descripción, que A3 lee al simular.
    titulo: str
    descripcion: str
    choques: dict[str, float]  # ticker de Yahoo → cambio de precio en %


def peor_tramo(
    serie: pd.Series,
    sesiones: int = REGLAS.escenario_sesiones,
    historia: int = REGLAS.escenario_historia,
) -> tuple[pd.Timestamp, pd.Timestamp, float] | None:
    """Inicio, fin y rendimiento del peor tramo de `sesiones` que termina en
    las últimas `historia` sesiones."""
    s = serie.dropna().iloc[-(historia + sesiones) :]
    cambios = (s / s.shift(sesiones) - 1).dropna()
    if cambios.empty:
        return None
    fin = cambios.idxmin()
    inicio = s.index[s.index.get_loc(fin) - sesiones]
    return inicio, fin, float(cambios.min() * 100)


def _fecha(t: pd.Timestamp) -> str:
    return t.date().isoformat()


def historicos(
    conn: sqlite3.Connection,
    cantidades: dict[str, int],
    principal: str | None,
    clave: Callable[[str], str] = mercado.clave_de,
) -> list[Escenario]:
    """E3, E4 y E5; el que no tenga datos suficientes no se arma."""
    involucradas = [e for e in dict.fromkeys([*cantidades, principal]) if e]
    if not involucradas:
        return []
    # Días naturales de sobra para 272 sesiones con los feriados de los dos
    # mercados.
    desde = (db.ahora() - timedelta(days=460)).date().isoformat()
    precios = mercado.cierres_mxn(conn, involucradas, desde).ffill(limit=5)
    salida = []
    if e3 := _peor_mes_cartera(precios, cantidades, principal, involucradas, clave):
        salida.append(e3)
    if e4 := _peso_fuerte(conn, desde, involucradas, clave):
        salida.append(e4)
    if principal and principal in precios:
        tramo = peor_tramo(precios[principal])
        if tramo and tramo[2] < 0:
            inicio, fin, cambio = tramo
            c = clave(principal)
            salida.append(
                Escenario(
                    "E5",
                    f"Peor mes de {c} en el último año (supuesto histórico).",
                    f"{c} repite su peor mes del último año: {cambio:.2f}% del "
                    f"{_fecha(inicio)} al {_fecha(fin)}. El resto de la cartera y "
                    "el efectivo no cambian. Es un supuesto histórico, no una "
                    "predicción ni una probabilidad.",
                    {principal: round(cambio, 2)},
                )
            )
    return salida


def _peor_mes_cartera(precios, cantidades, principal, involucradas, clave):
    tenidas = [e for e in cantidades if e in precios]
    if not tenidas:
        return None
    tabla = precios[tenidas].dropna()
    valor = (tabla * pd.Series(cantidades)[tenidas]).sum(axis=1)
    tramo = peor_tramo(valor)
    if tramo is None or tramo[2] >= 0:
        return None
    inicio, fin, cambio = tramo
    choques = {}
    for e in involucradas:
        if e in precios:
            a, b = precios.at[inicio, e], precios.at[fin, e]
            if pd.notna(a) and pd.notna(b):
                choques[e] = round(float(b / a - 1) * 100, 2)
    texto = (
        f"Cada emisora repite lo que hizo del {_fecha(inicio)} al {_fecha(fin)}, "
        "el peor mes del último año para las acciones que tienes hoy: juntas "
        f"cambiaron {cambio:.2f}%."
    )
    if principal and principal not in cantidades:
        c = clave(principal)
        texto += (
            f" {c} cambió {choques[principal]:+.2f}% en esas fechas."
            if principal in choques
            else f" {c} no cotizaba en esas fechas y queda sin cambio."
        )
    return Escenario(
        "E3",
        "Peor mes de tu cartera en el último año, con lo que hizo cada emisora "
        "en esas fechas (supuesto histórico).",
        texto + " El efectivo no cambia. Es un supuesto histórico, no una "
        "predicción ni una probabilidad.",
        choques,
    )


def _peso_fuerte(conn, desde, involucradas, clave):
    sic = [e for e in involucradas if not mercado.es_bmv(e)]
    fx = mercado.serie_tipo_de_cambio(conn)
    fx = fx[fx.index >= desde]
    tramo = peor_tramo(fx) if sic else None
    if tramo is None or tramo[2] >= 0:
        return None
    inicio, fin, cambio = tramo
    return Escenario(
        "E4",
        "El peso repite su mayor apreciación del último año; las emisoras del "
        "SIC caen eso en pesos (supuesto histórico).",
        f"El dólar pasa de {fx[inicio]:.4f} a {fx[fin]:.4f} pesos ({cambio:.2f}%), "
        f"como del {_fecha(inicio)} al {_fecha(fin)}. Las emisoras del SIC "
        f"({', '.join(clave(e) for e in sic)}) caen eso en pesos con su precio en "
        "dólares sin cambio; las de la BMV y el efectivo no cambian. Es un "
        "supuesto histórico, no una predicción ni una probabilidad.",
        {e: round(cambio, 2) for e in sic},
    )


def todos(
    conn: sqlite3.Connection,
    est: cartera.Estado,
    principal: str | None,
    clave: Callable[[str], str] = mercado.clave_de,
) -> list[Escenario]:
    """E1 y E2, las caídas planas de antes (D65), y los históricos."""
    choque = REGLAS.choque_e1_pct
    salida = []
    if principal:
        c = clave(principal)
        salida.append(
            Escenario(
                "E1",
                f"Caída hipotética de {-choque:g}% en {c}.",
                f"Caída hipotética de {-choque:g}% en {c}; resto del portafolio y "
                "efectivo constantes. Es un supuesto, no una predicción ni una "
                "probabilidad.",
                {principal: choque},
            )
        )
    if est.posiciones:
        salida.append(
            Escenario(
                "E2",
                f"Caída hipotética de {-choque:g}% en todas las acciones.",
                f"Caída hipotética de {-choque:g}% en todas las acciones del "
                "portafolio; efectivo constante. Es un supuesto, no una predicción.",
                {p.emisora: choque for p in est.posiciones},
            )
        )
    cantidades = {p.emisora: p.cantidad for p in est.posiciones}
    return salida + historicos(conn, cantidades, principal, clave)


# ═══════════════════════════════════════════
# La cuenta de A3, sin el modelo
# ═══════════════════════════════════════════


def perdidas(
    conn: sqlite3.Connection,
    emisora: str | None = None,
    cantidad: int = 0,
) -> list[dict[str, Any]]:
    """Pérdida de la cartera bajo cada escenario, hoy y tras comprar.

    Misma fórmula que `simular_escenarios`: la suma de valor por choque, con
    el efectivo constante. Una ganancia sale negativa.
    """
    est = cartera.estado(conn)
    claves = {p.emisora: p.clave for p in est.posiciones}
    escenarios = todos(conn, est, emisora, lambda e: claves.get(e, mercado.clave_de(e)))
    antes = {p.emisora: p.valor or 0.0 for p in est.posiciones}
    despues = dict(antes)
    if emisora and cantidad:
        precio = mercado.ultimo_precio_mxn(conn, emisora)
        if precio is None:
            return []
        despues[emisora] = despues.get(emisora, 0.0) + cantidad * precio[0]
    total = est.total or 0.0

    def perdida(valores: dict[str, float], e: Escenario) -> float:
        # + 0.0: sin exposición la pérdida es 0, no -0.
        return -sum(valores.get(x, 0.0) * c / 100 for x, c in e.choques.items()) + 0.0

    return [
        {
            "id": e.id,
            "titulo": e.titulo,
            "descripcion": e.descripcion,
            "antes": round(perdida(antes, e), 2),
            "despues": round(perdida(despues, e), 2),
            "antes_pct": round(perdida(antes, e) / total * 100, 2) if total else None,
        }
        for e in escenarios
    ]
