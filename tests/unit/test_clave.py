"""La clave del evaluador está completa y es coherente con la especificación.

Estas pruebas no evalúan al sistema: verifican que las rutas cumplen lo que
pide la rúbrica antes de ejecutar nada. Una ruta mal declarada —una
dependencia hacia un evento que no existe, un conteo que no coincide con el
documento— produciría una evaluación que mide otra cosa.
"""

import pytest

from proyecto_multiagente import (
    CRITERIOS_JUEZ,
    DATOS,
    RUTAS,
    Configuracion,
    CriterioTrayectoria,
    huella,
    huellas_campana,
)

# Conteos de la sección 2: (eventos evaluados, de los cuales herramientas).
CONTEOS_DEL_DOCUMENTO = {
    "R1": (2, 1),
    "R2": (5, 3),
    "R3": (5, 4),
    "R4": (2, 1),
    "R5": (7, 5),
    "R6": (7, 5),
}


def test_cinco_obligatorias_de_tipos_distintos():
    obligatorias = [r for r in RUTAS if r.obligatoria]
    assert [r.ruta_id for r in obligatorias] == ["R1", "R2", "R3", "R4", "R5"]
    assert len({r.tipo_caso for r in obligatorias}) == 5


def test_r6_queda_fuera_del_denominador():
    (r6,) = [r for r in RUTAS if not r.obligatoria]
    assert r6.ruta_id == "R6"


@pytest.mark.parametrize("ruta", RUTAS, ids=lambda r: r.ruta_id)
def test_cinco_campos_de_la_rubrica(ruta):
    assert ruta.entrada.strip()
    assert ruta.trayectoria
    assert ruta.estado
    assert ruta.justificacion_trayectoria.strip()
    assert ruta.criterio_resultado.strip()


@pytest.mark.parametrize("ruta", RUTAS, ids=lambda r: r.ruta_id)
def test_conteos_coinciden_con_el_documento(ruta):
    esperado = CONTEOS_DEL_DOCUMENTO[ruta.ruta_id]
    assert (ruta.eventos_esperados, ruta.herramientas_esperadas) == esperado


@pytest.mark.parametrize("ruta", RUTAS, ids=lambda r: r.ruta_id)
def test_dependencias_bien_formadas(ruta):
    ids = [e.id for e in ruta.trayectoria]
    assert len(ids) == len(set(ids))
    for antes, despues in ruta.dependencias:
        assert antes in ids and despues in ids
        assert ids.index(antes) < ids.index(despues), "declaradas en orden"
    for evento_id in ruta.reintentos_permitidos:
        assert evento_id in ids


@pytest.mark.parametrize("ruta", RUTAS, ids=lambda r: r.ruta_id)
def test_cada_herramienta_sigue_a_su_delegacion(ruta):
    """Ninguna llamada de especialista puede ocurrir sin que alguien lo invoque."""
    invocado_por = {e.destino: e.id for e in ruta.trayectoria if e.es_delegacion}
    deps = set(ruta.dependencias)
    for evento in ruta.trayectoria:
        if evento.es_delegacion:
            continue
        delegacion = invocado_por[evento.actor]
        alcanzables = {delegacion}
        cambio = True
        while cambio:
            nuevos = {b for a, b in deps if a in alcanzables} - alcanzables
            alcanzables |= nuevos
            cambio = bool(nuevos)
        assert evento.id in alcanzables


def test_solo_r1_es_exacta():
    exactas = [
        r.ruta_id for r in RUTAS if r.criterio_trayectoria is CriterioTrayectoria.EXACTA
    ]
    assert exactas == ["R1"]


def test_evidencia_y_falla_existen_en_los_datos():
    conocidos = set(DATOS.noticias) | set(DATOS.reportes)
    for ruta in RUTAS:
        assert set(ruta.evidencia_minima) <= conocidos
        if ruta.falla:
            assert ruta.falla in DATOS.fallas


def test_jueces_con_tres_criterios():
    for ruta in RUTAS:
        if ruta.juez:
            assert list(CRITERIOS_JUEZ[ruta.juez]) == ["C1", "C2", "C3"]
    assert {r.juez for r in RUTAS if r.juez} == {"J1", "J2"}


def test_huellas_estables_y_sensibles():
    config = Configuracion(modelo="m", modelo_juez="j")
    otra = Configuracion(modelo="otro", modelo_juez="j")
    assert huellas_campana(config) == huellas_campana(config)
    assert (
        huellas_campana(config)["configuracion"]
        != huellas_campana(otra)["configuracion"]
    )
    # El ritmo no cambia lo que ven los modelos: no es otro experimento.
    lenta = Configuracion(modelo="m", modelo_juez="j", llamadas_por_minuto=2)
    assert huellas_campana(lenta) == huellas_campana(config)
    assert huella({"a": 1}) != huella({"a": 2})
    assert huella({"a": 1, "b": 2}) == huella({"b": 2, "a": 1})


def test_las_api_keys_no_entran_en_las_huellas(monkeypatch):
    config = Configuracion(modelo="m", modelo_juez="j")
    sin = huellas_campana(config)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-prueba")
    assert huellas_campana(config) == sin
    assert "AIza" not in repr(config)


def test_una_sola_key_para_agentes_y_juez(monkeypatch):
    """Decisión D47: Gemini para todo, con un modelo distinto para el juez."""
    config = Configuracion.desde_entorno()
    assert config.modelo.startswith("gemini-")
    assert config.modelo_juez.startswith("gemini-")
    assert config.modelo != config.modelo_juez
    assert config.temperatura is None, "Gemini 3.6 en adelante no la admite"
    assert config.keys_faltantes() == ["GOOGLE_API_KEY"]
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-prueba")
    assert config.keys_faltantes() == []
