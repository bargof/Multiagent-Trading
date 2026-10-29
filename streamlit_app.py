"""App del comité de inversión sobre el Reto Actinver.

    streamlit run streamlit_app.py

Seis páginas: qué hacer hoy, la cartera contra los benchmarks, la
estrategia y su validación, las situaciones del vigía, el chat con el
comité y la bitácora de casos.
"""

import streamlit as st

from comite import ui
from comite.config import REGLAS

st.set_page_config(
    page_title="Comité de inversión · Reto Actinver",
    page_icon=":material/account_balance:",
    layout="wide",
)

conn = ui.conexion()
ui.asegurar_datos(conn)

st.session_state.setdefault("usar_comite", True)
st.session_state.setdefault("max_analisis", REGLAS.analisis_por_corrida)

pagina = st.navigation(
    [
        st.Page("app_pages/hoy.py", title="Qué hacer", icon=":material/task_alt:"),
        st.Page("app_pages/cartera.py", title="Cartera", icon=":material/pie_chart:"),
        st.Page(
            "app_pages/estrategia.py", title="Estrategia", icon=":material/insights:"
        ),
        st.Page(
            "app_pages/situaciones.py",
            title="Situaciones",
            icon=":material/notifications:",
        ),
        st.Page("app_pages/comite.py", title="Comité", icon=":material/forum:"),
        st.Page("app_pages/bitacora.py", title="Bitácora", icon=":material/history:"),
    ],
    position="top",
)

with st.sidebar:
    st.subheader("Comité de inversión")
    st.caption(
        "Cinco agentes (A0–A4) sobre datos reales del Reto Actinver. Tú apruebas "
        "y capturas cada orden."
    )
    st.toggle(
        "Usar el comité (gasta cuota de Gemini)",
        key="usar_comite",
        help="Sin el comité solo corren las reglas del vigía.",
    )
    st.number_input(
        "Situaciones a analizar por corrida",
        min_value=1,
        max_value=10,
        key="max_analisis",
        help="Cada análisis usa entre 4 y 13 llamadas al modelo y tarda ~1 min.",
    )
    ui.estado_modelo(conn)
    ui.estado_monitor(conn)

pagina.run()
