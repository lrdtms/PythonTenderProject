"""source_order

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 09:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

TABLES = (("boq_items", "ix_boq_items_version"), ("requirements", "ix_requirements_version"))


def upgrade() -> None:
    for table, index in TABLES:
        op.add_column(table, sa.Column('source_order', sa.Integer(), server_default='0', nullable=False))
        op.drop_index(index, table_name=table)
        op.create_index(index, table, ['document_version_id', 'source_order', 'position'], unique=False)


def downgrade() -> None:
    for table, index in TABLES:
        op.drop_index(index, table_name=table)
        op.create_index(index, table, ['document_version_id', 'position'], unique=False)
        op.drop_column(table, 'source_order')
