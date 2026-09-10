"""Run the monthly IDOS universe pipeline in GitHub Actions or locally."""

import json
import os
from pathlib import Path

from idos.workers.data.universe_pipeline import UniversePipeline


def main() -> int:
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    os.chdir(root)
    config = {
        "config_path": "idos-config",
        "journal_path": "idos-journal",
        "cache_path": "cache",
    }
    result = UniversePipeline(config).execute({})
    print("=== PIPELINE COMPLETE ===")
    print(f"Status: {result.status}")
    output = result.output if result.status != "failed" else {}
    if result.status == "failed":
        print(f"Error: {result.error}")
    else:
        print(f"Finviz: {output.get('finviz_count', 0)} tickers")
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
            {"status": str(result.status), "output": output, "error": result.error},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
