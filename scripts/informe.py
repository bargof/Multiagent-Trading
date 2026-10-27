"""Documento de resultados (entregable 2), generado desde una campaña.

Corto y fácil de leer, pero con lo que pide la rúbrica para cada ruta: sus
cinco campos, trayectoria y resultado esperados contra obtenidos, métricas y,
para cada falla, en qué paso falló y por qué. Los números salen de
reports/campanas/<id>/resultados.json, que escribe el ejecutable; ninguno se
copia a mano. El detalle completo se queda en ese JSON. El análisis sale de
analisis.json y la revisión de revision.md. No llama a ningún modelo.

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

# Lo que prueba cada ruta, dicho en simple.
QUE_PRUEBA = {
    "R1": "Explicar una noticia",
    "R2": "Cruzar una noticia con el reporte financiero",
    "R3": "Calcular una compra hipotética",
    "R4": "Pedir un precio que no está disponible",
    "R5": "Una compra que rompe el límite",
    "R6": "Una compra válida, que espera a una persona",
}
# El criterio de trayectoria de cada ruta y su justificación (sección 4 del
# ejecutable), dichos en simple.
COMO_SE_COMPARA = {
    "R1": "Exacto: con una sola herramienta basta, así que cualquier paso de más "
    "reprueba.",
    "R2": "En cualquier orden: noticias y finanzas no dependen una de la otra.",
    "R3": "En orden: primero los datos, después el cálculo y al final la "
    "simulación. Se permiten pasos extra.",
    "R4": "En orden: pedir el precio, ver el error y responder. Se permite un "
    "reintento.",
    "R5": "En orden: datos, cálculo, riesgo y validación. Se permiten pasos extra.",
    "R6": "En orden, igual que R5.",
}
# Solo las cifras que importan de cada resultado; las demás están en el JSON.
DESTACADOS = {
    "R1": ["estado", "metricas.evento", "metricas.sentimiento"],
    "R2": [
        "estado",
        "metricas.crecimiento_ingresos_pct",
        "metricas.variacion_utilidad_operativa_pct",
        "metricas.cambio_margen_pp",
    ],
    "R3": [
        "estado",
        "metricas.costo",
        "metricas.peso_xyz_pct",
        "metricas.efectivo_despues",
        "metricas.perdida_antes",
        "metricas.perdida_despues",
    ],
    "R4": ["estado", "error", "metricas.precio"],
    "R5": ["estado", "metricas.motivo", "metricas.peso_xyz_pct", "metricas.limite_pct"],
    "R6": [
        "estado",
        "metricas.costo",
        "metricas.peso_xyz_pct",
        "metricas.efectivo_despues",
    ],
}
NOMBRES = {
    "estado": "estado",
    "error": "error",
    "metricas.evento": "evento",
    "metricas.sentimiento": "sentimiento",
    "metricas.crecimiento_ingresos_pct": "crecimiento de ingresos",
    "metricas.variacion_utilidad_operativa_pct": "variación de utilidad operativa",
    "metricas.cambio_margen_pp": "cambio de margen",
    "metricas.costo": "costo",
    "metricas.peso_xyz_pct": "peso de XYZ",
    "metricas.efectivo_despues": "efectivo después",
    "metricas.perdida_antes": "pérdida en E1 antes",
    "metricas.perdida_despues": "pérdida en E1 después",
    "metricas.precio": "precio",
    "metricas.motivo": "motivo",
    "metricas.limite_pct": "límite",
    "cifras_sin_respaldo": "cifras sin respaldo",
}
UNIDADES = {
    "metricas.crecimiento_ingresos_pct": " %",
    "metricas.variacion_utilidad_operativa_pct": " %",
    "metricas.cambio_margen_pp": " pp",
    "metricas.peso_xyz_pct": " %",
    "metricas.limite_pct": " %",
}


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
    bajos: los pasos y los nombres de campo no tienen espacios."""
    # No se parte dentro de un número: 25,000 o 0.01 quedan juntos.
    partes = re.split(r"(?<=[,(={:._/])(?!\d)", str(texto))
    return r"\allowbreak{}".join(tex(p) for p in partes)


def cifra(campo: str, v) -> str:
    if v is None:
        return "ninguno"
    if isinstance(v, bool):
        return "sí" if v else "no"
    # La clave guarda los montos como texto ("5000"): se leen como número.
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
        v = float(v)
    if isinstance(v, int | float):
        v = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"
    elif isinstance(v, list):
        v = ", ".join(map(str, v)) or "ninguna"
    return f"{v}{UNIDADES.get(campo, '')}"


# --- Pasos legibles ---

