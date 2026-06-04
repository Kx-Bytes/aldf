"""add_user_profiles

Revision ID: a1b2c3d4e5f6
Revises: 34849fb626ca
Create Date: 2026-06-04

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '34849fb626ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('expanded_topics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('frequency', sa.String(20), nullable=False, server_default='daily'),
        sa.Column('scope', sa.String(20), nullable=False, server_default='federal'),
        sa.Column('min_relevance_score', sa.Integer(), nullable=False, server_default='70'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_user_profiles_email', 'user_profiles', ['email'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_profiles_email', table_name='user_profiles')
    op.drop_table('user_profiles')
