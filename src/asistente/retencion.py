"""Purga periódica de conversaciones, acciones y auditoría de tools según la `retencion_dias` de cada sistema, de la memoria por usuario según sus días sin uso y de la auditoría del panel según `ASISTENTE_ADMIN_AUDITORIA_DIAS`. También resume las métricas a `uso_diario` y purga los crudos (`evento_uso`, contadores)."""

import asyncio
import logging

from asistente.sistemas.registro import RegistroSistemas
from asistente.store.acciones import AccionesSql
from asistente.store.admin import AdminSql
from asistente.store.archivos import ArchivosSql
from asistente.store.auditoria import AuditoriaSql
from asistente.store.memoria import MemoriaSql
from asistente.store.repo import Repo
from asistente.store.resumen import ResumenSql

log = logging.getLogger(__name__)


async def purgar_todos(
    registro: RegistroSistemas, repo: Repo, acciones: AccionesSql | None = None,
    auditoria: AuditoriaSql | None = None, memoria: MemoriaSql | None = None,
    admin: AdminSql | None = None, admin_auditoria_dias: int = 0, resumen: ResumenSql | None = None,
    archivos: ArchivosSql | None = None,
) -> dict[str, int]:
    """Una pasada. Un sistema que falle no impide purgar a los demás."""
    borradas: dict[str, int] = {}
    for sistema in registro.todos():
        if resumen is not None:  # antes de purgar: `llamadas_tool` se lee aquí y se borra más abajo
            try:
                await resumen.resumir(sistema.id, sistema.retencion_dias)
            except Exception:
                log.exception("resumen de métricas de %s fallido", sistema.id)
        try:
            borradas[sistema.id] = await repo.purgar(sistema.id, sistema.retencion_dias)
            if acciones is not None:  # las acciones se retienen lo mismo que las conversaciones
                await acciones.purgar(sistema.id, sistema.retencion_dias)
            if auditoria is not None:  # los parámetros auditados también son datos de negocio
                await auditoria.purgar(sistema.id, sistema.retencion_dias)
            if memoria is not None:  # lo que no se usó en `memoria_dias_sin_uso` días, con la memoria encendida o no
                await memoria.purgar(sistema.id)
            if resumen is not None:  # solo días ya resumidos
                await resumen.purgar_eventos(sistema.id, sistema.retencion_dias)
        except Exception:
            log.exception("purga de %s fallida", sistema.id)
    if admin is not None and admin_auditoria_dias > 0:  # no es de ningún sistema: fuera del bucle
        try:
            n = await admin.purgar_auditoria(admin_auditoria_dias)
            if n:
                log.info("purga de retención: %d registros de auditoría del panel", n)
        except Exception:
            log.exception("purga de la auditoría del panel fallida")
    if archivos is not None:  # los vencidos no son descargables, pero sus bytes siguen en la BD hasta aquí
        try:
            await archivos.purgar()
        except Exception:
            log.exception("purga de archivos vencidos fallida")
    if resumen is not None:  # no es de ningún sistema
        try:
            await resumen.purgar_contadores()
        except Exception:
            log.exception("purga de contadores de uso fallida")
    total = sum(borradas.values())
    if total:
        log.info("purga de retención: %d conversaciones borradas %s", total, borradas)
    return borradas


async def bucle_purga(
    registro: RegistroSistemas, repo: Repo, intervalo_s: float, acciones: AccionesSql | None = None,
    auditoria: AuditoriaSql | None = None, memoria: MemoriaSql | None = None,
    admin: AdminSql | None = None, admin_auditoria_dias: int = 0, resumen: ResumenSql | None = None,
    archivos: ArchivosSql | None = None,
) -> None:
    """Purga al arrancar y luego cada `intervalo_s`. Se cancela al apagar."""
    while True:
        await purgar_todos(registro, repo, acciones, auditoria, memoria, admin, admin_auditoria_dias,
                           resumen, archivos)
        await asyncio.sleep(intervalo_s)
