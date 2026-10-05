"""consumo por sistema, mes y modelo (costo)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05 20:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('uso_modelo',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('mes', sa.DateTime(timezone=True), nullable=False),
    sa.Column('modelo', sa.String(length=200), nullable=False),
    sa.Column('llamadas', sa.Integer(), nullable=False),
    sa.Column('tokens_in', sa.BigInteger(), nullable=False),
    sa.Column('tokens_in_cache', sa.BigInteger(), nullable=False),
    sa.Column('tokens_out', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sistema_id', 'mes', 'modelo')
    )


def downgrade() -> None:
    op.drop_table('uso_modelo')
