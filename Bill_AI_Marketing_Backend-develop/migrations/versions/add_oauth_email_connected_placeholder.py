"""add_oauth_email_connected (placeholder)

Revision ID: add_oauth_email_connected
Revises: 0a2058e08560
Create Date: 2026-03-16

This is a compatibility migration to satisfy databases that already
have a revision named 'add_oauth_email_connected' applied.

If your schema already has the expected OAuth/email columns, this
migration is effectively a no-op.
"""

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = "add_oauth_email_connected"
down_revision = "0a2058e08560"
branch_labels = None
depends_on = None


def upgrade():
    # No-op: existing databases already applied this logical change.
    # New databases will pick up the real schema changes in the next revision.
    pass


def downgrade():
    # No-op placeholder for symmetry.
    pass

