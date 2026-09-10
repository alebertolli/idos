"""Run the enabled monthly strategy pipeline."""

import os
import argparse
from pathlib import Path

from idos.workers.data.strategy_pipeline import MonthlyStrategyWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(root)
    result = MonthlyStrategyWorker({"strategy_id": "MOMENTUM_ETF"}).execute(
        {"base_path": ".", "dry_run": args.dry_run, "persist": not args.no_persist}
    )
    print(f"Strategy status: {result.status}")
    print(result.output)
    if result.status == "failed":
        print(result.error or "monthly strategy failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
