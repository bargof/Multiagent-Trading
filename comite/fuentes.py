"""Noticias y reportes trimestrales de fuentes gratuitas.

Noticias: Google News RSS en español de México. No pide key y trae titular,
medio, liga y fecha; el resumen viene vacío y no extraigo el texto de los
artículos (sería raspar sitios ajenos). A1 trabaja con titulares, y su regla
de no agregar hechos que el texto no contenga sigue valiendo (decisión D63).

Reportes: estados trimestrales de yfinance (resultados, balance y flujo de
efectivo). No dicen cuándo se publicaron, así que la fecha de publicación se
estima y queda marcada como estimada: el corte T0 del comité la sigue
respetando. Con ellos `finanzas` calcula los indicadores que A2 lee en una
nota del reporte (decisión D73).

Calendario: la fecha del próximo reporte de yfinance (decisión D74).

Toda lectura de red tiene un límite de tiempo: el monitor corre solo y una
respuesta que nunca llega no debe detenerlo.
"""

import hashlib
import logging
import re
import sqlite3
import threading
import unicodedata
import urllib.parse
import warnings
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from comite import config, db, finanzas
from comite.mercado import clave_de, es_bmv, nombre_limpio

# (consulta, idioma) → titulares: dicts con titulo, fuente, url, fecha (aware).
LeerTitulares = Callable[[str, str], list[dict[str, Any]]]
# emisora → {"moneda": str, "trimestres": {fecha_fin: {partida: valor}}} o None.
LeerEstados = Callable[[str], dict[str, Any] | None]
# emisora → nombre corto de Yahoo o None.
LeerNombre = Callable[[str], str | None]
# emisora → fecha AAAA-MM-DD del reporte que anuncia el calendario, o None.
LeerCalendario = Callable[[str], str | None]

_RSS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
_IDIOMAS = {
    "es": {"hl": "es-419", "gl": "MX", "ceid": "MX:es-419"},
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
}

_CONTEXTO_FINANCIERO = {
    "es": "(acciones OR bolsa OR BMV OR resultados OR utilidad OR ingresos OR "
    "inversionistas OR analistas)",
    "en": "(stock OR shares OR earnings OR revenue OR analysts)",
}

