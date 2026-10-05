"""Migraciones de Alembic (`python -m asistente.store.migrar [orden] [revisión]`).

    (sin argumentos) | upgrade [rev]   sube a `rev` (por defecto `head`)
    downgrade <rev>                    baja a `rev` (lo usa `deploy/deploy.sh rollback`)
    head                               imprime la última revisión empaquetada (no toca la BD)

Usa las migraciones empaquetadas con el paquete, así funciona en la imagen de prod
sin alembic.ini. La URL se toma de ASISTENTE_DATABASE_URL (ver migrations/env.py).
"""
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def _config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return cfg


def main(orden: str = "upgrade", revision: str | None = None) -> None:
    # Compatibilidad: `migrar head` / `migrar <rev>` (forma antigua) equivale a `upgrade`.
    if orden not in ("upgrade", "downgrade", "head"):
        orden, revision = "upgrade", orden
    cfg = _config()
    if orden == "head":
        print(ScriptDirectory.from_config(cfg).get_current_head())
    elif orden == "downgrade":
        if not revision:
            raise SystemExit("downgrade requiere una revisión")
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision or "head")


if __name__ == "__main__":
    main(*sys.argv[1:3])
