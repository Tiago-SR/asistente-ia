"""índices para las purgas diarias de conversaciones y contadores

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-18 20:00:00.000000
"""
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_conv_sistema_actualizada", "conversaciones", ["sistema_id", "actualizada"])
    op.create_index("ix_contador_ventana_inicio", "contadores_uso", ["ventana", "inicio"])


def downgrade() -> None:
    op.drop_index("ix_contador_ventana_inicio", table_name="contadores_uso")
    op.drop_index("ix_conv_sistema_actualizada", table_name="conversaciones")
