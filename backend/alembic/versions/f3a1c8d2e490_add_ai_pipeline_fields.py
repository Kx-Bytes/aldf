"""add_ai_pipeline_fields

Revision ID: f3a1c8d2e490
Revises: 95e22ebe8425
Create Date: 2026-06-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3a1c8d2e490'
down_revision: Union[str, None] = '95e22ebe8425'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('legislative_documents', sa.Column('official_summary', sa.Text(), nullable=True))
    op.add_column('legislative_documents', sa.Column('relevance_score', sa.Integer(), nullable=True))
    op.add_column('legislative_documents', sa.Column('relevance_topics', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('legislative_documents', sa.Column('relevance_rationale', sa.Text(), nullable=True))
    op.add_column('legislative_documents', sa.Column('ai_summary', sa.Text(), nullable=True))
    op.add_column('legislative_documents', sa.Column('ai_generated_at', sa.DateTime(), nullable=True))
    op.add_column('legislative_documents', sa.Column('ai_source_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('legislative_documents', 'ai_source_hash')
    op.drop_column('legislative_documents', 'ai_generated_at')
    op.drop_column('legislative_documents', 'ai_summary')
    op.drop_column('legislative_documents', 'relevance_rationale')
    op.drop_column('legislative_documents', 'relevance_topics')
    op.drop_column('legislative_documents', 'relevance_score')
    op.drop_column('legislative_documents', 'official_summary')
