import pandas as pd
import streamlit as st

from comite import cartera, db, mercado, ui
from comite.config import REGLAS

conn = ui.conexion()

st.title("Cartera", anchor=False)

est = cartera.estado(conn)
tabla = cartera.tabla_posiciones(est)
with st.container(horizontal=True):
    st.metric("Valor total", ui.moneda(est.total), border=True)
    st.metric("Efectivo", ui.moneda(est.efectivo), border=True)
    st.metric("Posiciones", len(est.posiciones), border=True)
    fx = mercado.tipo_de_cambio(conn)
    st.metric(
        "USDMXN",
        f"{fx[0]:.4f}" if fx else "—",
        help=f"Al {fx[1]}" if fx else None,
        border=True,
    )

st.dataframe(
    tabla,
    hide_index=True,
    column_config={
        "Títulos": st.column_config.NumberColumn(format="%d"),
        "Costo promedio": st.column_config.NumberColumn(format="$%.2f"),
        "Precio": st.column_config.NumberColumn(format="$%.2f"),
        "Valor": st.column_config.NumberColumn(format="$%,.0f"),
        "Peso %": st.column_config.ProgressColumn(
            format="%.1f%%", min_value=0, max_value=100
        ),
        "Rend. %": st.column_config.NumberColumn(format="%+.2f%%"),
    },
    alt="Posiciones de la cartera valuadas en pesos",
)
st.caption(
    f"Límite de concentración: {REGLAS.concentracion_max_pct:.0f}% por emisora. Las "
    "emisoras del SIC se valúan con el tipo de cambio del día."
)

st.subheader("Estrés de tu cartera", anchor=False)
ui.mostrar_estres(conn)

st.subheader("Rendimiento contra los benchmarks del reto", anchor=False)
historia = cartera.historial(conn)
if historia.empty:
    st.caption("Aparece cuando captures tu cartera.")
else:
    st.line_chart(
        historia,
        y_label="Base 100",
        alt="Rendimiento de la cartera contra Conservador, Moderado y Agresivo",
    )
    st.caption(
        "Base 100 el día de la primera operación. Los benchmarks llegan hasta su "
        "último dato publicado en el archivo del reto."
    )

st.subheader("Capturar mi cuenta del reto", anchor=False)
claves = mercado.emisoras(conn)
opciones = sorted(claves["clave"]) if not claves.empty else []
emisora_de = mercado.mapa_claves(conn)

with st.expander(
    "Carga rápida: posiciones actuales y efectivo",
    icon=":material/upload:",
    expanded=not est.posiciones,
):
    st.caption(
        "Reemplaza la carga inicial. Escribe cada posición con su costo promedio "
        "en pesos y el efectivo que hoy muestra el reto."
    )
    actuales = pd.DataFrame(
        [
            {"Emisora": p.clave, "Títulos": p.cantidad, "Costo": p.costo_promedio}
            for p in est.posiciones
        ]
        or [{"Emisora": None, "Títulos": None, "Costo": None}]
    )
    with st.form("carga"):
        editadas = st.data_editor(
            actuales,
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "Emisora": st.column_config.SelectboxColumn(
                    options=opciones, required=True
                ),
                "Títulos": st.column_config.NumberColumn(min_value=1, step=1),
                "Costo": st.column_config.NumberColumn(
                    "Costo promedio (MXN)", min_value=0.0001, format="$%.2f"
                ),
            },
            alt="Editor de posiciones iniciales",
        )
        with st.container(horizontal=True, vertical_alignment="bottom"):
            efectivo = st.number_input(
                "Efectivo actual (MXN)",
                min_value=0.0,
                value=float(est.efectivo),
                step=1000.0,
            )
            fecha = st.date_input("Fecha de inicio", value=db.ahora().date())
            guardar = st.form_submit_button(
                "Guardar cartera", type="primary", icon=":material/save:"
            )
    if guardar:
        filas = editadas.dropna(subset=["Emisora", "Títulos", "Costo"])
        cartera.cargar_posiciones(
            conn,
            fecha.isoformat(),
            [
                {
                    "emisora": emisora_de[f["Emisora"]],
                    "cantidad": int(f["Títulos"]),
                    "precio": float(f["Costo"]),
                }
                for _, f in filas.iterrows()
            ],
            efectivo,
        )
        st.success("Cartera guardada.")
        st.rerun()

with st.expander(
    "Registrar una operación hecha fuera de la app", icon=":material/edit:"
):
    with st.form("operacion"):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            lado = st.segmented_control(
                "Operación", ["compra", "venta"], default="compra"
            )
            clave = st.selectbox("Emisora", opciones)
            cantidad = st.number_input("Títulos", min_value=1, step=1)
            precio = st.number_input("Precio (MXN)", min_value=0.0001, format="%.4f")
            folio = st.text_input("Folio")
            enviar = st.form_submit_button("Registrar", icon=":material/add:")
    if enviar and clave and lado:
        try:
            cartera.registrar(
                conn,
                fecha=db.ahora().date().isoformat(),
                lado=lado,
                emisora=emisora_de[clave],
                cantidad=int(cantidad),
                precio=float(precio),
                monto=int(cantidad) * float(precio),
                folio=folio or None,
            )
            st.success("Registrada.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

st.subheader("Libro de operaciones", anchor=False)
ops = cartera.operaciones(conn)
if ops.empty:
    st.caption("Sin operaciones.")
else:
    st.dataframe(
        ops[
            [
                "fecha",
                "lado",
                "emisora",
                "cantidad",
                "precio",
                "monto",
                "origen",
                "recomendacion_id",
                "folio",
                "nota",
            ]
        ].iloc[::-1],
        hide_index=True,
        column_config={
            "precio": st.column_config.NumberColumn(format="$%.2f"),
            "monto": st.column_config.NumberColumn(format="$%,.2f"),
        },
        alt="Libro de operaciones",
    )
