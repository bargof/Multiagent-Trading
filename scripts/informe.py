"""Documento de resultados (entregable 2), generado desde una campaña.

Todos los números salen de reports/campanas/<id>/resultados.json y
campana.json, que escribe el ejecutable; ninguno se copia a mano. Los cinco
campos de cada ruta salen de la clave del ejecutable. El análisis de fallas
sale de analisis.json, y la revisión humana de revision.md: si está sin
llenar, el documento lo dice. Volver a generarlo no llama a ningún modelo.

    .venv\\Scripts\\python scripts\\informe.py                 # campaña más reciente completa
    .venv\\Scripts\\python scripts\\informe.py reports\\campanas\\<id>
"""

import json
import re
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from diagrama import compilar  # noqa: E402

import proyecto_multiagente as pm  # noqa: E402

DESTINO = RAIZ / "reports" / "informe_resultados.pdf"
DIAGRAMA = RAIZ / "reports" / "diagrama_arquitectura.pdf"


# --- Texto para LaTeX ---

_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex(texto) -> str:
    return "".join(_ESCAPES.get(c, c) for c in str(texto))


def partible(texto) -> str:
    """Texto que puede partirse después de comas, paréntesis, puntos y guiones
    bajos: las trayectorias y los nombres de campo no tienen espacios."""
    # No se parte dentro de un número: 25,000 o 0.01 quedan juntos.
    partes = re.split(r"(?<=[,(={:._/])(?!\d)", str(texto))
    return r"\allowbreak{}".join(tex(p) for p in partes)


def codigo(texto) -> str:
    return r"\texttt{" + partible(texto) + "}"


def limpio(detalle: str) -> str:
    """<EstadoFinal.BLOQUEADA: 'bloqueada'> se lee mejor como bloqueada."""
    return re.sub(r"<\w+\.\w+: '([^']*)'>", r"\1", detalle)


def valor(v, largo: int = 48) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list | dict):
        v = json.dumps(v, ensure_ascii=False)
    v = str(v)
    return v if len(v) <= largo else v[: largo - 1] + "…"


def si_no(v) -> str:
    return "—" if v is None else ("sí" if v else r"\textbf{no}")


def decimal(v) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def de(par) -> str:
    return "—" if par is None else f"{par[0]}/{par[1]}"


def cuantos(lista) -> str:
    return "—" if lista is None else str(len(lista))


# --- Datos ---


def campana_completa_mas_reciente() -> Path:
    for campana in pm.campanas(pm.DIR_CAMPANAS):
        if not campana.pendientes():
            return campana.carpeta
    raise SystemExit("No hay ninguna campaña completa en reports/campanas.")


BORRADOR = "(borrador IA)"


def leer_revision(carpeta: Path) -> tuple[dict[str, list[dict]], bool]:
    """Lo que marcó el revisor en revision.md, por ejecución, y si confirmó el
    borrador del asistente.

    Un renglón cuenta como revisado si tiene [x]. Del juez se lee si el
    revisor está de acuerdo o en desacuerdo y su motivo; del resto, la marca
    y sus notas. Una nota que empieza con «(borrador IA)» la escribió el
    asistente: no es revisión humana hasta que una persona la confirme.
    """
    archivo = carpeta / "revision.md"
    if not archivo.is_file():
        return {}, False
    revision: dict[str, list[dict]] = {}
    actual = None
    texto = archivo.read_text(encoding="utf-8")
    confirmado = bool(re.search(r"- \[[xX]\] Revisé el borrador", texto))
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if m := re.match(r"### (R\d\.\d) ", linea):
            actual = m.group(1)
            revision[actual] = []
            continue
        if actual is None:
            continue
        if m := re.match(r"- (C\d), según el juez (cumple|no cumple):", linea):
            siguiente = lineas[i + 1] if i + 1 < len(lineas) else ""
            acuerdo = re.search(r"\[[xX]\] de acuerdo", siguiente)
            desacuerdo = re.search(r"\[[xX]\] en desacuerdo", siguiente)
            motivo = siguiente.split("Motivo:", 1)[-1].strip()
            revision[actual].append(
                {
                    "punto": f"{m.group(1)} (juez: {m.group(2)})",
                    "marcado": bool(acuerdo or desacuerdo),
                    "dictamen": "de acuerdo"
                    if acuerdo
                    else ("en desacuerdo" if desacuerdo else None),
                    "notas": motivo,
                }
            )
        elif m := re.match(r"- \[([ xX])\] (.*?)(?:Notas:(.*))?$", linea):
            revision[actual].append(
                {
                    "punto": m.group(2).strip(),
                    "marcado": m.group(1) in "xX",
                    "dictamen": "se cumple" if m.group(1) in "xX" else None,
                    "notas": (m.group(3) or "").strip(),
                }
            )
        elif m := re.match(r"- (Causa probable|Efecto):(.*)$", linea):
            if m.group(2).strip():
                revision[actual].append(
                    {
                        "punto": m.group(1),
                        "marcado": True,
                        "dictamen": "anotado",
                        "notas": m.group(2).strip(),
                    }
                )
    for lista in revision.values():
        for p in lista:
            if BORRADOR in p["notas"]:
                p["origen"] = "borrador IA, confirmado" if confirmado else "borrador IA"
                p["notas"] = p["notas"].replace(BORRADOR, "").strip()
            else:
                p["origen"] = "persona"
    return revision, confirmado


