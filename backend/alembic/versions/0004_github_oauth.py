"""github_oauth: add github_id, make hashed_password nullable

Revision ID: 0004_github_oauth
Revises: 0003_rebrand
Create Date: 2026-04-29 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_github_oauth"
down_revision: Union[str, Sequence[str], None] = "0003_rebrand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("operators", "hashed_password", existing_type=sa.String(), nullable=True)
    op.add_column("operators", sa.Column("github_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_operators_github_id"), "operators", ["github_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_operators_github_id"), table_name="operators")
    op.drop_column("operators", "github_id")
    op.alter_column("operators", "hashed_password", existing_type=sa.String(), nullable=False)
