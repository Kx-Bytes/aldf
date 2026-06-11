"""remove_unapproved_subjects

Revision ID: d2e3f4g5h6i7
Revises: c1d2e3f4g5h6
Create Date: 2026-06-11

Deletes all Subject rows whose names are not in the APPROVED_SUBJECTS list,
and cascades the removal through the document_subjects junction table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2e3f4g5h6i7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4g5h6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPROVED_SUBJECTS = [
    "Animal and plant health",
    "Animal protection and human-animal relationships",
    "Aquaculture",
    "Aquatic ecology",
    "Birds",
    "Crimes against animals and natural resources",
    "Fishes",
    "Insects",
    "Livestock",
    "Mammals",
    "Reptiles",
    "Service animals",
    "Veterinary medicine and animal diseases",
    "Wildlife conservation and habitat protection",
    "Ecology",
    "Endangered and threatened species",
    "Environmental assessment, monitoring, research",
    "Forests, forestry, trees",
    "Land use and conservation",
    "Lakes and rivers",
    "Marine and coastal resources, fisheries",
    "Marine pollution",
    "Watersheds",
    "Wetlands",
    "Wilderness and natural areas, wildlife refuges, wild rivers, habitats",
    "Agricultural practices and innovations",
    "Agricultural research",
    "Hunting and fishing",
    "Outdoor recreation",
    "Pest management",
    "Food supply, safety, and labeling",
    "Meat",
    "Seafood",
    "Environmental health",
    "Infectious and parasitic diseases",
    "World health",
    "Human trafficking",
    "Smuggling and trafficking",
]


def upgrade() -> None:
    conn = op.get_bind()

    # Get IDs of subjects NOT in the approved list.
    placeholders = ", ".join(f":s{i}" for i in range(len(APPROVED_SUBJECTS)))
    params = {f"s{i}": name for i, name in enumerate(APPROVED_SUBJECTS)}

    unapproved_ids = conn.execute(
        sa.text(f"SELECT id FROM subjects WHERE name NOT IN ({placeholders})"),
        params
    ).fetchall()

    if not unapproved_ids:
        return

    id_list = [row[0] for row in unapproved_ids]
    id_placeholders = ", ".join(f":id{i}" for i in range(len(id_list)))
    id_params = {f"id{i}": v for i, v in enumerate(id_list)}

    # Remove junction rows first, then the subject rows.
    conn.execute(
        sa.text(f"DELETE FROM document_subjects WHERE subject_id IN ({id_placeholders})"),
        id_params
    )
    conn.execute(
        sa.text(f"DELETE FROM subjects WHERE id IN ({id_placeholders})"),
        id_params
    )


def downgrade() -> None:
    # Deleted rows cannot be recovered — downgrade is a no-op.
    pass
