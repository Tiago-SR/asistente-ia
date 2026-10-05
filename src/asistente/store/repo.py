"""Repositorio de conversaciones. TODA consulta filtra por `(sistema_id, usuario_ref)`:
una conversación ajena es indistinguible de una inexistente."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from asistente.core.llm.base import LlamadaTool, Mensaje, Uso
from asistente.store.models import Conversacion
from asistente.store.models import Mensaje as FilaMensaje

_RESULTADO_ANTIGUO = json.dumps(
    {"ok": True, "nota": "resultado de un turno anterior omitido; vuelve a consultar si lo necesitas"},
    ensure_ascii=False,
)


def _a_json(m: Mensaje) -> dict:
    return {
        "texto": m.texto,
        "llamadas": [{"id": c.id, "nombre": c.nombre, "parametros": c.parametros} for c in m.llamadas],
        "llamada_id": m.llamada_id,
    }


def _desde_json(rol: str, c: dict) -> Mensaje:
    llamadas = tuple(LlamadaTool(x["id"], x["nombre"], x["parametros"]) for x in c.get("llamadas", []))
    return Mensaje(rol, c.get("texto", ""), llamadas, c.get("llamada_id"))  # type: ignore[arg-type]


def recortar(mensajes: list[Mensaje], max_turnos: int) -> list[Mensaje]:
    """Últimos `max_turnos` turnos (un turno empieza en un mensaje `user`, así nunca se separa
    una llamada de su resultado). Es el historial previo al turno en curso, así que todos sus
    resultados de tools son viejos y se reemplazan por una nota: contienen datos de clientes
    y ocupan contexto."""
    inicios = [i for i, m in enumerate(mensajes) if m.rol == "user"]
    if not inicios:
        return []
    desde = inicios[-max_turnos] if len(inicios) > max_turnos else 0
    salida = []
    for m in mensajes[desde:]:
        if m.rol == "tool":
            m = Mensaje("tool", _RESULTADO_ANTIGUO, llamada_id=m.llamada_id)
        salida.append(m)
    return salida


class Repo:
    def __init__(self, sesiones: async_sessionmaker[AsyncSession]) -> None:
        self._sesiones = sesiones

    @staticmethod
    def _propia(sistema_id: str, usuario_ref: str, conv_id: uuid.UUID):
        return (
            Conversacion.id == conv_id,
            Conversacion.sistema_id == sistema_id,
            Conversacion.usuario_ref == usuario_ref,
        )

    async def existe(self, sistema_id: str, usuario_ref: str, conv_id: uuid.UUID) -> bool:
        async with self._sesiones() as s:
            q = select(Conversacion.id).where(*self._propia(sistema_id, usuario_ref, conv_id))
            return (await s.execute(q)).first() is not None

    async def listar(self, sistema_id: str, usuario_ref: str, limite: int = 50) -> list[Conversacion]:
        async with self._sesiones() as s:
            q = (
                select(Conversacion)
                .where(Conversacion.sistema_id == sistema_id, Conversacion.usuario_ref == usuario_ref)
                .order_by(Conversacion.actualizada.desc())
                .limit(limite)
            )
            return list((await s.execute(q)).scalars())

    async def _mensajes(self, sistema_id, usuario_ref, conv_id) -> list[FilaMensaje] | None:
        async with self._sesiones() as s:
            if not (await s.execute(
                select(Conversacion.id).where(*self._propia(sistema_id, usuario_ref, conv_id))
            )).first():
                return None
            q = select(FilaMensaje).where(FilaMensaje.conversacion_id == conv_id).order_by(FilaMensaje.id)
            return list((await s.execute(q)).scalars())

    async def visibles(self, sistema_id: str, usuario_ref: str, conv_id: uuid.UUID) -> list[dict] | None:
        """Solo texto que vio el usuario; `None` si la conversación no es suya."""
        filas = await self._mensajes(sistema_id, usuario_ref, conv_id)
        if filas is None:
            return None
        return [
            {"rol": f.rol, "texto": f.contenido["texto"], "creado": f.creado.isoformat()}
            for f in filas
            if f.rol in ("user", "assistant") and f.contenido.get("texto")
        ]

    async def historial(
        self, sistema_id: str, usuario_ref: str, conv_id: uuid.UUID, max_turnos: int
    ) -> list[Mensaje]:
        filas = await self._mensajes(sistema_id, usuario_ref, conv_id) or []
        return recortar([_desde_json(f.rol, f.contenido) for f in filas], max_turnos)

    async def guardar_turno(
        self, sistema_id: str, usuario_ref: str, conv_id: uuid.UUID, titulo: str,
        nuevos: list[Mensaje], uso: Uso, modelo: str, prompt_version: str,
    ) -> None:
        """Crea la conversación si es nueva y agrega los mensajes en una sola transacción."""
        async with self._sesiones.begin() as s:
            conv = (await s.execute(
                select(Conversacion).where(*self._propia(sistema_id, usuario_ref, conv_id))
            )).scalar_one_or_none()
            if conv is None:
                conv = Conversacion(id=conv_id, sistema_id=sistema_id, usuario_ref=usuario_ref,
                                    titulo=titulo[:200])
                s.add(conv)
                await s.flush()
            conv.actualizada = func.now()
            ultimo = max((i for i, m in enumerate(nuevos) if m.rol == "assistant"), default=-1)
            for i, m in enumerate(nuevos):
                s.add(FilaMensaje(
                    conversacion_id=conv_id, rol=m.rol, contenido=_a_json(m),
                    # el uso del turno completo se registra en su mensaje final
                    tokens_in=uso.tokens_in if i == ultimo else None,
                    tokens_out=uso.tokens_out if i == ultimo else None,
                    modelo=modelo if m.rol == "assistant" else None,
                    prompt_version=prompt_version if m.rol == "assistant" else None,
                ))

    async def agregar_nota(
        self, sistema_id: str, usuario_ref: str, conv_id: uuid.UUID, texto: str
    ) -> bool:
        """Agrega un mensaje del asistente a una conversación ya guardada (p. ej. el resultado de
        una acción confirmada). `False` si la conversación no existe o no es del usuario."""
        async with self._sesiones.begin() as s:
            conv = (await s.execute(
                select(Conversacion).where(*self._propia(sistema_id, usuario_ref, conv_id))
            )).scalar_one_or_none()
            if conv is None:
                return False
            conv.actualizada = func.now()
            s.add(FilaMensaje(conversacion_id=conv_id, rol="assistant",
                              contenido=_a_json(Mensaje("assistant", texto))))
            return True

    async def borrar(self, sistema_id: str, usuario_ref: str, conv_id: uuid.UUID) -> bool:
        async with self._sesiones.begin() as s:
            r = await s.execute(
                delete(Conversacion).where(*self._propia(sistema_id, usuario_ref, conv_id))
            )
            return r.rowcount > 0

    async def purgar(self, sistema_id: str, retencion_dias: int, ahora: datetime | None = None) -> int:
        """Borra conversaciones inactivas más allá de la retención del sistema."""
        limite = (ahora or datetime.now(UTC)) - timedelta(days=retencion_dias)
        async with self._sesiones.begin() as s:
            r = await s.execute(
                delete(Conversacion).where(
                    Conversacion.sistema_id == sistema_id, Conversacion.actualizada < limite
                )
            )
            return r.rowcount
