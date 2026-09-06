"""Mirrors src/db/schema/attacks.ts (partial — see metadata.py)."""

from sqlalchemy import Column, Integer, Table, Text

from app.schema.metadata import metadata

attack_categories = Table(
    "attack_categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text),
)

vulnerabilities = Table(
    "vulnerabilities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("short_description", Text),
)

attacks = Table(
    "attacks",
    metadata,
    Column("vulnerability_id", Integer, primary_key=True),
    Column("attack_category_id", Integer, nullable=False),
    Column("module", Text),
    Column("component", Text),
    Column("equipment", Text),
    Column("targets", Text),
    Column("attack_type", Text),
    Column("expertise", Text),
    Column("knowledge_of_toe", Text),
    Column("opportunity", Text),
    Column("feasibility", Text),
    Column("feasibility_assessment", Text),
    Column("attack_rating", Text),
    Column("subclause", Text),
    Column("referenced_from", Text),
)
