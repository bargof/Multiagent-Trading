"""Base de datos SQLite: tres tablas principales y tres de apoyo.

Principales (decisión D60):
    operaciones      el portafolio como libro de movimientos; las posiciones
                     y el efectivo se derivan de aquí, nunca se editan.
    situaciones      lo que el vigía detecta a lo largo del tiempo, sobre la
                     cartera y sobre otras emisoras del reto.
    recomendaciones  qué hacer con cada situación, con el dictamen del comité
                     o la regla que la produjo, y su estado hasta ejecutarse.

Apoyo:
    emisoras, precios       universo del reto, precios diarios, tipo de cambio
                            y fecha del próximo reporte.
    benchmarks              Conservador, Moderado y Agresivo del reto.
    documentos              noticias y reportes crudos, con fuente y fecha.
    ejecuciones_comite      cada caso del comité: solicitud, respuesta y traza.
    parametros              la estrategia elegida, su ciclo de rebalanceo y la
                            última vuelta del monitor.

SQLite porque es un archivo, viene con Python y no pide servidor: el repo se
clona y funciona. Los CHECK hacen imposibles los estados que el código nunca
debe escribir, igual que los validadores de los contratos del comité.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from comite import config

# Aparte porque la migración la recrea cuando cambian sus tipos.
SITUACIONES = """
CREATE TABLE IF NOT EXISTS {nombre} (
    id            INTEGER PRIMARY KEY,
    clave         TEXT NOT NULL UNIQUE,     -- evita repetir la misma situación
    detectada     TEXT NOT NULL,
    emisora       TEXT,
    en_portafolio INTEGER NOT NULL,
    tipo          TEXT NOT NULL CHECK (tipo IN (
                      'noticias', 'reporte', 'precio', 'concentracion',
                      'estres', 'destacada', 'oportunidad', 'salida',
                      'calendario')),
    severidad     TEXT NOT NULL CHECK (severidad IN ('alta', 'media', 'baja')),
    titulo        TEXT NOT NULL,
    detalle       TEXT NOT NULL,
    datos         TEXT NOT NULL DEFAULT '{{}}',   -- JSON con las cifras
    evidencia     TEXT NOT NULL DEFAULT '[]',   -- JSON con doc_id
    estado        TEXT NOT NULL DEFAULT 'abierta'
                  CHECK (estado IN ('abierta', 'analizada', 'descartada'))
);
"""

ESQUEMA = (
    SITUACIONES.format(nombre="situaciones")
    + """
CREATE TABLE IF NOT EXISTS emisoras (
    emisora     TEXT PRIMARY KEY,           -- ticker de Yahoo: WALMEX.MX, AAPL
    clave       TEXT NOT NULL UNIQUE,       -- como la ve el comité: WALMEX, AAPL
    nombre      TEXT,                       -- para buscar noticias
    mercado     TEXT NOT NULL CHECK (mercado IN ('BMV', 'SIC')),
    moneda      TEXT NOT NULL CHECK (moneda IN ('MXN', 'USD')),
    con_datos   INTEGER NOT NULL DEFAULT 1,
    proximo_reporte TEXT                    -- AAAA-MM-DD, del calendario
);

CREATE TABLE IF NOT EXISTS precios (
    emisora     TEXT NOT NULL,
    fecha       TEXT NOT NULL,              -- AAAA-MM-DD
    cierre      REAL NOT NULL CHECK (cierre > 0),
    moneda      TEXT NOT NULL,
    fuente      TEXT NOT NULL,
    PRIMARY KEY (emisora, fecha)
);

CREATE TABLE IF NOT EXISTS benchmarks (
    nombre      TEXT NOT NULL,
    fecha       TEXT NOT NULL,
    valor       REAL NOT NULL,
    PRIMARY KEY (nombre, fecha)
);

