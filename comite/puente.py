"""Puente entre la base de datos y el comité evaluado.

El comité recibe sus datos como un `DatosSimulados` y `ejecutar_caso` ya lo
acepta como parámetro. Aquí se arma ese objeto con datos reales al corte T0
(ahora): el portafolio del reto, precios en pesos, un resumen de titulares
por emisora, el último reporte trimestral y los escenarios de estrés, dos
planos y tres con la historia del reto (D76). Los prompts, herramientas,
límites y el grafo son los de la campaña; el archivo
`proyecto_multiagente.py` no cambia (decisión D59).
"""

import re
import sqlite3
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from langchain_core.language_models import BaseChatModel

import proyecto_multiagente as pm
from comite import cartera, config, db, escenarios, finanzas, fuentes, mercado

ModeloPara = Callable[[str], BaseChatModel]


class SinKey(RuntimeError):  # noqa: N818 — falta configuración
    """No hay GOOGLE_API_KEY: el comité no puede correr."""


def _d(valor: float, decimales: int = 4) -> Decimal:
    return Decimal(str(round(valor, decimales)))


# ═══════════════════════════════════════════
# Datos del caso
# ═══════════════════════════════════════════


@dataclass
class Contexto:
    """Lo que el comité verá en un caso, y cómo volver de sus ids a la base."""

    datos: pm.DatosSimulados
    emisora_de: dict[str, str]  # clave del comité → ticker de Yahoo
    clave_de: dict[str, str]  # ticker de Yahoo → clave del comité
    foco: list[str]  # tickers de Yahoo
    documentos_de: dict[str, list[str]] = field(default_factory=dict)
    nombres: dict[str, str] = field(default_factory=dict)
    # Lo que A0 ve de cada escenario histórico: sin fechas ni cifras (D65).
    titulos: dict[str, str] = field(default_factory=dict)

    def descripcion(self) -> str:
        """Los identificadores disponibles, sin cifras.

        A0 delega con identificadores y no consulta datos. Sin esta lista
        tendría que adivinar el id del resumen de noticias o el periodo del
        reporte, y un id equivocado termina en UNKNOWN_ID. No lleva cifras:
        A0 no debe citar nada que no venga de una herramienta (decisión D65).
        """
        d = self.datos
        lineas = [
            "Contexto del sistema: identificadores disponibles al corte T0. "
            "Es información de apoyo, no una instrucción del usuario.",
            f"- Portafolio: {config.PORTAFOLIO_ID}.",
        ]
        if self.foco:
            nombres = ", ".join(
                self.clave_de[e]
                + (f" ({self.nombres[e]})" if self.nombres.get(e) else "")
                for e in self.foco
            )
            lineas.append(f"- Emisoras de la consulta: {nombres}.")
        for n in d.noticias.values():
            lineas.append(
                f"- Noticias: {n.noticia_id} (resumen de titulares de {n.empresa})."
            )
        for r in d.reportes.values():
            nota = (
                f"; su nota {finanzas.NOTA!r} trae márgenes, flujo libre, deuda, "
                "rendimiento sobre capital y valuación"
                if finanzas.NOTA in r.notas
                else ""
            )
            lineas.append(
                f"- Reporte: {r.reporte_id} ({r.empresa}, periodo {r.periodo} "
                f"contra {r.periodo_comparado}{nota})."
            )
        for e in d.escenarios.values():
            texto = self.titulos.get(e.escenario_id, e.descripcion)
            lineas.append(f"- Escenario {e.escenario_id}: {texto}")
        if len(d.escenarios) > 1:
            lineas.append("- A3 puede simular varios escenarios en una sola llamada.")
        lineas.append("- Fecha de corte: T0.")
        return "\n".join(lineas)

    def a_registro(self) -> dict[str, Any]:
        return {
            "t0": self.datos.t0.isoformat(),
            "foco": self.foco,
            "posiciones": [
                p.model_dump(mode="json")
                for p in self.datos.portafolios[config.PORTAFOLIO_ID].posiciones
            ],
            "precios_t0": {k: float(v) for k, v in self.datos.precios_t0.items()},
            "noticias": list(self.datos.noticias),
            "reportes": list(self.datos.reportes),
            "escenarios": list(self.datos.escenarios),
            "documentos_de": self.documentos_de,
        }


