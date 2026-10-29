"""El monitor: el recorrido completo cada cierto tiempo, en horario de mercado.

    python -m comite vigilar             cada 30 min, lunes a viernes 7:30–15:00
    python -m comite vigilar --una-vez   una vuelta (para el Programador de tareas)

No hace day trading ni opera solo (decisión D74). Lo que gana es no
esperar a que abras la app:
- titulares de la cartera cada vuelta;
- reportes y calendario cada `horas_entre_fundamentales`;
- el rebalanceo de la estrategia el día que toca.

Las propuestas nuevas te llegan como notificación de Windows y siguen
esperando tu aprobación.

Cuida la cuota. Analiza pocas situaciones por vuelta y deja de usar el comité
al llegar a `llamadas_monitor_max` llamadas en el día, para que el chat
conserve las suyas.
"""

import subprocess
import sys
import time as reloj_sistema
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from comite import config, db, proceso, puente, recomendador
from comite.config import REGLAS

# Hora de la Ciudad de México. La BMV abre a las 8:30 y el SIC sigue a
# Nueva York, que abre a las 7:30 mientras EUA tiene horario de verano.
INICIO, FIN = time(7, 30), time(15, 0)
ANALISIS_POR_VUELTA = 2
RUTA_BITACORA = config.DIR_DATOS / "monitor.log"


def en_horario(momento: datetime) -> bool:
    return momento.weekday() < 5 and INICIO <= momento.time() <= FIN


def toca_fundamentales(conn, ahora: datetime) -> bool:
    ultima = db.leer_parametro(conn, "fundamentales_al")
    if not ultima:
        return True
    transcurrido = ahora - datetime.fromisoformat(ultima)
    return transcurrido >= timedelta(hours=REGLAS.horas_entre_fundamentales)


@dataclass
class Vuelta:
    inicio: str
    con_comite: bool
    resumen: proceso.Resumen
    nuevas: list[dict] = field(default_factory=list)


def vuelta(
    conn,
    *,
    usar_comite: bool = True,
    max_analisis: int = ANALISIS_POR_VUELTA,
    lectores: proceso.Fuentes | None = None,
    modelo_para: puente.ModeloPara | None = None,
    avisar: proceso.Aviso = lambda paso, detalle: None,
) -> Vuelta:
    """Un recorrido, con el tope de cuota del monitor. Queda registrado."""
    ahora = db.ahora()
    antes = {r["id"] for r in recomendador.pendientes(conn)}
    llamadas = puente.llamadas_hoy(conn)
    con_comite = usar_comite and llamadas < REGLAS.llamadas_monitor_max
    resumen = proceso.recorrer(
        conn,
        usar_comite=con_comite,
        max_analisis=max_analisis,
        fundamentales=toca_fundamentales(conn, ahora),
        avisar=avisar,
        lectores=lectores,
        modelo_para=modelo_para,
    )
    if usar_comite and not con_comite:
        resumen.avisos.insert(
            0,
            f"Ya van {llamadas} llamadas hoy: el monitor sigue sin el comité para "
            "dejar cuota al chat.",
        )
    nuevas = [
        r
        for r in recomendador.pendientes(conn)
        if r["id"] not in antes and r["estado"] == "propuesta"
    ]
    db.guardar_parametro(
        conn,
        "monitor",
        {
            "ultima": ahora.isoformat(),
            "con_comite": con_comite,
            "situaciones_nuevas": resumen.situaciones_nuevas,
            "propuestas_nuevas": len(nuevas),
            "sin_analizar": resumen.sin_analizar,
            "avisos": resumen.avisos,
        },
    )
    return Vuelta(ahora.isoformat(), con_comite, resumen, nuevas)


def notificar_windows(titulo: str, texto: str) -> None:
    """Un globo de notificación de Windows, sin instalar nada."""
    if sys.platform != "win32":
        return

    def literal(s: str) -> str:
        return "'" + s.replace("'", "''")[:240] + "'"

    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(15000, {literal(titulo)}, {literal(texto)}, 'Info'); "
        "Start-Sleep -Seconds 16; $n.Dispose()"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _anotar(texto: str) -> None:
    linea = f"{db.ahora_iso()} {texto}"
    print(linea, flush=True)
    try:
        RUTA_BITACORA.parent.mkdir(parents=True, exist_ok=True)
        with RUTA_BITACORA.open("a", encoding="utf-8") as archivo:
            archivo.write(linea + "\n")
    except OSError:
        pass  # sin bitácora en disco, la consola basta


def correr(
    conn,
    *,
    cada_min: int = 30,
    una_vez: bool = False,
    forzar: bool = False,
    usar_comite: bool = True,
    max_analisis: int = ANALISIS_POR_VUELTA,
    notificar: bool = True,
    dormir: Callable[[float], None] = reloj_sistema.sleep,
) -> None:
    _anotar(
        f"Monitor: cada {cada_min} min, {INICIO:%H:%M}–{FIN:%H:%M} de lunes a "
        f"viernes; comité {'sí' if usar_comite else 'no'}."
    )
    while True:
        momento = db.ahora()
        if forzar or en_horario(momento):
            try:
                v = vuelta(
                    conn,
                    usar_comite=usar_comite,
                    max_analisis=max_analisis,
                    avisar=lambda paso, detalle: _anotar(f"[{paso}] {detalle}"),
                )
                for aviso in v.resumen.avisos:
                    _anotar(f"Aviso: {aviso}")
                _anotar(
                    f"Vuelta lista: {v.resumen.situaciones_nuevas} situaciones "
                    f"nuevas, {len(v.nuevas)} propuestas por aprobar."
                )
                if notificar and v.nuevas:
                    notificar_windows(
                        f"Comité: {len(v.nuevas)} propuesta(s) por aprobar",
                        " · ".join(r["razon"][:80] for r in v.nuevas[:3]),
                    )
            except Exception as error:  # noqa: BLE001 — la siguiente vuelta sigue
                _anotar(f"Error en la vuelta: {type(error).__name__}: {error}")
        else:
            _anotar("Fuera de horario de mercado: no hago nada.")
        if una_vez:
            return
        dormir(cada_min * 60)
