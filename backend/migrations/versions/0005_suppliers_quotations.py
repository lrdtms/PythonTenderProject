"""suppliers quotations

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16 23:40:09.458559
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # match_suggestions references boq_items(organisation_id, id), so the constraint comes first
    op.create_unique_constraint('uq_boq_items_org_id', 'boq_items', ['organisation_id', 'id'])
    op.create_table('suppliers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('name_key', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_suppliers_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suppliers')),
    sa.UniqueConstraint('organisation_id', 'id', name='uq_suppliers_org_id'),
    sa.UniqueConstraint('organisation_id', 'name_key', name='uq_suppliers_org_name_key')
    )
    op.create_table('quotations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('supplier_id', sa.Uuid(), nullable=False),
    sa.Column('reference', sa.String(length=100), nullable=True),
    sa.Column('quote_date', sa.Date(), nullable=True),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('prices_include_vat', sa.Boolean(), nullable=True),
    sa.Column('flags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organisation_id', 'run_id', 'document_version_id'], ['extraction_runs.organisation_id', 'extraction_runs.id', 'extraction_runs.document_version_id'], name='fk_quotations_run'),
    sa.ForeignKeyConstraint(['organisation_id', 'supplier_id'], ['suppliers.organisation_id', 'suppliers.id'], name='fk_quotations_supplier'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_quotations_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quotations')),
    sa.UniqueConstraint('organisation_id', 'document_version_id', name='uq_quotations_org_version'),
    sa.UniqueConstraint('organisation_id', 'id', 'document_version_id', name='uq_quotations_org_id_version'),
    sa.UniqueConstraint('organisation_id', 'id', name='uq_quotations_org_id')
    )
    op.create_table('quotation_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('quotation_id', sa.Uuid(), nullable=False),
    sa.Column('document_version_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('source_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('sku', sa.String(length=100), nullable=True),
    sa.Column('unit', sa.String(length=30), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('unit_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('raw_unit', sa.String(length=50), nullable=True),
    sa.Column('raw_quantity', sa.String(length=50), nullable=True),
    sa.Column('raw_price', sa.String(length=50), nullable=True),
    sa.Column('flags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('sheet', sa.String(length=200), nullable=True),
    sa.Column('cell_range', sa.String(length=40), nullable=True),
    sa.Column('review_status', sa.String(length=20), nullable=False),
    sa.Column('original_value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('corrected_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organisation_id', 'quotation_id', 'document_version_id'], ['quotations.organisation_id', 'quotations.id', 'quotations.document_version_id'], name='fk_quotation_items_quotation', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id', 'reviewed_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_quotation_items_reviewer_membership'),
    sa.ForeignKeyConstraint(['organisation_id', 'run_id', 'document_version_id'], ['extraction_runs.organisation_id', 'extraction_runs.id', 'extraction_runs.document_version_id'], name='fk_quotation_items_run'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_quotation_items_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quotation_items')),
    sa.UniqueConstraint('organisation_id', 'id', name='uq_quotation_items_org_id')
    )
    op.create_index('ix_quotation_items_quotation', 'quotation_items', ['quotation_id'], unique=False)
    op.create_index('ix_quotation_items_version', 'quotation_items', ['document_version_id', 'source_order', 'position'], unique=False)
    op.create_table('match_suggestions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('boq_item_id', sa.Uuid(), nullable=False),
    sa.Column('quotation_item_id', sa.Uuid(), nullable=False),
    sa.Column('supplier_id', sa.Uuid(), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('classification', sa.String(length=10), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('decided_by', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("classification IN ('clear', 'ambiguous')", name=op.f('ck_match_suggestions_ck_match_classification')),
    sa.CheckConstraint("status IN ('suggested', 'confirmed', 'rejected')", name=op.f('ck_match_suggestions_ck_match_status')),
    sa.ForeignKeyConstraint(['organisation_id', 'boq_item_id'], ['boq_items.organisation_id', 'boq_items.id'], name='fk_match_boq_item', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id', 'decided_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_match_decider_membership'),
    sa.ForeignKeyConstraint(['organisation_id', 'quotation_item_id'], ['quotation_items.organisation_id', 'quotation_items.id'], name='fk_match_quotation_item', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id', 'supplier_id'], ['suppliers.organisation_id', 'suppliers.id'], name='fk_match_supplier'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_match_suggestions_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_match_suggestions')),
    sa.UniqueConstraint('boq_item_id', 'quotation_item_id', name='uq_match_pair')
    )
    op.create_index('ix_match_boq_item', 'match_suggestions', ['boq_item_id'], unique=False)
    op.create_index('ix_match_quotation_item', 'match_suggestions', ['quotation_item_id'], unique=False)
    op.create_index('uq_match_confirmed_per_boq_supplier', 'match_suggestions', ['boq_item_id', 'supplier_id'], unique=True, postgresql_where=sa.text("status = 'confirmed'"))


def downgrade() -> None:
    op.drop_index('uq_match_confirmed_per_boq_supplier', table_name='match_suggestions', postgresql_where=sa.text("status = 'confirmed'"))
    op.drop_index('ix_match_quotation_item', table_name='match_suggestions')
    op.drop_index('ix_match_boq_item', table_name='match_suggestions')
    op.drop_table('match_suggestions')
    op.drop_index('ix_quotation_items_version', table_name='quotation_items')
    op.drop_index('ix_quotation_items_quotation', table_name='quotation_items')
    op.drop_table('quotation_items')
    op.drop_table('quotations')
    op.drop_table('suppliers')
    op.drop_constraint('uq_boq_items_org_id', 'boq_items', type_='unique')
