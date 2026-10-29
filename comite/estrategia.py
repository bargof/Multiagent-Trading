"""La estrategia de inversión: qué cartera tener, con una regla fija.

El backtest y el vigía usan este mismo código. Lo que se validó con el
historial del reto es exactamente lo que la app recomienda (decisiones D71 y
D72).

Cada estrategia elige N emisoras por su rendimiento de las últimas sesiones
(momentum) y les da 1/N del portafolio a cada una. Con filtro de tendencia,
solo entran emisoras arriba de su media de 200 sesiones y con momentum
positivo. Si no alcanzan N, lo que sobra se queda en efectivo: así la
estrategia se sale del mercado cuando casi nada sube.
"""

import sqlite3
from dataclasses import dataclass

import pandas as pd

from comite import config, db, mercado
from comite.config import REGLAS

MEDIA_TENDENCIA = 200


@dataclass(frozen=True)
class Estrategia:
    nombre: str
    descripcion: str
    top: int  # 0 = todo el universo elegible a igual peso
    ventana: int  # sesiones de momentum
    rebalanceo: int  # sesiones entre rebalanceos
    tendencia: bool = False
    confirmacion: int = 0  # sesiones recientes que deben sumar positivo

    @property
    def historia_minima(self) -> int:
        return max(
            self.ventana,
            MEDIA_TENDENCIA if self.tendencia else 0,
            self.confirmacion,
        )


# Fijadas en D71 antes de correr la comparación.
CANDIDATAS = (
    Estrategia(
        "regla_actual",
        "Las 3 mejores por 20 sesiones con 5 sesiones positivas; cada 20 sesiones "
        "(la regla de oportunidades de D64).",
        top=3,
        ventana=20,
        rebalanceo=20,
        confirmacion=5,
    ),
    Estrategia(
        "momentum_120_top10",
        "Las 10 mejores por 120 sesiones; cada 60 sesiones.",
        top=10,
        ventana=120,
        rebalanceo=60,
    ),
    Estrategia(
        "momentum_120_top10_tendencia",
        "Las 10 mejores por 120 sesiones, solo arriba de su media de 200; cada "
        "60 sesiones.",
        top=10,
        ventana=120,
        rebalanceo=60,
        tendencia=True,
    ),
    Estrategia(
        "momentum_60_top10_tendencia",
        "Las 10 mejores por 60 sesiones, solo arriba de su media de 200; cada "
        "20 sesiones.",
        top=10,
        ventana=60,
        rebalanceo=20,
        tendencia=True,
    ),
    Estrategia(
        "momentum_120_top15_tendencia",
        "Las 15 mejores por 120 sesiones, solo arriba de su media de 200; cada "
        "60 sesiones.",
        top=15,
        ventana=120,
        rebalanceo=60,
        tendencia=True,
    ),
)
# Referencia, no candidata: serían unas 200 órdenes a mano por rebalanceo.
IGUAL_PESO = Estrategia(
    "igual_peso_universo",
    "Todo el universo elegible a igual peso; cada 60 sesiones.",
    top=0,
    ventana=0,
    rebalanceo=60,
)

POR_NOMBRE = {e.nombre: e for e in (*CANDIDATAS, IGUAL_PESO)}


def vigente(conn: sqlite3.Connection) -> Estrategia | None:
    """La que elegiste en la app; sin elección, ninguna (decisión D72)."""
    return POR_NOMBRE.get(db.leer_parametro(conn, "estrategia") or "")


def elegir(conn: sqlite3.Connection, nombre: str | None) -> None:
    if nombre is not None and nombre not in POR_NOMBRE:
        raise ValueError(f"No conozco la estrategia {nombre!r}.")
    db.guardar_parametro(conn, "estrategia", nombre)
    # Otra estrategia es otro ciclo: el siguiente recorrido rebalancea, y lo
    # pendiente de la anterior ya no aplica.
    db.guardar_parametro(conn, "ciclo", None)
    with db.transaccion(conn):
        conn.execute(
            "UPDATE situaciones SET estado = 'descartada' WHERE estado = 'abierta' "
            "AND tipo IN ('oportunidad', 'salida')"
        )


def evaluar(precios: pd.DataFrame, estrategia: Estrategia) -> pd.DataFrame:
    """Señales de cada emisora con los cierres dados, el último es el corte.

    `precios` va en pesos, una columna por emisora y una fila por sesión. Un
    hueco de hasta 5 sesiones (feriados de la BMV o de EUA) se llena con el
    cierre anterior; uno más largo deja a la emisora fuera.
    """
    columnas = [
        "momentum_pct",
        "confirmacion_pct",
        "media_200",
        "distancia_media_pct",
        "en_tendencia",
        "elegible",
        "lugar",
        "peso_objetivo",
    ]
    n = estrategia.historia_minima
    if len(precios) <= n:
        return pd.DataFrame(columns=columnas)
    tabla = precios.ffill(limit=5)
    ultimo = tabla.iloc[-1]
    senales = pd.DataFrame(index=tabla.columns)
    if estrategia.ventana:
        senales["momentum_pct"] = (
            ultimo / tabla.iloc[-1 - estrategia.ventana] - 1
        ) * 100
    else:
        senales["momentum_pct"] = 0.0
    if estrategia.confirmacion:
        senales["confirmacion_pct"] = (
            ultimo / tabla.iloc[-1 - estrategia.confirmacion] - 1
        ) * 100
    else:
        senales["confirmacion_pct"] = float("nan")
    if len(tabla) >= MEDIA_TENDENCIA:
        ventana_media = tabla.iloc[-MEDIA_TENDENCIA:]
        # Una media con muchos huecos no describe la tendencia.
        completa = ventana_media.notna().sum() >= MEDIA_TENDENCIA * 0.9
        senales["media_200"] = ventana_media.mean().where(completa)
    else:
        senales["media_200"] = float("nan")
    senales["distancia_media_pct"] = (ultimo / senales["media_200"] - 1) * 100
    senales["en_tendencia"] = (senales["distancia_media_pct"] > 0) & (
        senales["momentum_pct"] > 0
    )
    elegible = (
        ultimo.notna()
        & (ultimo >= REGLAS.precio_minimo_mxn)
        & senales["momentum_pct"].notna()
        & ~pd.Series(
            [mercado.clave_de(e) in config.NO_OPORTUNIDAD for e in tabla.columns],
            index=tabla.columns,
        )
    )
    if estrategia.tendencia:
        elegible &= senales["en_tendencia"]
    if estrategia.confirmacion:
        elegible &= senales["confirmacion_pct"] > 0
    senales["elegible"] = elegible
    senales["lugar"] = (
        senales["momentum_pct"].where(elegible).rank(ascending=False, method="first")
    )
    if estrategia.top:
        elegidas = senales["lugar"] <= estrategia.top
        peso = 1 / estrategia.top
    else:
        elegidas = elegible
        peso = 1 / max(int(elegible.sum()), 1)
    senales["peso_objetivo"] = elegidas.astype(float) * peso
    return senales.sort_values(["lugar", "momentum_pct"], ascending=[True, False])


def objetivo(precios: pd.DataFrame, estrategia: Estrategia) -> dict[str, float]:
    """Emisora → peso objetivo. La suma puede ser menor que 1: el resto es
    efectivo."""
    senales = evaluar(precios, estrategia)
    if senales.empty:
        return {}
    elegidas = senales[senales["peso_objetivo"] > 0]
    return {e: float(p) for e, p in elegidas["peso_objetivo"].items()}
