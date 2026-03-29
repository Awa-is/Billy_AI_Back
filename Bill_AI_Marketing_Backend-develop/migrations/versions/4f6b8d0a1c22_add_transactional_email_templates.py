"""add_transactional_email_templates

Revision ID: 4f6b8d0a1c22
Revises: 3b1b0c2a4e9d
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f6b8d0a1c22'
down_revision = '3b1b0c2a4e9d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'transactional_email_templates',
        sa.Column('template_id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=True),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('subject', sa.String(length=250), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('template_id'),
        sa.UniqueConstraint('tenant_id', 'key', name='uq_transactional_template_tenant_key'),
    )


def downgrade():
    op.drop_table('transactional_email_templates')