# --- Secciones ---


def tabla_ejecuciones(filas: list[dict]) -> str:
    renglones = [
        rf"{f['ejecucion']} & {tex(f['veredicto'])} & {si_no(f['trayectoria_paso'])}"
        rf" & {si_no(f['resultado_paso'])} & {decimal(f['cobertura'])}"
        rf" & {decimal(f['precision'])} & {de(f['eventos'])} & {de(f['herramientas'])}"
        rf" & {valor(f['pasos_extra'])} & {cuantos(f['cifras_sin_respaldo'])}"
        rf" & {cuantos(f['acciones_prohibidas'])} & {f['llamadas_modelo']} \\"
        for f in filas
    ]
    return (
        r"""{\small\begin{tabular}{llcccccccccc}
\toprule
ejec. & veredicto & tray. & res. & cobert. & precis. & eventos & herram. & extra & sin resp. & prohib. & llamadas \\
\midrule
"""
        + "\n".join(renglones)
        + "\n\\bottomrule\n\\end{tabular}}\n"
    )


def comprobaciones(filas: list[dict]) -> str:
    """Resultado esperado frente a obtenido, campo por campo."""
    primera = next(f for f in filas if f["comprobaciones"])
    columnas = len(filas)
    ancho = f"{8.6 / columnas:.2f}cm"
    encabezado = " & ".join(f["ejecucion"] for f in filas)
    renglones = []
    for i, c in enumerate(primera["comprobaciones"]):
        esperado = valor(c["esperado"], 40)
        if c["tolerancia"]:
            esperado += f" ± {c['tolerancia']}"
        celdas = []
        for f in filas:
            if not f["comprobaciones"]:
                celdas.append("—")
                continue
            obs = f["comprobaciones"][i]
            texto = "ausente" if obs["ausente"] else valor(obs["observado"], 40)
            celdas.append(
                partible(texto)
                if obs["cumple"]
                else r"\textbf{" + partible(texto) + "}"
            )
        renglones.append(
            rf"{codigo(c['campo'])} & {partible(esperado)} & " + " & ".join(celdas)
        )
    return (
        rf"""{{\footnotesize\begin{{longtable}}{{L{{3.2cm}}L{{3.0cm}}*{{{columnas}}}{{L{{{ancho}}}}}}}
\toprule
campo & esperado & {encabezado} \\
\midrule
\endhead
"""
        + " \\\\\n".join(renglones)
        + " \\\\\n\\bottomrule\n\\end{longtable}}\n"
        + r"{\footnotesize En negrita, lo que no cumple.}"
        + "\n"
    )


