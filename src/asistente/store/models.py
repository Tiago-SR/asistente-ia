"""Modelos de persistencia.

Todo cuelga de `(sistema_id, usuario_ref)`; `usuario_ref` es el `sub` opaco del sistema.
Las consultas del repositorio deben filtrar siempre por ambos.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
    """Auditoría de cada tool ejecutada. Sin resultados completos, solo metadatos. Se purga con la
    retención del sistema; `parametros` alimenta `consultas_recientes`."""

    __tablename__ = "llamadas_tool"
    __table_args__ = (
        Index("ix_llamada_sistema_usuario", "sistema_id", "usuario_ref", "creada"),
        Index("ix_llamada_sistema_creada", "sistema_id", "creada"),  # métricas por rango
    )

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
    # Zona del usuario cuando hizo la consulta (IANA): permite decir «ayer» aunque cambie de zona.
    zona_horaria: Mapped[str | None] = mapped_column(String(64))
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

    Es la base del informe de costo (`GET /admin/api/uso`). No se purga con la retención de las
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


class UsoVoz(Base):
    """Caracteres sintetizados por sistema, mes y motor de voz del servidor (ElevenLabs u otro).

    Base del costo de TTS en `GET /admin/api/uso`: lo que se factura es por carácter, no por token.
    Solo cuenta la voz del servidor (la del navegador no cuesta). Como `uso_modelo`, no se purga.
    """

    __tablename__ = "uso_voz"
    __table_args__ = (UniqueConstraint("sistema_id", "mes", "proveedor", "modelo"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sistema_id: Mapped[str] = mapped_column(String(64))
    mes: Mapped[datetime] = mapped_column(_ahora())  # primer instante del mes (UTC)
    proveedor: Mapped[str] = mapped_column(String(64))
    modelo: Mapped[str] = mapped_column(String(200))
    llamadas: Mapped[int] = mapped_column(Integer, default=0)  # síntesis pedidas (una por frase)
    caracteres: Mapped[int] = mapped_column(BigInteger, default=0)


class EventoUso(Base):
    """Un hecho de uso (turno de chat, síntesis o dictado) para las métricas del panel. Se escribe en lote y
    puede perder filas: la contabilidad que factura es `uso_modelo`/`uso_voz`. Sin texto ni parámetros.
    Se purga a `min(90, retencion_dias del sistema)`; antes, `uso_diario` conserva el resumen sin usuario."""

    __tablename__ = "evento_uso"
    __table_args__ = (
        CheckConstraint("tipo IN ('llm', 'tts', 'stt')", name="ck_evento_uso_tipo"),
        CheckConstraint("resultado IN ('ok', 'error', 'limite')", name="ck_evento_uso_resultado"),
        Index("ix_evento_uso_sistema_creada", "sistema_id", "creada"),
        Index("ix_evento_uso_creada_brin", "creada", postgresql_using="brin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    creada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    sistema_id: Mapped[str] = mapped_column(String(64))
    usuario_ref: Mapped[str] = mapped_column(String(256), default="")
    tipo: Mapped[str] = mapped_column(String(8))
    resultado: Mapped[str] = mapped_column(String(8))
    motivo: Mapped[str] = mapped_column(String(32), default="")
    modelo: Mapped[str] = mapped_column(String(200), default="")
    canal: Mapped[str] = mapped_column(String(16), default="texto")
    n: Mapped[int] = mapped_column(Integer, default=1)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_in_cache: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    unidades: Mapped[int] = mapped_column(BigInteger, default=0)
    llamadas_llm: Mapped[int] = mapped_column(Integer, default=0)
    latencia_llm_ms: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
    costo_valle_usd: Mapped[float | None] = mapped_column(Float)
    costo_pico_usd: Mapped[float | None] = mapped_column(Float)


class UsoDiario(Base):
    """Resumen por día (UTC) de `evento_uso` y de `llamadas_tool`, sin usuario. Se recalcula de forma
    idempotente (sobrescribe) y se conserva: son las series largas del panel. Para las tools, `tipo='tool'`
    y el nombre de la tool va en `modelo`."""

    __tablename__ = "uso_diario"

    dia: Mapped[datetime] = mapped_column(Date, primary_key=True)
    sistema_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(8), primary_key=True)
    modelo: Mapped[str] = mapped_column(String(200), primary_key=True, default="")
    resultado: Mapped[str] = mapped_column(String(8), primary_key=True)
    motivo: Mapped[str] = mapped_column(String(32), primary_key=True, default="")
    canal: Mapped[str] = mapped_column(String(16), primary_key=True, default="")
    n: Mapped[int] = mapped_column(BigInteger, default=0)
    usuarios: Mapped[int] = mapped_column(Integer, default=0)  # distintos en el día
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_in_cache: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    unidades: Mapped[int] = mapped_column(BigInteger, default=0)
    costo_valle_usd: Mapped[float | None] = mapped_column(Float)
    costo_pico_usd: Mapped[float | None] = mapped_column(Float)
    # Eventos (no rechazos) sin tarifa: el costo suma solo el resto y no debe leerse como completo.
    n_sin_tarifa: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    latencia_sum_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    latencia_max_ms: Mapped[int | None] = mapped_column(Integer)
    p50_ms: Mapped[int | None] = mapped_column(Integer)
    p95_ms: Mapped[int | None] = mapped_column(Integer)


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
    destructiva: Mapped[bool] = mapped_column(Boolean, server_default="false")


class MemoriaUsuario(Base):
    """Lo que el usuario pidió recordar (Fase 1 de memoria): preferencias, alias y consultas guardadas.
    Clave de aislamiento `(sistema_id, usuario_ref)`. Un recuerdo vence cuando pasan
    `ASISTENTE_MEMORIA_DIAS_SIN_USO` días desde `ultimo_uso`, que se renueva al usarlo."""

    __tablename__ = "memoria_usuario"
    __table_args__ = (
        UniqueConstraint("sistema_id", "usuario_ref", "tipo", "clave", name="uq_memoria_clave"),
        CheckConstraint("tipo in ('preferencia', 'alias', 'consulta_guardada')", name="ck_memoria_tipo"),
        Index("ix_memoria_sistema_usuario", "sistema_id", "usuario_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sistema_id: Mapped[str] = mapped_column(String(64))
    usuario_ref: Mapped[str] = mapped_column(String(256))
    tipo: Mapped[str] = mapped_column(String(24))
    clave: Mapped[str] = mapped_column(String(64))
    valor: Mapped[dict | list | str | int] = mapped_column(JSONB)
    creada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    actualizada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    ultimo_uso: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())


class SistemaRegistro(Base):
    """Fuente de verdad del registro de sistemas (empresa = sistema). `config` es todo lo no secreto y se valida
    con el modelo `Sistema` al cargarlo; los secretos van cifrados en `SistemaSecreto`."""

    __tablename__ = "sistema"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # = `iss` de los tokens
    nombre: Mapped[str] = mapped_column(String(200))
    habilitado: Mapped[bool] = mapped_column(Boolean, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default="1")  # concurrencia optimista
    actualizado_en: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    actualizado_por: Mapped[str | None] = mapped_column(String(200))


class SistemaSecreto(Base):
    """Un secreto cifrado (AES-256-GCM, AAD `sistema_id:campo`). Se escribe, nunca se devuelve en claro."""

    __tablename__ = "sistema_secreto"

    sistema_id: Mapped[str] = mapped_column(
        ForeignKey("sistema.id", ondelete="CASCADE"), primary_key=True
    )
    campo: Mapped[str] = mapped_column(String(64), primary_key=True)  # auth_hs256, token_manifiesto, llm_api_key…
    kid: Mapped[str] = mapped_column(String(32))
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    cifrado: Mapped[bytes] = mapped_column(LargeBinary)
    huella: Mapped[str] = mapped_column(String(8))  # 4 caracteres de SHA-256, para reconocerlo sin exponerlo
    actualizado_en: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    actualizado_por: Mapped[str | None] = mapped_column(String(200))


class ToolEstado(Base):
    """Solo excepciones al valor por defecto (lectura sí, escritura no): una tool nueva del manifiesto no se
    enciende sola."""

    __tablename__ = "tool_estado"

    sistema_id: Mapped[str] = mapped_column(
        ForeignKey("sistema.id", ondelete="CASCADE"), primary_key=True
    )
    tool: Mapped[str] = mapped_column(String(128), primary_key=True)
    habilitada: Mapped[bool] = mapped_column(Boolean)
    # Solo destructivas: huella de la definición que aprobó un admin del panel (nunca viene del YAML).
    aprobada_huella: Mapped[str | None] = mapped_column(String(64))
    actualizado_en: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    actualizado_por: Mapped[str | None] = mapped_column(String(200))


class RegistroVersion(Base):
    """Una sola fila. Cada cambio al registro la incrementa en la misma transacción; las réplicas la sondean."""

    __tablename__ = "registro_version"
    __table_args__ = (CheckConstraint("id = 1", name="ck_registro_version_unica"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")


class AdminUsuario(Base):
    """Usuario del panel de administración (no confundir con los usuarios finales, que llegan en el JWT)."""

    __tablename__ = "admin_usuario"
    __table_args__ = (CheckConstraint("rol IN ('admin', 'operador')", name="ck_admin_usuario_rol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # siempre en minúsculas
    hash: Mapped[str] = mapped_column(String(200))  # argon2id
    rol: Mapped[str] = mapped_column(String(16))
    activo: Mapped[bool] = mapped_column(Boolean, server_default="true")
    fallos: Mapped[int] = mapped_column(Integer, server_default="0")
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(_ahora())
    ultimo_login: Mapped[datetime | None] = mapped_column(_ahora())
    creado_en: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())


class AdminSesion(Base):
    """Sesión del panel. Solo se guarda el SHA-256 del token (el valor en claro vive en la cookie)."""

    __tablename__ = "admin_sesion"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_usuario.id", ondelete="CASCADE"), index=True
    )
    csrf: Mapped[str] = mapped_column(String(64))
    creada: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())
    expira: Mapped[datetime] = mapped_column(_ahora())  # tope absoluto
    ultimo_uso: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now())


class AdminAuditoria(Base):
    """Quién cambió qué en el panel. `antes`/`despues` nunca llevan secretos."""

    __tablename__ = "admin_auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fecha: Mapped[datetime] = mapped_column(_ahora(), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(320))  # email, o `token` para la automatización
    accion: Mapped[str] = mapped_column(String(64))
    objetivo: Mapped[str | None] = mapped_column(String(200))
    antes: Mapped[dict | None] = mapped_column(JSONB)
    despues: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
