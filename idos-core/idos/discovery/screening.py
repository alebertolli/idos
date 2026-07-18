import yaml
from pathlib import Path
from typing import Any


class FinvizScreener:
    def __init__(self, screeners_dir: str = "idos-config/screeners"):
        self.path = Path(screeners_dir)
        self._screeners: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        for f in sorted(self.path.glob("*.yml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if data and "rules" in data:
                self._screeners[f.stem] = data

    def list_screeners(self) -> list[dict]:
        return [
            {
                "name": k,
                "description": v.get("description", ""),
                "expected_pass_rate": v.get("expected_pass_rate", 0),
                "rule_count": len(v.get("rules", [])),
            }
            for k, v in self._screeners.items()
        ]

    def run(self, financial_data: dict, screener_name: str) -> bool:
        screener = self._screeners.get(screener_name)
        if not screener:
            return False
        return self._evaluate(screener, financial_data)

    def run_all(self, financial_data: dict) -> dict[str, bool]:
        return {
            name: self._evaluate(s, financial_data)
            for name, s in self._screeners.items()
        }

    def passes_any(self, financial_data: dict) -> dict[str, bool]:
        results = self.run_all(financial_data)
        results["_passes_any"] = any(results.values())
        return results

    def passes_all(self, financial_data: dict) -> dict[str, bool]:
        results = self.run_all(financial_data)
        results["_passes_all"] = all(results.values())
        return results

    def _get_field(self, data: dict, field: str) -> float | None:
        raw = data.get(field)
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw.replace(",", "").replace("$", "").replace("%", ""))
            except (ValueError, TypeError):
                pass
        return None

    def _evaluate(self, screener: dict, data: dict) -> bool:
        mode = screener.get("mode", "all")
        rules = screener.get("rules", [])
        if not rules:
            return False

        results = []
        for rule in rules:
            field = rule["field"]
            operator = rule["operator"]
            threshold = rule["value"]
            actual = self._get_field(data, field)

            if actual is None:
                results.append(False)
                continue

            if operator == "lt":
                results.append(actual < threshold)
            elif operator == "gt":
                results.append(actual > threshold)
            elif operator == "lte":
                results.append(actual <= threshold)
            elif operator == "gte":
                results.append(actual >= threshold)
            elif operator == "eq":
                results.append(abs(actual - threshold) < 0.001)
            else:
                results.append(False)

        if mode == "all":
            return all(results)
        elif mode == "any":
            return any(results)
        return all(results)