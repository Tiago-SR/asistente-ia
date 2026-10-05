"""acciones con confirmación (Fase 5)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05 18:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('acciones',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('usuario_ref', sa.String(length=256), nullable=False),
    sa.Column('conversacion_id', sa.UUID(), nullable=True),
    sa.Column('tool', sa.String(length=64), nullable=False),
    sa.Column('parametros', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('huella', sa.String(length=128), nullable=False),
    sa.Column('resumen', sa.Text(), nullable=False),
    sa.Column('lineas', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('estado', sa.String(length=16), nullable=False),
    sa.Column('creada', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expira', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decidida', sa.DateTime(timezone=True), nullable=True),
    sa.Column('jti_confirmacion', sa.String(length=128), nullable=True),
    sa.Column('ok', sa.Boolean(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('status_http', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_accion_sistema_usuario', 'acciones', ['sistema_id', 'usuario_ref', 'creada'], unique=False)
    op.create_index(op.f('ix_acciones_conversacion_id'), 'acciones', ['conversacion_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_acciones_conversacion_id'), table_name='acciones')
    op.drop_index('ix_accion_sistema_usuario', table_name='acciones')
    op.drop_table('acciones')
