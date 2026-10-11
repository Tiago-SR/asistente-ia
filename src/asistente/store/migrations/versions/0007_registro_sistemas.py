"""registro de sistemas en BD: sistema, secretos cifrados, estado por tool y versión del registro

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('sistema',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('nombre', sa.String(length=200), nullable=False),
    sa.Column('habilitado', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_por', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sistema_secreto',
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('campo', sa.String(length=64), nullable=False),
    sa.Column('kid', sa.String(length=32), nullable=False),
    sa.Column('nonce', sa.LargeBinary(), nullable=False),
    sa.Column('cifrado', sa.LargeBinary(), nullable=False),
    sa.Column('huella', sa.String(length=8), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_por', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['sistema_id'], ['sistema.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('sistema_id', 'campo')
    )
    op.create_table('tool_estado',
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('tool', sa.String(length=128), nullable=False),
    sa.Column('habilitada', sa.Boolean(), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_por', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['sistema_id'], ['sistema.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('sistema_id', 'tool')
    )
    op.create_table('registro_version',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version', sa.BigInteger(), server_default='0', nullable=False),
    sa.CheckConstraint('id = 1', name='ck_registro_version_unica'),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute("INSERT INTO registro_version (id, version) VALUES (1, 0)")


def downgrade() -> None:
    op.drop_table('registro_version')
    op.drop_table('tool_estado')
    op.drop_table('sistema_secreto')
    op.drop_table('sistema')
