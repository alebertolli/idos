from typing import Any


class DiversificationController:
    def __init__(self, max_sector_pct: float = 25.0, max_single_position: float = 3.0,
                 max_thematic_correlation: float = 30.0, max_positions: int = 20,
                 max_pair_correlation: float = 0.75, max_correlated_weight: float = 10.0):
        self.max_sector = max_sector_pct
        self.max_position = max_single_position
        self.max_thematic = max_thematic_correlation
        self.max_positions = max_positions
        self.max_pair_correlation = max_pair_correlation
        self.max_correlated_weight = max_correlated_weight
        self._themes: dict[str, float] = {}
        self._correlation_matrix: dict[str, dict[str, float]] = {}
        self._ticker_weights: dict[str, float] = {}

    def check_sector(self, sector: str, current_exposure: float,
                     new_weight: float) -> dict[str, Any]:
        total = current_exposure + new_weight
        return {
            "passed": total <= self.max_sector,
            "current": current_exposure,
            "proposed": new_weight,
            "total": round(total, 1),
            "limit": self.max_sector,
        }

    def check_position(self, current_weight: float, new_weight: float) -> dict[str, Any]:
        total = current_weight + new_weight
        return {
            "passed": total <= self.max_position,
            "current": current_weight,
            "proposed": new_weight,
            "total": round(total, 1),
            "limit": self.max_position,
        }

    def check_thematic(self, themes: list[str], current_correlations: dict[str, float],
                       new_weight: float) -> dict[str, Any]:
        for theme in themes:
            correlated = current_correlations.get(theme, 0) + new_weight
            if correlated > self.max_thematic:
                return {"passed": False, "theme": theme, "total": round(correlated, 1), "limit": self.max_thematic}
        return {"passed": True}

    def check_count(self, current_count: int) -> dict[str, Any]:
        return {"passed": current_count < self.max_positions, "current": current_count, "limit": self.max_positions}

    def register_theme_exposure(self, theme: str, weight: float):
        self._themes[theme] = self._themes.get(theme, 0) + weight

    def get_theme_exposures(self) -> dict[str, float]:
        return dict(self._themes)

    def set_correlation(self, ticker_a: str, ticker_b: str, correlation: float):
        a, b = ticker_a.upper(), ticker_b.upper()
        if a not in self._correlation_matrix:
            self._correlation_matrix[a] = {}
        if b not in self._correlation_matrix:
            self._correlation_matrix[b] = {}
        self._correlation_matrix[a][b] = correlation
        self._correlation_matrix[b][a] = correlation

    def set_ticker_weight(self, ticker: str, weight: float):
        self._ticker_weights[ticker.upper()] = weight

    def check_correlation(self, ticker: str, weight: float) -> dict[str, Any]:
        ticker = ticker.upper()
        violations: list[dict[str, Any]] = []
        for other, r in self._correlation_matrix.get(ticker, {}).items():
            if abs(r) > self.max_pair_correlation:
                combined = weight + self._ticker_weights.get(other, 0)
                if combined > self.max_correlated_weight:
                    violations.append({
                        "with": other,
                        "correlation": r,
                        "combined_weight": round(combined, 1),
                        "limit": self.max_correlated_weight,
                    })
        return {
            "passed": len(violations) == 0,
            "violations": violations,
        }

    def get_correlation(self, ticker_a: str, ticker_b: str) -> float:
        return self._correlation_matrix.get(ticker_a.upper(), {}).get(ticker_b.upper(), 0.0)
