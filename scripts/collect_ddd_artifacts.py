from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-^]{0,14}$")
_PACKAGE_FILES = (
    "opportunity.yml",
    "ddd_report.yml",
    "decision_proposal.yml",
    "board_resolution.yml",
    "hypotheses.yml",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read DDD artifact source {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return value


def collect_ddd_artifacts(
    base_path: Path,
    tickers: list[str],
    run_started_at: str,
    output_dir: str = "cache/ddd-artifact",
    *,
    require_output: bool = False,
) -> dict[str, Any]:
    """Copy only the current run's public DDD decision packages into an artifact folder."""
    base = Path(base_path).resolve()
    output = (base / output_dir).resolve()
    if output == base or not output.is_relative_to(base):
        raise ValueError("DDD artifact output must stay inside the repository")
    if output.is_symlink():
        raise ValueError("DDD artifact output cannot be a symlink")

    started = _parse_timestamp(run_started_at)
    if started is None:
        raise ValueError("run_started_at must be an ISO-8601 timestamp")

    normalized_tickers = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
    for ticker in normalized_tickers:
        if not _TICKER_PATTERN.fullmatch(ticker):
            raise ValueError(f"Invalid ticker in DDD artifact scope: {ticker}")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, Any]] = []

    for ticker in normalized_tickers:
        opportunity_root = base / "idos-journal" / "companies" / ticker / "case_file" / "opportunities"
        if not opportunity_root.is_dir():
            continue
        for report_path in opportunity_root.glob("*/ddd_report.yml"):
            report = _load_mapping(report_path)
            generated_at = _parse_timestamp(report.get("generated_at"))
            if generated_at is None or generated_at < started:
                continue
            report_ticker = str(report.get("ticker", ticker)).upper()
            if report_ticker != ticker:
                continue
            opportunity_dir = report_path.parent
            opp_id = str(report.get("opp_id") or opportunity_dir.name)
            package_root = Path("companies") / ticker / "opportunities" / opp_id
            copied: list[str] = []

            candidates = [opportunity_dir / name for name in _PACKAGE_FILES]
            assessment_dir = opportunity_dir / "assessments"
            if assessment_dir.is_dir():
                for assessment_path in assessment_dir.glob("*.yml"):
                    assessment = _load_mapping(assessment_path)
                    assessed_at = _parse_timestamp(assessment.get("generated_at"))
                    if assessed_at is not None and assessed_at >= started:
                        candidates.append(assessment_path)

            for source in candidates:
                if not source.is_file():
                    continue
                relative = source.relative_to(opportunity_dir)
                destination = output / package_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied.append(destination.relative_to(output).as_posix())

            if "ddd_report.yml" not in {Path(item).name for item in copied}:
                continue
            packages.append({
                "ticker": ticker,
                "opp_id": opp_id,
                "generated_at": report.get("generated_at"),
                "files": sorted(copied),
            })

    if require_output and normalized_tickers and not packages:
        raise ValueError("No DDD package was generated for the selected ticker(s) in this workflow run")

    manifest = {
        "artifact_version": 1,
        "run_started_at": run_started_at,
        "tickers": normalized_tickers,
        "opportunities": packages,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect current-run DDD reports for a GitHub Actions artifact.")
    parser.add_argument("--base-path", type=Path, default=Path.cwd())
    parser.add_argument("--tickers", default="")
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--output-dir", default="cache/ddd-artifact")
    parser.add_argument("--require-output", action="store_true")
    args = parser.parse_args()
    tickers = [ticker.strip() for ticker in args.tickers.split(",") if ticker.strip()]
    manifest = collect_ddd_artifacts(
        args.base_path,
        tickers,
        args.started_at,
        args.output_dir,
        require_output=args.require_output,
    )
    print(
        f"[DDD-ARTIFACT] {len(manifest['opportunities'])} opportunity package(s); "
        f"{sum(len(item['files']) for item in manifest['opportunities'])} file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
