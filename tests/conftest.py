"""Ninguna prueba gasta cuota de Gemini (decisión D50).

Cada prueba empieza sin keys ni modelos elegidos por el entorno, y con httpx
cortado: si algo intentara salir a la red, la prueba falla en vez de gastar
una llamada. También se quita la pausa antes del reintento, que solo sirve
frente al servidor real.
"""

import httpx
import pytest

import proyecto_multiagente

_DEL_ENTORNO = (
    *proyecto_multiagente.VARIABLES_DE_KEY,
    "MODEL_NAME",
    "JUDGE_MODEL",
    "GEMINI_RPM",
)


@pytest.fixture(autouse=True)
def sin_red_ni_keys(monkeypatch):
    # setenv antes de delenv, como en test_configuracion: así se restaura el
    # valor original aunque la prueba escriba en os.environ por su cuenta.
    for variable in _DEL_ENTORNO:
        monkeypatch.setenv(variable, "")
        monkeypatch.delenv(variable)

    def cortado(self, request, *args, **kwargs):
        raise AssertionError(f"Una prueba intentó salir a la red: {request.url}")

    monkeypatch.setattr(httpx.Client, "send", cortado)
    monkeypatch.setattr(httpx.AsyncClient, "send", cortado)
    monkeypatch.setattr(
        proyecto_multiagente, "pausar_antes_de_reintentar", lambda: None
    )
