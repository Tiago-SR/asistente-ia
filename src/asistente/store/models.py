"""Modelos de persistencia.

Todo cuelga de `(sistema_id, usuario_ref)`; `usuario_ref` es el `sub` opaco del sistema.
Las consultas del repositorio deben filtrar siempre por ambos.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _ahora():
    return DateTime(timezone=True)


class Conversacion(Base):
    __tablename__ = "conversaciones"
    __table_args__ = (Index("ix_conv_sistema_usuario", "sistema_id", "usuario_ref", "actualizada"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sistema_id: Mapped[str] = mapped_column(String(64))
    usuario_ref: Mapped[str] = mapped_column(String(256))
    titulo: Mapped[str | None] = mapped_column(String(200))
    creada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    actualizada: Mapped[datetime] = mapped_column(
        _ahora(), server_default=func.now(), onupdate=func.now()
    )

    mensajes: Mapped[list["Mensaje"]] = relationship(
        back_populates="conversacion",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Mensaje.id",
    )


class Mensaje(Base):
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversaciones.id", ondelete="CASCADE"), index=True
    )
    rol: Mapped[str] = mapped_column(String(16))  # user | assistant
    contenido: Mapped[list | dict] = mapped_column(JSONB)  # bloques de contenido neutros
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    modelo: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    creado: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())

    conversacion: Mapped[Conversacion] = relationship(back_populates="mensajes")


class LlamadaTool(Base):
    """Auditoría de cada tool ejecutada. Sin resultados completos, solo metadatos."""

    __tablename__ = "llamadas_tool"
    __table_args__ = (Index("ix_llamada_sistema_usuario", "sistema_id", "usuario_ref", "creada"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Sin FK: la auditoría puede sobrevivir al borrado de la conversación.
    conversacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    sistema_id: Mapped[str] = mapped_column(String(64))
    usuario_ref: Mapped[str] = mapped_column(String(256))
    jti: Mapped[str] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(128))
    parametros: Mapped[dict | None] = mapped_column(JSONB)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(500))
    status_http: Mapped[int | None] = mapped_column(Integer)
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
    bytes_respuesta: Mapped[int | None] = mapped_column(Integer)
    creada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())


class ContadorUso(Base):
    """Contadores por ventana para rate limit y cuotas. `usuario_ref` vacío = total del sistema."""

    __tablename__ = "contadores_uso"
    __table_args__ = (UniqueConstraint("sistema_id", "usuario_ref", "ventana", "inicio"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sistema_id: Mapped[str] = mapped_column(String(64))
    usuario_ref: Mapped[str] = mapped_column(String(256), default="")
    ventana: Mapped[str] = mapped_column(String(8))  # min | dia | mes
    inicio: Mapped[datetime] = mapped_column(_ahora())
    mensajes: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(BigInteger, default=0)


class UsoModelo(Base):
    """Consumo por sistema, mes y modelo, con la caché de entrada aparte (cuesta distinto).

    Es la base del informe de costo (`GET /admin/uso`). No se purga con la retención de las
    conversaciones: son pocas filas y sirven para facturar meses atrás.
    """

    __tablename__ = "uso_modelo"
    __table_args__ = (UniqueConstraint("sistema_id", "mes", "modelo"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sistema_id: Mapped[str] = mapped_column(String(64))
    mes: Mapped[datetime] = mapped_column(_ahora())  # primer instante del mes (UTC)
    modelo: Mapped[str] = mapped_column(String(200))
    llamadas: Mapped[int] = mapped_column(Integer, default=0)  # llamadas al LLM, no mensajes
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_in_cache: Mapped[int] = mapped_column(BigInteger, default=0)  # parte de tokens_in
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)


class Accion(Base):
    """Propuesta de una escritura y su ciclo de vida (Fase 5). El `id` es aleatorio de 128 bits y
    no adivinable; la fila es la autoridad del estado: pendiente → confirmada → ejecutada | fallida,
    o cancelada | expirada | reemplazada. Toda consulta filtra por `(sistema_id, usuario_ref)`."""

    __tablename__ = "acciones"
    __table_args__ = (Index("ix_accion_sistema_usuario", "sistema_id", "usuario_ref", "creada"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sistema_id: Mapped[str] = mapped_column(String(64))
    usuario_ref: Mapped[str] = mapped_column(String(256))
    conversacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    parametros: Mapped[dict] = mapped_column(JSONB)
    huella: Mapped[str] = mapped_column(String(128))
    resumen: Mapped[str] = mapped_column(Text)
    lineas: Mapped[list] = mapped_column(JSONB, default=list)
    estado: Mapped[str] = mapped_column(String(16), default="pendiente")
    creada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    expira: Mapped[datetime] = mapped_column(_ahora())
    decidida: Mapped[datetime | None] = mapped_column(_ahora())
    jti_confirmacion: Mapped[str | None] = mapped_column(String(128))
    ok: Mapped[bool | None] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(500))
    status_http: Mapped[int | None] = mapped_column(Integer)
