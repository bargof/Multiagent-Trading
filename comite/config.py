"""Rutas, identificadores y umbrales de la aplicación.

Los umbrales se fijan aquí, antes de usarse, igual que los límites del
comité: una regla que se ajusta después de ver qué recomienda ya no es una
regla (decisión D64).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from proyecto_multiagente import ZONA_MX

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
RUTA_DB = Path(os.environ.get("COMITE_DB", DIR_DATOS / "comite.db"))
# El Excel que entrega el reto. Si no está, se usa la copia compacta que sí
# va en el repo (data/precios_reto.csv.gz), generada con `importar-reto`.
RUTA_EXCEL_RETO = RAIZ / "Benchmarks_time_series.xlsx"
RUTA_HISTORIA = DIR_DATOS / "precios_reto.csv.gz"
# Antes de esta fecha el historial no sirve para el reto y solo pesaría.
HISTORIA_DESDE = "2024-01-01"

ZONA = ZONA_MX
PORTAFOLIO_ID = "RETO"
POLITICA_ID = "POL-RETO"
BENCHMARKS = ("Conservador", "Moderado", "Agresivo")
# El tipo de cambio se guarda como una emisora más para reusar la tabla de
# precios: las acciones del SIC cotizan en dólares en Yahoo y en pesos en el
# reto.
TIPO_CAMBIO = "USDMXN"
TICKER_TIPO_CAMBIO = "MXN=X"
EFECTIVO_INICIAL = 1_000_000
# La que eligió el criterio de D71 en entrenamiento. No se activa sola: la
# estrategia vigente la eliges tú en la app y se guarda en la base, porque
# su riesgo es mucho mayor que el del Agresivo (decisión D72).
ESTRATEGIA_PROTOCOLO = "momentum_120_top15_tendencia"

# ETFs apalancados o inversos: su rendimiento de 20 días no dice nada de una
# empresa y siempre encabezarían cualquier ranking de momentum.
NO_OPORTUNIDAD = frozenset(
    {"TQQQ", "SQQQ", "SOXL", "SPXL", "SPXS", "TNA", "FAS", "TECL", "QLD", "PSQ"}
)


@dataclass(frozen=True)
class Reglas:
    """Umbrales del vigía, del recomendador y del ejecutor (decisión D64)."""

    # Política del reto: los mismos controles duros de POL1.
    concentracion_max_pct: float = 30.0
    # Por debajo del límite, pero una caída de 10% ya pesa: situación de estrés.
    alerta_concentracion_pct: float = 20.0
    choque_e1_pct: float = -10.0
    # Escenarios históricos de A3 (D76): el peor tramo de 20 sesiones, un mes
    # de bolsa, dentro de las últimas 252, un año.
    escenario_sesiones: int = 20
    escenario_historia: int = 252
    # Movimientos de precio que abren una situación.
    movimiento_dia_pct: float = 5.0
    movimiento_semana_pct: float = 10.0
    destacada_dia_pct: float = 8.0
    # Estrategia (D71 y D72): solo emisoras de $10 o más, y una orden de
    # rebalanceo menor a 0.2% del portafolio no vale la comisión.
    precio_minimo_mxn: float = 10.0
    orden_minima_pct: float = 0.2
    # Calendario: días antes de un reporte en que se avisa.
    dias_aviso_reporte: int = 3
    # Venta parcial cuando noticia negativa y caída coinciden.
    reduccion_pct: float = 25.0
    caida_para_reducir_pct: float = -5.0
    # Ejecución.
    deriva_precio_max_pct: float = 3.0
    vigencia_dias: int = 2
    # Noticias.
    noticias_ventana_dias: int = 7
    titulares_por_resumen: int = 6
    # Cuota: cuántas situaciones analiza el comité por corrida.
    analisis_por_corrida: int = 4
    # Monitor: deja de usar el comité al llegar aquí, para que el chat
    # conserve parte de las ~500 llamadas diarias.
    llamadas_monitor_max: int = 350
    # Reportes y calendario cambian poco: no se piden en cada vuelta.
    horas_entre_fundamentales: int = 6


REGLAS = Reglas()
