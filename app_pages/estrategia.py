import pandas as pd
import streamlit as st

from comite import backtest, cartera, config, db, estrategia, mercado, ui

conn = ui.conexion()

st.title("Estrategia", anchor=False)
st.caption(
    "Qué cartera tener según una regla fija, probada con el historial del reto "
    "antes de usarla. El vigía propone el rebalanceo; las compras pasan por el "
    "comité y las ventas son de la regla. Tú apruebas cada orden."
)


@st.cache_data(show_spinner="Probando las estrategias con el historial del reto…")
def _comparar(ultima_fecha: str) -> backtest.Comparacion | str:
    # ultima_fecha solo es la llave del caché: con precios nuevos se recalcula.
    try:
        return backtest.comparar(*backtest.cargar(ui.conexion()))
    except ValueError as error:
        return str(error)


ultima = db.fila(conn, "SELECT MAX(fecha) AS f FROM precios")["f"] or ""
comparacion = _comparar(ultima)

# --- Elegir ---
vigente = estrategia.vigente(conn)
opciones = [None, *(e.nombre for e in estrategia.CANDIDATAS[1:])]


def _etiqueta(nombre: str | None) -> str:
    if nombre is None:
        return "Ninguna: solo vigilar riesgo, noticias y reportes"
    marca = (
        " · elegida por el protocolo" if nombre == config.ESTRATEGIA_PROTOCOLO else ""
    )
    return f"{nombre}{marca}"


def _cambiar() -> None:
    estrategia.elegir(conn, st.session_state.estrategia_elegida)


with st.container(border=True):
    st.radio(
        "Estrategia vigente",
        opciones,
        index=opciones.index(vigente.nombre if vigente else None),
        format_func=_etiqueta,
        captions=[
            "El vigía no propone compras ni rebalanceo.",
            *(e.descripcion for e in estrategia.CANDIDATAS[1:]),
        ],
        key="estrategia_elegida",
        on_change=_cambiar,
    )
    st.caption(
        "Cambiar de estrategia descarta las órdenes pendientes del ciclo y el "
        "siguiente recorrido arma uno nuevo. El reto pide al menos cinco "
        "emisoras distintas para concursar: todas las candidatas tienen 10 o 15."
    )

# --- El ciclo vigente ---
if vigente is not None:
    st.subheader("Cartera objetivo", anchor=False)
    ciclo = db.leer_parametro(conn, "ciclo")
    if not ciclo or ciclo.get("estrategia") != vigente.nombre:
        st.info(
            "Corre el proceso en **Qué hacer** para iniciar el ciclo: ahí se "
            "calcula la cartera objetivo y las órdenes del rebalanceo.",
            icon=":material/play_arrow:",
        )
    else:
        # Igual que el vigía: sesiones con cierre después de la señal y antes
        # de hoy.
        transcurridas = db.fila(
            conn,
            "SELECT COUNT(DISTINCT fecha) AS n FROM precios WHERE fecha > ? "
            "AND fecha < ?",
            ciclo["senal_al"],
            db.ahora().date().isoformat(),
        )["n"]
        with st.container(horizontal=True):
            st.metric("Inicio del ciclo", ciclo["inicio"], border=True)
            st.metric(
                "Señal con cierres al",
                ciclo["senal_al"],
                border=True,
            )
            st.metric(
                "Próximo rebalanceo",
                f"en {max(vigente.rebalanceo - transcurridas, 0)} sesiones",
                border=True,
            )
        est = cartera.estado(conn)
        total = est.total
        claves = mercado.mapa_claves(conn)
        inversa = {v: k for k, v in claves.items()}
        filas = []
        for emisora in dict.fromkeys([*ciclo["objetivo"], *est.emisoras]):
            s = ciclo.get("senales", {}).get(emisora, {})
            p = next((x for x in est.posiciones if x.emisora == emisora), None)
            orden = next(
                (o for o in ciclo.get("ordenes", []) if o["emisora"] == emisora), None
            )
            filas.append(
                {
                    "Emisora": inversa.get(emisora, mercado.clave_de(emisora)),
                    "Lugar": s.get("lugar"),
                    f"Rend. {vigente.ventana} ses. %": s.get("momentum_pct"),
                    "Vs. media 200 %": s.get("distancia_media_pct"),
                    "Peso objetivo %": round(
                        ciclo["objetivo"].get(emisora, 0) * 100, 1
                    ),
                    "Peso hoy %": round(p.valor / total * 100, 1)
                    if p and p.valor and total
                    else 0.0,
                    "Orden del ciclo": f"{orden['lado']} {orden['cantidad']}"
                    if orden
                    else "—",
                }
            )
        st.dataframe(
            pd.DataFrame(filas),
            hide_index=True,
            alt="Cartera objetivo de la estrategia contra la cartera actual",
        )
        efectivo = 100 - sum(ciclo["objetivo"].values()) * 100
        if efectivo > 0.5:
            st.caption(
                f"{efectivo:.0f}% queda en efectivo: no hay suficientes emisoras "
                "en tendencia para llenar todos los lugares."
            )

