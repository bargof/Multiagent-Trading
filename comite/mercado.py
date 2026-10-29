"""Universo del reto, precios diarios, tipo de cambio y benchmarks.

El Excel del reto trae el historial de cierres de Yahoo Finance de las 226
emisoras y de los tres benchmarks; comparé sus cierres del 23 de octubre de
2026 contra yfinance y coinciden. Por eso el Excel es el historial y
yfinance solo agrega los días que faltan (decisión D61).

Las emisoras del SIC cotizan en dólares en Yahoo y en pesos en el reto: todo
precio que sale de este módulo hacia la cartera o el comité va en MXN,
convertido con el cierre de USDMXN del mismo día o el anterior disponible.
"""

import logging
import re
import sqlite3
import warnings
from collections.abc import Callable, Iterable
from pathlib import Path

import pandas as pd

from comite import config, db

# Descarga: (tickers, fecha_inicio AAAA-MM-DD) → DataFrame de cierres con un
# índice de fechas y una columna por ticker. Inyectable para las pruebas.
Descarga = Callable[[list[str], str], pd.DataFrame]

# Nombres con los que la prensa mexicana llama a las emisoras más comunes.
# El nombre corto de Yahoo («WAL MART DE MEXICO SAB DE CV») casi no aparece
# en titulares, así que la búsqueda de noticias lo encontraría poco.
NOMBRES_BMV = {
    "AMXB": "América Móvil",
    "ALSEA": "Alsea",
    "ALPEKA": "Alpek",
    "ASURB": "ASUR aeropuertos",
    "BBAJIOO": "BanBajío",
    "BIMBOA": "Grupo Bimbo",
    "BOLSAA": "Bolsa Mexicana de Valores",
    "CEMEXCPO": "Cemex",
    "CHDRAUIB": "Chedraui",
    "CUERVO": "Becle Cuervo",
    "FEMSAUBD": "FEMSA",
    "FIBRAMQ12": "Fibra Macquarie",
    "FIBRAPL14": "Fibra Prologis",
    "FUNO11": "Fibra Uno",
    "GAPB": "Grupo Aeroportuario del Pacífico",
    "GCARSOA1": "Grupo Carso",
    "GCC": "GCC cementos",
    "GENTERA": "Gentera",
    "GFINBURO": "Inbursa",
    "GFNORTEO": "Banorte",
    "GMEXICOB": "Grupo México",
    "GRUMAB": "Gruma",
    "KIMBERA": "Kimberly-Clark de México",
    "KOFUBL": "Coca-Cola FEMSA",
    "LABB": "Genomma Lab",
    "LIVEPOLC-1": "Liverpool",
    "MEGACPO": "Megacable",
    "NAFTRACISHRS": "NAFTRAC",
    "OMAB": "OMA aeropuertos",
    "ORBIA": "Orbia",
    "PE&OLES": "Peñoles",
    "PINFRA": "Pinfra",
    "Q": "Quálitas",
    "RA": "Regional Banregio",
    "SITES1A-1": "Sitios Latinoamérica",
    "TLEVISACPO": "Televisa",
    "VESTA": "Vesta",
    "VOLARA": "Volaris",
    "WALMEX": "Walmex",
}

# Las más operadas del SIC. Sirven para buscar noticias en español y para que
# el chat reconozca «Apple» o «Nvidia» además del ticker.
NOMBRES_SIC = {
    "AAPL": "Apple",
    "ABNB": "Airbnb",
    "AMD": "AMD",
    "AMZN": "Amazon",
    "AVGO": "Broadcom",
    "BABA": "Alibaba",
    "BAC": "Bank of America",
    "BRK-B": "Berkshire Hathaway",
    "COST": "Costco",
    "DIS": "Disney",
    "GOOGL": "Alphabet Google",
    "INTC": "Intel",
    "JPM": "JPMorgan",
    "KO": "Coca-Cola",
    "LLY": "Eli Lilly",
    "MA": "Mastercard",
    "MCD": "McDonald's",
    "MELI": "Mercado Libre",
    "META": "Meta Platforms",
    "MSFT": "Microsoft",
    "NFLX": "Netflix",
    "NKE": "Nike",
    "NVDA": "Nvidia",
    "ORCL": "Oracle",
    "PEP": "PepsiCo",
    "PFE": "Pfizer",
    "PLTR": "Palantir",
    "PYPL": "PayPal",
    "SBUX": "Starbucks",
    "SHOP": "Shopify",
    "TSLA": "Tesla",
    "TSM": "TSMC",
    "UBER": "Uber",
    "V": "Visa",
    "WMT": "Walmart",
    "XOM": "Exxon Mobil",
}

