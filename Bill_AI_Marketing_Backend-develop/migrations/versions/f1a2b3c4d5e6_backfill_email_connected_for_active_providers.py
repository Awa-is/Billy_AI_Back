"""backfill_email_connected_for_active_providers

Revision ID: f1a2b3c4d5e6
Revises: 3b1b0c2a4e9d
Create Date: 2026-03-17

Backfills email_connected = TRUE for any user_email_providers row that
already has an access_token (meaning the user had connected their email
before the email_connected column was added). Also backfills the users
table email_connected flag for those users.

This fixes the critical bug where existing connected providers had
email_connected=FALSE (the migration default) causing all email sends
to silently fail - the send_email_via_oauth query requires
email_connected=True to find the provider.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "7a1c9f4d2b10"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Fix 1: Backfill user_email_providers.email_connected = TRUE
    # for all rows that have a non-null access_token AND is_active=TRUE.
    # These rows represent users who had already connected their email
    # before this column was introduced.
    bind.execute(sa.text("""
        UPDATE user_email_providers
        SET email_connected = TRUE
        WHERE access_token IS NOT NULL
          AND is_active = TRUE
          AND email_connected = FALSE
    """))

    # Fix 2: Backfill users.email_connected = TRUE for any user
    # who has at least one active, connected provider.
    bind.execute(sa.text("""
        UPDATE users
        SET email_connected = TRUE
        WHERE user_id IN (
            SELECT DISTINCT user_id
            FROM user_email_providers
            WHERE is_active = TRUE
              AND email_connected = TRUE
        )
        AND email_connected = FALSE
    """))


def downgrade():
    # Intentionally a no-op: we cannot safely revert a data backfill
    # without knowing which rows were previously FALSE vs already TRUE.
    pass
