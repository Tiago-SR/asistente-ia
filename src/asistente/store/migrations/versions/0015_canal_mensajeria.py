"""canal de mensajería: mensajes (dedupe por sistema + id) y vínculos contacto→sistema

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-26 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

_ahora = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "canal_mensajes",
        sa.Column("sistema_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("contacto", sa.String(32), nullable=False),
        sa.Column("direccion", sa.String(8), nullable=False),
        sa.Column("tipo", sa.String(24), nullable=False),
        sa.Column("estado", sa.String(24), nullable=False, server_default="recibido"),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=_ahora, nullable=False),
    )
    op.create_index("ix_canal_mensajes_creado", "canal_mensajes", ["creado_en"])
    op.create_table(
        "canal_vinculos",
        sa.Column("sistema_id", sa.String(64), primary_key=True),
        sa.Column("contacto", sa.String(32), primary_key=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=_ahora, nullable=False),
        sa.Column("ultimo_uso", sa.DateTime(timezone=True), server_default=_ahora, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("canal_vinculos")
    op.drop_table("canal_mensajes")