_SUFIJOS_SOCIEDAD = re.compile(
    r"\b(s\.?a\.?b\.?|s\.?a\.?|de c\.?v\.?|inc\.?|corp(oration)?\.?|co\.?|"
    r"ltd\.?|plc|holdings?|group|company|class [a-c]|the)\b",
    re.IGNORECASE,
)


def clave_de(emisora: str) -> str:
    """Identificador que ve el comité: sin el sufijo .MX de Yahoo.

    Los usuarios y la prensa dicen WALMEX, no WALMEX.MX; si el comité usara
    el ticker de Yahoo, A0 tendría que adivinar el sufijo y un error daría
    UNKNOWN_ID (decisión D62).
    """
    return emisora.removesuffix(".MX").upper()


def es_bmv(emisora: str) -> bool:
    return emisora.upper().endswith(".MX")


def nombre_limpio(nombre_yahoo: str | None) -> str | None:
    if not nombre_yahoo:
        return None
    limpio = _SUFIJOS_SOCIEDAD.sub(" ", nombre_yahoo)
    limpio = re.sub(r"[,.]+", " ", limpio)
    return " ".join(limpio.split()).strip() or None


# ═══════════════════════════════════════════
# Importación del reto
# ═══════════════════════════════════════════


def leer_historia(ruta: Path | None = None) -> pd.DataFrame:
    """Cierres del reto: del Excel si existe, si no de la copia del repo."""
    ruta_excel = Path(ruta) if ruta else config.RUTA_EXCEL_RETO
    if ruta_excel.is_file() and ruta_excel.suffix == ".xlsx":
        tabla = pd.read_excel(ruta_excel, index_col=0)
    elif config.RUTA_HISTORIA.is_file():
        tabla = pd.read_csv(config.RUTA_HISTORIA, index_col=0, parse_dates=True)
    else:
        raise FileNotFoundError(
            f"No encuentro {ruta_excel.name} ni {config.RUTA_HISTORIA}."
        )
    tabla.index = pd.to_datetime(tabla.index)
    tabla = tabla.loc[config.HISTORIA_DESDE :]
    return tabla.dropna(axis=1, how="all").sort_index()


def guardar_copia_compacta(
    tabla: pd.DataFrame, tipo_de_cambio: pd.Series | None = None
) -> Path:
    """La copia que va en el repo: desde 2024, con USDMXN y comprimida
    (≈0.5 MB, no 15)."""
    config.RUTA_HISTORIA.parent.mkdir(parents=True, exist_ok=True)
    if tipo_de_cambio is not None and not tipo_de_cambio.empty:
        tabla = tabla.join(tipo_de_cambio.rename(config.TIPO_CAMBIO), how="left")
    tabla.to_csv(config.RUTA_HISTORIA, float_format="%.6g", compression="gzip")
    return config.RUTA_HISTORIA


def importar_reto(conn: sqlite3.Connection, tabla: pd.DataFrame) -> dict[str, int]:
    """Universo, historial de precios y benchmarks desde la tabla del reto."""
    bench = [c for c in tabla.columns if c in config.BENCHMARKS]
    especiales = {*config.BENCHMARKS, config.TIPO_CAMBIO}
    emisoras = [c for c in tabla.columns if c not in especiales]
    claves: dict[str, str] = {}
    for emisora in emisoras:
        clave = clave_de(emisora)
        # Si dos tickers compartieran clave, el segundo conserva el sufijo.
        claves[emisora] = emisora if clave in claves.values() else clave
    with db.transaccion(conn):
        for emisora in emisoras:
            bmv = es_bmv(emisora)
            conn.execute(
                """INSERT INTO emisoras (emisora, clave, nombre, mercado, moneda)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (emisora) DO UPDATE SET
                       clave = excluded.clave,
                       nombre = COALESCE(excluded.nombre, emisoras.nombre)""",
                (
                    emisora,
                    claves[emisora],
                    NOMBRES_BMV.get(claves[emisora])
                    or NOMBRES_SIC.get(claves[emisora]),
                    "BMV" if bmv else "SIC",
                    "MXN" if bmv else "USD",
                ),
            )
        con_fx = (
            [*emisoras, config.TIPO_CAMBIO] if config.TIPO_CAMBIO in tabla else emisoras
        )
        n_precios = _guardar_cierres(conn, tabla[con_fx], "reto_excel")
        n_bench = 0
        for nombre in bench:
            serie = tabla[nombre].dropna()
            conn.executemany(
                "INSERT OR REPLACE INTO benchmarks VALUES (?, ?, ?)",
                [(nombre, f.date().isoformat(), float(v)) for f, v in serie.items()],
            )
            n_bench += len(serie)
    return {"emisoras": len(emisoras), "precios": n_precios, "benchmarks": n_bench}


