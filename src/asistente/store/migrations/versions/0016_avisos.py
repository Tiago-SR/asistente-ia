"""avisos salientes del sistema anfitrión y usuario_ref en los vínculos del canal

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

_ahora = sa.text("now()")


def upgrade() -> None:
    op.add_column("canal_vinculos", sa.Column("usuario_ref", sa.String(256), nullable=True))
    op.create_table(
        "avisos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("sistema_id", sa.String(64), nullable=False),
        sa.Column("id_evento", sa.String(128), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("wa_id", sa.String(32), nullable=False),
        sa.Column("usuario_ref", sa.String(256), nullable=False),
        sa.Column("tipo", sa.String(64), nullable=False),
        sa.Column("ref", sa.String(40), nullable=True),
        sa.Column("texto", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(16), nullable=False, server_default="pendiente"),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proximo_intento", sa.DateTime(timezone=True), server_default=_ahora, nullable=False),
        sa.Column("lease_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("caduca_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("mensaje_id", sa.String(128), nullable=True),
        sa.Column("enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=_ahora, nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=_ahora, nullable=False),
        sa.UniqueConstraint("sistema_id", "id_evento"),
    )
    op.create_index("ix_aviso_cola", "avisos", ["estado", "proximo_intento"])
    op.create_index("ix_aviso_numero", "avisos", ["sistema_id", "wa_id", "enviado_en"])
    op.create_index("ix_aviso_creado", "avisos", ["creado_en"])


def downgrade() -> None:
    op.drop_table("avisos")
    op.drop_column("canal_vinculos", "usuario_ref")
