"""Mirrors src/db/schema/joins.ts (partial — see metadata.py)."""

from sqlalchemy import Column, Integer, Table, Text

from app.schema.metadata import metadata

ea_covers_attack = Table(
    "ea_covers_attack",
    metadata,
    Column("evaluation_activity_id", Text, primary_key=True),
    Column("attack_vulnerability_id", Integer, primary_key=True),
    Column("rationale", Text),
)
