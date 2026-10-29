"""Línea de comandos de la aplicación.

    python -m comite importar-reto [--excel RUTA]   universo, historial y benchmarks
    python -m comite cargar-cartera CSV --efectivo N [--fecha AAAA-MM-DD]
    python -m comite recorrer [--sin-comite] [--max N]
    python -m comite vigilar [--cada MIN] [--una-vez] [--forzar] [--sin-comite]
    python -m comite backtest
    python -m comite estrategia [NOMBRE | ninguna]
    python -m comite preguntar "texto"
    python -m comite estado

La app (streamlit run streamlit_app.py) hace lo mismo con botones.
"""

import argparse
import csv
import sys
from pathlib import Path

from comite import (
    backtest,
    cartera,
    db,
    estrategia,
    mercado,
    monitor,
    proceso,
    recomendador,
)


def _imprimir_estado(conn) -> None:
    est = cartera.estado(conn)
    print(cartera.tabla_posiciones(est).to_string(index=False))
    total = est.total
    print(f"\nTotal: ${total:,.2f}" if total else "\nTotal: sin precio completo")
    pendientes = recomendador.pendientes(conn)
    print(f"\nRecomendaciones pendientes: {len(pendientes)}")
    for r in pendientes:
        print(f"  #{r['id']} [{r['estado']}] {r['razon']}")


def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m comite")
    sub = parser.add_subparsers(dest="comando", required=True)
    imp = sub.add_parser("importar-reto", help="Importa el Excel del reto.")
    imp.add_argument("--excel", type=Path)
    carga = sub.add_parser("cargar-cartera", help="Carga posiciones desde un CSV.")
    carga.add_argument("csv", type=Path, help="Columnas: emisora,cantidad,precio")
    carga.add_argument("--efectivo", type=float, required=True)
    carga.add_argument("--fecha", default=db.ahora().date().isoformat())
    rec = sub.add_parser("recorrer", help="Actualiza, vigila, analiza y recomienda.")
    rec.add_argument("--sin-comite", action="store_true")
    rec.add_argument("--max", type=int, default=None)
    vig = sub.add_parser("vigilar", help="El recorrido cada N minutos en horario.")
    vig.add_argument("--cada", type=int, default=30, help="Minutos entre vueltas.")
    vig.add_argument("--una-vez", action="store_true")
    vig.add_argument("--forzar", action="store_true", help="Aun fuera de horario.")
    vig.add_argument("--sin-comite", action="store_true")
    vig.add_argument("--max", type=int, default=monitor.ANALISIS_POR_VUELTA)
    vig.add_argument("--sin-avisos", action="store_true")
    sub.add_parser("backtest", help="Las estrategias contra el historial del reto.")
    est = sub.add_parser("estrategia", help="Muestra o elige la estrategia.")
    est.add_argument("nombre", nargs="?")
    pre = sub.add_parser("preguntar", help="Una pregunta libre al comité.")
    pre.add_argument("texto")
    sub.add_parser("estado", help="Cartera y recomendaciones pendientes.")
    args = parser.parse_args()

    conn = db.conectar()
    if args.comando == "importar-reto":
        tabla = mercado.leer_historia(args.excel)
        print(mercado.importar_reto(conn, tabla))
        try:
            print(f"USDMXN: {mercado.importar_tipo_de_cambio(conn)} cierres")
        except Exception as error:  # noqa: BLE001 — sin red se sigue
            print(f"No se pudo descargar USDMXN: {error}")
        if args.excel or mercado.config.RUTA_EXCEL_RETO.is_file():
            copia = mercado.guardar_copia_compacta(
                tabla, mercado.serie_tipo_de_cambio(conn)
            )
            print(f"Copia compacta: {copia}")
    elif args.comando == "cargar-cartera":
        with args.csv.open(encoding="utf-8") as archivo:
            posiciones = [
                {
                    "emisora": f["emisora"].strip(),
                    "cantidad": int(f["cantidad"]),
                    "precio": float(f["precio"]),
                }
                for f in csv.DictReader(archivo)
            ]
        cartera.cargar_posiciones(conn, args.fecha, posiciones, args.efectivo)
        _imprimir_estado(conn)
    elif args.comando == "recorrer":
        resumen = proceso.recorrer(
            conn,
            usar_comite=not args.sin_comite,
            max_analisis=args.max or proceso.REGLAS.analisis_por_corrida,
            avisar=lambda paso, detalle: print(f"[{paso}] {detalle}"),
        )
        for aviso in resumen.avisos:
            print(f"Aviso: {aviso}")
        _imprimir_estado(conn)
    elif args.comando == "vigilar":
        monitor.correr(
            conn,
            cada_min=args.cada,
            una_vez=args.una_vez,
            forzar=args.forzar,
            usar_comite=not args.sin_comite,
            max_analisis=args.max,
            notificar=not args.sin_avisos,
        )
    elif args.comando == "backtest":
        comparacion = backtest.comparar(*backtest.cargar(conn))
        columnas = [
            "estrategia",
            "rendimiento_pct",
            "anual_pct",
            "volatilidad_pct",
            "caida_maxima_pct",
            "anual_entre_caida",
            "ordenes",
        ]
        for periodo in ("entrenamiento", "prueba"):
            tabla = comparacion.tabla[comparacion.tabla["periodo"] == periodo]
            print(f"\n{periodo}")
            print(tabla[columnas].to_string(index=False))
        print(f"\nElegida por el criterio de D71: {comparacion.elegida}")
    elif args.comando == "estrategia":
        if args.nombre:
            nombre = None if args.nombre == "ninguna" else args.nombre
            estrategia.elegir(conn, nombre)
        vigente = estrategia.vigente(conn)
        print(f"Vigente: {vigente.nombre if vigente else 'ninguna'}")
        for e in estrategia.CANDIDATAS:
            print(f"  {e.nombre}: {e.descripcion}")
    elif args.comando == "preguntar":
        consulta = proceso.preguntar(conn, args.texto)
        if consulta.respuesta:
            r = consulta.respuesta
            print(f"Estado: {r.estado.value}\n\n{r.resumen}")
            print(f"\nEvidencia: {', '.join(r.evidencia) or '(ninguna)'}")
        else:
            print(f"Error: {consulta.error}")
    elif args.comando == "estado":
        _imprimir_estado(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
