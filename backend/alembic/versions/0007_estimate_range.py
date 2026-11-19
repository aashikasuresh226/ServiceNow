"""AI estimate range: estimate_high_cents

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19 20:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("service_requests") as batch:
        batch.add_column(sa.Column("estimate_high_cents", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("service_requests") as batch:
        batch.drop_column("estimate_high_cents")