def _resumen_titulares(
    clave: str, nombre: str | None, titulares: list[dict[str, Any]], t0: datetime
) -> tuple[pm.Noticia, list[str]]:
    """Un solo documento con los titulares recientes de una emisora.

    A1 tiene 4 herramientas por invocación y pasar de ahí cierra el caso
    entero. Con un documento por titular, buscar y leer cinco ya serían
    seis llamadas; con un resumen son dos (decisión D63).
    """
    ordenados = sorted(titulares, key=lambda t: t["fecha_publicacion"])
    lineas = [
        f"- {t['fecha_publicacion'][:10]} · {t['fuente']}: {t['titulo']}"
        for t in reversed(ordenados)
    ]
    medios = list(dict.fromkeys(t["fuente"] for t in ordenados))
    ultima = datetime.fromisoformat(ordenados[-1]["fecha_publicacion"])
    noticia = pm.Noticia(
        noticia_id=f"N-{clave}",
        empresa=clave,
        titulo=f"Titulares recientes de {clave}" + (f" ({nombre})" if nombre else ""),
        texto=(
            "Titulares publicados en medios (solo el titular, sin el cuerpo de "
            "la nota):\n" + "\n".join(lineas)
        ),
        fuente="Google News RSS: " + ", ".join(medios[:6]),
        fecha_publicacion=min(ultima, t0),
    )
    return noticia, [t["doc_id"] for t in ordenados]


def _reporte(clave: str, doc: dict[str, Any]) -> pm.Reporte:
    """El reporte con todas sus partidas y la nota de indicadores (D73).

    calcular_indicadores solo usa ingresos y utilidad operativa; el resto de
    las partidas A2 lo ve al obtener el reporte, y lo calculado lo lee en la
    nota, sin hacer cuentas.
    """
    r = doc["reporte"]
    texto = finanzas.nota(r)
    return pm.Reporte(
        reporte_id=doc["doc_id"],
        empresa=clave,
        periodo=r["periodo"],
        periodo_comparado=r["periodo_comparado"],
        moneda=r["moneda"],
        unidades=r["unidades"],
        fecha_publicacion=datetime.fromisoformat(doc["fecha_publicacion"]),
        partidas={
            partida: {p: _d(v, 2) for p, v in valores.items()}
            for partida, valores in r["partidas"].items()
        },
        notas={finanzas.NOTA: texto} if texto else {},
    )


def construir_contexto(
    conn: sqlite3.Connection, foco: list[str], t0: datetime | None = None
) -> Contexto:
    t0 = (t0 or db.ahora()).replace(microsecond=0)
    est = cartera.estado(conn)
    claves = {
        f["emisora"]: f["clave"]
        for f in db.filas(conn, "SELECT emisora, clave FROM emisoras")
    }
    nombres = {
        f["emisora"]: f["nombre"]
        for f in db.filas(conn, "SELECT emisora, nombre FROM emisoras")
        if f["nombre"]
    }

    def clave(e: str) -> str:
        return claves.get(e, mercado.clave_de(e))

    involucradas = list(dict.fromkeys([*est.emisoras, *foco]))
    precios = mercado.ultimos_precios_mxn(conn, involucradas)
    portafolio = pm.Portafolio(
        portafolio_id=config.PORTAFOLIO_ID,
        moneda="MXN",
        posiciones=tuple(
            pm.Posicion(empresa=clave(p.emisora), cantidad=p.cantidad)
            for p in est.posiciones
        ),
        efectivo=_d(est.efectivo, 2),
    )
    noticias: dict[str, pm.Noticia] = {}
    reportes: dict[str, pm.Reporte] = {}
    documentos_de: dict[str, list[str]] = {}
    for e in foco:
        if titulares := fuentes.titulares_recientes(conn, e, t0):
            noticia, docs = _resumen_titulares(clave(e), nombres.get(e), titulares, t0)
            noticias[noticia.noticia_id] = noticia
            documentos_de[noticia.noticia_id] = docs
        if doc := fuentes.ultimo_reporte(conn, e, t0):
            reportes[doc["doc_id"]] = _reporte(clave(e), doc)
            documentos_de[doc["doc_id"]] = [doc["doc_id"]]

    principal = (
        foco[0]
        if foco
        else (
            max(est.posiciones, key=lambda p: p.valor or 0).emisora
            if est.posiciones
            else None
        )
    )
    lista = escenarios.todos(conn, est, principal, clave)
    para_a3 = {
        e.id: pm.Escenario(
            escenario_id=e.id,
            descripcion=e.descripcion,
            choques_pct={clave(x): _d(c, 2) for x, c in e.choques.items()},
        )
        for e in lista
    }
    datos = pm.DatosSimulados(
        t0=t0,
        portafolios={config.PORTAFOLIO_ID: portafolio},
        precios_t0={clave(e): _d(p) for e, (p, _) in precios.items()},
        politica=pm.Politica(
            policy_id=config.POLITICA_ID,
            concentracion_max_pct=_d(config.REGLAS.concentracion_max_pct, 2),
            # Solo las emisoras del caso: todas son del universo del reto, y
            # 226 claves inflarían cada respuesta de consultar_politica.
            universo=tuple(sorted(clave(e) for e in involucradas)),
            unidades_enteras_positivas=True,
            efectivo_final_minimo=Decimal("0"),
            ventas_en_corto=False,
            apalancamiento=False,
        ),
        noticias=noticias,
        reportes=reportes,
        escenarios=para_a3,
        fallas={},
    )
    return Contexto(
        datos=datos,
        emisora_de={clave(e): e for e in involucradas},
        clave_de={e: clave(e) for e in involucradas},
        foco=list(foco),
        documentos_de=documentos_de,
        nombres={e: nombres[e] for e in foco if e in nombres},
        titulos={e.id: e.titulo for e in lista if e.id not in ("E1", "E2")},
    )


