"""SQLAlchemy ORM models for runs, datapoints and settings-version provenance.

The ``settings_version`` provenance chain — previously an unbounded in-memory
registry — is persisted here so any output datapoint can be traced to the exact
inputs that produced it, forming an auditable evidence trail for evaluation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_name: Mapped[str] = mapped_column(String(128))
    protocol: Mapped[str] = mapped_column(String(32), default="bbm92")
    shots_per_window: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    datapoints: Mapped[list[DataPointRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    settings_versions: Mapped[list[SettingsVersionRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SettingsVersionRow(Base):
    __tablename__ = "settings_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    active_from_epoch: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[RunRow] = relationship(back_populates="settings_versions")


class DataPointRow(Base):
    __tablename__ = "datapoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    epoch: Mapped[int] = mapped_column(Integer, index=True)
    epoch_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sim_time_ns: Mapped[float | None] = mapped_column(Float, nullable=True)
    settings_version: Mapped[int] = mapped_column(Integer)
    attack_enabled: Mapped[bool] = mapped_column(default=False)
    shots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qber: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    run: Mapped[RunRow] = relationship(back_populates="datapoints")


__all__ = ["Base", "DataPointRow", "RunRow", "SettingsVersionRow"]