def _guardar_cierres(conn: sqlite3.Connection, tabla: pd.DataFrame, fuente: str) -> int:
    registros = []
    for emisora in tabla.columns:
        moneda = "MXN" if es_bmv(emisora) or emisora == config.TIPO_CAMBIO else "USD"
        for fecha, cierre in tabla[emisora].dropna().items():
            if cierre > 0:
                registros.append(
                    (
                        emisora,
                        pd.Timestamp(fecha).date().isoformat(),
                        float(cierre),
                        moneda,
                        fuente,
                    )
                )
    conn.executemany("INSERT OR REPLACE INTO precios VALUES (?, ?, ?, ?, ?)", registros)
    return len(registros)


# ═══════════════════════════════════════════
# Actualización con yfinance
# ═══════════════════════════════════════════


def descargar_yfinance(tickers: list[str], desde: str) -> pd.DataFrame:
    import yfinance as yf

    # yfinance avisa por cada ticker deslistado y pandas 3 por su uso de
    # inplace; nada de eso es accionable aquí.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        datos = yf.download(
            tickers, start=desde, progress=False, auto_adjust=False, threads=True
        )
    if datos is None or datos.empty:
        return pd.DataFrame()
    cierres = datos["Close"]
    if isinstance(cierres, pd.Series):
        cierres = cierres.to_frame(tickers[0])
    return cierres


def importar_tipo_de_cambio(
    conn: sqlite3.Connection, descargar: Descarga = descargar_yfinance
) -> int:
    """Historial de USDMXN desde HISTORIA_DESDE: el Excel del reto no lo trae
    y sin él ninguna emisora del SIC tiene precio en pesos."""
    tabla = descargar([config.TICKER_TIPO_CAMBIO], config.HISTORIA_DESDE)
    if tabla.empty:
        return 0
    tabla = tabla.rename(columns={config.TICKER_TIPO_CAMBIO: config.TIPO_CAMBIO})
    with db.transaccion(conn):
        return _guardar_cierres(conn, tabla[[config.TIPO_CAMBIO]], "yfinance")


def serie_tipo_de_cambio(conn: sqlite3.Connection) -> pd.Series:
    tabla = cierres(conn, [config.TIPO_CAMBIO])
    if tabla.empty or config.TIPO_CAMBIO not in tabla:
        return pd.Series(dtype=float, name=config.TIPO_CAMBIO)
    return tabla[config.TIPO_CAMBIO].dropna()


def actualizar_precios(
    conn: sqlite3.Connection,
    descargar: Descarga = descargar_yfinance,
    dias: int = 45,
) -> dict[str, object]:
    """Cierres recientes de todo el universo y del tipo de cambio.

    Una sola descarga en lote: 226 tickers tardan unos 5 s. Las emisoras que
    Yahoo ya no cotiza quedan marcadas sin datos y el vigía no las mira.
    """
    universo = [
        e["emisora"]
        for e in db.filas(conn, "SELECT emisora FROM emisoras ORDER BY emisora")
    ]
    if len(serie_tipo_de_cambio(conn)) < 100:
        importar_tipo_de_cambio(conn, descargar)
    desde = (db.ahora() - pd.Timedelta(days=dias)).date().isoformat()
    tabla = descargar([*universo, config.TICKER_TIPO_CAMBIO], desde)
    if tabla.empty:
        return {"emisoras": 0, "precios": 0, "sin_datos": universo, "ultima": None}
    tabla = tabla.rename(columns={config.TICKER_TIPO_CAMBIO: config.TIPO_CAMBIO})
    con_datos = [c for c in tabla.columns if tabla[c].notna().any()]
    sin_datos = sorted(set(universo) - set(con_datos))
    with db.transaccion(conn):
        n = _guardar_cierres(conn, tabla[con_datos], "yfinance")
        conn.execute("UPDATE emisoras SET con_datos = 1")
        conn.executemany(
            "UPDATE emisoras SET con_datos = 0 WHERE emisora = ?",
            [(e,) for e in sin_datos],
        )
    ultima = pd.Timestamp(tabla.dropna(how="all").index.max()).date().isoformat()
    return {
        "emisoras": len(con_datos),
        "precios": n,
        "sin_datos": sin_datos,
        "ultima": ultima,
    }


