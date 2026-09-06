"""Entry point: ``certiqs-seceval``.

Two modes:
  * ``certiqs-seceval <campaign.yaml> [--out report.json]`` — run a campaign as a
    CLI and write a reproducible report (recommended; campaigns are long-running).
  * ``certiqs-seceval --serve`` — start the HTTP service.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from certiqs_sim.config.settings import get_settings
from certiqs_sim.services.seceval.campaign import CampaignSpec, run_campaign
from certiqs_sim.services.seceval.report import build_report
from certiqs_sim.telemetry.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="certiqs-seceval")
    parser.add_argument("campaign", nargs="?", help="Path to a campaign YAML spec")
    parser.add_argument("--out", help="Write the JSON report to this path")
    parser.add_argument("--config-root", help="Override the config root directory")
    parser.add_argument("--serve", action="store_true", help="Run the HTTP service instead")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("certiqs-seceval", settings.log_level, settings.log_json)

    if args.serve:
        import uvicorn

        uvicorn.run(
            "certiqs_sim.services.seceval.app:create_app",
            factory=True,
            host=settings.host,
            port=settings.port + 3,
            log_level=settings.log_level.lower(),
        )
        return

    if not args.campaign:
        parser.error("a campaign YAML path is required (or pass --serve)")

    config_root = Path(args.config_root) if args.config_root else settings.config_root
    spec = CampaignSpec.from_yaml(Path(args.campaign))
    results = run_campaign(spec, config_root)
    report = build_report(spec, results)

    output = report.to_json()
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        sys.stderr.write(f"report written to {args.out} ({report.digest})\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