_PASO = re.compile(
    r"^(?:#\d+ )?(?P<actor>[^.(]+)\.(?P<nombre>\w+)\((?P<args>.*)\)"
    r"(?: → (?P<estado>\w+)(?P<bloqueado> BLOQUEADO)?)?$"
)
# Lo que no ayuda a leer el paso: la fecha de corte es la misma en todos.
_SIN_MOSTRAR = {"fecha_corte", "corte", "tarea", "version"}


def argumentos(texto: str) -> str:
    valores = []
    if m := re.search(r"propuesta=\{([^}]*)\}", texto):
        p = dict(re.findall(r'"(\w+)":"?([^",]*)"?', m.group(1)))
        valores.append(f"compra {p.get('cantidad')} {p.get('empresa')}")
        texto = texto.replace(m.group(0), "")
    for clave, v in re.findall(r'(\w+)=("[^"]*"|\[[^\]]*\]|[\w.]+)', texto):
        if clave not in _SIN_MOSTRAR:
            valores.append(v.strip('"[]').replace('"', ""))
    return ", ".join(v for v in valores if v)


def paso(texto: str) -> str:
    """«#3 A0→A1.consultar_noticias(empresa="XYZ", id="N1") → ok» se lee
    «A0→A1 consultar_noticias(XYZ, N1)»."""
    m = _PASO.match(texto)
    if not m:
        return texto
    legible = f"{m['actor']} {m['nombre']}({argumentos(m['args'])})"
    if m["estado"] == "error":
        legible += " → error"
    if m["bloqueado"]:
        legible += " → bloqueado"
    return legible


def camino(pasos: list[str]) -> str:
    return r" \,·\, ".join(
        r"\mbox{\texttt{" + partible(paso(p)) + "}}"
        if len(paso(p)) < 40
        else r"\texttt{" + partible(paso(p)) + "}"
        for p in pasos
    )


def lista(nombres: list[str]) -> str:
    if len(nombres) == 1:
        return nombres[0]
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


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
    revisor está de acuerdo o en desacuerdo; del resto, la marca y sus notas.
    Una nota que empieza con «(borrador IA)» no es revisión humana hasta que
    una persona la confirme.
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
            revision[actual].append(
                {
                    "punto": m.group(1),
                    "juez": True,
                    "marcado": bool(acuerdo or desacuerdo),
                    "dictamen": "de acuerdo"
                    if acuerdo
                    else ("en desacuerdo" if desacuerdo else None),
                    "notas": siguiente.split("Motivo:", 1)[-1].strip(),
                }
            )
        elif m := re.match(r"- \[([ xX])\] (.*?)(?:Notas:(.*))?$", linea):
            revision[actual].append(
                {
                    "punto": m.group(2).strip(),
                    "juez": False,
                    "marcado": m.group(1) in "xX",
                    "dictamen": "se cumple" if m.group(1) in "xX" else None,
                    "notas": (m.group(3) or "").strip(),
                }
            )
    for puntos in revision.values():
        for p in puntos:
            p["humano"] = BORRADOR not in p["notas"] or confirmado
            p["notas"] = p["notas"].replace(BORRADOR, "").strip()
    return revision, confirmado


# --- Secciones ---


def resultado_obtenido(ruta: dict) -> str:
    """Igual que lo esperado, o lo que no cumplió en cada ejecución."""
    iguales, distintas = [], []
    for f in ruta["ejecuciones"]:
        malas = [c for c in f["comprobaciones"] or [] if not c["cumple"]]
        if f["comprobaciones"] and not malas:
            iguales.append(f["ejecucion"])
            continue
        # Solo los campos con nombre legible; el resto se cuenta.
        visibles = [c for c in malas if c["campo"] in NOMBRES]
        detalle = "; ".join(
            f"{NOMBRES[c['campo']]} "
            + ("ausente" if c["ausente"] else cifra(c["campo"], c["observado"]))
            + f" (se esperaba {cifra(c['campo'], c['esperado'])})"
            for c in visibles
        )
        if otros := len(malas) - len(visibles):
            detalle += f", y {otros} cifras más ausentes"
        distintas.append(rf"\textbf{{{f['ejecucion']}}}: {tex(detalle)}")
    partes = []
    if iguales:
        partes.append(f"igual a lo esperado en {lista(iguales)}")
    partes += distintas
    return ". ".join(p[0].upper() + p[1:] for p in partes) + "."


