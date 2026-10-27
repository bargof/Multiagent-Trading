"""Los cuatro entregables en dist/: el .py, el informe, el diagrama y el ZIP.

El ZIP lleva el código, las pruebas, la documentación y la evidencia de las
campañas. Nunca lleva .env, el entorno virtual ni archivos de compilación, y
no se escribe si algún archivo contiene algo con forma de API key de Google.

    .venv\\Scripts\\python scripts\\empacar.py
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIST = RAIZ / "dist"
ZIP = DIST / "comite_inversion_multiagente.zip"

INCLUIR = (
    "proyecto_multiagente.py",
    "README.md",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "docs/*.md",
    "tests/*.py",
    "tests/unit/*.py",
    "scripts/*.py",
    "reports/congelacion*.json",
    "reports/campanas/*/*",
    "reports/informe_resultados.pdf",
    "reports/diagrama_arquitectura.pdf",
)
SUELTOS = (
    "proyecto_multiagente.py",
    "reports/informe_resultados.pdf",
    "reports/diagrama_arquitectura.pdf",
)
# Las keys de Google AI Studio empiezan con AIza y siguen 35 caracteres.
KEY = re.compile(rb"AIza[0-9A-Za-z_\-]{35}")


def archivos() -> list[Path]:
    encontrados = sorted({p for patron in INCLUIR for p in RAIZ.glob(patron)})
    return [p for p in encontrados if p.is_file() and p.name != ".env"]


def main() -> int:
    lista = archivos()
    faltan = [s for s in SUELTOS if not (RAIZ / s).is_file()]
    if faltan:
        raise SystemExit(f"Faltan entregables: {', '.join(faltan)}")
    con_key = [p for p in lista if KEY.search(p.read_bytes())]
    if con_key:
        nombres = ", ".join(str(p.relative_to(RAIZ)) for p in con_key)
        raise SystemExit(f"No se empaca: hay algo con forma de API key en {nombres}")

    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in lista:
            zf.write(p, Path("comite_inversion_multiagente") / p.relative_to(RAIZ))
    for s in SUELTOS:
        shutil.copyfile(RAIZ / s, DIST / Path(s).name)
    print(f"{len(lista)} archivos en {ZIP}")
    for s in SUELTOS:
        print(f"Entregable: {DIST / Path(s).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
