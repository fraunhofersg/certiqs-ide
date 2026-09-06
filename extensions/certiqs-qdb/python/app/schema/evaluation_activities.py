"""Mirrors src/db/schema/evaluationActivities.ts (see metadata.py)."""

from sqlalchemy import Boolean, Column, Integer, Table, Text

from app.schema.metadata import metadata

evaluation_activities = Table(
    "evaluation_activities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("pass_description", Text),
    Column("fail_description", Text),
    Column("threshold_description", Text),
    Column("dependencies", Text),
    Column("is_iso_mandated", Boolean, nullable=False),
    Column("subclause", Text, nullable=False),
    Column("referenced_from", Text, nullable=False),
)

ea_parameters = Table(
    "ea_parameters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ea_code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("symbol", Text),
    Column("parameter_type", Text, nullable=False),
    Column("description", Text),
    Column("constraints", Text),
)
