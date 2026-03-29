"""add_password_reset_tokens

Revision ID: 63e0d2f3a9b1
Revises: 4f6b8d0a1c22
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '63e0d2f3a9b1'
down_revision = '4f6b8d0a1c22'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'password_reset_tokens' not in insp.get_table_names():
        op.create_table(
            'password_reset_tokens',
            sa.Column('token_id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('token_id'),
            sa.UniqueConstraint('token_hash'),
        )


def downgrade():
    op.drop_table('password_reset_tokens')

