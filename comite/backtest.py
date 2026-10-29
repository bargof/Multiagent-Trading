"""Backtest de las estrategias con el historial del reto (decisión D71).

Las mismas funciones de `estrategia` deciden la cartera; aquí solo se simula
el paso del tiempo:
- la señal usa cierres hasta la sesión anterior y se opera al cierre;
- cada operación cuesta COSTO_PCT del monto, que es un supuesto;
- se permiten fracciones de título.

Lo que no corrige: el universo es la lista de 2026 (sesgo de
supervivencia) y los cierres no incluyen dividendos.
"""

import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from comite import config, mercado
from comite.config import REGLAS
from comite.estrategia import CANDIDATAS, IGUAL_PESO, Estrategia, objetivo

COSTO_PCT = 0.25
FIN_ENTRENAMIENTO = pd.Timestamp("2025-09-30")
# Una orden menor a esto no vale la comisión ni la captura.
ORDEN_MINIMA = REGLAS.orden_minima_pct / 100


@dataclass
class Simulacion:
    estrategia: Estrategia
    valor: pd.Series  # base 100
    ordenes: pd.Series  # órdenes por fecha de rebalanceo
    pesos: dict[pd.Timestamp, dict[str, float]] = field(default_factory=dict)


def cargar(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cierres en pesos del universo con datos y los benchmarks del reto."""
    if len(mercado.serie_tipo_de_cambio(conn)) < 100:
        # Sin USDMXN las emisoras del SIC quedan sin precio en pesos y el
        # backtest sería solo de la BMV. Así salió mi primera corrida (D72).
        raise ValueError(
            "Falta el historial de USDMXN: el backtest dejaría fuera al SIC."
        )
    universo = [e for e in mercado.emisoras(conn)["emisora"] if e != config.TIPO_CAMBIO]
    precios = mercado.cierres_mxn(conn, universo, config.HISTORIA_DESDE)
    return precios.dropna(how="all"), mercado.benchmarks(conn)


def inicio_comun(precios: pd.DataFrame, estrategias: list[Estrategia]) -> int:
    """La primera sesión en la que todas tienen la historia que necesitan."""
    return max(e.historia_minima for e in estrategias) + 1


def simular(
    precios: pd.DataFrame,
    estrategia: Estrategia,
    inicio: int,
    costo_pct: float = COSTO_PCT,
) -> Simulacion:
    senal_base = precios
    valuacion = precios.ffill().to_numpy()
    fechas = precios.index
    titulos = np.zeros(precios.shape[1])
    efectivo = 100.0
    valores, ordenes, pesos = [], {}, {}
    for i in range(inicio, len(fechas)):
        hoy = np.nan_to_num(valuacion[i])
        if (i - inicio) % estrategia.rebalanceo == 0:
            # Solo cierres hasta ayer: hoy se opera al cierre, sin verlo antes.
            meta = objetivo(senal_base.iloc[:i], estrategia)
            total = efectivo + float(titulos @ hoy)
            deseado = np.zeros_like(titulos)
            for j, emisora in enumerate(precios.columns):
                if emisora in meta and hoy[j] > 0:
                    deseado[j] = meta[emisora] * total / hoy[j]
            cambio = (deseado - titulos) * hoy
            grandes = np.abs(cambio) >= ORDEN_MINIMA * total
            deseado = np.where(grandes, deseado, titulos)
            cambio = np.where(grandes, cambio, 0.0)
            costo = float(np.abs(cambio).sum()) * costo_pct / 100
            efectivo += -float(cambio.sum()) - costo
            titulos = deseado
            ordenes[fechas[i]] = int(grandes.sum())
            pesos[fechas[i]] = meta
        valores.append(efectivo + float(titulos @ hoy))
    valor = pd.Series(valores, index=fechas[inicio:], name=estrategia.nombre)
    return Simulacion(
        estrategia=estrategia,
        valor=valor / valor.iloc[0] * 100,
        ordenes=pd.Series(ordenes, dtype=int),
        pesos=pesos,
    )


def metricas(serie: pd.Series) -> dict[str, float]:
    serie = serie.dropna()
    if len(serie) < 2:
        return {}
    anios = (serie.index[-1] - serie.index[0]).days / 365.25
    total = serie.iloc[-1] / serie.iloc[0] - 1
    diarios = serie.pct_change().dropna()
    sesiones_por_anio = len(diarios) / anios if anios else 252
    caida = (serie / serie.cummax() - 1).min()
    anual = (1 + total) ** (1 / anios) - 1 if anios else float("nan")
    return {
        "rendimiento_pct": round(total * 100, 2),
        "anual_pct": round(anual * 100, 2),
        "volatilidad_pct": round(diarios.std() * np.sqrt(sesiones_por_anio) * 100, 2),
        "caida_maxima_pct": round(caida * 100, 2),
        "anual_entre_caida": round(anual / abs(caida), 3) if caida else float("nan"),
    }


@dataclass
class Comparacion:
    series: pd.DataFrame  # base 100 desde el inicio común
    tabla: pd.DataFrame  # métricas por estrategia y periodo
    elegida: str
    inicio: pd.Timestamp
    fin_entrenamiento: pd.Timestamp
    simulaciones: dict[str, Simulacion]


def _tramo(serie: pd.Series, desde=None, hasta=None) -> pd.Series:
    tramo = serie.loc[desde:hasta].dropna()
    return tramo / tramo.iloc[0] * 100 if not tramo.empty else tramo


def comparar(
    precios: pd.DataFrame,
    benchmarks: pd.DataFrame,
    fin_entrenamiento: pd.Timestamp = FIN_ENTRENAMIENTO,
    costo_pct: float = COSTO_PCT,
) -> Comparacion:
    """Candidatas y referencias con el mismo inicio, en entrenamiento y prueba."""
    todas = [*CANDIDATAS, IGUAL_PESO]
    inicio = inicio_comun(precios, todas)
    sims = {e.nombre: simular(precios, e, inicio, costo_pct) for e in todas}
    series = pd.DataFrame({n: s.valor for n, s in sims.items()})
    desde = series.index[0]
    for nombre in config.BENCHMARKS:
        if nombre in benchmarks:
            b = benchmarks[nombre].loc[desde:].dropna()
            if not b.empty:
                series[nombre] = b / b.iloc[0] * 100
    filas = []
    prueba_desde = fin_entrenamiento + pd.Timedelta(days=1)
    for nombre in series:
        sim = sims.get(nombre)
        anios_entrenamiento = max((fin_entrenamiento - desde).days / 365.25, 1 / 365.25)
        for periodo, tramo in (
            ("entrenamiento", _tramo(series[nombre], hasta=fin_entrenamiento)),
            ("prueba", _tramo(series[nombre], desde=prueba_desde)),
            ("completo", _tramo(series[nombre])),
        ):
            fila = {"estrategia": nombre, "periodo": periodo, **metricas(tramo)}
            if sim is not None:
                ordenes = (
                    sim.ordenes.loc[:fin_entrenamiento]
                    if periodo == "entrenamiento"
                    else sim.ordenes.loc[prueba_desde:]
                    if periodo == "prueba"
                    else sim.ordenes
                )
                fila["ordenes"] = int(ordenes.sum())
                fila["ordenes_por_rebalanceo"] = (
                    round(float(ordenes.mean()), 1) if len(ordenes) else 0.0
                )
                if periodo == "entrenamiento":
                    fila["ordenes_por_anio"] = round(
                        int(ordenes.sum()) / anios_entrenamiento, 1
                    )
            fila["candidata"] = nombre in {e.nombre for e in CANDIDATAS}
            filas.append(fila)
    tabla = pd.DataFrame(filas)
    return Comparacion(
        series=series,
        tabla=tabla,
        elegida=elegir(tabla),
        inicio=desde,
        fin_entrenamiento=fin_entrenamiento,
        simulaciones=sims,
    )


def elegir(tabla: pd.DataFrame) -> str:
    """El criterio de D71: el mayor rendimiento anual entre caída máxima en
    entrenamiento; en empate, el de menos órdenes."""
    entrenamiento = tabla[(tabla["periodo"] == "entrenamiento") & tabla["candidata"]]
    orden = entrenamiento.sort_values(
        ["anual_entre_caida", "ordenes"], ascending=[False, True]
    )
    return str(orden.iloc[0]["estrategia"])
