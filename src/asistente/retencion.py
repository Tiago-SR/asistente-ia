"""Purga periódica de conversaciones, acciones y auditoría de tools según la `retencion_dias` de cada sistema, de la memoria por usuario según sus días sin uso y de la auditoría del panel según `ASISTENTE_ADMIN_AUDITORIA_DIAS`."""

import asyncio
import logging

from asistente.sistemas.registro import RegistroSistemas
from asistente.store.acciones import AccionesSql
from asistente.store.admin import AdminSql
from asistente.store.auditoria import AuditoriaSql
from asistente.store.memoria import MemoriaSql
from asistente.store.repo import Repo

log = logging.getLogger(__name__)


async def purgar_todos(
    registro: RegistroSistemas, repo: Repo, acciones: AccionesSql | None = None,
    auditoria: AuditoriaSql | None = None, memoria: MemoriaSql | None = None,
    admin: AdminSql | None = None, admin_auditoria_dias: int = 0,
) -> dict[str, int]:
    """Una pasada. Un sistema que falle no impide purgar a los demás."""
    borradas: dict[str, int] = {}
    for sistema in registro.todos():
        try:
            borradas[sistema.id] = await repo.purgar(sistema.id, sistema.retencion_dias)
            if acciones is not None:  # las acciones se retienen lo mismo que las conversaciones
                await acciones.purgar(sistema.id, sistema.retencion_dias)
            if auditoria is not None:  # los parámetros auditados también son datos de negocio
                await auditoria.purgar(sistema.id, sistema.retencion_dias)
            if memoria is not None:  # lo que no se usó en `memoria_dias_sin_uso` días, con la memoria encendida o no
                await memoria.purgar(sistema.id)
        except Exception:
            log.exception("purga de %s fallida", sistema.id)
    if admin is not None and admin_auditoria_dias > 0:  # no es de ningún sistema: fuera del bucle
        try:
            n = await admin.purgar_auditoria(admin_auditoria_dias)
            if n:
                log.info("purga de retención: %d registros de auditoría del panel", n)
        except Exception:
            log.exception("purga de la auditoría del panel fallida")
    total = sum(borradas.values())
    if total:
        log.info("purga de retención: %d conversaciones borradas %s", total, borradas)
    return borradas


async def bucle_purga(
    registro: RegistroSistemas, repo: Repo, intervalo_s: float, acciones: AccionesSql | None = None,
    auditoria: AuditoriaSql | None = None, memoria: MemoriaSql | None = None,
    admin: AdminSql | None = None, admin_auditoria_dias: int = 0,
) -> None:
    """Purga al arrancar y luego cada `intervalo_s`. Se cancela al apagar."""
    while True:
        await purgar_todos(registro, repo, acciones, auditoria, memoria, admin, admin_auditoria_dias)
        await asyncio.sleep(intervalo_s)
