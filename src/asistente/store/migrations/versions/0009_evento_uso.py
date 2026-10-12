"""métricas de uso: evento_uso (crudo, 90 días) y uso_diario (resumen sin usuario)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('evento_uso',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('creada', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('usuario_ref', sa.String(length=256), server_default='', nullable=False),
    sa.Column('tipo', sa.String(length=8), nullable=False),
    sa.Column('resultado', sa.String(length=8), nullable=False),
    sa.Column('motivo', sa.String(length=32), server_default='', nullable=False),
    sa.Column('modelo', sa.String(length=200), server_default='', nullable=False),
    sa.Column('canal', sa.String(length=16), server_default='texto', nullable=False),
    sa.Column('n', sa.Integer(), server_default='1', nullable=False),
    sa.Column('tokens_in', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tokens_in_cache', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tokens_out', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('unidades', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('llamadas_llm', sa.Integer(), server_default='0', nullable=False),
    sa.Column('latencia_llm_ms', sa.Integer(), nullable=True),
    sa.Column('ttft_ms', sa.Integer(), nullable=True),
    sa.Column('duracion_ms', sa.Integer(), nullable=True),
    sa.Column('costo_valle_usd', sa.Float(), nullable=True),
    sa.Column('costo_pico_usd', sa.Float(), nullable=True),
    sa.CheckConstraint("tipo IN ('llm', 'tts', 'stt')", name='ck_evento_uso_tipo'),
    sa.CheckConstraint("resultado IN ('ok', 'error', 'limite')", name='ck_evento_uso_resultado'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_evento_uso_sistema_creada', 'evento_uso', ['sistema_id', 'creada'])
    op.create_index('ix_evento_uso_creada_brin', 'evento_uso', ['creada'], postgresql_using='brin')
    op.create_table('uso_diario',
    sa.Column('dia', sa.Date(), nullable=False),
    sa.Column('sistema_id', sa.String(length=64), nullable=False),
    sa.Column('tipo', sa.String(length=8), nullable=False),
    sa.Column('modelo', sa.String(length=200), server_default='', nullable=False),
    sa.Column('resultado', sa.String(length=8), nullable=False),
    sa.Column('motivo', sa.String(length=32), server_default='', nullable=False),
    sa.Column('canal', sa.String(length=16), server_default='', nullable=False),
    sa.Column('n', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('usuarios', sa.Integer(), server_default='0', nullable=False),
    sa.Column('tokens_in', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tokens_in_cache', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('tokens_out', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('unidades', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('costo_valle_usd', sa.Float(), nullable=True),
    sa.Column('costo_pico_usd', sa.Float(), nullable=True),
    sa.Column('latencia_sum_ms', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('latencia_max_ms', sa.Integer(), nullable=True),
    sa.Column('p50_ms', sa.Integer(), nullable=True),
    sa.Column('p95_ms', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('dia', 'sistema_id', 'tipo', 'modelo', 'resultado', 'motivo', 'canal')
    )


def downgrade() -> None:
    op.drop_table('uso_diario')
    op.drop_table('evento_uso')
