"""Run the enabled monthly strategy pipeline."""

import os
import argparse
from pathlib import Path

from idos.strategy.catalog import StrategyCatalog
from idos.strategy.routing import enabled_profiles_for_runner
from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(root)
    candidate_tickers = [
        ticker.strip().upper()
        for ticker in os.environ.get("IDOS_CANDIDATE_TICKERS", "").split(",")
        if ticker.strip()
    ]
    catalog = StrategyCatalog(Path("idos-config/strategies.yml"))
    profiles = enabled_profiles_for_runner(catalog, "monthly_signal")
    failed = False
    for profile in profiles:
        result = MonthlyStrategyWorker({"strategy_id": profile.strategy_id}).execute(
            {
                "base_path": ".",
                "dry_run": args.dry_run,
                "persist": not args.no_persist,
                "candidate_tickers": candidate_tickers,
            }
        )
        print(f"{profile.strategy_id} status: {result.status.value}")
        print(result.output)
        if result.status.value == "failed":
            print(result.error or f"{profile.strategy_id} monthly strategy failed")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