def trayectorias(ruta: dict) -> str:
    esperada = "\n".join(rf"\item {codigo(e)}" for e in ruta["trayectoria_esperada"])
    partes = [
        r"\textbf{Trayectoria esperada} ("
        + tex(ruta["criterio_trayectoria"])
        + "):\n\\begin{enumerate}[nosep,leftmargin=*]\n"
        + esperada
        + "\n\\end{enumerate}"
    ]
    for f in ruta["ejecuciones"]:
        pasos = "\n".join(rf"\item {codigo(p)}" for p in f["trayectoria_obtenida"])
        partes.append(
            rf"\textbf{{Obtenida en {f['ejecucion']}}} ({tex(f['veredicto'])}):"
            + "\n\\begin{itemize}[nosep,leftmargin=*,label={}]\n"
            + (pasos or r"\item —")
            + "\n\\end{itemize}"
        )
    return "{\\footnotesize\\raggedright\n" + "\n\n".join(partes) + "\n\n}\n"


def seccion_ruta(ruta: dict, clave: pm.Ruta, analisis: dict) -> str:
    juez = ""
    if clave.juez:
        criterios = pm.CRITERIOS_JUEZ[clave.juez]
        juez = (
            rf"\item[Juez {clave.juez}] Aprueba con los tres criterios:"
            + "\n\\begin{itemize}[nosep]\n"
            + "\n".join(rf"\item {k}: {tex(v)}" for k, v in criterios.items())
            + "\n\\end{itemize}\n"
        )
    control = ""
    if "control" in ruta:
        c = ruta["control"]
        control = (
            rf"\textbf{{Control:}} bloqueó en {c['bloqueadas']} de "
            rf"{ruta['realizadas']}; liberaciones indebidas: {c['liberadas']}." + "\n\n"
        )
    fallas = [f for f in ruta["ejecuciones"] if f["veredicto"] != "aprobada"]
    analisis_ruta = ""
    if fallas:
        items = []
        for f in fallas:
            d = f["primer_paso_divergente"]
            donde = (
                tex(d["plano"]) + (f" \\#{d['seq']}" if d["seq"] else "")
                if d
                else "sin divergencia"
            )
            nota = analisis.get(f["ejecucion"], {})
            items.append(
                rf"\item[{f['ejecucion']}] \textbf{{Primer paso divergente}} "
                rf"({donde}): {partible(limpio(d['detalle']) if d else f['motivo'] or '')}"
                + "\\\\\n"
                + rf"\textbf{{Causa probable:}} {tex(nota.get('causa', 'pendiente de análisis.'))}"
                + "\\\\\n"
                + rf"\textbf{{Efecto:}} {tex(nota.get('efecto', 'pendiente de análisis.'))}"
            )
        analisis_ruta = (
            "\\paragraph{Análisis de fallas}\n{\\raggedright\n"
            "\\begin{description}[style=nextline,leftmargin=1.2cm]\n"
            + "\n".join(items)
            + "\n\\end{description}\n\n}\n"
        )
    peor = ruta["peor"] or "—"
    return rf"""
\subsection{{{ruta["ruta"]} · {tex(ruta["tipo_caso"])}}}

\begin{{description}}[leftmargin=3.4cm,style=sameline,font=\normalfont\bfseries]
\item[Entrada] «{tex(ruta["entrada"])}»
\item[Resultado esperado] estado \texttt{{{tex(ruta["estado_esperado"])}}}, con las
comprobaciones de la tabla de abajo y sus tolerancias.
{juez}\item[Criterio de trayectoria] \texttt{{{tex(ruta["criterio_trayectoria"])}}}.
{tex(clave.justificacion_trayectoria)}
\item[Criterio de resultado] {tex(ruta["criterio_resultado"])}
\end{{description}}

\textbf{{Aprobadas: {ruta["aprobadas"]} de {ruta["realizadas"]}.}} Peor ejecución:
{peor}.

{control}{tabla_ejecuciones(ruta["ejecuciones"])}

\medskip
\textbf{{Resultado esperado y obtenido}}

{comprobaciones(ruta["ejecuciones"])}

{trayectorias(ruta)}
{analisis_ruta}"""


