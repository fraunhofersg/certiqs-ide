"""Repositories that persist runs, datapoints, and settings-version provenance.

:class:`SqlRepository` writes to any SQLAlchemy-supported database (Postgres in
production, SQLite for tests).  :class:`NullRepository` is a no-op used when no
``database_url`` is configured, so the platform runs fully in-memory in dev
without a database.
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from certiqs_sim.persistence.models import (
    Base,
    DataPointRow,
    RunRow,
    SettingsVersionRow,
)


class Repository(Protocol):
    """Minimal persistence surface used by the engine/API services."""

    def create_run(
        self, run_id: str, config_name: str, protocol: str, shots_per_window: int
    ) -> None: ...

    def finish_run(self, run_id: str, status: str = "stopped") -> None: ...

    def save_settings_version(
        self, run_id: str, version: int, active_from_epoch: int, snapshot: dict[str, Any]
    ) -> None: ...

    def save_datapoint(self, run_id: str, datapoint: dict[str, Any]) -> None: ...

    def get_datapoints(self, run_id: str, since_epoch: int = -1) -> list[dict[str, Any]]: ...

    def get_settings_for_epoch(self, run_id: str, epoch: int) -> dict[str, Any] | None: ...


class NullRepository:
    """No-op repository (used when persistence is disabled)."""

    def create_run(self, *args: Any, **kwargs: Any) -> None:
        return None

    def finish_run(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_settings_version(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_datapoint(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_datapoints(self, run_id: str, since_epoch: int = -1) -> list[dict[str, Any]]:
        return []

    def get_settings_for_epoch(self, run_id: str, epoch: int) -> dict[str, Any] | None:
        return None


class SqlRepository:
    def __init__(self, database_url: str, create_all: bool = True) -> None:
        self.engine = create_engine(database_url, future=True)
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )
        if create_all:
            Base.metadata.create_all(self.engine)

    def create_run(
        self, run_id: str, config_name: str, protocol: str, shots_per_window: int
    ) -> None:
        with self._session_factory() as session:
            existing = session.get(RunRow, run_id)
            if existing is None:
                session.add(
                    RunRow(
                        id=run_id,
                        config_name=config_name,
                        protocol=protocol,
                        shots_per_window=shots_per_window,
                        status="running",
                    )
                )
                session.commit()

    def finish_run(self, run_id: str, status: str = "stopped") -> None:
        from datetime import datetime, timezone

        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is not None:
                row.status = status
                row.stopped_at = datetime.now(timezone.utc)
                session.commit()

    def save_settings_version(
        self, run_id: str, version: int, active_from_epoch: int, snapshot: dict[str, Any]
    ) -> None:
        with self._session_factory() as session:
            session.add(
                SettingsVersionRow(
                    run_id=run_id,
                    version=version,
                    active_from_epoch=active_from_epoch,
                    snapshot=snapshot,
                )
            )
            session.commit()

    def save_datapoint(self, run_id: str, datapoint: dict[str, Any]) -> None:
        metrics = datapoint.get("metrics", {}) or {}
        with self._session_factory() as session:
            session.add(
                DataPointRow(
                    run_id=run_id,
                    epoch=int(datapoint["epoch"]),
                    epoch_end=datapoint.get("epoch_end"),
                    sim_time_ns=datapoint.get("sim_time_ns"),
                    settings_version=int(datapoint.get("settings_version", 0)),
                    attack_enabled=bool(datapoint.get("attack_enabled", False)),
                    shots=datapoint.get("shots"),
                    qber=metrics.get("qber"),
                    metrics=metrics,
                )
            )
            session.commit()

    def get_datapoints(self, run_id: str, since_epoch: int = -1) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            stmt = (
                select(DataPointRow)
                .where(DataPointRow.run_id == run_id, DataPointRow.epoch > since_epoch)
                .order_by(DataPointRow.epoch)
            )
            rows = session.scalars(stmt).all()
            return [
                {
                    "epoch": r.epoch,
                    "epoch_end": r.epoch_end,
                    "sim_time_ns": r.sim_time_ns,
                    "settings_version": r.settings_version,
                    "attack_enabled": r.attack_enabled,
                    "shots": r.shots,
                    "metrics": r.metrics,
                }
                for r in rows
            ]

    def get_settings_for_epoch(self, run_id: str, epoch: int) -> dict[str, Any] | None:
        with self._session_factory() as session:
            dp = session.scalars(
                select(DataPointRow).where(
                    DataPointRow.run_id == run_id, DataPointRow.epoch == epoch
                )
            ).first()
            if dp is None:
                return None
            sv = session.scalars(
                select(SettingsVersionRow).where(
                    SettingsVersionRow.run_id == run_id,
                    SettingsVersionRow.version == dp.settings_version,
                )
            ).first()
            return sv.snapshot if sv is not None else None


def build_repository(database_url: str | None) -> Repository:
    """Return a SQL repository when a URL is configured, else a no-op repository."""
    if database_url:
        return SqlRepository(database_url)
    return NullRepository()


__all__ = [
    "NullRepository",
    "Repository",
    "SqlRepository",
    "build_repository",
]
