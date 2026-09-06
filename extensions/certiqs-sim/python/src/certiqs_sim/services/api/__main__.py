"""Entry point: ``python -m certiqs_sim.services.api`` / ``certiqs-api``."""

from __future__ import annotations

from certiqs_sim.config.settings import get_settings


def main() -> None:
    import uvicorn
    from certiqs_sim.runtime.preload import preload_netsquid

    preload_netsquid()
    settings = get_settings()
    uvicorn.run(
        "certiqs_sim.services.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=settings.uvicorn_access_log,
    )


if __name__ == "__main__":
    main()
