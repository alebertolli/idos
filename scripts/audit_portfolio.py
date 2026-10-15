"""Audit an explicitly supplied portfolio snapshot without publishing it."""

import argparse
import json
from pathlib import Path

from idos.portfolio.audit import PortfolioAuditError, audit_portfolio
from idos.portfolio.sheets_snapshot import snapshot_from_sheets_values


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a private portfolio snapshot")
    parser.add_argument("snapshot", type=Path,
                        help="Private JSON snapshot or {\"sheets\": {tab: rows}} export")
    parser.add_argument("--output", type=Path, help="Optional private JSON report path")
    args = parser.parse_args()
    try:
        snapshot_input = json.loads(args.snapshot.read_text(encoding="utf-8"))
        snapshot = (snapshot_from_sheets_values(snapshot_input["sheets"])
                    if isinstance(snapshot_input, dict) and "sheets" in snapshot_input
                    else snapshot_input)
        report = audit_portfolio(snapshot)
    except (OSError, json.JSONDecodeError, PortfolioAuditError) as exc:
        parser.error(str(exc))
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
