"""Piezas de la app de Streamlit compartidas entre páginas.

La lógica vive en el resto del paquete; aquí solo se presenta. Ninguna
prueba importa este módulo.
"""

import json
from typing import Any

import pandas as pd
import streamlit as st

from comite import analisis, config, db, escenarios, mercado, puente, recomendador

COLOR_ACCION = {
    "comprar": "green",
    "vender": "red",
    "mantener": "blue",
    "vigilar": "orange",
    "no_operar": "gray",
}
ICONO_ACCION = {
    "comprar": ":material/add_shopping_cart:",
    "vender": ":material/sell:",
    "mantener": ":material/pause_circle:",
    "vigilar": ":material/visibility:",
    "no_operar": ":material/block:",
}
COLOR_SEVERIDAD = {"alta": "red", "media": "orange", "baja": "gray"}
ESTADOS_COMITE = {
    "informativo": ("Informativo", "blue"),
    "calculo_hipotetico": ("Cálculo hipotético", "violet"),
    "datos_insuficientes": ("Datos insuficientes", "orange"),
    "bloqueada": ("Bloqueada por riesgo", "red"),
    "pendiente_revision_humana": ("Conforme · pendiente de tu revisión", "green"),
    "error_controlado": ("Error controlado", "gray"),
}


@st.cache_resource
def conexion():
    return db.conectar()


def asegurar_datos(conn) -> None:
    """Primera vez: universo, historial, benchmarks y tipo de cambio."""
    if db.fila(conn, "SELECT 1 FROM emisoras LIMIT 1"):
        return
    with st.status("Preparando la base del reto por primera vez…", expanded=True) as s:
        tabla = mercado.leer_historia()
        resumen = mercado.importar_reto(conn, tabla)
        st.write(
            f"{resumen['emisoras']} emisoras y {resumen['precios']:,} cierres "
            "importados del reto."
        )
        if mercado.serie_tipo_de_cambio(conn).empty:
            try:
                n = mercado.importar_tipo_de_cambio(conn)
                st.write(f"Tipo de cambio USDMXN: {n} cierres.")
            except Exception as error:  # noqa: BLE001
                st.warning(f"No pude descargar USDMXN: {error}")
        s.update(label="Base lista", state="complete")


def accion_badge(accion: str) -> None:
    st.badge(
        recomendador.ACCIONES[accion],
        icon=ICONO_ACCION[accion],
        color=COLOR_ACCION[accion],
    )


def estado_comite_badge(estado: str | None) -> None:
    if not estado:
        return
    texto, color = ESTADOS_COMITE.get(estado, (estado, "gray"))
    st.badge(texto, color=color)


def documentos(conn, doc_ids: list[str]) -> list[dict[str, Any]]:
    if not doc_ids:
        return []
    marcas = ",".join("?" * len(doc_ids))
    return db.filas(
        conn,
        f"SELECT * FROM documentos WHERE doc_id IN ({marcas}) "
        "ORDER BY fecha_publicacion DESC",
        *doc_ids,
    )


def mostrar_evidencia(conn, doc_ids: list[str]) -> None:
    docs = documentos(conn, doc_ids)
    if not docs:
        st.caption("Sin documentos citados.")
        return
    for d in docs:
        fecha = d["fecha_publicacion"][:10]
        estimada = " (fecha estimada)" if d["fecha_estimada"] else ""
        titulo = d["titulo"].replace("[", "(").replace("]", ")")
        enlace = f"[{titulo}]({d['url']})" if d["url"] else titulo
        st.markdown(f"- {fecha}{estimada} · {d['fuente']} · {enlace}")


def mostrar_metricas(metricas: dict[str, Any]) -> None:
    if not metricas:
        return
    filas = [
        {"Métrica": k.replace("_", " "), "Valor": _texto(v)}
        for k, v in metricas.items()
    ]
    st.dataframe(
        pd.DataFrame(filas),
        hide_index=True,
        alt="Cifras calculadas por las herramientas del comité",
    )


def _texto(valor: Any) -> str:
    if isinstance(valor, float):
        return f"{valor:,.2f}"
    return str(valor)


def pasos_de_traza(traza_jsonl: str | None) -> list[dict[str, Any]]:
    """Delegaciones y herramientas, en orden: la trayectoria del caso."""
    if not traza_jsonl:
        return []
    pasos = []
    for linea in traza_jsonl.splitlines():
        e = json.loads(linea)
        if e["clase"] not in ("delegacion", "herramienta"):
            continue
        actor = e["actor"] + (f" → {e['destino']}" if e.get("destino") else "")
        args = {k: v for k, v in (e.get("args") or {}).items() if k not in ("tarea",)}
        pasos.append(
            {
                "#": e["seq"],
                "Quién": actor,
                "Qué": e["nombre"],
                "Argumentos": json.dumps(args, ensure_ascii=False)[:160],
                "Estado": e["status"] + (" · bloqueado" if e.get("bloqueado") else ""),
            }
        )
    return pasos


def mostrar_trayectoria(traza_jsonl: str | None) -> None:
    pasos = pasos_de_traza(traza_jsonl)
    if not pasos:
        st.caption("Sin pasos registrados.")
        return
    st.dataframe(
        pd.DataFrame(pasos),
        hide_index=True,
        alt="Trayectoria del caso: delegaciones y herramientas en orden",
    )


