"""Indicadores financieros para A2, calculados por el sistema (decisión D73).

A2 tiene tres herramientas fijas en el ejecutable congelado, y
`calcular_indicadores` solo mira ingresos y utilidad operativa. El resto lo
calcula este módulo con los estados trimestrales de yfinance:
- márgenes;
- flujo libre;
- deuda neta contra EBITDA;
- rendimiento sobre capital;
- valuación.

Le llega a A2 como la nota `indicadores_adicionales` del reporte, que lee
con `consultar_nota`. Así A2 sigue sin calcular cifras por su cuenta: las
interpreta, como pide su prompt.
"""

from datetime import date
from typing import Any

NOTA = "indicadores_adicionales"

# Umbrales de las alertas de la ficha. Son informativos: no cambian ninguna
# recomendación (decisión D75).
DEUDA_EBITDA_ALTA = 3.0
CAIDA_MARGEN_PP = 2.0
# Yahoo a veces trae un trimestre mal capturado: una variación así se marca.
VARIACION_ATIPICA_PCT = 200.0


def _millones(valor: float | None) -> float | None:
    return None if valor is None else round(valor / 1e6, 2)


def _cociente(a: float | None, b: float | None, escala: float = 1.0):
    if a is None or b is None or b == 0:
        return None
    return round(a / b * escala, 2)


def _variacion(nuevo: float | None, base: float | None) -> float | None:
    if nuevo is None or base is None or base == 0:
        return None
    return round((nuevo - base) / abs(base) * 100, 2)


def _doce_meses(
    trimestres: dict[str, dict[str, float]], actual: str, partida: str
) -> float | None:
    """La suma de los cuatro trimestres que terminan en `actual`, si están."""
    fechas = sorted(
        (f for f in trimestres if f <= actual and partida in trimestres[f]),
        reverse=True,
    )[:4]
    if len(fechas) < 4 or fechas[0] != actual:
        return None
    if (date.fromisoformat(fechas[0]) - date.fromisoformat(fechas[-1])).days > 300:
        return None  # falta un trimestre en medio
    return sum(trimestres[f][partida] for f in fechas)


def indicadores(
    trimestres: dict[str, dict[str, float]], actual: str, previo: str
) -> dict[str, float | None]:
    """Montos en millones; porcentajes y veces con dos decimales."""
    a, p = trimestres.get(actual, {}), trimestres.get(previo, {})
    flujo_libre = a.get("flujo_libre")
    if flujo_libre is None and a.get("flujo_operativo") is not None:
        if a.get("capex") is not None:
            flujo_libre = a["flujo_operativo"] + a["capex"]  # capex es negativo
    deuda_neta = (
        a["deuda_total"] - a["efectivo"]
        if a.get("deuda_total") is not None and a.get("efectivo") is not None
        else None
    )
    ebitda_12m = _doce_meses(trimestres, actual, "ebitda")
    utilidad_12m = _doce_meses(trimestres, actual, "utilidad_neta")
    return {
        "margen_bruto_pct": _cociente(a.get("utilidad_bruta"), a.get("ingresos"), 100),
        "margen_bruto_anterior_pct": _cociente(
            p.get("utilidad_bruta"), p.get("ingresos"), 100
        ),
        "margen_neto_pct": _cociente(a.get("utilidad_neta"), a.get("ingresos"), 100),
        "margen_neto_anterior_pct": _cociente(
            p.get("utilidad_neta"), p.get("ingresos"), 100
        ),
        "crecimiento_utilidad_neta_pct": _variacion(
            a.get("utilidad_neta"), p.get("utilidad_neta")
        ),
        "flujo_operativo": _millones(a.get("flujo_operativo")),
        "capex": _millones(a.get("capex")),
        "flujo_libre": _millones(flujo_libre),
        "flujo_libre_entre_utilidad_neta": _cociente(
            flujo_libre, a.get("utilidad_neta")
        ),
        "deuda_total": _millones(a.get("deuda_total")),
        "efectivo": _millones(a.get("efectivo")),
        "deuda_neta": _millones(deuda_neta),
        "ebitda_12m": _millones(ebitda_12m),
        "deuda_neta_entre_ebitda_12m": (
            _cociente(deuda_neta, ebitda_12m) if ebitda_12m and ebitda_12m > 0 else None
        ),
        "utilidad_neta_12m": _millones(utilidad_12m),
        "rendimiento_sobre_capital_pct": _cociente(
            utilidad_12m, a.get("capital_contable"), 100
        ),
    }


_ETIQUETAS = {
    "margen_bruto_pct": "margen bruto",
    "margen_neto_pct": "margen neto",
    "crecimiento_utilidad_neta_pct": "variación de la utilidad neta",
    "flujo_libre": "flujo libre",
    "deuda_neta_entre_ebitda_12m": "deuda neta entre EBITDA de 12 meses",
    "rendimiento_sobre_capital_pct": "rendimiento sobre capital",
    "per": "precio entre utilidad",
}


def _num(valor: float) -> str:
    return f"{valor:,.2f}"


