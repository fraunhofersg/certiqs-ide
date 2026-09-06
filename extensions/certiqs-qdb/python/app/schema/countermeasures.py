"""Mirrors src/db/schema/countermeasures.ts (partial — see metadata.py)."""

from sqlalchemy import Column, Integer, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY

from app.schema.metadata import metadata

countermeasures = Table(
    "countermeasures",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("countermeasure_type", Text, nullable=False),
    Column("module", Text),
    Column("component_type_ids", ARRAY(Integer)),
)

vulnerability_countermeasures = Table(
    "vulnerability_countermeasures",
    metadata,
    Column("vulnerability_id", Integer, primary_key=True),
    Column("countermeasure_id", Integer, primary_key=True),
    Column("defense_effectiveness", ARRAY(Text)),
)
