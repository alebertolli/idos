from typing import Any, Optional


class DataValidator:
    def __init__(self, tolerance_pct: float = 20.0):
        self.tolerance_pct = tolerance_pct

    def cross_validate(self, sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        non_comparable: list[dict[str, Any]] = []
        field_sources: dict[str, list[str]] = {}

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

            # Keep provenance per field. A global source_count is not enough to
            # establish coverage for a critical metric when providers have
            # different schemas or return partial responses.
            field_sources[key] = list(values)

            if len(values) == 1:
                merged[key] = list(values.values())[0]
                continue

            numeric_values = {
                k: v for k, v in values.items() if isinstance(v, (int, float))
            }

            if len(numeric_values) < 2:
                merged[key] = self._pick_best(values)
                continue

            comparability = self._financial_metric_comparability(
                key, numeric_values, sources
            )
            if comparability is not None:
                comparable_sources, reason, metadata = comparability
                if len(comparable_sources) < 2:
                    non_comparable.append({
                        "field": key,
                        "reason": reason,
                        "sources": metadata,
                        "selected_source": self._pick_best_source(numeric_values),
                        "comparable_sources": sorted(comparable_sources),
                        "excluded_sources": sorted(set(numeric_values) - comparable_sources),
                    })
                    merged[key] = self._pick_best(numeric_values)
                    continue
                if comparable_sources != set(numeric_values):
                    non_comparable.append({
                        "field": key,
                        "reason": reason,
                        "sources": metadata,
                        "comparable_sources": sorted(comparable_sources),
                        "excluded_sources": sorted(set(numeric_values) - comparable_sources),
                    })
                numeric_values = {
                    source: value for source, value in numeric_values.items()
                    if source in comparable_sources
                }

            vals = list(numeric_values.values())
            avg = sum(vals) / len(vals)
            spread = max(vals) - min(vals)
            deviation = spread / abs(avg) * 100 if avg != 0 else None
            if (deviation is None and spread > 0) or (
                deviation is not None and deviation > self.tolerance_pct
            ):
                conflicts.append({
                    "field": key,
                    "sources": numeric_values,
                    "avg": avg,
                    "deviation_pct": round(deviation, 1) if deviation is not None else None,
                })

            merged[key] = round(avg, 2) if isinstance(avg, float) else avg

        return {
            "merged_data": merged,
            "conflicts": conflicts,
            "source_count": len(sources),
            "sources_used": list(sources.keys()),
            "field_sources": field_sources,
            "non_comparable": non_comparable,
        }

    @staticmethod
    def _financial_metric_comparability(
        field: str,
        values: dict[str, Any],
        sources: dict[str, dict[str, Any]],
    ) -> tuple[set[str], str, dict[str, Any]] | None:
        """Compare provider values only when their declared bases and cutoffs match.

        Metrics without provider metadata retain the legacy numeric comparison.
        Once any source declares metadata, missing or incompatible metadata is
        reported and excluded from the comparison rather than treated as a conflict.
        """
        metadata_by_source = {}
        for source_name in values:
            source_metadata = sources[source_name].get("financial_metric_metadata")
            source_metadata = source_metadata if isinstance(source_metadata, dict) else {}
            metric_metadata = source_metadata.get(field)
            if isinstance(metric_metadata, dict):
                metadata_by_source[source_name] = metric_metadata

        if not metadata_by_source:
            return None

        signatures = {}
        for source_name in values:
            item = metadata_by_source.get(source_name)
            if not item:
                continue
            period = item.get("period_type")
            unit = item.get("unit")
            period_end = item.get("period_end_date")
            currency = item.get("currency")
            if (
                isinstance(period, str)
                and period.strip().upper() not in {"", "UNSPECIFIED", "PROVIDER_REPORTED_UNSPECIFIED"}
                and unit
                and period_end
            ):
                signatures[source_name] = (period, unit, currency, period_end)

        groups: dict[tuple[Any, ...], set[str]] = {}
        for source_name, signature in signatures.items():
            groups.setdefault(signature, set()).add(source_name)
        comparable_sources = max(groups.values(), key=len, default=set())
        if len(comparable_sources) == len(values):
            return None

        reasons = []
        if len(signatures) != len(values):
            reasons.append("missing_period_unit_or_cutoff")
        if len(groups) > 1:
            reasons.append("different_period_unit_currency_or_cutoff")
        details = {
            source: metadata_by_source.get(source, {"status": "metadata_missing"})
            for source in values
        }
        return comparable_sources, ";".join(reasons) or "insufficient_comparable_sources", details

    @staticmethod
    def _pick_best_source(values: dict[str, Any]) -> str:
        priorities = ["stockanalysis.com", "yfinance", "finviz.com", "sec_edgar"]
        return next((source for source in priorities if source in values), next(iter(values)))

    def _pick_best(self, values: dict[str, Any]) -> Any:
        return values[self._pick_best_source(values)]

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