def nota(reporte: dict[str, Any]) -> str | None:
    """El texto de la nota para A2: cada cifra con su fórmula y su periodo."""
    ind = reporte.get("indicadores") or {}
    if not ind:
        return None
    actual, previo = reporte["periodo"], reporte["periodo_comparado"]
    unidades = f"{reporte['unidades']} de {reporte['moneda']}"
    lineas = [
        "Indicadores calculados por el sistema con los estados trimestrales de "
        f"Yahoo Finance ({unidades}). No son cifras publicadas por la empresa ni "
        "una recomendación.",
        "",
        f"Rentabilidad ({actual} contra {previo}):",
    ]
    for clave, nombre in (
        ("margen_bruto", "Margen bruto"),
        ("margen_neto", "Margen neto"),
    ):
        nuevo, viejo = ind.get(f"{clave}_pct"), ind.get(f"{clave}_anterior_pct")
        if nuevo is not None and viejo is not None:
            lineas.append(
                f"- {nombre}: {_num(nuevo)}% contra {_num(viejo)}% "
                f"({nuevo - viejo:+.2f} puntos porcentuales)."
            )
        elif nuevo is not None:
            lineas.append(f"- {nombre}: {_num(nuevo)}%.")
    if (variacion := ind.get("crecimiento_utilidad_neta_pct")) is not None:
        atipica = abs(variacion) > VARIACION_ATIPICA_PCT
        lineas.append(
            f"- Variación de la utilidad neta: {variacion:+.2f}%."
            + (
                " Es atípica: puede ser un error de captura de la fuente y "
                "conviene corroborarla con el reporte de la empresa."
                if atipica
                else ""
            )
        )
    if ind.get("flujo_libre") is not None:
        lineas += ["", f"Flujo de efectivo ({actual}):"]
        partes = []
        if ind.get("flujo_operativo") is not None:
            partes.append(f"flujo operativo {_num(ind['flujo_operativo'])}")
        if ind.get("capex") is not None:
            partes.append(f"inversión en activo fijo {_num(ind['capex'])}")
        partes.append(f"flujo libre {_num(ind['flujo_libre'])}")
        lineas.append("- " + "; ".join(partes) + ".")
        if ind.get("flujo_libre_entre_utilidad_neta") is not None:
            lineas.append(
                "- Flujo libre entre utilidad neta: "
                f"{_num(ind['flujo_libre_entre_utilidad_neta'])} veces."
            )
    if ind.get("deuda_neta") is not None:
        lineas += [
            "",
            f"Balance al cierre de {actual}:",
            f"- Deuda total {_num(ind['deuda_total'])}; efectivo "
            f"{_num(ind['efectivo'])}; deuda neta {_num(ind['deuda_neta'])}.",
        ]
        if ind.get("deuda_neta_entre_ebitda_12m") is not None:
            lineas.append(
                "- Deuda neta entre EBITDA de los últimos 4 trimestres "
                f"({_num(ind['ebitda_12m'])}): "
                f"{_num(ind['deuda_neta_entre_ebitda_12m'])} veces."
            )
    if ind.get("rendimiento_sobre_capital_pct") is not None:
        lineas.append(
            "- Rendimiento sobre capital (utilidad neta de 4 trimestres entre "
            f"capital contable): {_num(ind['rendimiento_sobre_capital_pct'])}%."
        )
    val = reporte.get("valuacion") or {}
    partes = []
    if val.get("per") is not None:
        partes.append(f"precio entre utilidad {_num(val['per'])} veces")
    if val.get("precio_valor_libros") is not None:
        partes.append(
            f"precio entre valor en libros {_num(val['precio_valor_libros'])} veces"
        )
    if val.get("dividendo_pct") is not None:
        partes.append(f"dividendo de 12 meses {_num(val['dividendo_pct'])}% del precio")
    if partes:
        fecha = reporte.get("fecha_valuacion", "")[:10]
        lineas += [
            "",
            f"Valuación (Yahoo Finance, al {fecha}): " + "; ".join(partes) + ".",
        ]
    faltan = [n for c, n in _ETIQUETAS.items() if c in ind and ind[c] is None]
    if faltan:
        lineas += ["", "No disponibles en los estados: " + ", ".join(faltan) + "."]
    return "\n".join(lineas)


def alertas(reporte: dict[str, Any] | None) -> list[str]:
    """Señales del reporte para la ficha. No deciden nada (decisión D75)."""
    if not reporte:
        return []
    ind = reporte.get("indicadores") or {}
    partidas = reporte.get("partidas", {})
    actual, previo = reporte["periodo"], reporte["periodo_comparado"]
    salida = []

    def var(partida: str) -> float | None:
        valores = partidas.get(partida, {})
        return _variacion(valores.get(actual), valores.get(previo))

    g, u = var("ingresos"), var("utilidad_operativa")
    if g is not None and u is not None and g < 0 and u < 0:
        salida.append(
            f"Caen ingresos ({g:+.1f}%) y utilidad operativa ({u:+.1f}%) contra "
            f"{previo}."
        )
    if ind.get("flujo_libre") is not None and ind["flujo_libre"] < 0:
        salida.append(f"Flujo libre negativo en {actual}.")
    veces = ind.get("deuda_neta_entre_ebitda_12m")
    if veces is not None and veces > DEUDA_EBITDA_ALTA:
        salida.append(f"Deuda neta de {veces:.1f} veces el EBITDA de 12 meses.")
    nuevo, viejo = ind.get("margen_neto_pct"), ind.get("margen_neto_anterior_pct")
    if nuevo is not None and viejo is not None and nuevo - viejo < -CAIDA_MARGEN_PP:
        salida.append(f"El margen neto bajó {viejo - nuevo:.1f} puntos porcentuales.")
    if ind.get("utilidad_neta_12m") is not None and ind["utilidad_neta_12m"] < 0:
        salida.append("Pérdida neta en los últimos 4 trimestres.")
    return salida


def deterioro_operativo(reporte: dict[str, Any] | None) -> bool:
    """Ingresos y utilidad operativa caen a la vez: la misma señal de D67."""
    if not reporte:
        return False
    return any(a.startswith("Caen ingresos") for a in alertas(reporte))
