from datetime import date

import streamlit as st

from comite import (
    analisis,
    cartera,
    db,
    ejecucion,
    estrategia,
    proceso,
    recomendador,
    ui,
)

conn = ui.conexion()

st.title("Qué hacer hoy", anchor=False)

est = cartera.estado(conn)
if not est.posiciones and est.efectivo == 0:
    st.info(
        "Captura primero tus posiciones y tu efectivo del reto en la página "
        "**Cartera**. Sin cartera el vigía solo puede mirar el mercado.",
        icon=":material/info:",
        title="Todavía no hay cartera",
    )
if estrategia.vigente(conn) is None:
    st.info(
        "Sin estrategia elegida, el vigía cuida riesgo, noticias y reportes, pero "
        "no propone qué comprar. Revisa la validación y elige una en "
        "**Estrategia**.",
        icon=":material/insights:",
    )

# --- Indicadores ---
historia = cartera.historial(conn)
total = est.total
with st.container(horizontal=True):
    st.metric("Valor del portafolio", ui.moneda(total), border=True)
    if not historia.empty:
        mio = historia["Mi portafolio"].iloc[-1] - 100
        st.metric("Rendimiento", f"{mio:+.2f}%", border=True)
        if "Moderado" in historia and historia["Moderado"].notna().any():
            ultimo = historia["Moderado"].last_valid_index()
            dif = historia.at[ultimo, "Mi portafolio"] - historia.at[ultimo, "Moderado"]
            st.metric(
                "Contra el benchmark Moderado",
                f"{dif:+.2f} pp",
                help=f"Al {ultimo.date()}, último dato publicado del benchmark.",
                border=True,
            )
    st.metric(
        "Efectivo",
        f"{est.efectivo / total * 100:.1f}%" if total else ui.moneda(est.efectivo),
        border=True,
    )
    st.metric("Por decidir", len(recomendador.pendientes(conn)), border=True)

# --- El recorrido ---
with st.container(border=True):
    st.markdown(
        "**Recorrer todo el proceso**: actualiza precios, noticias y reportes, "
        "aplica las reglas del vigía y le pasa al comité las situaciones más "
        "importantes. Al final quedan abajo las acciones que te recomiendo."
    )
    ultimo = proceso.ultimo_recorrido(conn)
    if ultimo:
        st.caption(f"Último recorrido: {ultimo[:16].replace('T', ' ')}")
    ui.estado_monitor(conn)
    if st.button(
        "Recorrer todo el proceso",
        type="primary",
        icon=":material/play_arrow:",
        width="stretch",
    ):
        with st.status("Recorriendo el proceso…", expanded=True) as estado:

            def avisar(paso: str, detalle: str) -> None:
                st.write(f"**{paso}** · {detalle}")

            resumen = proceso.recorrer(
                conn,
                usar_comite=st.session_state.usar_comite,
                max_analisis=int(st.session_state.max_analisis),
                avisar=avisar,
            )
            for aviso in resumen.avisos:
                st.warning(aviso)
            estado.update(
                label=(
                    f"Listo: {resumen.situaciones_nuevas} situaciones nuevas, "
                    f"{len(resumen.por_regla) + len(resumen.por_comite)} "
                    f"recomendaciones, {resumen.sin_analizar} sin analizar"
                ),
                state="complete",
                expanded=False,
            )

# --- Lo que hay que decidir ---
st.subheader("Lo que te recomiendo hacer", anchor=False)
pendientes = recomendador.pendientes(conn)
if not pendientes:
    st.caption(
        "No hay compras ni ventas pendientes. Corre el proceso o pregúntale al "
        "comité en el chat."
    )


