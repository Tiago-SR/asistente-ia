"""archivo: Excel generado por el asistente, con vencimiento

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-18 18:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "archivo",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sistema_id", sa.String(64), nullable=False),
        sa.Column("usuario_ref", sa.String(256), nullable=False),
        sa.Column("conversacion_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origen", sa.String(16), nullable=False, server_default="generado"),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("datos", sa.LargeBinary(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_archivo_sistema_usuario", "archivo", ["sistema_id", "usuario_ref", "creado"])
    op.create_index("ix_archivo_expira", "archivo", ["expira_en"])
    op.create_index("ix_archivo_conversacion_id", "archivo", ["conversacion_id"])


def downgrade() -> None:
    op.drop_table("archivo")
