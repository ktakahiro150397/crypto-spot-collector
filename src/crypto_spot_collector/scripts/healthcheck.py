"""Container healthcheck for the Hyperliquid runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

from crypto_spot_collector.trading.deployment import check_health


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--max-age-seconds", type=float, default=90.0)
    args = parser.parse_args()
    check_health(
        Path(args.state_dir) / "health.json",
        max_age_seconds=args.max_age_seconds,
    )


if __name__ == "__main__":
    main()