# Nombres de partida de yfinance → los del reporte. calcular_indicadores lee
# ingresos y utilidad_operativa; el resto lo ve A2 en obtener_reporte y en la
# nota de indicadores.
PARTIDAS_RESULTADOS = {
    "ingresos": ("Total Revenue", "Operating Revenue"),
    "utilidad_bruta": ("Gross Profit",),
    "utilidad_operativa": ("Operating Income", "Total Operating Income As Reported"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "utilidad_neta": ("Net Income", "Net Income Common Stockholders"),
}
PARTIDAS_BALANCE = {
    "efectivo": (
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ),
    "deuda_total": ("Total Debt",),
    "capital_contable": ("Stockholders Equity", "Common Stock Equity"),
}
PARTIDAS_FLUJO = {
    "flujo_operativo": ("Operating Cash Flow",),
    "capex": ("Capital Expenditure",),
    "flujo_libre": ("Free Cash Flow",),
}
PARTIDAS = PARTIDAS_RESULTADOS | PARTIDAS_BALANCE | PARTIDAS_FLUJO
# Días entre el cierre del trimestre y la publicación estimada. La BMV da 20
# días hábiles y la SEC 40 días naturales; 30 es un punto medio.
DIAS_PUBLICACION = 30


# ═══════════════════════════════════════════
# Lectores reales (red)
# ═══════════════════════════════════════════


def con_limite(funcion: Callable[..., Any], *args: Any, segundos: float = 45) -> Any:
    """Llama a `funcion` y se rinde a los `segundos`.

    El hilo es daemon: si la red nunca responde se queda colgado él, no el
    monitor ni la app.
    """
    resultado: dict[str, Any] = {}

    def correr() -> None:
        try:
            resultado["valor"] = funcion(*args)
        except BaseException as error:  # noqa: BLE001 — se relanza abajo
            resultado["error"] = error

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    hilo.join(segundos)
    if hilo.is_alive():
        nombre = getattr(funcion, "__name__", "lectura")
        raise TimeoutError(f"{nombre} no respondió en {segundos:.0f} s")
    if "error" in resultado:
        raise resultado["error"]
    return resultado.get("valor")


def titulares_google_news(consulta: str, idioma: str = "es") -> list[dict[str, Any]]:
    import feedparser

    url = _RSS.format(q=urllib.parse.quote(consulta), **_IDIOMAS[idioma])
    feed = feedparser.parse(url, agent="comite-inversion/0.1")
    titulares = []
    for entrada in feed.entries:
        fecha = entrada.get("published_parsed")
        if not fecha or not entrada.get("link"):
            continue
        fuente = (entrada.get("source") or {}).get("title") or "Google News"
        titulares.append(
            {
                "titulo": _sin_medio(entrada.get("title", ""), fuente),
                "fuente": fuente,
                "url": entrada["link"],
                "fecha": datetime(*fecha[:6], tzinfo=UTC),
            }
        )
    return titulares


def _partidas(
    tabla: pd.DataFrame | None,
    partidas: dict[str, tuple[str, ...]],
    trimestres: dict[str, dict[str, float]],
) -> None:
    if tabla is None or tabla.empty:
        return
    for columna in tabla.columns:
        fecha = pd.Timestamp(columna).date().isoformat()
        for partida, nombres in partidas.items():
            for nombre in nombres:
                if nombre in tabla.index and pd.notna(tabla.at[nombre, columna]):
                    trimestres.setdefault(fecha, {})[partida] = float(
                        tabla.at[nombre, columna]
                    )
                    break


def estados_yfinance(emisora: str) -> dict[str, Any] | None:
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ticker = yf.Ticker(emisora)
        resultados = ticker.quarterly_income_stmt
        if resultados is None or resultados.empty:
            return None
        trimestres: dict[str, dict[str, float]] = {}
        _partidas(resultados, PARTIDAS_RESULTADOS, trimestres)
        # Balance y flujo enriquecen el reporte; sin ellos sigue sirviendo.
        for leer_tabla, partidas in (
            (lambda: ticker.quarterly_balance_sheet, PARTIDAS_BALANCE),
            (lambda: ticker.quarterly_cashflow, PARTIDAS_FLUJO),
        ):
            try:
                _partidas(leer_tabla(), partidas, trimestres)
            except Exception:  # noqa: BLE001, S110
                pass
        try:
            info = ticker.get_info() or {}
        except Exception:  # noqa: BLE001 — sin moneda, se deduce del mercado
            info = {}
    if not trimestres:
        return None
    dividendo = info.get("trailingAnnualDividendYield")
    return {
        "moneda": info.get("financialCurrency")
        or ("MXN" if es_bmv(emisora) else "USD"),
        "trimestres": trimestres,
        "valuacion": {
            "per": info.get("trailingPE"),
            "precio_valor_libros": info.get("priceToBook"),
            "dividendo_pct": None if dividendo is None else dividendo * 100,
        },
    }


def proximo_reporte_yfinance(emisora: str) -> str | None:
    """La fecha que anuncia Yahoo. Si la empresa aún no fija la siguiente,
    a veces es la del último reporte."""
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        calendario = yf.Ticker(emisora).calendar or {}
    fechas = calendario.get("Earnings Date") or []
    return min(fechas).isoformat() if fechas else None


def nombre_yfinance(emisora: str) -> str | None:
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            info = yf.Ticker(emisora).get_info() or {}
    except Exception:  # noqa: BLE001 — sin nombre se busca por la clave
        return None
    return info.get("shortName") or info.get("longName")


# ═══════════════════════════════════════════
# Noticias
# ═══════════════════════════════════════════


def _sin_medio(titulo: str, fuente: str) -> str:
    """Google News termina cada titular con « - Medio»; el medio va aparte."""
    sufijo = f" - {fuente}"
    return titulo[: -len(sufijo)].strip() if titulo.endswith(sufijo) else titulo.strip()


def _plano(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).lower()


def nombre_para_buscar(
    conn: sqlite3.Connection, emisora: str, leer_nombre: LeerNombre = nombre_yfinance
) -> str:
    """El nombre guardado; si no hay, el de Yahoo limpio; si no, la clave."""
    fila = db.fila(
        conn, "SELECT nombre, clave FROM emisoras WHERE emisora = ?", emisora
    )
    if fila and fila["nombre"]:
        return fila["nombre"]
    nombre = nombre_limpio(leer_nombre(emisora))
    if nombre:
        with db.transaccion(conn):
            conn.execute(
                "UPDATE emisoras SET nombre = ? WHERE emisora = ?", (nombre, emisora)
            )
        return nombre
    return fila["clave"] if fila else clave_de(emisora)


def _id_noticia(url: str) -> str:
    return "N-" + hashlib.sha1(url.encode()).hexdigest()[:8].upper()


def actualizar_noticias(
    conn: sqlite3.Connection,
    emisoras_: Iterable[str],
    leer: LeerTitulares = titulares_google_news,
    leer_nombre: LeerNombre = nombre_yfinance,
    ventana_dias: int = config.REGLAS.noticias_ventana_dias,
) -> dict[str, int]:
    """Titulares nuevos por emisora. Un fallo de una emisora no tumba a las demás."""
    nuevas: dict[str, int] = {}
    obtenido = db.ahora_iso()
    for emisora in dict.fromkeys(emisoras_):
        nombre = nombre_para_buscar(conn, emisora, leer_nombre)
        # «Banorte» trae noticias del estadio y «Apple» de cada producto: el
        # contexto financiero las filtra. Si quedan muy pocas, se busca solo
        # el nombre.
        base = f'"{nombre}" when:{ventana_dias}d'
        try:
            titulares = con_limite(leer, f"{base} {_CONTEXTO_FINANCIERO['es']}", "es")
            if len(titulares) < 3:
                titulares += con_limite(leer, base, "es")
            # Para el SIC la prensa en español a veces no basta.
            if len(titulares) < 3 and not es_bmv(emisora):
                titulares += con_limite(
                    leer, f"{base} {_CONTEXTO_FINANCIERO['en']}", "en"
                )
        except Exception as error:  # noqa: BLE001 — se reporta y se sigue
            logging.getLogger(__name__).warning("Noticias de %s: %s", emisora, error)
            nuevas[emisora] = -1
            continue
        n = 0
        with db.transaccion(conn):
            for t in titulares:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO documentos
                       (doc_id, tipo, emisora, titulo, fuente, url,
                        fecha_publicacion, obtenido)
                       VALUES (?, 'noticia', ?, ?, ?, ?, ?, ?)""",
                    (
                        _id_noticia(t["url"]),
                        emisora,
                        t["titulo"],
                        t["fuente"],
                        t["url"],
                        t["fecha"].astimezone(config.ZONA).isoformat(),
                        obtenido,
                    ),
                )
                n += cursor.rowcount
        nuevas[emisora] = n
    return nuevas


def titulares_recientes(
    conn: sqlite3.Connection,
    emisora: str,
    hasta: datetime,
    dias: int = config.REGLAS.noticias_ventana_dias,
    maximo: int = config.REGLAS.titulares_por_resumen,
) -> list[dict[str, Any]]:
    """Los titulares más útiles al corte: primero los que nombran a la emisora.

    Google devuelve artículos que mencionan el nombre en cualquier parte; un
    titular que no lo nombra suele ser de otro tema y A1 solo verá titulares.
    """
    desde = (hasta - timedelta(days=dias)).isoformat()
    candidatos = db.filas(
        conn,
        """SELECT * FROM documentos
           WHERE tipo = 'noticia' AND emisora = ?
             AND fecha_publicacion >= ? AND fecha_publicacion <= ?
           ORDER BY fecha_publicacion DESC""",
        emisora,
        desde,
        hasta.isoformat(),
    )
    fila = db.fila(
        conn, "SELECT nombre, clave FROM emisoras WHERE emisora = ?", emisora
    )
    claves = {_plano(fila["clave"])} if fila else set()
    if fila and fila["nombre"]:
        claves |= {_plano(p) for p in fila["nombre"].split() if len(p) > 3}
    vistos: set[str] = set()
    unicos = []
    for c in candidatos:
        # El mismo titular reproducido por varios medios cuenta una vez.
        firma = re.sub(r"\W+", "", _plano(c["titulo"]))[:60]
        if firma not in vistos:
            vistos.add(firma)
            unicos.append(c)
    nombra = [c for c in unicos if any(k in _plano(c["titulo"]) for k in claves)]
    otros = [c for c in unicos if c not in nombra]
    return (nombra + otros)[:maximo]


# ═══════════════════════════════════════════
# Reportes
# ═══════════════════════════════════════════


def periodo_de(fecha_fin: str) -> str:
    """Trimestre calendario del cierre: 2026-09-30 → 2026Q3."""
    f = datetime.fromisoformat(fecha_fin)
    return f"{f.year}Q{(f.month - 1) // 3 + 1}"


def _comparable(fechas: list[str], actual: str) -> tuple[str, str] | None:
    """El mismo trimestre del año anterior; si no está, el trimestre previo.

    yfinance a veces omite trimestres. Comparar contra el anterior cambia la
    lectura (estacionalidad), por eso el tipo de comparación viaja en el
    reporte y A2 lo ve.
    """
    f = datetime.fromisoformat(actual)
    anual = [x for x in fechas if abs((datetime.fromisoformat(x) - f).days + 365) <= 20]
    if anual:
        return anual[0], "anual"
    previas = sorted(x for x in fechas if x < actual)
    if previas and (f - datetime.fromisoformat(previas[-1])).days <= 120:
        return previas[-1], "trimestral"
    return None


def reporte_desde_estados(
    emisora: str, estados: dict[str, Any], ahora: datetime
) -> dict[str, Any] | None:
    trimestres = estados["trimestres"]
    # El balance trae trimestres que el estado de resultados no: solo cuentan
    # los que tienen ingresos.
    fechas = sorted(
        (f for f in trimestres if "ingresos" in trimestres[f]), reverse=True
    )
    for actual in fechas:
        par = _comparable(fechas, actual)
        if par is None:
            continue
        previo, comparacion = par
        p_actual, p_previo = periodo_de(actual), periodo_de(previo)
        partidas: dict[str, dict[str, float]] = {}
        for partida in PARTIDAS:
            valores = {}
            for fecha, periodo in ((actual, p_actual), (previo, p_previo)):
                valor = trimestres[fecha].get(partida)
                if valor is not None:
                    valores[periodo] = round(valor / 1e6, 2)
            if valores:
                partidas[partida] = valores
        fin = datetime.fromisoformat(actual).replace(tzinfo=config.ZONA)
        publicado = min(
            fin + timedelta(days=DIAS_PUBLICACION), ahora - timedelta(hours=1)
        )
        return {
            "doc_id": f"F-{clave_de(emisora)}-{p_actual}",
            "periodo": p_actual,
            "periodo_comparado": p_previo,
            "comparacion": comparacion,
            "fin_periodo": actual,
            "moneda": estados["moneda"],
            "unidades": "millones",
            "partidas": partidas,
            "fecha_publicacion": publicado.replace(microsecond=0).isoformat(),
            "indicadores": finanzas.indicadores(trimestres, actual, previo),
            "valuacion": estados.get("valuacion") or {},
            "fecha_valuacion": ahora.date().isoformat(),
        }
    return None


def actualizar_reportes(
    conn: sqlite3.Connection,
    emisoras_: Iterable[str],
    leer: LeerEstados = estados_yfinance,
) -> dict[str, str | None]:
    """El último trimestre comparable de cada emisora. ETFs y fondos no tienen."""
    resultado: dict[str, str | None] = {}
    ahora = db.ahora()
    for emisora in dict.fromkeys(emisoras_):
        try:
            estados = con_limite(leer, emisora)
        except Exception as error:  # noqa: BLE001
            logging.getLogger(__name__).warning("Reporte de %s: %s", emisora, error)
            resultado[emisora] = None
            continue
        reporte = reporte_desde_estados(emisora, estados, ahora) if estados else None
        if reporte is None:
            resultado[emisora] = None
            continue
        # El mismo trimestre se vuelve a leer: Yahoo completa partidas días
        # después del reporte. La fecha de publicación estimada no cambia.
        with db.transaccion(conn):
            conn.execute(
                """INSERT INTO documentos
                   (doc_id, tipo, emisora, titulo, fuente, url, fecha_publicacion,
                    fecha_estimada, datos, obtenido)
                   VALUES (?, 'reporte', ?, ?, 'yfinance (Yahoo Finance)', ?, ?, 1,
                           ?, ?)
                   ON CONFLICT (doc_id) DO UPDATE SET
                       datos = excluded.datos, obtenido = excluded.obtenido""",
                (
                    reporte["doc_id"],
                    emisora,
                    f"Estado de resultados {reporte['periodo']} de {clave_de(emisora)}",
                    f"https://finance.yahoo.com/quote/{emisora}/financials",
                    reporte["fecha_publicacion"],
                    db.a_json(reporte),
                    db.ahora_iso(),
                ),
            )
        resultado[emisora] = reporte["doc_id"]
    return resultado


def actualizar_calendario(
    conn: sqlite3.Connection,
    emisoras_: Iterable[str],
    leer: LeerCalendario = proximo_reporte_yfinance,
) -> dict[str, str | None]:
    """La fecha de reporte que anuncia el calendario de cada emisora."""
    fechas: dict[str, str | None] = {}
    for emisora in dict.fromkeys(emisoras_):
        try:
            fechas[emisora] = con_limite(leer, emisora, segundos=20)
        except Exception as error:  # noqa: BLE001
            logging.getLogger(__name__).warning("Calendario de %s: %s", emisora, error)
            continue
        with db.transaccion(conn):
            conn.execute(
                "UPDATE emisoras SET proximo_reporte = ? WHERE emisora = ?",
                (fechas[emisora], emisora),
            )
    return fechas


def ultimo_reporte(
    conn: sqlite3.Connection, emisora: str, hasta: datetime
) -> dict[str, Any] | None:
    fila = db.fila(
        conn,
        """SELECT * FROM documentos
           WHERE tipo = 'reporte' AND emisora = ? AND fecha_publicacion <= ?
           ORDER BY json_extract(datos, '$.fin_periodo') DESC LIMIT 1""",
        emisora,
        hasta.isoformat(),
    )
    if fila is None:
        return None
    return fila | {"reporte": db.de_json(fila["datos"])}
