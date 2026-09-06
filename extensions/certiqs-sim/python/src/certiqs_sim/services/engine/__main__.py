"""Entry point: ``python -m certiqs_sim.services.engine`` / ``certiqs-engine``."""

from __future__ import annotations

from certiqs_sim.config.settings import get_settings


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "certiqs_sim.services.engine.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port + 1,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
