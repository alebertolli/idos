"""Run the monthly IDOS universe pipeline in GitHub Actions or locally."""

import json
import os
from pathlib import Path

from idos.workers.data.universe_pipeline import UniversePipeline
from idos.strategy.catalog import StrategyCatalog
from idos.strategy.routing import enabled_profiles_for_runner


def main() -> int:
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(root)
    config = {
        "config_path": "idos-config",
        "journal_path": "idos-journal",
        "cache_path": "cache",
    }
    requested_tickers = [
        ticker.strip().upper()
        for ticker in os.environ.get("IDOS_CANDIDATE_TICKERS", "").split(",")
        if ticker.strip()
    ]
    catalog = StrategyCatalog(Path("idos-config/strategies.yml"))
    profiles = enabled_profiles_for_runner(catalog, "universe")
    strategy_results = {}
    for profile in profiles:
        result = UniversePipeline({**config, "strategy_id": profile.strategy_id}).execute(
            {"candidate_tickers": requested_tickers}
        )
        strategy_results[profile.strategy_id] = {
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
        }
        print(f"{profile.strategy_id} status: {result.status.value}")
        if result.status.value == "failed":
            print(f"{profile.strategy_id} error: {result.error}")

    primary = strategy_results.get("COMPOUNDER") or next(
        iter(strategy_results.values()), {"status": "skipped", "output": {}, "error": None}
    )
    output = primary["output"]
    failed = any(item["status"] == "failed" for item in strategy_results.values())
    print("=== PIPELINE COMPLETE ===")
    print(f"Status: {'failed' if failed else 'success'}")
    if not failed:
        print(
            f"Candidate universe: {output.get('candidate_count', 0)} tickers "
            f"from {output.get('candidate_source', 'unknown source')}"
        )
        print(f"Operable: {output.get('operable_count', 0)} tickers")
        print(f"Fetched: {output.get('fetch_new', 0)} new, {output.get('fetch_cached', 0)} cached")
        print(f"Scout: {output.get('scout_passed', 0)} passed, {output.get('scout_rejected', 0)} rejected")
        print(
            "Opportunities: "
            f"{output.get('opportunities_created', 0)} created, "
            f"{output.get('opportunities_eligible', 0)} eligible, "
            f"{output.get('opportunities_existing', 0)} existing"
        )
        print(f"Duration: {output.get('duration_seconds', 0):.0f}s")
    Path("cache").mkdir(exist_ok=True)
    Path("cache/pipeline_results.json").write_text(
        json.dumps(
            {
                "status": "failed" if failed else "success",
                "output": output,
                "error": "; ".join(
                    f"{strategy_id}: {item['error']}"
                    for strategy_id, item in strategy_results.items()
                    if item["error"]
                ) or None,
                "strategies": strategy_results,
                "multibaggers": strategy_results.get(
                    "MULTIBAGGERS", {"status": "disabled"}
                ),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