# --- Validación ---
st.subheader("Validación con el historial del reto", anchor=False)
if isinstance(comparacion, str):
    st.warning(comparacion, icon=":material/warning:")
    st.stop()

if comparacion.elegida != config.ESTRATEGIA_PROTOCOLO:
    st.warning(
        f"Con los datos de esta base el criterio elige {comparacion.elegida}, no "
        f"{config.ESTRATEGIA_PROTOCOLO}. Revisa que el historial y el tipo de "
        "cambio estén completos.",
        icon=":material/warning:",
    )

st.markdown(
    f"""
Probé cinco reglas, fijadas antes de ver resultados (decisión D71), con los
cierres del reto en pesos, desde **{comparacion.inicio.date()}**:
- **Entrenamiento** hasta el {comparacion.fin_entrenamiento.date()}. Ahí se
  elige, por rendimiento anual entre caída máxima.
- **Prueba** después. Ahí solo se mira si lo elegido sigue funcionando.
"""
)

columnas = {
    "estrategia": "Estrategia",
    "rendimiento_pct": "Rendimiento %",
    "anual_pct": "Anual %",
    "volatilidad_pct": "Volatilidad %",
    "caida_maxima_pct": "Caída máxima %",
    "anual_entre_caida": "Anual / caída",
    "ordenes": "Órdenes",
}
pestanas = st.tabs(["Prueba", "Entrenamiento", "Periodo completo"])
for pestana, periodo in zip(
    pestanas, ("prueba", "entrenamiento", "completo"), strict=True
):
    with pestana:
        tabla = comparacion.tabla[comparacion.tabla["periodo"] == periodo]
        st.dataframe(
            tabla[list(columnas)].rename(columns=columnas),
            hide_index=True,
            column_config={"Órdenes": st.column_config.NumberColumn(format="%d")},
            alt=f"Métricas de las estrategias en {periodo}",
        )

mostrar = list(
    dict.fromkeys(
        [
            config.ESTRATEGIA_PROTOCOLO,
            *([vigente.nombre] if vigente else []),
            "igual_peso_universo",
            "regla_actual",
            "Agresivo",
            "Moderado",
        ]
    )
)
serie = comparacion.series[[c for c in mostrar if c in comparacion.series]]
st.line_chart(serie, x_label="Fecha", y_label="Valor (base 100)")
st.caption(
    f"La prueba empieza el {comparacion.fin_entrenamiento.date()} + 1 día. "
    "regla_actual es la regla de oportunidades que el vigía usaba antes; la "
    "retiré por estos resultados."
)

with st.expander("Lo que este backtest no dice", icon=":material/info:"):
    st.markdown(
        f"""
- **Sesgo de supervivencia**: el universo es la lista del reto de 2026; las
  emisoras que desaparecieron no están.
- **Sin dividendos**: son cierres sin ajustar.
- **Comisión supuesta** de {backtest.COSTO_PCT}% por lado: no encontré la del reto.
- **Riesgo alto**: las estrategias de momentum duplican o triplican la
  volatilidad del Agresivo, con caídas de 20% a 40%. El resultado de prueba
  depende de pocas emisoras que subieron mucho.
- **Un solo año de prueba**, en un solo régimen de mercado. Que haya
  funcionado no garantiza que funcione en las semanas que quedan del reto.
"""
    )
