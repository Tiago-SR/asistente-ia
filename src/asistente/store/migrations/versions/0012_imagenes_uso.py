"""evento_uso y uso_diario: imágenes adjuntas por turno y la mayor (para mostrar el uso real junto a los límites)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18 12:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evento_uso", sa.Column("imagenes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("evento_uso", sa.Column("imagen_max_kb", sa.Integer(), nullable=True))
    op.add_column("uso_diario", sa.Column("imagenes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("uso_diario", sa.Column("imagenes_max_turno", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("uso_diario", sa.Column("imagen_max_kb", sa.Integer(), nullable=True))


def downgrade() -> None:
    for t, cols in (("uso_diario", ("imagen_max_kb", "imagenes_max_turno", "imagenes")),
                    ("evento_uso", ("imagen_max_kb", "imagenes"))):
        for c in cols:
            op.drop_column(t, c)
