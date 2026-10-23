"""Run the monthly IDOS universe pipeline in GitHub Actions or locally."""

import json
import os
from pathlib import Path

from idos.workers.data.universe_pipeline import UniversePipeline
from idos.strategy.catalog import StrategyCatalog
from idos.strategy.routing import enabled_profiles_for_runner


def format_strategy_summary(strategy_id: str, status: str, output: dict) -> str:
    """Format only metrics produced by a strategy; avoid false zeroes across profiles."""
    fields = []
    candidate_source = output.get("candidate_source")
    if candidate_source:
        fields.append(f"candidate_source={candidate_source}")
    metric_keys = (
        "candidate_count",
        "operable_count",
        "fetch_new",
        "fetch_cached",
        "scout_passed",
        "scout_rejected",
        "opportunities_created",
        "opportunities_eligible",
        "opportunities_existing",
        "processed",
        "passed",
        "blocked",
        "created",
        "existing",
        "duration_seconds",
    )
    fields.extend(
        f"{key}={output[key]}"
        for key in metric_keys
        if key in output and output[key] is not None
    )
    summary = f"{strategy_id}: status={status}"
    return f"{summary}; " + ", ".join(fields) if fields else summary


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
    ] or None
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

    failed = any(item["status"] == "failed" for item in strategy_results.values())
    print("=== PIPELINE COMPLETE ===")
    print(f"Status: {'failed' if failed else 'success'}")
    for strategy_id, item in strategy_results.items():
        output = item["output"] if isinstance(item["output"], dict) else {}
        print(format_strategy_summary(strategy_id, item["status"], output))
        if item["error"]:
            print(f"{strategy_id} error: {item['error']}")

    primary = strategy_results.get("COMPOUNDER") or next(
        iter(strategy_results.values()), {"output": {}}
    )
    output = primary["output"]
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
