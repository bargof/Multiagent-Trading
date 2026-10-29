"""La ficha de una emisora: precio, tendencia, reporte y calendario (D75).

Todo es aritmética sobre la base y no usa el modelo. Muestra de un vistazo lo
que el comité no ve, la tendencia del precio, junto a lo que A2 lee del
reporte. Las alertas informan; no cambian ninguna recomendación.
"""

import math
import sqlite3
from datetime import date, timedelta
from typing import Any

import pandas as pd

from comite import db, finanzas, fuentes, mercado
from comite.config import REGLAS
from comite.estrategia import MEDIA_TENDENCIA

CAIDA_DESDE_MAXIMO_ALERTA = -20.0


def tecnicos(serie: pd.Series) -> dict[str, Any]:
    s = serie.dropna()
    if len(s) < 2:
        return {}
    ultimo = float(s.iloc[-1])

    def rendimiento(sesiones: int) -> float | None:
        if len(s) <= sesiones:
            return None
        return round((ultimo / float(s.iloc[-1 - sesiones]) - 1) * 100, 2)

    media = (
        float(s.iloc[-MEDIA_TENDENCIA:].mean()) if len(s) >= MEDIA_TENDENCIA else None
    )
    diarios = s.pct_change().dropna().iloc[-60:]
    return {
        "precio": round(ultimo, 4),
        "fecha": s.index[-1].date().isoformat(),
        "rend_1d_pct": rendimiento(1),
        "rend_5d_pct": rendimiento(5),
        "rend_20d_pct": rendimiento(20),
        "rend_60d_pct": rendimiento(60),
        "rend_120d_pct": rendimiento(120),
        "media_200": None if media is None else round(media, 4),
        "distancia_media_pct": (
            None if media is None else round((ultimo / media - 1) * 100, 2)
        ),
        "volatilidad_60d_pct": (
            round(float(diarios.std()) * math.sqrt(252) * 100, 2)
            if len(diarios) >= 20
            else None
        ),
        "caida_desde_maximo_pct": round(
            (ultimo / float(s.iloc[-252:].max()) - 1) * 100, 2
        ),
    }


def alertas_tecnicas(tec: dict[str, Any]) -> list[str]:
    salida = []
    if tec.get("distancia_media_pct") is not None and tec["distancia_media_pct"] < 0:
        salida.append(
            f"Cotiza {abs(tec['distancia_media_pct']):.1f}% abajo de su media de "
            f"{MEDIA_TENDENCIA} sesiones."
        )
    caida = tec.get("caida_desde_maximo_pct")
    if caida is not None and caida <= CAIDA_DESDE_MAXIMO_ALERTA:
        salida.append(f"Está {abs(caida):.1f}% abajo de su máximo de 12 meses.")
    return salida


def proximo_reporte(conn: sqlite3.Connection, emisora: str) -> str | None:
    f = db.fila(conn, "SELECT proximo_reporte FROM emisoras WHERE emisora = ?", emisora)
    return f["proximo_reporte"] if f else None


def reporta_pronto(fecha: str | None, hoy: date, dias: int) -> bool:
    if not fecha:
        return False
    return hoy <= date.fromisoformat(fecha) <= hoy + timedelta(days=dias)


def ficha(conn: sqlite3.Connection, emisora: str) -> dict[str, Any]:
    hoy = db.ahora()
    desde = (hoy - timedelta(days=400)).date().isoformat()
    precios = mercado.cierres_mxn(conn, [emisora], desde)
    tec = tecnicos(precios[emisora]) if emisora in precios else {}
    doc = fuentes.ultimo_reporte(conn, emisora, hoy)
    reporte = doc["reporte"] if doc else None
    fecha_reporte = proximo_reporte(conn, emisora)
    alertas = finanzas.alertas(reporte) + alertas_tecnicas(tec)
    if reporta_pronto(fecha_reporte, hoy.date(), REGLAS.dias_aviso_reporte):
        alertas.append(f"Reporta resultados el {fecha_reporte}.")
    return {
        "emisora": emisora,
        "clave": mercado.clave_de(emisora),
        "tecnicos": tec,
        "doc_id": doc["doc_id"] if doc else None,
        "reporte": reporte,
        "proximo_reporte": fecha_reporte,
        "alertas": alertas,
    }