@st.fragment
def tarjeta(rec: dict) -> None:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            ui.accion_badge(rec["accion"])
            st.badge(
                "Aprobada · falta capturarla"
                if rec["estado"] == "aprobada"
                else "Por aprobar",
                color="violet" if rec["estado"] == "aprobada" else "gray",
            )
            st.badge(
                "Comité" if rec["origen"] == "comite" else "Regla",
                icon=":material/groups:"
                if rec["origen"] == "comite"
                else ":material/rule:",
                color="blue" if rec["origen"] == "comite" else "gray",
            )
            if rec["situacion"]:
                st.caption(rec["situacion"])
        st.markdown(rec["razon"])
        if rec["resumen_comite"] or rec["run_id"]:
            with st.expander(
                "Análisis del comité y evidencia", icon=":material/description:"
            ):
                ui.estado_comite_badge(rec["estado_comite"])
                if rec["resumen_comite"]:
                    st.markdown(rec["resumen_comite"])
                ui.mostrar_metricas(db.de_json(rec["metricas"], {}))
                ui.mostrar_evidencia(conn, db.de_json(rec["evidencia"], []))
        if rec["emisora"]:
            with st.expander(
                f"Ficha de {rec['clave'] or rec['emisora']}",
                icon=":material/query_stats:",
            ):
                ui.mostrar_ficha(conn, rec["emisora"])
        if rec["accion"] == "comprar" and rec["cantidad"]:
            with st.expander("Estrés de la compra", icon=":material/thunderstorm:"):
                ui.mostrar_estres(conn, rec["emisora"], int(rec["cantidad"]))
        if rec["estado"] == "propuesta":
            with st.container(horizontal=True):
                if st.button(
                    "Aprobar",
                    key=f"aprobar-{rec['id']}",
                    type="primary",
                    icon=":material/check:",
                ):
                    try:
                        ejecucion.aprobar(conn, rec["id"])
                        st.rerun()
                    except ejecucion.OrdenInvalida as error:
                        st.error(str(error), icon=":material/error:")
                if st.button(
                    "Rechazar", key=f"rechazar-{rec['id']}", icon=":material/close:"
                ):
                    ejecucion.rechazar(conn, rec["id"])
                    st.rerun()
        else:
            try:
                boleta = ejecucion.boleta(conn, rec["id"])
            except ejecucion.OrdenInvalida as error:
                st.warning(f"La orden ya no es válida: {error}")
                if st.button("Descartar", key=f"descartar-{rec['id']}"):
                    ejecucion.rechazar(conn, rec["id"], "Ya no era válida.")
                    st.rerun()
                return
            st.markdown("**Captúrala en el simulador del reto:**")
            st.code(boleta.texto(), language=None)
            with st.form(f"registro-{rec['id']}", border=False):
                with st.container(horizontal=True, vertical_alignment="bottom"):
                    precio = st.number_input(
                        "Precio ejecutado",
                        value=float(boleta.precio_actual),
                        min_value=0.0001,
                        format="%.4f",
                    )
                    titulos = st.number_input(
                        "Títulos",
                        value=int(boleta.titulos),
                        min_value=1,
                        max_value=int(boleta.titulos),
                    )
                    folio = st.text_input("Folio del reto")
                    enviado = st.form_submit_button(
                        "Registrar ejecución",
                        icon=":material/done_all:",
                        type="primary",
                    )
                if enviado:
                    try:
                        ejecucion.registrar(
                            conn,
                            rec["id"],
                            precio=precio,
                            cantidad=int(titulos),
                            folio=folio or None,
                        )
                        st.success("Registrada: tu cartera ya la incluye.")
                        st.rerun(scope="app")
                    except ejecucion.OrdenInvalida as error:
                        st.error(str(error))
            if st.button("Cancelar", key=f"cancelar-{rec['id']}"):
                ejecucion.rechazar(conn, rec["id"], "Cancelada antes de capturarla.")
                st.rerun(scope="app")


for rec in pendientes:
    tarjeta(rec)

# --- Calendario de la cartera ---
hoy = db.ahora().date()
proximos = [
    (p.clave, fecha)
    for p in est.posiciones
    if (fecha := analisis.proximo_reporte(conn, p.emisora)) and fecha >= hoy.isoformat()
]
if proximos:
    st.subheader("Próximos reportes de tu cartera", anchor=False)
    st.caption(
        "Según el calendario de Yahoo. Tres días antes, el vigía te avisa; cuando "
        "el trimestre aparece, lo pasa al comité."
    )
    with st.container(horizontal=True):
        for clave, fecha in sorted(proximos, key=lambda x: x[1]):
            dias = (date.fromisoformat(fecha) - hoy).days
            st.metric(clave, fecha, f"en {dias} días", delta_color="off", border=True)

# --- Lo demás ---
st.subheader("Lo que no requiere acción", anchor=False)
otras = [
    r
    for r in recomendador.recientes(conn, 40)
    if r["estado"] in ("informativa", "bloqueada")
]
if not otras:
    st.caption("Todavía nada.")
for rec in otras[:15]:
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            ui.accion_badge(rec["accion"])
            st.caption(
                f"{rec['creada'][:16].replace('T', ' ')} · {rec['situacion'] or ''}"
            )
        st.markdown(rec["razon"])
        if rec["resumen_comite"]:
            with st.expander("Análisis del comité", icon=":material/description:"):
                st.markdown(rec["resumen_comite"])
                ui.mostrar_evidencia(conn, db.de_json(rec["evidencia"], []))
