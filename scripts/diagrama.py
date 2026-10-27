"""Diagrama de arquitectura (entregable 3), generado desde el código.

Las herramientas de cada agente, las delegaciones del supervisor y los modelos
salen de proyecto_multiagente.py, así que el diagrama no puede mostrar algo
que no exista. Escribe reports/diagrama_arquitectura.pdf con xelatex.

    .venv\\Scripts\\python scripts\\diagrama.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import proyecto_multiagente as pm  # noqa: E402

DESTINO = RAIZ / "reports" / "diagrama_arquitectura.pdf"

# El papel de cada agente en pocas palabras; el detalle está en PROMPTS.
ROLES = {
    "A0": "Supervisor",
    "A1": "Noticias",
    "A2": "Finanzas",
    "A3": "Portafolio",
    "A4": "Riesgo",
}


def tex(texto: str) -> str:
    for viejo, nuevo in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("&", r"\&")):
        texto = texto.replace(viejo, nuevo)
    return texto


def herramientas(agente: str) -> str:
    return r"\\ ".join(rf"\texttt{{{tex(h)}}}" for h in pm.CATALOGO[agente])


def delegacion_a(destino: str) -> str:
    (nombre,) = [d.nombre for d in pm.DELEGACIONES.values() if d.destino == destino]
    return tex(nombre)


def documento() -> str:
    assert set(ROLES) == set(pm.SALIDAS), "ROLES no coincide con los agentes"
    assert set(pm.CATALOGO) == {"A1", "A2", "A3", "A4"}
    assert {d.destino for d in pm.DELEGACIONES.values()} == {"A1", "A2", "A3"}

    def agente(a: str) -> str:
        return (
            rf"\textbf{{{a} · {ROLES[a]}}}\\[1pt]"
            rf"{{\footnotesize salida: \texttt{{{pm.SALIDAS[a].__name__}}}}}\\[3pt]"
            rf"{{\footnotesize {herramientas(a)}}}"
        )

    return rf"""\documentclass[tikz,border=10pt]{{standalone}}
\usepackage{{fontspec}}
\usetikzlibrary{{positioning,arrows.meta,fit,backgrounds,calc}}
\definecolor{{azul}}{{HTML}}{{2F5D8A}}
\definecolor{{verde}}{{HTML}}{{3B7A57}}
\definecolor{{naranja}}{{HTML}}{{C26A1B}}
\definecolor{{gris}}{{HTML}}{{5B6270}}
\begin{{document}}
\sffamily
\begin{{tikzpicture}}[
  >={{Stealth[length=2.4mm]}},
  font=\small,
  paso/.style={{draw=gris, rounded corners=2pt, fill=gris!8, align=center,
    minimum height=11mm, text width=2.9cm, inner sep=3pt}},
  agente/.style={{draw=azul, thick, rounded corners=4pt, fill=azul!7,
    align=left, text width=3.6cm, inner sep=6pt}},
  control/.style={{draw=naranja, thick, rounded corners=2pt, fill=naranja!10,
    align=center, minimum height=11mm, text width=2.9cm, inner sep=3pt}},
  caja/.style={{draw=gris, rounded corners=3pt, fill=white, align=left,
    inner sep=6pt}},
  humano/.style={{draw=verde, very thick, rounded corners=4pt, fill=verde!10,
    align=left, inner sep=6pt}},
  flujo/.style={{->, thick, draw=gris!90!black}},
  delega/.style={{->, thick, draw=azul}},
  vuelve/.style={{->, dashed, draw=azul!70}},
  etiqueta/.style={{font=\footnotesize, fill=white, inner sep=1.5pt}},
]

% --- Grafo de control ---
\node[caja, text width=2.4cm] (usuario) at (0, 2.6)
  {{\textbf{{Usuario}}\\{{\footnotesize solicitud en texto}}}};
\node[paso] (iniciar) at (0, 0) {{\texttt{{iniciar}}\\{{\footnotesize fecha de corte T0}}}};
\node[agente, text width=2.9cm, align=center] (supervisor) at (3.6, 0)
  {{\textbf{{A0 · Supervisor}}\\{{\footnotesize agentes como herramientas}}\\
  {{\footnotesize salida: \texttt{{{pm.SALIDAS["A0"].__name__}}}}}}};
\node[paso] (clasificar) at (7.3, 0)
  {{\texttt{{clasificar\_salida}}\\{{\footnotesize ¿hay propuesta?}}}};
\node[control] (riesgo) at (10.9, 0)
  {{\texttt{{revisar\_riesgo}}\\{{\footnotesize siempre invoca a A4}}}};
\node[control] (verificar) at (14.6, 0)
  {{\texttt{{verificar\_control}}\\{{\footnotesize validación determinista}}}};
\node[paso] (finalizar) at (18.2, 0)
  {{\texttt{{finalizar}}\\{{\footnotesize compone la respuesta}}}};

\draw[flujo] (usuario) -- (iniciar);
\draw[flujo] (iniciar) -- (supervisor);
\draw[flujo] (supervisor) -- (clasificar);
\draw[flujo] (clasificar) -- node[etiqueta, above=2pt] {{sí}} (riesgo);
\draw[flujo] (riesgo) -- (verificar);
\draw[flujo] (verificar) -- (finalizar);
\draw[flujo] (clasificar.north) -- ++(0, 1.1) -| node[etiqueta, pos=0.25]
  {{no: informativo, cálculo, datos insuficientes}} (finalizar.north);