def estado_modelo(conn) -> None:
    """Key y cuota, en la barra lateral."""
    if puente.hay_key():
        usadas = puente.llamadas_hoy(conn)
        st.caption(f":material/key: Gemini listo · {usadas} de ~500 llamadas hoy")
    else:
        st.caption(":material/key_off: Sin GOOGLE_API_KEY: el comité no puede correr.")


_INDICADORES = {
    "margen_bruto_pct": "Margen bruto %",
    "margen_neto_pct": "Margen neto %",
    "crecimiento_utilidad_neta_pct": "Variación utilidad neta %",
    "flujo_libre": "Flujo libre (millones)",
    "deuda_neta": "Deuda neta (millones)",
    "deuda_neta_entre_ebitda_12m": "Deuda neta / EBITDA 12m (veces)",
    "rendimiento_sobre_capital_pct": "Rendimiento sobre capital %",
}


def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:+.1f}%"


def mostrar_ficha(conn, emisora: str) -> None:
    """Precio, tendencia, reporte y calendario de una emisora (D75)."""
    f = analisis.ficha(conn, emisora)
    tec = f["tecnicos"]
    if tec:
        with st.container(horizontal=True):
            st.metric(f"Precio al {tec['fecha']}", f"${tec['precio']:,.2f}")
            st.metric("20 sesiones", _pct(tec["rend_20d_pct"]))
            st.metric("120 sesiones", _pct(tec["rend_120d_pct"]))
            st.metric("Contra su media de 200", _pct(tec["distancia_media_pct"]))
            st.metric(
                "Desde su máximo de 12 meses", _pct(tec["caida_desde_maximo_pct"])
            )
            st.metric(
                "Volatilidad anual",
                "—"
                if tec["volatilidad_60d_pct"] is None
                else f"{tec['volatilidad_60d_pct']:.0f}%",
            )
    reporte = f["reporte"]
    if reporte:
        ind = reporte.get("indicadores") or {}
        val = reporte.get("valuacion") or {}
        filas = [
            {"Indicador": nombre, "Valor": _texto(ind.get(clave))}
            for clave, nombre in _INDICADORES.items()
            if ind.get(clave) is not None
        ]
        if val.get("per") is not None:
            filas.append(
                {"Indicador": "Precio / utilidad (veces)", "Valor": _texto(val["per"])}
            )
        if filas:
            st.caption(
                f"Reporte {reporte['periodo']} contra {reporte['periodo_comparado']} "
                f"({f['doc_id']}), en {reporte['moneda']}. Lo mismo que A2 lee en "
                "su nota de indicadores."
            )
            st.dataframe(
                pd.DataFrame(filas),
                hide_index=True,
                alt="Indicadores financieros del último reporte",
            )
    if f["proximo_reporte"]:
        st.caption(
            f"Fecha de reporte según el calendario de Yahoo: {f['proximo_reporte']}"
        )
    for alerta in f["alertas"]:
        st.markdown(f":orange[:material/warning:] {alerta}")


def mostrar_estres(conn, emisora: str | None = None, cantidad: int = 0) -> None:
    """Pérdida bajo los escenarios de A3, hoy y con la compra (D76)."""
    filas = escenarios.perdidas(conn, emisora, cantidad)
    if not filas:
        st.caption("Sin posiciones ni precios no hay escenarios que simular.")
        return
    if emisora and cantidad:
        tabla = pd.DataFrame(
            {
                "Escenario": [f["id"] for f in filas],
                "Supuesto": [f["titulo"] for f in filas],
                "Pérdida hoy": [f["antes"] for f in filas],
                "Con la compra": [f["despues"] for f in filas],
                "Cambio": [f["despues"] - f["antes"] for f in filas],
            }
        )
        formato = {
            c: st.column_config.NumberColumn(format="$%,.0f")
            for c in ("Pérdida hoy", "Con la compra", "Cambio")
        }
    else:
        tabla = pd.DataFrame(
            {
                "Escenario": [f["id"] for f in filas],
                "Supuesto": [f["titulo"] for f in filas],
                "Pérdida": [f["antes"] for f in filas],
                "% de la cartera": [f["antes_pct"] for f in filas],
            }
        )
        formato = {
            "Pérdida": st.column_config.NumberColumn(format="$%,.0f"),
            "% de la cartera": st.column_config.NumberColumn(format="%.2f%%"),
        }
    st.dataframe(
        tabla,
        hide_index=True,
        column_config=formato,
        alt="Pérdida de la cartera bajo cada escenario de estrés",
    )
    st.caption(
        "Una pérdida negativa es ganancia. Son supuestos, no predicciones; el "
        "efectivo no cambia."
    )
    for f in filas:
        st.caption(f"**{f['id']}.** {f['descripcion']}")


def estado_monitor(conn) -> None:
    registro = db.leer_parametro(conn, "monitor")
    if not registro:
        st.caption(
            ":material/schedule: El monitor no ha corrido. Para dejarlo vigilando: "
            "`python -m comite vigilar`."
        )
        return
    hora = registro["ultima"][:16].replace("T", " ")
    st.caption(
        f":material/schedule: Monitor: última vuelta {hora} · "
        f"{registro['propuestas_nuevas']} propuestas nuevas"
        + ("" if registro["con_comite"] else " · sin comité")
    )


def moneda(valor: float | None) -> str:
    return "—" if valor is None else f"${valor:,.0f}"


def nombre_portafolio() -> str:
    return config.PORTAFOLIO_ID
