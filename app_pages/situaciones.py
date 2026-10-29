import pandas as pd
import streamlit as st

from comite import db, puente, recomendador, ui

conn = ui.conexion()

st.title("Situaciones", anchor=False)
st.caption(
    "Lo que el vigía detecta con reglas fijas, sin gastar cuota: concentración, "
    "estrés tipo E1, movimientos de precio, noticias, reportes y calendario de "
    "tu cartera, el rebalanceo de tu estrategia y emisoras del reto que destacan."
)

filtro = st.segmented_control(
    "Mostrar", ["Abiertas", "Todas"], default="Abiertas", label_visibility="collapsed"
)
sql = "SELECT * FROM situaciones"
if filtro == "Abiertas":
    sql += " WHERE estado = 'abierta'"
sql += (
    " ORDER BY CASE severidad WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END,"
    " detectada DESC LIMIT 300"
)
situaciones = db.filas(conn, sql)
if not situaciones:
    st.caption("No hay situaciones. Corre el proceso en **Qué hacer**.")
    st.stop()

tabla = pd.DataFrame(situaciones)[
    ["id", "detectada", "severidad", "tipo", "titulo", "detalle", "estado"]
]
tabla["detectada"] = tabla["detectada"].str[:16].str.replace("T", " ")
seleccion = st.dataframe(
    tabla,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={"id": st.column_config.NumberColumn("#", format="%d")},
    alt="Situaciones detectadas por el vigía",
)

filas = seleccion.selection.rows
if not filas:
    st.caption("Selecciona una situación para ver el detalle o analizarla.")
    st.stop()

sit = situaciones[filas[0]]
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.badge(sit["severidad"], color=ui.COLOR_SEVERIDAD[sit["severidad"]])
        st.badge(sit["tipo"], color="blue")
        st.badge(sit["estado"], color="gray")
    st.markdown(f"**{sit['titulo']}**\n\n{sit['detalle']}")
    datos = db.de_json(sit["datos"], {})
    if datos:
        ui.mostrar_metricas(datos)
    ui.mostrar_evidencia(conn, db.de_json(sit["evidencia"], []))
    if sit["emisora"]:
        with st.expander("Ficha de la emisora", icon=":material/query_stats:"):
            ui.mostrar_ficha(conn, sit["emisora"])

    solicitud = recomendador.solicitud_para(conn, sit)
    if sit["estado"] != "abierta":
        recs = db.filas(
            conn, "SELECT * FROM recomendaciones WHERE situacion_id = ?", sit["id"]
        )
        for rec in recs:
            ui.accion_badge(rec["accion"])
            st.markdown(rec["razon"])
    elif solicitud is None:
        if st.button("Resolver con la regla", icon=":material/rule:"):
            recomendador.guardar(conn, recomendador.por_regla(conn, sit))
            st.rerun()
    else:
        st.caption(f"Pregunta para el comité: _{solicitud[0]}_")
        if st.button(
            "Analizar con el comité",
            type="primary",
            icon=":material/groups:",
            disabled=not puente.hay_key(),
        ):
            with st.status(":shimmer[El comité está trabajando]", expanded=False) as s:
                consulta = puente.consultar(
                    conn,
                    solicitud[0],
                    solicitud[1],
                    origen="vigia",
                    situacion_id=sit["id"],
                )
                rec = recomendador.desde_comite(conn, sit, consulta)
                recomendador.guardar(conn, rec)
                s.update(label=f"Listo en {consulta.segundos:.0f} s", state="complete")
            st.rerun()