def seccion_revision(revision: dict[str, list[dict]]) -> str:
    puntos = [p for lista in revision.values() for p in lista]
    marcados = [p for p in puntos if p["marcado"]]
    humanos = [p for p in marcados if p["origen"] != "borrador IA"]
    sin_confirmar = [p for p in marcados if p["origen"] == "borrador IA"]
    if not marcados:
        return (
            r"La revisión humana de la sección 6.3 todavía no está registrada. Se "
            r"hace en \texttt{revision.md}, en la carpeta de la campaña, y este "
            r"documento se vuelve a generar sin llamar a ningún modelo. Hasta "
            r"entonces, todos los juicios de este documento son los del evaluador "
            r"automático y los del juez." + "\n"
        )

    del_juez = [p for p in humanos if "juez" in p["punto"]]
    acuerdos = sum(p["dictamen"] == "de acuerdo" for p in del_juez)
    estado = (
        rf"Revisé {len(humanos)} de {len(puntos)} puntos. En R1 y R2 coincidí con el "
        rf"juez en {acuerdos} de {len(del_juez)} criterios. Cuando discrepo, quedan "
        r"los dos juicios y la puntuación automática no cambia."
    )
    if sin_confirmar:
        estado += (
            rf" Otros {len(sin_confirmar)} puntos son un borrador sin confirmar y no "
            r"cuentan como revisión humana."
        )
    # Los acuerdos sin nota ya están en el conteo de arriba.
    renglones = "\n".join(
        rf"{ej} & {tex(p['punto'])} & {tex(p['dictamen'] or 'sin marcar')} & "
        rf"{partible(p['notas'])} \\"
        for ej, lista in revision.items()
        for p in lista
        if p["notas"] or p["dictamen"] == "en desacuerdo"
    )
    return (
        estado
        + "\n\n"
        + r"{\footnotesize\begin{longtable}{lL{4.4cm}lL{8.0cm}}"
        + "\n\\toprule\n"
        + r"ejec. & punto & dictamen & notas \\"
        + "\n\\midrule\n\\endhead\n"
        + renglones
        + "\n\\bottomrule\n\\end{longtable}}\n"
    )


def seccion_anteriores(carpeta: Path) -> str:
    """Las demás campañas de reports/campanas, con lo que alcanzaron a correr."""
    partes = []
    for otra in pm.campanas(pm.DIR_CAMPANAS):
        if otra.carpeta == carpeta:
            continue
        resumen = otra.resumen()
        filas = [f for r in resumen["rutas"] for f in r["ejecuciones"]]
        filas += resumen["interrumpidas"]
        detalle = "; ".join(
            f"{f['ejecucion']} {f['veredicto']}"
            for f in sorted(filas, key=lambda f: f["inicio"])
        )
        partes.append(
            rf"\item \texttt{{{otra.id}}} ({tex(resumen['estado'])}), agentes "
            rf"\texttt{{{tex(resumen['modelos']['agentes'])}}}, juez "
            rf"\texttt{{{tex(resumen['modelos']['juez'])}}}, congelación: "
            rf"{tex(resumen['congelacion']['estado'])}. Ejecuciones: {tex(detalle)}."
        )
    if not partes:
        return "No hubo otras campañas.\n"
    return "\\begin{itemize}\n" + "\n".join(partes) + "\n\\end{itemize}\n"


