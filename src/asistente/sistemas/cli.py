"""Operación del registro de sistemas en BD (dentro del contenedor):

    python -m asistente.sistemas.cli importar-yaml [RUTA] [--reemplazar]
    python -m asistente.sistemas.cli exportar-yaml [RUTA]
    python -m asistente.sistemas.cli rotar-clave
    python -m asistente.sistemas.cli generar-clave

Necesitan `ASISTENTE_DATABASE_URL` y, para secretos, `ASISTENTE_CLAVES_MAESTRAS` (`kid:base64[,kid:base64]`).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from asistente.sistemas import registro_bd
from asistente.sistemas.cifrado import Cifrador, ClaveAusente, ErrorCifrado, generar_clave


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="asistente.sistemas.cli", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="comando", required=True)
    i = sub.add_parser("importar-yaml", help="carga el YAML en la BD, cifrando los secretos del entorno")
    i.add_argument("ruta", nargs="?", default=os.environ.get("ASISTENTE_SISTEMAS_PATH", "/config/sistemas.yaml"))
    i.add_argument("--reemplazar", action="store_true", help="sobrescribe si la BD ya tiene sistemas")
    e = sub.add_parser("exportar-yaml", help="vuelca el registro como YAML, sin secretos")
    e.add_argument("ruta", nargs="?", help="archivo de salida (por defecto, la salida estándar)")
    sub.add_parser("rotar-clave", help="re-cifra los secretos con la primera clave maestra")
    sub.add_parser("generar-clave", help="imprime una clave maestra nueva (base64)")
    return p


async def _ejecutar(args: argparse.Namespace) -> int:
    url = os.environ.get("ASISTENTE_DATABASE_URL")
    if not url:
        print("falta ASISTENTE_DATABASE_URL", file=sys.stderr)
        return 2
    motor = create_async_engine(url)
    sesiones = async_sessionmaker(motor, expire_on_commit=False)
    try:
        try:
            cifrador = Cifrador.desde_entorno()
        except ClaveAusente:
            cifrador = None
        if args.comando == "importar-yaml":
            n = await registro_bd.importar_yaml(sesiones, cifrador, args.ruta, reemplazar=args.reemplazar)
            print(f"importados {n} sistema(s)")
        elif args.comando == "exportar-yaml":
            texto = yaml.safe_dump(await registro_bd.exportar_yaml(sesiones), allow_unicode=True, sort_keys=False)
            if args.ruta:
                Path(args.ruta).write_text(texto, encoding="utf-8")
            else:
                print(texto, end="")
        elif args.comando == "rotar-clave":
            if cifrador is None:
                print("falta ASISTENTE_CLAVES_MAESTRAS", file=sys.stderr)
                return 2
            print(f"rotados {await registro_bd.rotar_clave(sesiones, cifrador)} secreto(s)")
    except (registro_bd.ErrorRegistro, ErrorCifrado) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        await motor.dispose()
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.comando == "generar-clave":
        print(generar_clave())
        return 0
    return asyncio.run(_ejecutar(args))


if __name__ == "__main__":
    sys.exit(main())
