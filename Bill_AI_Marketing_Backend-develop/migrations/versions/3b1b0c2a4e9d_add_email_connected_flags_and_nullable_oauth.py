"""add_email_connected_flags_and_nullable_oauth

Revision ID: 3b1b0c2a4e9d
Revises: add_oauth_email_connected
Create Date: 2026-03-16

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3b1b0c2a4e9d"
down_revision = "add_oauth_email_connected"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    user_columns = {c["name"] for c in insp.get_columns("users")}
    uep_columns = {c["name"] for c in insp.get_columns("user_email_providers")}

    if "email_connected" not in user_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "email_connected",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    # Make access_token nullable if it isn't already, and add email_connected
    with op.batch_alter_table("user_email_providers", schema=None) as batch_op:
        # Not all backends expose nullability cleanly here; this is safe to run
        batch_op.alter_column(
            "access_token",
            existing_type=sa.TEXT(),
            nullable=True,
        )
        if "email_connected" not in uep_columns:
            batch_op.add_column(
                sa.Column(
                    "email_connected",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade():
    with op.batch_alter_table("user_email_providers", schema=None) as batch_op:
        batch_op.drop_column("email_connected")
        batch_op.alter_column(
            "access_token",
            existing_type=sa.TEXT(),
            nullable=False,
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_connected")