def documento(carpeta: Path) -> str:
    campana = pm.Campana(carpeta)
    meta = campana.meta
    resumen = json.loads((carpeta / "resultados.json").read_text(encoding="utf-8"))
    analisis_archivo = carpeta / "analisis.json"
    analisis = (
        json.loads(analisis_archivo.read_text(encoding="utf-8"))
        if analisis_archivo.is_file()
        else {"fallas": {}, "patrones": []}
    )
    revision, _ = leer_revision(carpeta)
    claves = {r.ruta_id: r for r in pm.RUTAS}
    if meta["huellas"]["expectativas"] != pm.huella(pm.RUTAS):
        raise SystemExit("La clave del archivo no es la de la campaña: no se genera.")

    ob, comp = resumen["obligatorias"], resumen["complementarias"]
    rutas_ob = [r for r in resumen["rutas"] if r["obligatoria"]]
    rutas_comp = [r for r in resumen["rutas"] if not r["obligatoria"]]
    uso = resumen["uso"]
    r5 = next(r for r in rutas_ob if "control" in r)
    prohibidas = sum(
        len(f["acciones_prohibidas"] or [])
        for r in resumen["rutas"]
        for f in r["ejecuciones"]
    )
    resumen_rutas = "\n".join(
        rf"{r['ruta']} & {tex(r['tipo_caso'])} & \texttt{{{tex(r['criterio_trayectoria'])}}}"
        rf" & {r['aprobadas']}/{r['realizadas']} & {r['peor']} \\"
        for r in resumen["rutas"]
    )
    agentes = "\n".join(
        rf"{a} & {tex(rol)} & "
        + ", ".join(rf"\texttt{{{tex(h)}}}" for h in pm.CATALOGO.get(a, ()))
        + (
            ", ".join(
                rf"\texttt{{{tex(d.nombre)}}} (→{d.destino})"
                for d in pm.DELEGACIONES.values()
            )
            if a == "A0"
            else ""
        )
        + rf" & \texttt{{{tex(pm.SALIDAS[a].__name__)}}} \\"
        for a, rol in (
            ("A0", "Supervisor"),
            ("A1", "Noticias"),
            ("A2", "Finanzas"),
            ("A3", "Portafolio"),
            ("A4", "Riesgo"),
        )
    )
    patrones = "\n".join(rf"\item {tex(p)}" for p in analisis.get("patrones", []))
    total = ob["realizadas"] + comp["realizadas"]
    # Las frases del resumen se arman con los datos, no se dan por hechas.
    frase_prohibidas = (
        f"y no hubo acciones prohibidas en ninguna de las {total}"
        if prohibidas == 0
        else f"y hubo {prohibidas} acciones prohibidas en las {total}"
    )
    interrumpidas = len(resumen["interrumpidas"])
    frase_campana = (
        "La campaña coincide con la congelación"
        if meta["congelacion"]["estado"] == "coincide"
        else "La campaña \\textbf{no} coincide con la congelación"
    ) + (
        " y no tuvo interrupciones."
        if interrumpidas == 0
        else f" y tuvo {interrumpidas} interrupciones, que se repitieron."
    )
    limites = pm.LIMITES
    modelos = meta["modelos"]

    return rf"""\documentclass[10pt]{{article}}
\usepackage{{fontspec}}
\usepackage[a4paper,margin=1.8cm]{{geometry}}
\usepackage[spanish,es-noshorthands]{{babel}}
\usepackage{{booktabs,longtable,array,xcolor,enumitem,graphicx}}
\usepackage[hidelinks]{{hyperref}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{5pt}}
\newcolumntype{{L}}[1]{{>{{\raggedright\arraybackslash}}p{{#1}}}}
\begin{{document}}

{{\raggedright\LARGE\bfseries Comité de inversión multiagente:\\ resultados de la evaluación\par}}

\medskip
Proyecto final, Módulo 4 · Diplomado en AI \& LLMs para Mercados Financieros ·
ITAM. Especificación v{tex(meta["especificacion"])}. Campaña
\texttt{{{tex(meta["campana"])}}}, iniciada el {tex(meta["creada"][:16].replace("T", " a las "))}.

\section{{Resumen}}

Definí cinco rutas de prueba antes de correr el sistema, una por cada tipo de
caso de la rúbrica, y corrí cada una tres veces.

\begin{{itemize}}[nosep]
\item \textbf{{Obligatorias: {ob["aprobadas"]} de {ob["planeadas"]} aprobadas}}
({ob["fallidas"]} fallidas, {ob["no_completadas"]} sin completar,
{ob["errores"]} errores del programa).
\item R6, que va aparte: {comp["aprobadas"]} de {comp["planeadas"]}.
\item R5 bloqueó la compra en {r5["control"]["bloqueadas"]} de {r5["realizadas"]}
ejecuciones, {frase_prohibidas}.
\item {frase_campana} Costó
{uso["agentes"]["llamadas"] + uso["juez"]["llamadas"]} llamadas a los modelos y
{uso["segundos"] / 60:.0f} minutos.
\end{{itemize}}

\begin{{center}}\small
\begin{{tabular}}{{llccl}}
\toprule
ruta & tipo de caso & trayectoria & aprobadas & peor ejecución \\
\midrule
{resumen_rutas}
\bottomrule
\end{{tabular}}
\end{{center}}

Lo que más se repite:
\begin{{itemize}}[nosep]
{patrones}
\end{{itemize}}

Los números salen de \texttt{{reports/campanas/{tex(meta["campana"])}/resultados.json}},
que escribe el ejecutable. Cuento todas las ejecuciones: no escogí ni reemplacé
ninguna.

\section{{El sistema}}

Es un sistema de tipo \textbf{{supervisor con agentes como herramientas, dentro de un
grafo de control determinista}}. Antes de programarlo comparé cuatro patrones:

\begin{{itemize}}[nosep]
\item \textbf{{Supervisor}}, la base: un agente central decide qué especialistas
consultar y solo activa los que hacen falta.
\item \textbf{{Grafo de control}}, alrededor del supervisor: impone los pasos que no
pueden quedar a criterio de un modelo, como la revisión de riesgo y la validación.
\item \textbf{{Paralelo}}: útil para consultas independientes, pero no lo usé en esta
versión. Todo corre de uno en uno, y la traza queda en orden.
\item \textbf{{Enjambre}}, descartado: que los agentes se pasen el control entre ellos
agrega variación y ciclos que un comité de inversión no necesita.
\end{{itemize}}

Por eso las flechas del diagrama son tareas y respuestas, no traspasos de control.
El supervisor, A0, no consulta datos ni calcula: llama a A1 (noticias), A2
(finanzas) y A3 (portafolio) como si fueran herramientas, les pasa una tarea y
recibe su respuesta estructurada. Cada especialista solo puede usar sus propias
herramientas y empieza sin memoria en cada invocación. Si A0 propone una
operación, el grafo siempre consulta a A4 (riesgo) y luego valida la propuesta en
código, donde ninguna aprobación puede anular un límite duro. Toda llamada a
herramienta pasa por la Mesa, que revisa permisos, descuenta presupuesto y deja
traza. No hay forma de ejecutar operaciones: una propuesta válida queda pendiente
de que una persona decida.

\begin{{center}}\small
\begin{{tabular}}{{llL{{9.2cm}}l}}
\toprule
agente & papel & herramientas & salida \\
\midrule
{agentes}
\bottomrule
\end{{tabular}}
\end{{center}}

\textbf{{Configuración.}} Agentes: \texttt{{{tex(modelos["agentes"])}}}; juez:
\texttt{{{tex(modelos["juez"])}}}, otro modelo. Sin temperatura y con razonamiento
\texttt{{{tex(modelos["razonamiento"])}}}. Por caso, como máximo
{limites.herramientas_por_especialista} herramientas por invocación,
{limites.invocaciones_especialistas} invocaciones, {limites.llamadas_modelo} llamadas
al modelo y {limites.timeout_caso_s}~s. Versiones: {tex(", ".join(f"{k} {v}" for k, v in meta["versiones"].items()))};
Python {tex(meta["python"])}.

El diagrama está en la página \pageref{{fig:diagrama}} y en
\texttt{{reports/diagrama\_arquitectura.pdf}}.

\begin{{figure}}[p]
\centering
\includegraphics[angle=90,height=0.9\textheight]{{{DIAGRAMA.as_posix()}}}
\caption{{Arquitectura: supervisor con agentes como herramientas dentro del grafo de
control.}}
\label{{fig:diagrama}}
\end{{figure}}

\section{{Cómo lo evalué}}

\begin{{itemize}}
\item \textbf{{La evaluación es a priori.}} La definí en el documento de plan antes de
programar el sistema: cinco rutas, una por tipo de caso de la rúbrica, cada una
con sus cinco campos (entrada, trayectoria esperada con argumentos, resultado
esperado con tolerancia, criterio de trayectoria y criterio de resultado). Los
esperados los calculé a mano con los datos ficticios, y los copié al código como
una clave separada que ningún agente ve.
\item \textbf{{Antes de correr}} probé el evaluador con 23 trazas con defectos
plantados y congelé el archivo (SHA-256
\texttt{{{tex(meta["archivo_sha256"][:16])}}}…); la campaña comprueba que no cambió.
\item \textbf{{Cada ejecución se mide en tres planos}}: la trayectoria (qué agentes y
herramientas, con qué argumentos y en qué orden), el resultado (exacto, con
tolerancia o con juez) y los controles. Aprueba solo si pasan los tres.
\item \textbf{{Métricas.}} Cobertura es herramientas correctas sobre esperadas (lo
que la rúbrica llama precisión); precisión es correctas sobre realizadas. Además,
eventos reales contra esperados, pasos extra, cifras sin respaldo y acciones
prohibidas.
\item \textbf{{Tres repeticiones por ruta}}, cada una desde cero. Reporto la tasa de
aprobación y la peor ejecución de cada ruta.
\end{{itemize}}

\section{{Las rutas obligatorias}}
{"".join(seccion_ruta(r, claves[r["ruta"]], analisis["fallas"]) for r in rutas_ob)}

\section{{Ruta complementaria}}
R6 va aparte y no entra en las 15 obligatorias.
{"".join(seccion_ruta(r, claves[r["ruta"]], analisis["fallas"]) for r in rutas_comp)}

\section{{El juez}}

J1 y J2 son llamadas aparte a \texttt{{{tex(modelos["juez"])}}}, sin herramientas y con
los criterios escritos en el código. La ruta aprueba solo si se cumplen los tres;
si el juez no responde o devuelve algo inválido, el juicio queda sin completar y no
cuenta como aprobado.

El juez comparte proveedor con los agentes y es un modelo chico, así que puede
equivocarse o premiar cierta redacción. Por eso no lo uso para números, y contrasté
sus juicios con mi revisión.

\section{{Revisión humana}}

{seccion_revision(revision)}

\section{{Otras campañas}}

No borré ninguna campaña. La primera, con \texttt{{gemini-3.6-flash}}, se cortó por
cuota: ese modelo permite 20 llamadas al día y la campaña necesitaba unas 150. La
conservo, y para la oficial cambié a los modelos Flash Lite, que permiten 500.

{seccion_anteriores(carpeta)}

\section{{Limitaciones}}

\begin{{itemize}}
\item Tres repeticiones muestran variación, pero no miden la confiabilidad en
producción.
\item Agentes y juez son modelos chicos de un mismo proveedor; uno mayor
probablemente fallaría menos.
\item El detector de cifras confundió la zona horaria de una fecha con una cifra y
reprobó R4.1 y R4.2. Lo reporto tal cual: corregirlo exige una campaña nueva.
\item La regla de cifras con respaldo es estricta: reprueba una cifra correcta que el
modelo calculó por su cuenta, como el 800 de R5.3.
\item No fijé la temperatura, porque la guía de Gemini 3 recomienda no bajarla; por
eso hay variación entre repeticiones.
\item Los datos son ficticios. El sistema no mide rentabilidad ni ejecuta
operaciones.
\end{{itemize}}

\section{{Cómo reproducirlo}}

Con las dependencias del comentario inicial y la variable \texttt{{GOOGLE\_API\_KEY}}:

\begin{{itemize}}[nosep]
\item \texttt{{python proyecto\_multiagente.py}} corre la campaña e imprime la tabla.
\item \texttt{{python proyecto\_multiagente.py --tabla}} la vuelve a imprimir sin
llamar a los modelos.
\item \texttt{{python proyecto\_multiagente.py --probar-evaluador}} corre las pruebas
del evaluador, sin red.
\end{{itemize}}

Como los modelos no tienen temperatura 0, otra corrida puede dar otras
trayectorias. Los números de este documento son los de la campaña
\texttt{{{tex(meta["campana"])}}}.

\end{{document}}
"""


def main() -> int:
    carpeta = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else campana_completa_mas_reciente()
    )
    if not DIAGRAMA.is_file():
        raise SystemExit("Falta el diagrama: corre antes scripts/diagrama.py.")
    pdf = compilar(
        documento(carpeta), RAIZ / "reports" / "build" / "informe", "informe"
    )
    shutil.copyfile(pdf, DESTINO)
    print(f"Informe en {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
