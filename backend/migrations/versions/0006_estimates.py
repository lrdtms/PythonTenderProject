"""estimates

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('pricing_defaults',
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('markup_basis', sa.String(length=15), nullable=False),
    sa.Column('default_markup_percent', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("markup_basis IN ('cost', 'selling_price')", name=op.f('ck_pricing_defaults_ck_defaults_basis')),
    sa.CheckConstraint('vat_rate >= 0 AND vat_rate <= 100', name=op.f('ck_pricing_defaults_ck_defaults_vat')),
    sa.ForeignKeyConstraint(['organisation_id', 'updated_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_pricing_defaults_updater_membership'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_pricing_defaults_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('organisation_id', name=op.f('pk_pricing_defaults'))
    )
    op.create_table('estimates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('tender_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('vat_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('markup_basis', sa.String(length=15), nullable=False),
    sa.Column('markup_percent', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('based_on_version', sa.Integer(), nullable=True),
    sa.Column('subtotal_cost', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('markup_total', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('subtotal_ex_vat', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('vat_total', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('total_inc_vat', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("markup_basis IN ('cost', 'selling_price')", name=op.f('ck_estimates_ck_estimates_basis')),
    sa.CheckConstraint("status IN ('draft', 'reviewed', 'approved')", name=op.f('ck_estimates_ck_estimates_status')),
    sa.ForeignKeyConstraint(['organisation_id', 'approved_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_estimates_approver_membership'),
    sa.ForeignKeyConstraint(['organisation_id', 'created_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_estimates_creator_membership'),
    sa.ForeignKeyConstraint(['organisation_id', 'reviewed_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_estimates_reviewer_membership'),
    sa.ForeignKeyConstraint(['organisation_id', 'tender_id'], ['tenders.organisation_id', 'tenders.id'], name='fk_estimates_tender'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_estimates_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_estimates')),
    sa.UniqueConstraint('organisation_id', 'id', name='uq_estimates_org_id'),
    sa.UniqueConstraint('organisation_id', 'tender_id', 'version', name='uq_estimates_version')
    )
    op.create_index('uq_estimates_one_draft', 'estimates', ['tender_id'], unique=True, postgresql_where=sa.text("status = 'draft'"))
    op.create_table('estimate_lines',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('estimate_id', sa.Uuid(), nullable=False),
    sa.Column('boq_item_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('section', sa.String(length=200), nullable=True),
    sa.Column('item_no', sa.String(length=50), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('unit', sa.String(length=30), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('price_source', sa.String(length=12), nullable=False),
    sa.Column('match_suggestion_id', sa.Uuid(), nullable=True),
    sa.Column('supplier_id', sa.Uuid(), nullable=True),
    sa.Column('supplier_name', sa.String(length=200), nullable=True),
    sa.Column('quotation_item_id', sa.Uuid(), nullable=True),
    sa.Column('quoted_unit_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('quoted_currency', sa.String(length=3), nullable=True),
    sa.Column('quoted_includes_vat', sa.Boolean(), nullable=True),
    sa.Column('unit_price_ex_vat', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('labour_rate', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('markup_override_percent', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('exclude_reason', sa.Text(), nullable=True),
    sa.Column('unit_mismatch_acknowledged', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('material_cost', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('labour_cost', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('cost', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('markup', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('total', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('flags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("price_source IN ('supplier', 'manual', 'excluded', 'unresolved')", name=op.f('ck_estimate_lines_ck_estimate_lines_source')),
    sa.ForeignKeyConstraint(['organisation_id', 'estimate_id'], ['estimates.organisation_id', 'estimates.id'], name='fk_estimate_lines_estimate', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id', 'updated_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_estimate_lines_updater_membership'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_estimate_lines_organisation_id_organisations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_estimate_lines')),
    sa.UniqueConstraint('estimate_id', 'boq_item_id', name='uq_estimate_lines_boq_item')
    )
    op.create_index('ix_estimate_lines_estimate', 'estimate_lines', ['estimate_id', 'position'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_estimate_lines_estimate', table_name='estimate_lines')
    op.drop_table('estimate_lines')
    op.drop_index('uq_estimates_one_draft', table_name='estimates', postgresql_where=sa.text("status = 'draft'"))
    op.drop_table('estimates')
    op.drop_table('pricing_defaults')
