"""plans and organisation plans

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    plans = op.create_table('plans',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('max_tenders', sa.Integer(), nullable=False),
    sa.Column('max_uploads_per_month', sa.Integer(), nullable=False),
    sa.Column('max_storage_mb', sa.Integer(), nullable=False),
    sa.Column('max_exports_per_month', sa.Integer(), nullable=False),
    sa.Column('max_members', sa.Integer(), nullable=False),
    sa.CheckConstraint('max_exports_per_month > 0', name=op.f('ck_plans_max_exports_positive')),
    sa.CheckConstraint('max_members > 0', name=op.f('ck_plans_max_members_positive')),
    sa.CheckConstraint('max_storage_mb > 0', name=op.f('ck_plans_max_storage_positive')),
    sa.CheckConstraint('max_tenders > 0', name=op.f('ck_plans_max_tenders_positive')),
    sa.CheckConstraint('max_uploads_per_month > 0', name=op.f('ck_plans_max_uploads_positive')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_plans'))
    )
    op.bulk_insert(plans, [
        {'code': 'demo', 'name': 'Demo', 'max_tenders': 25, 'max_uploads_per_month': 200,
         'max_storage_mb': 1024, 'max_exports_per_month': 200, 'max_members': 10},
        {'code': 'starter', 'name': 'Starter', 'max_tenders': 3, 'max_uploads_per_month': 10,
         'max_storage_mb': 50, 'max_exports_per_month': 20, 'max_members': 3},
    ])
    op.create_table('organisation_plans',
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.Column('plan_code', sa.String(length=20), nullable=False),
    sa.Column('changed_by', sa.Uuid(), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organisation_id', 'changed_by'], ['memberships.organisation_id', 'memberships.user_id'], name='fk_organisation_plans_changer_membership'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], name=op.f('fk_organisation_plans_organisation_id_organisations')),
    sa.ForeignKeyConstraint(['plan_code'], ['plans.code'], name=op.f('fk_organisation_plans_plan_code_plans')),
    sa.PrimaryKeyConstraint('organisation_id', name=op.f('pk_organisation_plans'))
    )


def downgrade() -> None:
    op.drop_table('organisation_plans')
    op.drop_table('plans')