def trayectoria_obtenida(ruta: dict) -> str:
    iguales, con_extras, distintas = [], [], []
    for f in ruta["ejecuciones"]:
        if f["trayectoria_paso"] and not f["pasos_extra"]:
            iguales.append(f["ejecucion"])
        elif f["trayectoria_paso"]:
            con_extras.append(f"{f['ejecucion']} (+{f['pasos_extra']})")
        else:
            distintas.append(
                rf"\textbf{{{f['ejecucion']}}}: {camino(f['trayectoria_obtenida'])}"
            )
    partes = []
    if iguales:
        partes.append(f"Igual a la esperada en {lista(iguales)}.")
    if con_extras:
        partes.append(f"Correcta, con pasos extra permitidos, en {lista(con_extras)}.")
    return " ".join(partes) + "".join(rf"\par {d}" for d in distintas)


def si_no(v: bool) -> str:
    return "sí" if v else r"\textbf{no}"


def tabla(ruta: dict) -> str:
    renglones = "\n".join(
        rf"{f['ejecucion']} & {si_no(f['veredicto'] == 'aprobada')}"
        rf" & {si_no(f['trayectoria_paso'])}"
        rf" & {si_no(f['resultado_paso'])}"
        rf" & {f['cobertura'] * 100:.0f} \%"
        rf" & {f['eventos'][0]} de {f['eventos'][1]} \\"
        for f in ruta["ejecuciones"]
    )
    return (
        r"""\begin{tabular}{lccccc}
\toprule
& aprobó & camino bien & respuesta bien & herramientas correctas & pasos \\
\midrule
"""
        + renglones
        + "\n\\bottomrule\n\\end{tabular}"
    )


def seccion_ruta(ruta: dict, clave: pm.Ruta, analisis: dict) -> str:
    primera = ruta["ejecuciones"][0]
    por_campo = {c["campo"]: c for c in primera["comprobaciones"]}
    esperado = ", ".join(
        f"sin {NOMBRES[k]}"
        if por_campo[k]["esperado"] is None
        else f"{NOMBRES[k]} {cifra(k, por_campo[k]['esperado'])}"
        for k in DESTACADOS[ruta["ruta"]]
        if k in por_campo
    )
    tolerancia = any(c["tolerancia"] for c in primera["comprobaciones"])
    if clave.juez:
        como = f"exacto, y el texto con el juez {clave.juez} (3 criterios)"
    elif tolerancia:
        como = "estado exacto y cifras con tolerancia de ±0.01"
    else:
        como = "exacto"

    fallas = [f for f in ruta["ejecuciones"] if f["veredicto"] != "aprobada"]
    por_que = ""
    if fallas:
        renglones = []
        for f in fallas:
            d = f["primer_paso_divergente"]
            plano = {"trayectoria": "el camino", "resultado": "la respuesta"}.get(
                d["plano"], "un control"
            )
            donde = f" en el paso \\#{d['seq']}" if d["seq"] else ""
            nota = analisis.get(f["ejecucion"], {})
            renglones.append(
                rf"\item \textbf{{{f['ejecucion']}}}: falló {plano}{donde}. "
                + tex(nota.get("breve") or nota.get("causa") or "")
            )
        por_que = (
            "\n\\textbf{Por qué falló}\n\\begin{itemize}[nosep,leftmargin=*]\n"
            + "\n".join(renglones)
            + "\n\\end{itemize}\n"
        )
    control = ""
    if "control" in ruta:
        c = ruta["control"]
        control = (
            rf" Bloqueó la compra en {c['bloqueadas']} de {ruta['realizadas']}"
            + (
                " y no liberó ninguna."
                if c["liberadas"] == 0
                else f" y liberó {c['liberadas']}."
            )
        )
    return rf"""
\subsection*{{{ruta["ruta"]} · {tex(QUE_PRUEBA[ruta["ruta"]])} \hfill
\normalsize {ruta["aprobadas"]} de {ruta["realizadas"]} aprobadas}}

\begin{{description}}[leftmargin=3.3cm,style=sameline,font=\normalfont\bfseries,nosep,itemsep=3pt]
\item[Pide] «{tex(ruta["entrada"])}»
\item[Camino esperado] {camino(ruta["trayectoria_esperada"])}
\item[Cómo se compara] {tex(COMO_SE_COMPARA[ruta["ruta"]])}
\item[Camino obtenido] {trayectoria_obtenida(ruta)}
\item[Respuesta esperada] {partible(esperado)}. Se compara {como}.
\item[Respuesta obtenida] {resultado_obtenido(ruta)}{control}
\end{{description}}

\smallskip
{{\small {tabla(ruta)}}}
{por_que}"""