# ═══════════════════════════════════════════
# Lectura
# ═══════════════════════════════════════════


def emisoras(conn: sqlite3.Connection, solo_con_datos: bool = True) -> pd.DataFrame:
    sql = "SELECT * FROM emisoras"
    if solo_con_datos:
        sql += " WHERE con_datos = 1"
    return pd.DataFrame(db.filas(conn, sql + " ORDER BY emisora"))


def mapa_claves(conn: sqlite3.Connection) -> dict[str, str]:
    """clave del comité → ticker de Yahoo."""
    return {
        f["clave"]: f["emisora"]
        for f in db.filas(conn, "SELECT clave, emisora FROM emisoras")
    }


def cierres(
    conn: sqlite3.Connection, emisoras_: Iterable[str], desde: str | None = None
) -> pd.DataFrame:
    """Cierres en su moneda original, una columna por emisora."""
    lista = list(dict.fromkeys(emisoras_))
    if not lista:
        return pd.DataFrame()
    marcas = ",".join("?" * len(lista))
    sql = f"SELECT emisora, fecha, cierre FROM precios WHERE emisora IN ({marcas})"
    params: list[object] = list(lista)
    if desde:
        sql += " AND fecha >= ?"
        params.append(desde)
    largo = pd.DataFrame(db.filas(conn, sql, *params))
    if largo.empty:
        return pd.DataFrame(columns=lista)
    tabla = largo.pivot(index="fecha", columns="emisora", values="cierre")
    tabla.index = pd.to_datetime(tabla.index)
    return tabla.sort_index()


def cierres_mxn(
    conn: sqlite3.Connection, emisoras_: Iterable[str], desde: str | None = None
) -> pd.DataFrame:
    """Cierres en pesos: las del SIC por el tipo de cambio del día.

    Si un día falta el tipo de cambio, se usa el anterior; un precio no se
    queda sin convertir.
    """
    lista = list(dict.fromkeys(emisoras_))
    tabla = cierres(conn, [*lista, config.TIPO_CAMBIO], desde)
    if tabla.empty:
        return tabla
    fx = tabla.pop(config.TIPO_CAMBIO) if config.TIPO_CAMBIO in tabla else None
    usd = [c for c in tabla.columns if not es_bmv(c)]
    if usd:
        if fx is None or fx.dropna().empty:
            # Sin tipo de cambio un precio en dólares no es un precio en
            # pesos: queda vacío y la cartera lo reporta sin valor, no en cero.
            tabla[usd] = float("nan")
        else:
            tabla[usd] = tabla[usd].mul(fx.ffill().bfill(), axis=0)
    return tabla


def ultimo_precio_mxn(
    conn: sqlite3.Connection, emisora: str
) -> tuple[float, str] | None:
    tabla = cierres_mxn(conn, [emisora], _hace_dias(20))
    if tabla.empty or emisora not in tabla or tabla[emisora].dropna().empty:
        return None
    serie = tabla[emisora].dropna()
    return float(serie.iloc[-1]), serie.index[-1].date().isoformat()


def ultimos_precios_mxn(
    conn: sqlite3.Connection, emisoras_: Iterable[str]
) -> dict[str, tuple[float, str]]:
    lista = list(dict.fromkeys(emisoras_))
    if not lista:
        return {}
    tabla = cierres_mxn(conn, lista, _hace_dias(20))
    resultado = {}
    for emisora in lista:
        if emisora in tabla and not tabla[emisora].dropna().empty:
            serie = tabla[emisora].dropna()
            resultado[emisora] = (
                float(serie.iloc[-1]),
                serie.index[-1].date().isoformat(),
            )
    return resultado


def tipo_de_cambio(conn: sqlite3.Connection) -> tuple[float, str] | None:
    f = db.fila(
        conn,
        "SELECT cierre, fecha FROM precios WHERE emisora = ? "
        "ORDER BY fecha DESC LIMIT 1",
        config.TIPO_CAMBIO,
    )
    return (f["cierre"], f["fecha"]) if f else None


def benchmarks(conn: sqlite3.Connection) -> pd.DataFrame:
    largo = pd.DataFrame(db.filas(conn, "SELECT * FROM benchmarks"))
    if largo.empty:
        return pd.DataFrame()
    tabla = largo.pivot(index="fecha", columns="nombre", values="valor")
    tabla.index = pd.to_datetime(tabla.index)
    return tabla.sort_index()


def _hace_dias(dias: int) -> str:
    return (db.ahora() - pd.Timedelta(days=dias)).date().isoformat()
