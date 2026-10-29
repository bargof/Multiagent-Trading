"""El recorrido completo: actualizar → vigilar → analizar → recomendar.

Es lo que hace el botón de la app y `python -m comite recorrer`. Cada paso
avisa su avance para que la app lo muestre. Si una fuente falla, se anota y
se sigue con lo que hay; si el modelo se queda sin cuota, se dejan las
situaciones restantes abiertas para la siguiente corrida (decisión D69).
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from comite import cartera, db, fuentes, mercado, puente, recomendador, vigia
from comite.config import REGLAS

Aviso = Callable[[str, str], None]


@dataclass
class Fuentes:
    """Los lectores de red, sustituibles en las pruebas."""

    descargar: mercado.Descarga = mercado.descargar_yfinance
    titulares: fuentes.LeerTitulares = fuentes.titulares_google_news
    estados: fuentes.LeerEstados = fuentes.estados_yfinance
    nombre: fuentes.LeerNombre = fuentes.nombre_yfinance
    calendario: fuentes.LeerCalendario = fuentes.proximo_reporte_yfinance


@dataclass
class Resumen:
    precios: dict[str, Any] = field(default_factory=dict)
    noticias: dict[str, int] = field(default_factory=dict)
    reportes: dict[str, Any] = field(default_factory=dict)
    calendario: dict[str, Any] = field(default_factory=dict)
    situaciones_nuevas: int = 0
    descartadas: int = 0
    expiradas: int = 0
    por_regla: list[int] = field(default_factory=list)
    por_comite: list[int] = field(default_factory=list)
    sin_analizar: int = 0
    avisos: list[str] = field(default_factory=list)


def _cuota_agotada(consulta: puente.Consulta) -> bool:
    r = consulta.respuesta
    if r is not None and r.error is not None:
        return r.error.value == "MODEL_UNAVAILABLE"
    return bool(consulta.error and "RateLimit" in consulta.error)


def recorrer(
    conn: sqlite3.Connection,
    *,
    usar_comite: bool = True,
    max_analisis: int = REGLAS.analisis_por_corrida,
    actualizar: bool = True,
    fundamentales: bool = True,
    avisar: Aviso = lambda paso, detalle: None,
    lectores: Fuentes | None = None,
    modelo_para: puente.ModeloPara | None = None,
) -> Resumen:
    lectores = lectores or Fuentes()
    resumen = Resumen()
    est = cartera.estado(conn)

    if actualizar:
        avisar("precios", "Descargando cierres del universo y el tipo de cambio…")
        try:
            resumen.precios = mercado.actualizar_precios(conn, lectores.descargar)
            avisar(
                "precios",
                f"{resumen.precios['emisoras']} emisoras con precio "
                f"al {resumen.precios['ultima']}.",
            )
        except Exception as error:  # noqa: BLE001 — se sigue con el historial
            resumen.avisos.append(f"Precios: {error}")
            avisar("precios", f"No se pudieron actualizar: {error}")
        est = cartera.estado(conn)
        if est.emisoras:
            avisar("noticias", f"Buscando titulares de {len(est.emisoras)} posiciones…")
            resumen.noticias = fuentes.actualizar_noticias(
                conn, est.emisoras, lectores.titulares, lectores.nombre
            )
        # Reportes y calendario cambian poco: el monitor los pide cada
        # algunas horas (D74). Van también las emisoras del objetivo de la
        # estrategia, para que A2 tenga su reporte cuando se proponga comprar.
        ciclo = db.leer_parametro(conn, "ciclo") or {}
        interes = list(dict.fromkeys([*est.emisoras, *ciclo.get("objetivo", {})]))
        if fundamentales and interes:
            avisar(
                "reportes", f"Leyendo estados trimestrales de {len(interes)} emisoras…"
            )
            resumen.reportes = fuentes.actualizar_reportes(
                conn, interes, lectores.estados
            )
            avisar("calendario", "Consultando fechas de reporte…")
            resumen.calendario = fuentes.actualizar_calendario(
                conn, interes, lectores.calendario
            )
            db.guardar_parametro(conn, "fundamentales_al", db.ahora_iso())

    avisar("vigia", "Aplicando las reglas del vigía…")
    resumen.descartadas = vigia.descartar_viejas(conn)
    resumen.expiradas = recomendador.expirar(conn)
    resumen.situaciones_nuevas = vigia.guardar(conn, vigia.detectar(conn))
    abiertas = vigia.abiertas(conn)
    avisar(
        "vigia",
        f"{resumen.situaciones_nuevas} situaciones nuevas, {len(abiertas)} abiertas.",
    )

    para_comite = []
    for sit in abiertas:
        if recomendador.solicitud_para(conn, sit) is None:
            resumen.por_regla.append(
                recomendador.guardar(conn, recomendador.por_regla(conn, sit))
            )
        else:
            para_comite.append(sit)
    if resumen.por_regla:
        avisar("reglas", f"{len(resumen.por_regla)} recomendaciones por regla.")
    # Primero lo urgente (caídas fuertes de la cartera), luego las compras de
    # la estrategia, que es lo que validó el backtest, y al final el resto:
    # analizar noticias de una emisora que la estrategia está vendiendo
    # gastaría la cuota del día antes de llegar a las compras.
    para_comite.sort(
        key=lambda s: (s["severidad"] != "alta", s["tipo"] != "oportunidad")
    )

    if not usar_comite or not para_comite:
        resumen.sin_analizar = len(para_comite)
        return resumen
    if modelo_para is None and not puente.hay_key():
        resumen.sin_analizar = len(para_comite)
        resumen.avisos.append("Falta GOOGLE_API_KEY: el comité no corrió.")
        return resumen

    for i, sit in enumerate(para_comite[:max_analisis], 1):
        if actualizar and not sit["en_portafolio"]:
            foco = [sit["emisora"]]
            fuentes.actualizar_noticias(conn, foco, lectores.titulares, lectores.nombre)
            if sit["tipo"] == "oportunidad":
                fuentes.actualizar_reportes(conn, foco, lectores.estados)
        # La solicitud se arma después: menciona el reporte si ya lo hay.
        solicitud, foco = recomendador.solicitud_para(conn, sit)
        avisar("comite", f"({i}/{min(len(para_comite), max_analisis)}) {sit['titulo']}")
        consulta = puente.consultar(
            conn,
            solicitud,
            foco,
            origen="vigia",
            situacion_id=sit["id"],
            modelo_para=modelo_para,
        )
        rec = recomendador.desde_comite(conn, sit, consulta)
        resumen.por_comite.append(recomendador.guardar(conn, rec))
        avisar("comite", f"→ {recomendador.ACCIONES[rec['accion']]}: {rec['razon']}")
        if _cuota_agotada(consulta):
            resumen.avisos.append(
                "El modelo no respondió (cuota o saturación): las situaciones "
                "restantes quedan abiertas."
            )
            break
    resumen.sin_analizar = len(vigia.abiertas(conn))
    return resumen


def preguntar(
    conn: sqlite3.Connection,
    pregunta: str,
    *,
    actualizar: bool = True,
    lectores: Fuentes | None = None,
    modelo_para: puente.ModeloPara | None = None,
) -> puente.Consulta:
    """Una pregunta libre al comité, como las rutas de la evaluación.

    Si la pregunta no nombra una emisora, el foco es la cartera completa.
    Las noticias y el reporte de las emisoras nombradas se traen al momento.
    """
    lectores = lectores or Fuentes()
    foco = puente.emisoras_mencionadas(conn, pregunta)
    if actualizar and foco:
        fuentes.actualizar_noticias(conn, foco, lectores.titulares, lectores.nombre)
        fuentes.actualizar_reportes(conn, foco, lectores.estados)
    if not foco:
        foco = cartera.estado(conn).emisoras[:3]
    return puente.consultar(
        conn, pregunta, foco, origen="chat", modelo_para=modelo_para
    )


def ultimo_recorrido(conn: sqlite3.Connection) -> str | None:
    f = db.fila(conn, "SELECT MAX(detectada) AS d FROM situaciones")
    return f["d"] if f else None
