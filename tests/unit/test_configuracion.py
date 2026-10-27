"""El .env local: lo único que toca las keys, así que no puede equivocarse.

Una key mal leída no falla aquí, falla minutos después como un error de
autenticación del proveedor, lejos de su causa.
"""

import os
from pathlib import Path

import pytest

from proyecto_multiagente import cargar_env_local


@pytest.fixture
def entorno_limpio(monkeypatch):
    # setenv antes de delenv: así monkeypatch registra el valor original y lo
    # restaura al terminar, aunque cargar_env_local escriba en os.environ por
    # su cuenta. Con delenv solo, una variable que no existía no se registra
    # y la key falsa de la prueba seguiría viva en el resto de la suite.
    for variable in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MODEL_NAME"):
        monkeypatch.setenv(variable, "")
        monkeypatch.delenv(variable)
    return monkeypatch


def cargar(tmp_path, texto):
    ruta = tmp_path / ".env"
    ruta.write_text(texto, encoding="utf-8")
    cargar_env_local(ruta)


def test_lee_keys_y_ignora_comentarios(tmp_path, entorno_limpio):
    cargar(
        tmp_path,
        "# comentario\n"
        "OPENAI_API_KEY=sk-abc   # agentes\n"
        'ANTHROPIC_API_KEY="sk-ant-x #y"\n'
        "\n"
        "linea sin igual\n",
    )
    assert os.environ["OPENAI_API_KEY"] == "sk-abc"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-x #y"


def test_la_plantilla_vacia_no_define_nada(tmp_path, entorno_limpio):
    cargar(tmp_path, "OPENAI_API_KEY=\nANTHROPIC_API_KEY=   \n")
    assert "OPENAI_API_KEY" not in os.environ
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_no_sobrescribe_variables_del_sistema(tmp_path, entorno_limpio):
    entorno_limpio.setenv("OPENAI_API_KEY", "sk-del-sistema")
    cargar(tmp_path, "OPENAI_API_KEY=sk-del-archivo\n")
    assert os.environ["OPENAI_API_KEY"] == "sk-del-sistema"


def test_sin_archivo_no_pasa_nada(tmp_path, entorno_limpio):
    cargar_env_local(tmp_path / "no-existe.env")


def test_la_plantilla_del_repo_no_define_keys(entorno_limpio):
    """Copiar .env.example tal cual no debe dejar una key con basura."""
    cargar_env_local(Path(__file__).resolve().parents[2] / ".env.example")
    assert "OPENAI_API_KEY" not in os.environ
    assert "ANTHROPIC_API_KEY" not in os.environ
