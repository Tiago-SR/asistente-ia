"""uso_diario.n_sin_tarifa (para no presentar como completo un costo parcial) e índice de llamadas_tool por rango

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12 18:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("uso_diario", sa.Column("n_sin_tarifa", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_index("ix_llamada_sistema_creada", "llamadas_tool", ["sistema_id", "creada"])


def downgrade() -> None:
    op.drop_index("ix_llamada_sistema_creada", table_name="llamadas_tool")
    op.drop_column("uso_diario", "n_sin_tarifa")
