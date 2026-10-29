import pandas as pd
import streamlit as st

from comite import db, ui

conn = ui.conexion()

st.title("Bitácora", anchor=False)
st.caption(
    "Cada caso del comité queda con su solicitud, los datos que vio, la respuesta "
    "y la traza completa: la misma evidencia que en la campaña de evaluación."
)

casos = db.filas(
    conn,
    """SELECT run_id, inicio, origen, estado, llamadas_modelo, tokens_entrada,
              tokens_salida, segundos, error, solicitud, resumen, respuesta, traza,
              contexto
       FROM ejecuciones_comite ORDER BY inicio DESC LIMIT 200""",
)
if not casos:
    st.caption("Todavía no hay casos.")
    st.stop()

tabla = pd.DataFrame(casos)[
    ["run_id", "inicio", "origen", "estado", "llamadas_modelo", "segundos", "error"]
]
tabla["inicio"] = tabla["inicio"].str[:16].str.replace("T", " ")
with st.container(horizontal=True):
    st.metric("Casos", len(casos), border=True)
    st.metric("Llamadas al modelo", int(tabla["llamadas_modelo"].sum()), border=True)
    st.metric("Con error", int(tabla["error"].notna().sum()), border=True)

seleccion = st.dataframe(
    tabla,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    alt="Casos del comité",
)
if not seleccion.selection.rows:
    st.caption("Selecciona un caso para ver su trayectoria.")
else:
    caso = casos[seleccion.selection.rows[0]]
    with st.container(border=True):
        ui.estado_comite_badge(caso["estado"])
        if caso["error"]:
            st.error(caso["error"])
        st.markdown("**Solicitud**")
        st.text(caso["solicitud"])
        if caso["resumen"]:
            st.markdown("**Respuesta**")
            st.markdown(caso["resumen"])
            respuesta = db.de_json(caso["respuesta"], {})
            ui.mostrar_metricas(respuesta.get("metricas", {}))
        st.markdown("**Trayectoria**")
        ui.mostrar_trayectoria(caso["traza"])
        with st.expander("Datos que vio el comité", icon=":material/dataset:"):
            st.json(db.de_json(caso["contexto"], {}), expanded=False)

st.subheader("Historial de recomendaciones", anchor=False)
recs = db.filas(
    conn,
    """SELECT r.id, r.creada, r.origen, r.accion, e.clave AS emisora, r.cantidad,
              r.estado, r.razon, r.nota
       FROM recomendaciones r LEFT JOIN emisoras e ON e.emisora = r.emisora
       ORDER BY r.id DESC LIMIT 300""",
)
if recs:
    tabla = pd.DataFrame(recs)
    tabla["creada"] = tabla["creada"].str[:16].str.replace("T", " ")
    st.dataframe(tabla, hide_index=True, alt="Historial de recomendaciones")
