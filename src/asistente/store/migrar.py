"""Aplica las migraciones de Alembic (`python -m asistente.store.migrar`).

Usa las migraciones empaquetadas con el paquete, así funciona en la imagen de prod
sin alembic.ini. La URL se toma de ASISTENTE_DATABASE_URL (ver migrations/env.py).
"""
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def main(revision: str = "head") -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(cfg, revision)


if __name__ == "__main__":
    main(*sys.argv[1:2])