def seccion_juez(resumen: dict, revision: dict[str, list[dict]], modelo: str) -> str:
    criterios = [
        c
        for r in resumen["rutas"]
        for f in r["ejecuciones"]
        if f["juez"] and f["juez"]["criterios"]
        for c in f["juez"]["criterios"]
    ]
    aprobados = sum(c["cumple"] for c in criterios)
    texto = (
        rf"En R1 y R2 la respuesta es texto libre, así que la califica un juez: otro "
        rf"modelo (\texttt{{{tex(modelo)}}}) que revisa tres criterios escritos antes "
        r"de correr, por ejemplo «describe que XYZ redujo su guía de 8\,\% a 3\,\%». La "
        rf"respuesta aprueba solo si cumple los tres. El juez dio por cumplidos "
        rf"{aprobados} de {len(criterios)}."
    )
    del_juez = [p for puntos in revision.values() for p in puntos if p["juez"]]
    revisados = [p for p in del_juez if p["marcado"] and p["humano"]]
    if revisados:
        acuerdos = sum(p["dictamen"] == "de acuerdo" for p in revisados)
        desacuerdos = [
            ej
            for ej, puntos in revision.items()
            for p in puntos
            if p["juez"] and p["humano"] and p["dictamen"] == "en desacuerdo"
        ]
        texto += (
            rf" Yo revisé esos mismos criterios y coincidí en {acuerdos} de "
            rf"{len(revisados)}"
            + (
                f"; en {lista(desacuerdos)} el juez fue más generoso que yo."
                if desacuerdos
                else "."
            )
        )
    return (
        texto
        + r" Su límite: es un modelo chico del mismo proveedor que los agentes y puede "
        r"premiar cierta redacción. Por eso solo lo uso para texto, nunca para "
        r"números, y cuando discrepo quedan los dos juicios sin cambiar la "
        r"puntuación automática."
    )


def nota_campanas(carpeta: Path) -> str:
    otras = [c for c in pm.campanas(pm.DIR_CAMPANAS) if c.carpeta != carpeta]
    if not otras:
        return ""
    return (
        "Antes de esta campaña hubo otra con \\texttt{gemini-3.6-flash}, que se cortó "
        "por cuota (ese modelo permite 20 llamadas al día). No la borré: está en "
        "\\texttt{reports/campanas/" + tex(otras[-1].id) + "}."
    )


