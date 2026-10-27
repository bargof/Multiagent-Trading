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


def seccion_revision(revision: dict[str, list[dict]], confirmado: bool) -> str:
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

    def desacuerdos(grupo: list[dict]) -> int:
        return sum(p["dictamen"] == "en desacuerdo" for p in grupo)

    renglones = "\n".join(
        rf"{ej} & {tex(p['punto'])} & {tex(p['dictamen'] or 'sin marcar')} & "
        rf"{tex(p['origen'])} & {partible(p['notas'])} \\"
        for ej, lista in revision.items()
        for p in lista
        if p["marcado"] or p["notas"]
    )
    estado = (
        rf"Puntos revisados por una persona: {len(humanos)} de {len(puntos)}; "
        rf"desacuerdos con el juez: {desacuerdos(humanos)}."
    )
    if sin_confirmar:
        estado += (
            rf" Otros {len(sin_confirmar)} puntos son un borrador preparado con "
            r"asistencia de IA que una persona todavía no confirma: no cuentan como "
            r"revisión humana (desacuerdos con el juez en el borrador: "
            rf"{desacuerdos(sin_confirmar)})."
        )
    elif confirmado:
        estado += (
            r" Parte de ellos partió de un borrador preparado con asistencia de IA, "
            r"que la persona revisora corrigió y confirmó."
        )
    return (
        estado
        + r" Si la revisión discrepa del juez, se registran los dos juicios y la "
        r"puntuación automática no se sustituye."
        + "\n\n"
        + r"{\footnotesize\begin{longtable}{lL{4.2cm}lL{2.1cm}L{5.8cm}}"
        + "\n\\toprule\n"
        + r"ejec. & punto & dictamen & origen & notas \\"
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
    revision, confirmado = leer_revision(carpeta)
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

\begin{{itemize}}[nosep]
\item \textbf{{Obligatorias: {ob["aprobadas"]} de {ob["planeadas"]} aprobadas}} (fallidas
{ob["fallidas"]}, no completadas {ob["no_completadas"]}, errores del programa
{ob["errores"]}).
\item Complementaria R6, fuera del denominador: {comp["aprobadas"]} de {comp["planeadas"]}.
\item Control: R5 bloqueó en {r5["control"]["bloqueadas"]} de {r5["realizadas"]}, con
{r5["control"]["liberadas"]} liberaciones indebidas. Acciones prohibidas en las
{ob["realizadas"] + comp["realizadas"]} ejecuciones: {prohibidas}.
\item Congelación: {tex(meta["congelacion"]["estado"])}. Ejecuciones interrumpidas:
{len(resumen["interrumpidas"])}.
\item Uso: {uso["agentes"]["llamadas"]} llamadas a \texttt{{{tex(uso["agentes"]["modelo"])}}}
({uso["agentes"]["tokens"].get("input_tokens", 0):,} tokens de entrada y
{uso["agentes"]["tokens"].get("output_tokens", 0):,} de salida) y {uso["juez"]["llamadas"]}
al juez \texttt{{{tex(uso["juez"]["modelo"])}}}; {uso["segundos"] / 60:.1f} minutos de
ejecución.
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

Patrones que se repiten:
\begin{{itemize}}[nosep]
{patrones}
\end{{itemize}}

Todos los números de este documento salen de
\texttt{{reports/campanas/{tex(meta["campana"])}/resultados.json}}, que escribe el
ejecutable al correr. Las ejecuciones se cuentan todas: ninguna se escogió ni se
reemplazó.

\section{{El sistema}}

Cinco agentes de LangChain (\texttt{{create\_agent}}) dentro de un grafo de control
determinista de LangGraph. El supervisor A0 usa a A1, A2 y A3 como herramientas:
les manda una tarea con datos clave y recibe su salida estructurada. Si A0 propone
un movimiento, el grafo invoca siempre a A4 y después valida la propuesta con
reglas deterministas; ninguna aprobación anula un límite duro. Cada llamada a
herramienta pasa por la Mesa, que aplica los permisos de cada agente, el
presupuesto y la traza. No existe herramienta de ejecución.

\begin{{center}}\small
\begin{{tabular}}{{llL{{9.2cm}}l}}
\toprule
agente & papel & herramientas & salida \\
\midrule
{agentes}
\bottomrule
\end{{tabular}}
\end{{center}}

\textbf{{Configuración.}} Agentes: \texttt{{{tex(modelos["agentes"])}}}. Juez:
\texttt{{{tex(modelos["juez"])}}}, un modelo distinto. Sin temperatura y con
razonamiento \texttt{{{tex(modelos["razonamiento"])}}}; {modelos["llamadas_por_minuto"]}
llamadas por minuto por modelo. Límites por caso: {limites.herramientas_por_especialista}
herramientas por invocación, {limites.invocaciones_especialistas} invocaciones de
especialistas, {limites.llamadas_modelo} llamadas al modelo, {limites.timeout_caso_s}~s
de trabajo y un reintento de transporte. Versiones: {tex(", ".join(f"{k} {v}" for k, v in meta["versiones"].items()))};
Python {tex(meta["python"])}.

El diagrama de arquitectura (entregable 3) está en la página siguiente y en
\texttt{{reports/diagrama\_arquitectura.pdf}}.

\begin{{figure}}[p]
\centering
\includegraphics[angle=90,height=0.93\textheight]{{{DIAGRAMA.as_posix()}}}
\end{{figure}}
\clearpage

\section{{Cómo se evaluó}}

\begin{{itemize}}
\item \textbf{{Antes de correr.}} Las rutas, su trayectoria y su resultado esperados
están escritos en el ejecutable. Las 23 pruebas sintéticas del evaluador
(trazas con un defecto plantado) salieron como se esperaba, y la congelación
registró las huellas de datos, expectativas, juez, agentes, límites y
configuración, más el SHA-256 del archivo (\texttt{{{tex(meta["archivo_sha256"][:16])}}}…).
La campaña comprueba esas huellas al empezar.
\item \textbf{{Tres planos por ejecución.}} Trayectoria (actor, herramienta y
argumentos normalizados, con el criterio de cada ruta y sus dependencias),
resultado (exacto, con tolerancia o con juez) y controles (acciones prohibidas).
Una ejecución aprueba solo si pasan los tres.
\item \textbf{{Métricas.}} Cobertura = herramientas correctas / esperadas (la
«precisión» de la rúbrica); precisión = correctas / realizadas; eventos =
invocaciones y herramientas, reales / esperados; pasos extra; cifras del texto
sin respaldo en la traza; acciones prohibidas.
\item \textbf{{Repeticiones.}} Tres por ruta, por rondas (R1–R5, tres veces) y R6 al
final, cada una con estado limpio y modelos sin caché. Se reporta la tasa de
aprobación y la peor ejecución de cada ruta.
\item \textbf{{Fallas del proveedor.}} Si el modelo no responde ni al único reintento
(cuota, saturación, timeout), la ejecución se conserva, no cuenta y se repite; en
esta campaña no hubo ninguna.
\end{{itemize}}

\section{{Las rutas obligatorias}}
{"".join(seccion_ruta(r, claves[r["ruta"]], analisis["fallas"]) for r in rutas_ob)}

\section{{Ruta complementaria}}
R6 se reporta aparte, fuera del denominador de las 15 obligatorias.
{"".join(seccion_ruta(r, claves[r["ruta"]], analisis["fallas"]) for r in rutas_comp)}

\section{{El juez}}

J1 y J2 son llamadas separadas a \texttt{{{tex(modelos["juez"])}}}, sin herramientas,
con el prompt y los criterios escritos en el ejecutable. Reciben la solicitud, las
observaciones de las herramientas y la respuesta; devuelven tres criterios binarios
con una justificación, y la ruta aprueba solo con los tres. Un JSON inválido o un
juez que no responde deja el juicio sin completar, que no cuenta como aprobado.

\textbf{{Límites.}} El juez comparte proveedor con los agentes y es un modelo Lite:
puede favorecer ciertas redacciones o equivocarse. Por eso no sustituye las
comprobaciones objetivas, y la revisión humana de R1 y R2 se reporta aparte. En esta
campaña aprobó los 18 criterios de R1 y R2.

\section{{Revisión humana}}

{seccion_revision(revision, confirmado)}

\section{{Otras campañas}}

Ninguna campaña se borra. La campaña anterior corrió con modelos que la cuota
gratuita no permitía terminar: \texttt{{gemini-3.6-flash}} tiene un límite de 20
llamadas al día en este proyecto, y la campaña necesitaba unas 150. Se detuvo por
cuota, se conserva, y los agentes y el juez pasaron a los modelos Flash Lite (500 al
día) antes de congelar de nuevo.

{seccion_anteriores(carpeta)}

\section{{Limitaciones}}

\begin{{itemize}}
\item Tres repeticiones por ruta muestran variación, pero no son una estimación de
confiabilidad en producción.
\item Agentes y juez son modelos Lite de un mismo proveedor, elegidos por la cuota
gratuita. Un modelo mayor probablemente fallaría menos.
\item El detector de cifras sin respaldo partió las fechas ISO con hora y zona
horaria: un falso positivo del evaluador que reprobó R4.1 y R4.2. Se reporta y no se
corrigió en esta campaña; corregirlo exige una campaña nueva.
\item La regla de cifras con respaldo es estricta: reprueba una cifra correcta que el
modelo calculó por su cuenta, como el 800 de R5.3.
\item No se envía temperatura: con estos modelos, la guía de Gemini 3 recomienda no
bajarla. Se espera variación entre repeticiones.
\item Los datos son ficticios. El sistema no estima rentabilidad, no se conecta con un
intermediario y no ejecuta operaciones.
\end{{itemize}}

\section{{Cómo reproducirlo}}

Con las dependencias del comentario inicial y una sola variable, \texttt{{GOOGLE\_API\_KEY}}:

\begin{{itemize}}[nosep]
\item \texttt{{python proyecto\_multiagente.py}} corre la campaña e imprime la tabla.
\item \texttt{{python proyecto\_multiagente.py --tabla}} vuelve a imprimirla sin llamar a
los modelos.
\item \texttt{{python proyecto\_multiagente.py --probar-evaluador}} corre las pruebas
sintéticas, sin red.
\end{{itemize}}

Los modelos no tienen temperatura 0, así que otra corrida puede dar otras
trayectorias: los números de este documento son los de la campaña
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