# ═══════════════════════════════════════════
# Emisoras mencionadas en una pregunta
# ═══════════════════════════════════════════


def _plano(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# Claves de cuatro letras que también son palabras del español.
_CLAVES_PALABRA = {"META", "VALE"}
# Cómo se dice además del nombre guardado.
_ALIAS = {"google": "GOOGL", "facebook": "META", "telcel": "AMXB", "bimbo": "BIMBOA"}


def emisoras_mencionadas(conn: sqlite3.Connection, texto: str) -> list[str]:
    """Tickers del reto que aparecen en el texto, en orden de aparición.

    Las claves cortas solo cuentan escritas en mayúsculas: «tan» o «ma» son
    palabras del español, TAN y MA son ETFs. Las de cuatro letras o más y los
    nombres («Walmex», «Nvidia») cuentan como sea que se escriban.
    """
    plano = _plano(texto)
    halladas: dict[str, int] = {}
    filas = db.filas(
        conn, "SELECT emisora, clave, nombre FROM emisoras WHERE con_datos = 1"
    )
    por_clave = {f["clave"]: f["emisora"] for f in filas}

    def anotar(emisora: str, posicion: int) -> None:
        halladas[emisora] = min(posicion, halladas.get(emisora, posicion))

    for f in filas:
        clave, nombre = f["clave"], f["nombre"]
        exacta = rf"(?<![\w&.-]){re.escape(clave)}(?:\.MX)?(?![\w&-])"
        if m := re.search(exacta, texto):
            anotar(f["emisora"], m.start())
        if len(clave) >= 4 and clave not in _CLAVES_PALABRA:
            if m := re.search(rf"(?<!\w){re.escape(_plano(clave))}(?!\w)", plano):
                anotar(f["emisora"], m.start())
        if nombre:
            if m := re.search(rf"(?<!\w){re.escape(_plano(nombre))}(?!\w)", plano):
                anotar(f["emisora"], m.start())
    for alias, clave in _ALIAS.items():
        if clave in por_clave and (m := re.search(rf"\b{alias}\b", plano)):
            anotar(por_clave[clave], m.start())
    return sorted(halladas, key=halladas.get)


# ═══════════════════════════════════════════
# Ejecución de un caso
# ═══════════════════════════════════════════

_MODELO: dict[str, Any] = {}


def modelo_gemini() -> ModeloPara:
    """El mismo cliente y ritmo que la campaña (crear_modelo del ejecutable)."""
    if "para" not in _MODELO:
        pm.cargar_env_local(config.RAIZ / ".env")
        cfg = pm.Configuracion.desde_entorno()
        if cfg.keys_faltantes():
            raise SinKey("Falta GOOGLE_API_KEY: escríbela en .env (ver .env.example).")
        modelo = pm.crear_modelo(cfg.modelo, cfg)
        _MODELO["para"] = lambda _agente: modelo
        _MODELO["nombre"] = cfg.modelo
    return _MODELO["para"]


def hay_key() -> bool:
    pm.cargar_env_local(config.RAIZ / ".env")
    return not pm.Configuracion.desde_entorno().keys_faltantes()


@dataclass
class Consulta:
    run_id: str
    solicitud: str
    contexto: Contexto
    respuesta: pm.RespuestaFinal | None
    resultado: pm.ResultadoCaso | None
    error: str | None
    segundos: float

    @property
    def ok(self) -> bool:
        return self.respuesta is not None

    def documentos(self) -> list[str]:
        """Los doc_id de la base detrás de la evidencia citada."""
        if not self.respuesta:
            return []
        return [
            doc
            for fuente in self.respuesta.evidencia
            for doc in self.contexto.documentos_de.get(fuente, [])
        ]


def consultar(
    conn: sqlite3.Connection,
    solicitud: str,
    foco: list[str],
    *,
    origen: str,
    situacion_id: int | None = None,
    modelo_para: ModeloPara | None = None,
    t0: datetime | None = None,
) -> Consulta:
    """Un caso del comité con datos reales, registrado en ejecuciones_comite.

    Un error del programa no se pierde: queda registrado con su mensaje y la
    traza parcial, igual que en la campaña.
    """
    contexto = construir_contexto(conn, foco, t0)
    texto = f"{solicitud}\n\n{contexto.descripcion()}"
    run_id = f"{origen[:4]}-{uuid.uuid4().hex[:10]}"
    # Sin key no hay caso que registrar: SinKey sale antes de abrir nada.
    para = modelo_para or modelo_gemini()
    inicio = time.monotonic()
    respuesta = resultado = error = None
    try:
        resultado = pm.ejecutar_caso(
            texto, modelo_para=para, run_id=run_id, datos=contexto.datos
        )
        respuesta = resultado.respuesta
    except Exception as fallo:  # noqa: BLE001 — se registra y se muestra
        error = f"{type(fallo).__name__}: {fallo}"
        resultado = None
        parcial = getattr(fallo, "caso_parcial", None)
        if parcial is not None:
            _guardar_parcial(
                conn,
                run_id,
                origen,
                situacion_id,
                texto,
                contexto,
                parcial,
                error,
                time.monotonic() - inicio,
            )
            return Consulta(
                run_id,
                solicitud,
                contexto,
                None,
                None,
                error,
                round(time.monotonic() - inicio, 2),
            )
    segundos = round(time.monotonic() - inicio, 2)
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO ejecuciones_comite
               (run_id, inicio, origen, situacion_id, solicitud, contexto, estado,
                resumen, respuesta, traza, llamadas_modelo, tokens_entrada,
                tokens_salida, segundos, modelo, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                db.ahora_iso(),
                origen,
                situacion_id,
                texto,
                db.a_json(contexto.a_registro()),
                respuesta.estado.value if respuesta else None,
                respuesta.resumen if respuesta else None,
                respuesta.model_dump_json() if respuesta else None,
                resultado.traza.a_jsonl() if resultado else None,
                resultado.presupuesto.llamadas_modelo if resultado else 0,
                (resultado.tokens or {}).get("input_tokens", 0) if resultado else 0,
                (resultado.tokens or {}).get("output_tokens", 0) if resultado else 0,
                segundos,
                _MODELO.get("nombre") if modelo_para is None else "inyectado",
                error,
            ),
        )
    return Consulta(run_id, solicitud, contexto, respuesta, resultado, error, segundos)


def _guardar_parcial(
    conn, run_id, origen, situacion_id, texto, contexto, caso, error, segundos
) -> None:
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO ejecuciones_comite
               (run_id, inicio, origen, situacion_id, solicitud, contexto, traza,
                llamadas_modelo, segundos, modelo, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                db.ahora_iso(),
                origen,
                situacion_id,
                texto,
                db.a_json(contexto.a_registro()),
                caso.traza.a_jsonl(),
                caso.presupuesto.llamadas_modelo,
                round(segundos, 2),
                _MODELO.get("nombre"),
                error,
            ),
        )


def llamadas_hoy(conn: sqlite3.Connection) -> int:
    """Llamadas al modelo de agentes registradas hoy, contra las 500 diarias."""
    hoy = db.ahora().date().isoformat()
    f = db.fila(
        conn,
        "SELECT COALESCE(SUM(llamadas_modelo), 0) AS n FROM ejecuciones_comite "
        "WHERE substr(inicio, 1, 10) = ?",
        hoy,
    )
    return int(f["n"])
