"""caracteres sintetizados por sistema, mes y motor de voz (costo de TTS)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06 20:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('uso_voz',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('mes', sa.DateTime(timezone=True), nullable=False),
    sa.Column('proveedor', sa.String(length=64), nullable=False),
    sa.Column('modelo', sa.String(length=200), nullable=False),
    sa.Column('llamadas', sa.Integer(), nullable=False),
    sa.Column('caracteres', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sistema_id', 'mes', 'proveedor', 'modelo')
    )


def downgrade() -> None:
    op.drop_table('uso_voz')
