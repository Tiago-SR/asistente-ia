"""usuarios del panel de administración: usuario, sesión y auditoría

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11 18:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('admin_usuario',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('hash', sa.String(length=200), nullable=False),
    sa.Column('rol', sa.String(length=16), nullable=False),
    sa.Column('activo', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('fallos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('bloqueado_hasta', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_login', sa.DateTime(timezone=True), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("rol IN ('admin', 'operador')", name='ck_admin_usuario_rol'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('admin_sesion',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('usuario_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('csrf', sa.String(length=64), nullable=False),
    sa.Column('creada', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expira', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ultimo_uso', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['admin_usuario.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index('ix_admin_sesion_usuario_id', 'admin_sesion', ['usuario_id'])
    op.create_table('admin_auditoria',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('fecha', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor', sa.String(length=320), nullable=False),
    sa.Column('accion', sa.String(length=64), nullable=False),
    sa.Column('objetivo', sa.String(length=200), nullable=True),
    sa.Column('antes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('despues', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_auditoria_fecha', 'admin_auditoria', ['fecha'])


def downgrade() -> None:
    op.drop_table('admin_auditoria')
    op.drop_table('admin_sesion')
    op.drop_table('admin_usuario')
