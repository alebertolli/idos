"""One real request through the configured adapter; synthetic data only."""
import argparse
import json
from pathlib import Path

from idos.ai.service import LLMService


def run_smoke() -> dict:
    client = LLMService().clients["openai"]
    response = client.generate(
        'Synthetic company: revenue=100, operating_profit=20. No BEAR/BULL targets supplied. '
        'Return JSON only: operating_margin_pct (number), valuation_status '
        '("INSUFFICIENT_DATA" if targets absent), trade_authorized (false). Do not invent data.',
        system_prompt="Validate supplied evidence. This is a synthetic integration test. Return compact JSON.",
        max_tokens=512, response_format="json",
    )
    expected = {"operating_margin_pct": 20, "valuation_status": "INSUFFICIENT_DATA", "trade_authorized": False}
    try:
        passed = response.success and json.loads(response.content) == expected
    except (TypeError, ValueError):
        passed = False
    return {
        "passed": bool(passed), "requested_model": client.model,
        "response_model": response.model, "tokens_in": response.tokens_in,
        "tokens_out_including_reasoning": response.tokens_out,
        "reasoning_tokens": response.tokens_reasoning, "latency_ms": response.latency_ms,
        "max_completion_tokens": 512, "reasoning_effort": client.openai_reasoning_effort,
        "error": response.error, "synthetic_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run_smoke()
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
