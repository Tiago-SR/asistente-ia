"""tool_estado.aprobada_huella (aprobación de tools destructivas atada a la definición) y acciones.destructiva

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-14 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_estado", sa.Column("aprobada_huella", sa.String(64), nullable=True))
    op.add_column("acciones", sa.Column("destructiva", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("acciones", "destructiva")
    op.drop_column("tool_estado", "aprobada_huella")
