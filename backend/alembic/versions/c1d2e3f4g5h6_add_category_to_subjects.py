"""add_category_to_subjects

Revision ID: c1d2e3f4g5h6
Revises: 34849fb626ca
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4g5h6'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subjects', sa.Column('category', sa.String(100), nullable=True))

    # Back-fill existing rows using the same ALDF taxonomy from matching.py
    US_STATES = {
        "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut",
        "Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa",
        "Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan",
        "Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada","New Hampshire",
        "New Jersey","New Mexico","New York","North Carolina","North Dakota","Ohio","Oklahoma",
        "Oregon","Pennsylvania","Rhode Island","South Carolina","South Dakota","Tennessee",
        "Texas","Utah","Vermont","Virginia","Washington","West Virginia","Wisconsin","Wyoming",
    }

    SUBJECT_CATEGORIES = {
        "Animals Used in Research": [
            "Animal and plant health",
            "Environmental assessment, monitoring, research",
            "Veterinary medicine and animal diseases",
            "Infectious and parasitic diseases",
            "Environmental health",
            "World health",
        ],
        "Farmed Animals": [
            "Livestock",
            "Agricultural practices and innovations",
            "Agricultural research",
            "Aquaculture",
            "Meat",
            "Seafood",
            "Food supply, safety, and labeling",
            "Pest management",
        ],
        "Wildlife": [
            "Birds",
            "Fishes",
            "Insects",
            "Mammals",
            "Reptiles",
            "Aquatic ecology",
            "Ecology",
            "Endangered and threatened species",
            "Forests, forestry, trees",
            "Hunting and fishing",
            "Land use and conservation",
            "Lakes and rivers",
            "Marine and coastal resources, fisheries",
            "Marine pollution",
            "Outdoor recreation",
            "Watersheds",
            "Wetlands",
            "Wilderness and natural areas, wildlife refuges, wild rivers, habitats",
            "Wildlife conservation and habitat protection",
        ],
        "Companion & Captive Animals": [
            "Animal protection and human-animal relationships",
            "Crimes against animals and natural resources",
            "Service animals",
        ],
        "Legal & Policy Issues": [
            "Human trafficking",
            "Smuggling and trafficking",
        ],
    }

    subject_to_category = {
        subject: category
        for category, subjects in SUBJECT_CATEGORIES.items()
        for subject in subjects
    }

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name FROM subjects")).fetchall()
    for row in rows:
        subject_id, name = row
        if name in US_STATES:
            category = "Region"
        else:
            category = subject_to_category.get(name, "Other")
        conn.execute(
            sa.text("UPDATE subjects SET category = :cat WHERE id = :id"),
            {"cat": category, "id": subject_id}
        )


def downgrade() -> None:
    op.drop_column('subjects', 'category')