\draw[flujo, draw=naranja] (verificar.south) -- ++(0, -0.75) -| node[etiqueta, pos=0.25]
  {{devolución con los motivos de A4 (máx.\ {pm.LIMITES.devoluciones_revision})}}
  ($(supervisor.south)+(1.1,0)$);

\begin{{scope}}[on background layer]
  \node[draw=gris!60, dashed, rounded corners=6pt, fit={{(iniciar)(finalizar)
    (supervisor)(clasificar)($(clasificar.north)+(0,1.3)$)($(verificar.south)+(0,-0.95)$)}},
    inner sep=8pt] (grafo) {{}};
\end{{scope}}
\node[text=gris, font=\footnotesize, anchor=south east] at (grafo.north east)
  {{Grafo de control determinista (LangGraph)}};

% --- Especialistas ---
\node[agente] (a1) at (0.6, -4.6) {{{agente("A1")}}};
\node[agente] (a2) at (5.0, -4.6) {{{agente("A2")}}};
\node[agente] (a3) at (9.4, -4.6) {{{agente("A3")}}};
\node[agente] (a4) at (14.0, -4.6) {{{agente("A4")}}};

% A0 llama a cada especialista como una herramienta y recibe su salida.
\draw[thick, draw=azul] (supervisor.south) -- (3.6, -2.4);
\draw[thick, draw=azul] (0.6, -2.4) -- (9.4, -2.4);
\foreach \a/\x/\n in {{a1/0.6/{delegacion_a("A1")},a2/5.0/{delegacion_a("A2")},a3/9.4/{delegacion_a("A3")}}} {{
  \draw[delega] (\x, -2.4) -- node[etiqueta, pos=0.45] {{\texttt{{\n}}}} (\a.north);
}}
\node[font=\footnotesize, text=azul, anchor=west, fill=white, inner sep=1pt] at (3.75, -1.85)
  {{tarea y datos clave $\downarrow$\quad salida estructurada $\uparrow$}};
\draw[delega] (riesgo.south) -- ++(0, -1.95) -| node[etiqueta, pos=0.25, above=1pt]
  {{propuesta registrada}} (a4.north);

% --- Mesa y datos ---
\node[control, text width=15.4cm, minimum height=10mm] (mesa) at (7.4, -7.6)
  {{\textbf{{Mesa}}: cada llamada pasa por los permisos de su agente, el
  presupuesto ({pm.LIMITES.herramientas_por_especialista} herramientas por
  invocación, {pm.LIMITES.invocaciones_especialistas} invocaciones,
  {pm.LIMITES.llamadas_modelo} llamadas al modelo, {pm.LIMITES.timeout_caso_s}~s
  por caso) y la traza}};
\foreach \a in {{a1,a2,a3,a4}} {{ \draw[flujo] (\a.south) -- (\a.south |- mesa.north); }}
\node[caja, text width=15.1cm, align=center] (datos) at (7.4, -9.2)
  {{\textbf{{Datos simulados y fechados}} en el archivo: P1, POL1, N1, N2, F1, T0, E1;
  falla inyectable QERR}};
\draw[flujo] (mesa) -- (datos);

% --- Salida y control humano ---
\node[caja, text width=4.1cm] (respuesta) at (18.5, -3.7)
  {{\textbf{{Respuesta final}}\\{{\footnotesize \texttt{{RespuestaFinal}}: estado,
  métricas de la traza, evidencia, dictamen}}}};
\draw[flujo] (finalizar) -- (finalizar |- respuesta.north);
\node[humano, text width=4.1cm] (humano) at (18.5, -7.3)
  {{\textbf{{Punto de control humano}}\\[2pt]{{\footnotesize
  \texttt{{pendiente\_revision\_humana}}: decide una persona, fuera del sistema.\\[2pt]
  \texttt{{bloqueada}}: ninguna aprobación anula un límite duro.\\[2pt]
  No hay herramienta de ejecución ni conexión con un intermediario.}}}};
\draw[flujo, draw=verde] (respuesta) -- (humano);

% --- Evaluación ---
\node[caja, text width=21cm, align=left, draw=gris!70, fill=gris!5] (evaluacion) at (9.3, -11.1)
  {{\textbf{{Evaluación}} (en el mismo archivo, fuera del alcance de los agentes):
  la traza JSONL se compara con la clave R1–R6 en tres planos, trayectoria,
  resultado y controles. Juez J1/J2 en R1 y R2: \texttt{{{tex(pm.MODELO_JUEZ)}}}, sin
  herramientas. Agentes A0–A4: \texttt{{{tex(pm.MODELO_AGENTES)}}}.}};
\end{{tikzpicture}}
\end{{document}}
"""


def compilar(fuente: str, carpeta: Path, nombre: str) -> Path:
    """xelatex en una carpeta de trabajo; devuelve el PDF."""
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.tex").write_text(fuente, encoding="utf-8")
    xelatex = shutil.which("xelatex") or str(
        Path.home() / "AppData/Local/Programs/MiKTeX/miktex/bin/x64/xelatex.exe"
    )
    for _ in range(2):  # la segunda pasada resuelve referencias y tablas largas
        proceso = subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", f"{nombre}.tex"],
            cwd=carpeta,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proceso.returncode != 0:
            raise RuntimeError(proceso.stdout[-3000:])
    return carpeta / f"{nombre}.pdf"


def main() -> int:
    pdf = compilar(documento(), RAIZ / "reports" / "build" / "diagrama", "diagrama")
    shutil.copyfile(pdf, DESTINO)
    print(f"Diagrama en {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