CREATE TABLE IF NOT EXISTS operaciones (
    id                INTEGER PRIMARY KEY,
    fecha             TEXT NOT NULL,
    lado              TEXT NOT NULL
                      CHECK (lado IN ('deposito', 'compra', 'venta', 'retiro')),
    emisora           TEXT,
    cantidad          INTEGER,
    precio            REAL,                 -- MXN por título
    monto             REAL NOT NULL CHECK (monto >= 0),   -- MXN
    origen            TEXT NOT NULL
                      CHECK (origen IN ('inicial', 'manual', 'recomendacion')),
    recomendacion_id  INTEGER REFERENCES recomendaciones (id),
    folio             TEXT,
    nota              TEXT,
    creada            TEXT NOT NULL,
    CHECK (
        (lado IN ('compra', 'venta') AND emisora IS NOT NULL
         AND cantidad > 0 AND precio > 0)
        OR (lado IN ('deposito', 'retiro') AND emisora IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS documentos (
    doc_id            TEXT PRIMARY KEY,
    tipo              TEXT NOT NULL CHECK (tipo IN ('noticia', 'reporte')),
    emisora           TEXT NOT NULL,
    titulo            TEXT NOT NULL,
    fuente            TEXT NOT NULL,
    url               TEXT,
    fecha_publicacion TEXT NOT NULL,        -- ISO con zona
    fecha_estimada    INTEGER NOT NULL DEFAULT 0,
    datos             TEXT,                 -- JSON: partidas de un reporte
    obtenido          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recomendaciones (
    id              INTEGER PRIMARY KEY,
    creada          TEXT NOT NULL,
    situacion_id    INTEGER REFERENCES situaciones (id),
    origen          TEXT NOT NULL CHECK (origen IN ('comite', 'regla')),
    accion          TEXT NOT NULL CHECK (accion IN (
                        'comprar', 'vender', 'mantener', 'vigilar', 'no_operar')),
    emisora         TEXT,
    cantidad        INTEGER CHECK (cantidad IS NULL OR cantidad > 0),
    precio_ref      REAL,                   -- MXN al momento de recomendar
    monto_ref       REAL,
    razon           TEXT NOT NULL,          -- qué hacer, en lenguaje claro
    estado_comite   TEXT,                   -- EstadoFinal del comité
    decision_riesgo TEXT,                   -- dictamen de A4
    hash_propuesta  TEXT,
    resumen_comite  TEXT,
    metricas        TEXT NOT NULL DEFAULT '{}',
    evidencia       TEXT NOT NULL DEFAULT '[]',
    run_id          TEXT REFERENCES ejecuciones_comite (run_id),
    estado          TEXT NOT NULL CHECK (estado IN (
                        'informativa', 'propuesta', 'aprobada', 'ejecutada',
                        'rechazada', 'bloqueada', 'expirada')),
    actualizada     TEXT NOT NULL,
    nota            TEXT,
    -- Solo compra o venta llevan movimiento, y solo ellas pueden avanzar
    -- hacia la ejecución.
    CHECK (
        (accion IN ('comprar', 'vender') AND emisora IS NOT NULL
         AND cantidad IS NOT NULL)
        OR (accion NOT IN ('comprar', 'vender')
            AND estado IN ('informativa', 'bloqueada', 'expirada'))
    )
);

CREATE TABLE IF NOT EXISTS ejecuciones_comite (
    run_id          TEXT PRIMARY KEY,
    inicio          TEXT NOT NULL,
    origen          TEXT NOT NULL CHECK (origen IN ('vigia', 'chat')),
    situacion_id    INTEGER REFERENCES situaciones (id),
    solicitud       TEXT NOT NULL,
    contexto        TEXT,                   -- JSON: qué datos vio el comité
    estado          TEXT,
    resumen         TEXT,
    respuesta       TEXT,                   -- JSON de RespuestaFinal
    traza           TEXT,                   -- JSONL
    llamadas_modelo INTEGER NOT NULL DEFAULT 0,
    tokens_entrada  INTEGER NOT NULL DEFAULT 0,
    tokens_salida   INTEGER NOT NULL DEFAULT 0,
    segundos        REAL,
    modelo          TEXT,
    error           TEXT
);

-- Posiciones derivadas del libro: la cartera nunca se edita a mano.
CREATE VIEW IF NOT EXISTS posiciones AS
SELECT emisora,
       SUM(CASE lado WHEN 'compra' THEN cantidad ELSE -cantidad END) AS cantidad,
       SUM(CASE lado WHEN 'compra' THEN monto ELSE 0 END)
         / SUM(CASE lado WHEN 'compra' THEN cantidad ELSE 0 END) AS costo_promedio
FROM operaciones
WHERE lado IN ('compra', 'venta')
GROUP BY emisora
HAVING SUM(CASE lado WHEN 'compra' THEN cantidad ELSE -cantidad END) > 0;

CREATE INDEX IF NOT EXISTS ix_documentos_emisora
    ON documentos (emisora, tipo, fecha_publicacion);
CREATE INDEX IF NOT EXISTS ix_situaciones_estado ON situaciones (estado, severidad);
CREATE INDEX IF NOT EXISTS ix_recomendaciones_estado ON recomendaciones (estado);

CREATE TABLE IF NOT EXISTS parametros (
    clave       TEXT PRIMARY KEY,
    valor       TEXT NOT NULL,              -- JSON
    actualizado TEXT NOT NULL
);
"""
)


def ahora() -> datetime:
    return datetime.now(config.ZONA).replace(microsecond=0)


def ahora_iso() -> str:
    return ahora().isoformat()


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = Path(ruta or config.RUTA_DB)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Streamlit atiende cada interacción en un hilo
    # distinto y la conexión vive en caché. Las escrituras son cortas y van
    # en transacciones explícitas.
    conn = sqlite3.connect(ruta, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(ESQUEMA)
    _migrar(conn)
    return conn


def _migrar(conn: sqlite3.Connection) -> None:
    """Una base del bloque 7 sigue sirviendo: se le agrega lo del bloque 8.

    SQLite no deja cambiar un CHECK; la tabla de situaciones se recrea con
    los tipos nuevos y conserva sus filas e ids.
    """
    columnas = {f["name"] for f in conn.execute("PRAGMA table_info(emisoras)")}
    if "proximo_reporte" not in columnas:
        conn.execute("ALTER TABLE emisoras ADD COLUMN proximo_reporte TEXT")
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'situaciones'"
    ).fetchone()[0]
    if "'salida'" in sql:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute(SITUACIONES.format(nombre="situaciones_nueva"))
            conn.execute("INSERT INTO situaciones_nueva SELECT * FROM situaciones")
            conn.execute("DROP TABLE situaciones")
            conn.execute("ALTER TABLE situaciones_nueva RENAME TO situaciones")
        conn.executescript(ESQUEMA)  # los índices de la tabla nueva
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


@contextmanager
def transaccion(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    with conn:
        yield conn


def _serializable(valor: Any) -> Any:
    # Las cifras del comité son Decimal: como número, no como texto.
    if isinstance(valor, Decimal):
        return float(valor)
    return str(valor)


def a_json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=_serializable)


def de_json(texto: str | None, omision: Any = None) -> Any:
    if not texto:
        return omision
    return json.loads(texto)


def filas(conn: sqlite3.Connection, sql: str, *params: Any) -> list[dict[str, Any]]:
    return [dict(f) for f in conn.execute(sql, params).fetchall()]


def fila(conn: sqlite3.Connection, sql: str, *params: Any) -> dict[str, Any] | None:
    resultado = conn.execute(sql, params).fetchone()
    return dict(resultado) if resultado else None


def leer_parametro(conn: sqlite3.Connection, clave: str, omision: Any = None) -> Any:
    f = fila(conn, "SELECT valor FROM parametros WHERE clave = ?", clave)
    return de_json(f["valor"], omision) if f else omision


def guardar_parametro(conn: sqlite3.Connection, clave: str, valor: Any) -> None:
    with transaccion(conn):
        conn.execute(
            "INSERT OR REPLACE INTO parametros VALUES (?, ?, ?)",
            (clave, a_json(valor), ahora_iso()),
        )
