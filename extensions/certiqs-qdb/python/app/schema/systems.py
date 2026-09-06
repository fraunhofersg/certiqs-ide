"""Mirrors src/db/schema/systems.ts (partial — only tables/columns referenced
so far by ported code; see metadata.py for the incremental-mirroring rule)."""

from sqlalchemy import Boolean, Column, DateTime, Integer, Table, Text

from app.schema.metadata import metadata

protocol_families = Table(
    "protocol_families",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("encoding_id", Integer),
    Column("architecture_id", Integer),
)

protocols = Table(
    "protocols",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("protocol_family_id", Integer, nullable=False),
    Column("name", Text, nullable=False),
)

systems = Table(
    "systems",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Text, nullable=False),
    Column("is_public", Boolean, nullable=False),
    Column("name", Text, nullable=False),
    Column("manufacturer", Text, nullable=False),
    Column("toe_boundary", Text),
    Column("hardware_revision", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("double_click_handling", Text),
    Column("basis_choice", Text),
    Column("deployment", Text),
    Column("detector_accepts_clicks_outside_gate", Boolean),
    Column("optical_path_direction", Text),
    Column("source_type", Text),
    Column("local_oscillator_type", Text),
    Column("phase_randomisation_method", Text),
    Column("reconciliation_algorithm", Text),
)

system_protocols = Table(
    "system_protocols",
    metadata,
    Column("system_id", Integer, primary_key=True),
    Column("protocol_id", Integer, primary_key=True),
    Column("is_primary", Boolean, nullable=False),
)
