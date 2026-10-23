"""exports

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('exports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('tender_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('estimate_id', sa.Uuid(), nullable=True),
    sa.Column('estimate_version', sa.Integer(), nullable=True),
    sa.Column('label', sa.String(length=10), nullable=False),
    sa.Column('file_key', sa.String(length=500), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('generated_by', sa.Uuid(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(kind = 'estimate_xlsx' AND estimate_id IS NOT NULL AND estimate_version IS NOT NULL) OR (kind = 'checklist_pdf' AND estimate_id IS NULL AND estimate_version IS NULL)", name=op.f('ck_exports_ck_exports_estimate_cols')),
    sa.CheckConstraint("kind <> 'checklist_pdf' OR label IN ('draft', 'approved')", name=op.f('ck_exports_ck_exports_checklist_label')),
    sa.CheckConstraint("kind IN ('estimate_xlsx', 'checklist_pdf')", name=op.f('ck_exports_ck_exports_kind')),
    sa.CheckConstraint("label IN ('draft', 'reviewed', 'approved')", name=op.f('ck_exports_ck_exports_label')),
    sa.ForeignKeyConstraint(['organisation_id', 'estimate_id'], ['estimates.organisation_id', 'estimates.id'], name='fk_exports_estimate'),
    sa.ForeignKeyConstraint(['organisation_id', 'generated_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_exports_generator_membership'),
    sa.ForeignKeyConstraint(['organisation_id', 'tender_id'], ['tenders.organisation_id', 'tenders.id'], name='fk_exports_tender'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_exports_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exports')),
    sa.UniqueConstraint('organisation_id', 'id', name='uq_exports_org_id')
    )
    op.create_index('ix_exports_tender', 'exports', ['organisation_id', 'tender_id', 'generated_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_exports_tender', table_name='exports')
    op.drop_table('exports')
