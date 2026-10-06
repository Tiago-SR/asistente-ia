"""memoria por usuario: preferencias, alias y consultas guardadas

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06 18:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'memoria_usuario',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sistema_id', sa.String(length=64), nullable=False),
        sa.Column('usuario_ref', sa.String(length=256), nullable=False),
        sa.Column('tipo', sa.String(length=24), nullable=False),
        sa.Column('clave', sa.String(length=64), nullable=False),
        sa.Column('valor', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('creada', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actualizada', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ultimo_uso', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("tipo in ('preferencia', 'alias', 'consulta_guardada')", name='ck_memoria_tipo'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sistema_id', 'usuario_ref', 'tipo', 'clave', name='uq_memoria_clave'),
    )
    op.create_index('ix_memoria_sistema_usuario', 'memoria_usuario', ['sistema_id', 'usuario_ref'])


def downgrade() -> None:
    op.drop_index('ix_memoria_sistema_usuario', table_name='memoria_usuario')
    op.drop_table('memoria_usuario')