def documento(carpeta: Path) -> str:
    meta = pm.Campana(carpeta).meta
    resumen = json.loads((carpeta / "resultados.json").read_text(encoding="utf-8"))
    archivo_analisis = carpeta / "analisis.json"
    analisis = (
        json.loads(archivo_analisis.read_text(encoding="utf-8"))
        if archivo_analisis.is_file()
        else {}
    )
    revision, _ = leer_revision(carpeta)
    claves = {r.ruta_id: r for r in pm.RUTAS}
    if meta["huellas"]["expectativas"] != pm.huella(pm.RUTAS):
        raise SystemExit("La clave del archivo no es la de la campaña: no se genera.")

    ob = resumen["obligatorias"]
    rutas = resumen["rutas"]
    r5 = next(r for r in rutas if "control" in r)
    prohibidas = sum(
        len(f["acciones_prohibidas"] or []) for r in rutas for f in r["ejecuciones"]
    )
    total = sum(r["realizadas"] for r in rutas)
    tabla_rutas = "\n".join(
        rf"{r['ruta']} & {tex(QUE_PRUEBA[r['ruta']])} & {r['aprobadas']} de "
        rf"{r['realizadas']} & "
        + str(sum(bool(f["trayectoria_paso"]) for f in r["ejecuciones"]))
        + r" de 3 & "
        + str(sum(bool(f["resultado_paso"]) for f in r["ejecuciones"]))
        + r" de 3 \\"
        + (r" \midrule" if r["ruta"] == "R5" else "")
        for r in rutas
    )
    puntos = lambda clave: "\n".join(  # noqa: E731
        rf"\item {tex(t)}" for t in analisis.get(clave, [])
    )
    uso = resumen["uso"]
    modelos = meta["modelos"]

    return rf"""\documentclass[11pt]{{article}}
\usepackage{{fontspec}}
\usepackage[a4paper,margin=2.2cm]{{geometry}}
\usepackage[spanish,es-noshorthands]{{babel}}
\usepackage{{booktabs,array,enumitem,graphicx}}
\usepackage[hidelinks]{{hyperref}}
\renewcommand{{\familydefault}}{{\sfdefault}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{6pt}}
\begin{{document}}
\raggedright

{{\LARGE\bfseries Comité de inversión multiagente\par}}
\smallskip
{{\large Resultados de la evaluación\par}}
\smallskip
{{\small Proyecto final · Módulo 4 · Diplomado en AI \& LLMs para Mercados
Financieros · ITAM\par}}

\bigskip
Hice un sistema de cinco agentes que analiza una compra sobre un portafolio ficticio
y la pasa por una revisión de riesgo. Para evaluarlo definí, antes de programarlo,
cinco casos de prueba, y corrí cada uno tres veces.

\section*{{Lo más importante}}

\begin{{center}}
\begin{{tabular}}{{ccc}}
{{\Huge\bfseries {ob["aprobadas"]} de {ob["planeadas"]}}} &
{{\Huge\bfseries {r5["control"]["bloqueadas"]} de {r5["realizadas"]}}} &
{{\Huge\bfseries {prohibidas}}} \\[4pt]
rutas aprobadas & veces que se bloqueó & acciones prohibidas \\
& la compra que rompía el límite & en {total} ejecuciones \\
\end{{tabular}}
\end{{center}}

\medskip
\begin{{center}}
\begin{{tabular}}{{llccc}}
\toprule
& qué prueba & aprobó & camino bien & respuesta bien \\
\midrule
{tabla_rutas}
\bottomrule
\end{{tabular}}
\end{{center}}
{{\small R6 es un caso extra y no cuenta en el 9 de 15.\par}}

\begin{{itemize}}[nosep,leftmargin=*]
{puntos("aprendizajes")}
\end{{itemize}}

\section*{{El sistema}}

Es un \textbf{{supervisor con agentes como herramientas, dentro de un grafo de
control}}. El supervisor (A0) decide a quién consultar: A1 lee noticias, A2 analiza
el reporte financiero y A3 calcula sobre el portafolio. Si A0 propone una compra, el
grafo la manda siempre a A4, el de riesgo, y luego la valida en código: ninguna
aprobación puede saltarse un límite. Si la compra cumple, no se ejecuta, queda para
que una persona decida.

Lo elegí sobre un enjambre, donde los agentes se pasan el control entre ellos,
porque así el camino es predecible. Los modelos deciden e interpretan, pero el
código calcula y controla. El diagrama está en la página \pageref{{fig:diagrama}}.

\begin{{figure}}[p]
\centering
\includegraphics[angle=90,height=0.9\textheight]{{{DIAGRAMA.as_posix()}}}
\caption{{Arquitectura del sistema.}}
\label{{fig:diagrama}}
\end{{figure}}

\section*{{Cómo lo evalué}}

\begin{{itemize}}[leftmargin=*]
\item \textbf{{Antes de programar}} escribí los cinco casos, uno por cada tipo que
pide la rúbrica, y R6 como extra. Cada uno tiene la pregunta, el camino esperado
(qué agentes y herramientas, con qué datos), la respuesta esperada y cómo se
comparan. Los valores los calculé a mano; los agentes nunca los ven.
\item \textbf{{Antes de correr}} probé el evaluador con 23 casos con errores
plantados y congelé el código, para no poder cambiar nada después.
\item \textbf{{Una ruta aprueba}} si el camino está bien, la respuesta está bien y
no hubo acciones prohibidas. Cuento las tres corridas de cada ruta.
\item \textbf{{Métricas}}: \emph{{herramientas correctas}} es el porcentaje de las
herramientas esperadas que usó con los datos correctos (lo que la rúbrica llama
precisión), y \emph{{pasos}} es cuántos dio contra los que esperaba.
\end{{itemize}}

\section*{{Ruta por ruta}}
{"".join(seccion_ruta(r, claves[r["ruta"]], analisis.get("fallas", {})) for r in rutas)}

\section*{{El juez}}

{seccion_juez(resumen, revision, modelos["juez"])}

\section*{{Qué sigue}}

\begin{{itemize}}[nosep,leftmargin=*]
{puntos("siguiente")}
\end{{itemize}}

\section*{{Notas}}

{{\small Agentes: \texttt{{{tex(modelos["agentes"])}}}; juez:
\texttt{{{tex(modelos["juez"])}}}. La campaña \texttt{{{tex(meta["campana"])}}}
coincide con la congelación y costó {uso["agentes"]["llamadas"] + uso["juez"]["llamadas"]}
llamadas a los modelos. {nota_campanas(carpeta)} Todos los números salen de
\texttt{{resultados.json}}, que escribe el ejecutable, y ahí está el detalle completo
de cada ejecución. Para reproducirlo: \texttt{{python proyecto\_multiagente.py}}, con
la variable \texttt{{GOOGLE\_API\_KEY}}. Como los modelos no tienen temperatura 0,
otra corrida puede dar otros caminos.\par}}

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
