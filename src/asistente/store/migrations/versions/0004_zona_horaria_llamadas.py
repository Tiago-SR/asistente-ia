"""zona horaria del usuario en cada llamada auditada (consultas_recientes)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('llamadas_tool', sa.Column('zona_horaria', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('llamadas_tool', 'zona_horaria')
