from typing import Any, Optional


class DataValidator:
    def __init__(self, tolerance_pct: float = 20.0):
        self.tolerance_pct = tolerance_pct

    def cross_validate(self, sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []

        all_keys: set[str] = set()
        for data in sources.values():
            all_keys.update(data.keys())

        for key in sorted(all_keys):
            values = {}
            for source_name, data in sources.items():
                if key in data and data[key] is not None:
                    values[source_name] = data[key]

            if len(values) == 0:
                continue

            if len(values) == 1:
                merged[key] = list(values.values())[0]
                continue

            numeric_values = {
                k: v for k, v in values.items() if isinstance(v, (int, float))
            }

            if len(numeric_values) < 2:
                merged[key] = self._pick_best(values)
                continue

            vals = list(numeric_values.values())
            avg = sum(vals) / len(vals)

            for src, val in numeric_values.items():
                if avg != 0:
                    deviation = abs(val - avg) / abs(avg) * 100
                    if deviation > self.tolerance_pct:
                        conflicts.append({
                            "field": key,
                            "sources": {src: val},
                            "avg": avg,
                            "deviation_pct": round(deviation, 1),
                        })

            merged[key] = round(avg, 2) if isinstance(avg, float) else avg

        return {
            "merged_data": merged,
            "conflicts": conflicts,
            "source_count": len(sources),
            "sources_used": list(sources.keys()),
        }

    def _pick_best(self, values: dict[str, Any]) -> Any:
        priorities = ["stockanalysis.com", "yfinance", "finviz.com", "sec_edgar"]
        for source in priorities:
            if source in values:
                return values[source]
        return list(values.values())[0]

    def validate_metrics(self, data: dict[str, Any]) -> list[str]:
        warnings = []
        if data.get("debt_equity_ratio") and isinstance(data["debt_equity_ratio"], (int, float)):
            if data["debt_equity_ratio"] > 5:
                warnings.append(f"D/E alto ({data['debt_equity_ratio']:.1f})")
        if data.get("current_ratio") and isinstance(data["current_ratio"], (int, float)):
            if data["current_ratio"] < 0.5:
                warnings.append(f"Current ratio bajo ({data['current_ratio']:.1f})")
        if data.get("operating_margin_pct") and isinstance(data["operating_margin_pct"], (int, float)):
            if data["operating_margin_pct"] < -20:
                warnings.append(f"Margen operativo negativo severo ({data['operating_margin_pct']:.1f}%)")
        return warnings
