"""add review_bills to user_profiles

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10

"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b2c3d4e5f6a1'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_profiles',
        sa.Column('review_bills', JSONB(), nullable=False, server_default='[]')
    )


def downgrade() -> None:
    op.drop_column('user_profiles', 'review_bills')
