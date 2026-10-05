"""Purga periódica de conversaciones según la `retencion_dias` de cada sistema."""

import asyncio
import logging

from asistente.sistemas.registro import RegistroSistemas
from asistente.store.repo import Repo

log = logging.getLogger(__name__)


async def purgar_todos(registro: RegistroSistemas, repo: Repo) -> dict[str, int]:
    """Una pasada. Un sistema que falle no impide purgar a los demás."""
    borradas: dict[str, int] = {}
    for sistema in registro.todos():
        try:
            borradas[sistema.id] = await repo.purgar(sistema.id, sistema.retencion_dias)
        except Exception:
            log.exception("purga de %s fallida", sistema.id)
    total = sum(borradas.values())
    if total:
        log.info("purga de retención: %d conversaciones borradas %s", total, borradas)
    return borradas


async def bucle_purga(registro: RegistroSistemas, repo: Repo, intervalo_s: float) -> None:
    """Purga al arrancar y luego cada `intervalo_s`. Se cancela al apagar."""
    while True:
        await purgar_todos(registro, repo)
        await asyncio.sleep(intervalo_s)
