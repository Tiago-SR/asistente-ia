"""Purga periódica de conversaciones según la `retencion_dias` de cada sistema."""

import asyncio
import logging

from asistente.sistemas.registro import RegistroSistemas
from asistente.store.acciones import AccionesSql
from asistente.store.repo import Repo

log = logging.getLogger(__name__)


async def purgar_todos(
    registro: RegistroSistemas, repo: Repo, acciones: AccionesSql | None = None
) -> dict[str, int]:
    """Una pasada. Un sistema que falle no impide purgar a los demás."""
    borradas: dict[str, int] = {}
    for sistema in registro.todos():
        try:
            borradas[sistema.id] = await repo.purgar(sistema.id, sistema.retencion_dias)
            if acciones is not None:  # las acciones se retienen lo mismo que las conversaciones
                await acciones.purgar(sistema.id, sistema.retencion_dias)
        except Exception:
            log.exception("purga de %s fallida", sistema.id)
    total = sum(borradas.values())
    if total:
        log.info("purga de retención: %d conversaciones borradas %s", total, borradas)
    return borradas


async def bucle_purga(
    registro: RegistroSistemas, repo: Repo, intervalo_s: float, acciones: AccionesSql | None = None
) -> None:
    """Purga al arrancar y luego cada `intervalo_s`. Se cancela al apagar."""
    while True:
        await purgar_todos(registro, repo, acciones)
        await asyncio.sleep(intervalo_s)
