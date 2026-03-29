"""add_token_blocklist

Revision ID: 7a1c9f4d2b10
Revises: 63e0d2f3a9b1
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a1c9f4d2b10'
down_revision = '63e0d2f3a9b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'token_blocklist',
        sa.Column('block_id', sa.String(length=36), nullable=False),
        sa.Column('jti', sa.String(length=36), nullable=False),
        sa.Column('token_type', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('block_id'),
        sa.UniqueConstraint('jti'),
    )


def downgrade():
    op.drop_table('token_blocklist')

