from dataclasses import dataclass, field
from enum import StrEnum
from statistics import mean, pstdev
from typing import Any

DEFAULT_BANDS = {"demand": 65, "absorption": 45, "supply": 25}
DEFAULT_WEIGHTS = {
    "structure": 0.40,
    "supply_demand": 0.30,
    "relative_strength": 0.20,
    "volatility": 0.10,
}


class WyckoffPhase(StrEnum):
    ACCUMULATION = "accumulation"
    MARKUP = "markup"
    DISTRIBUTION = "distribution"
    MARKDOWN = "markdown"
    ABSORPTION = "absorption"
    UNKNOWN = "unknown"


@dataclass
class WyckoffResult:
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    raw_llm_response: dict | None = None
    indicators: dict[str, Any] = field(default_factory=dict)
    score: int = 0
    prompt_version: str = "algorithmic-v1"
    entry_point: str = ""
    confidence_label: str = ""
    wyckoff_stop_loss: float | None = None
    wyckoff_price_target: float | None = None
    entry_point_price: float | None = None
    llm_error: str = ""


class WyckoffAnalyzer:
    """Composite supply/demand indicator. 100% algorithmic, 0 LLM (SDD-9 §5.1).

    Score 0-100 composed of:
      - Estructura (40%): fin de minimos decrecientes, maximos crecientes,
        ruptura de base relevante, precio vs MA50/200.
      - Oferta/Demanda (30%): volumen en dias alcistas vs bajistas, climax,
        sequia de volumen en retrocesos.
      - Fuerza Relativa (20%): retorno del ticker vs benchmark (SPY) en 1-3 meses.
      - Volatilidad (10%): contraccion de rango (ATR reciente vs historico).

    Bands (configurables): >= demand -> ACCUMULATION, [absorption, demand) ->
    ABSORPTION, [supply, absorption) -> MARKDOWN, < supply -> DISTRIBUTION.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        bands: dict[str, int] | None = None,
    ):
        self.weights = weights or DEFAULT_WEIGHTS
        self.bands = bands or DEFAULT_BANDS

    def analyze(
        self,
        price_data: list[dict[str, Any]],
        benchmark_data: list[dict[str, Any]] | None = None,
    ) -> WyckoffResult:
        if not price_data or len(price_data) < 20:
            return WyckoffResult(phase=WyckoffPhase.UNKNOWN)

        component_scores = self._compute_components(price_data, benchmark_data)
        score = self._composite_score(component_scores)
        phase = self._classify(score)

        indicators = self._compute_indicators(price_data, phase, component_scores)
        confidence = self._confidence(score)

        return WyckoffResult(
            phase=phase,
            raw_llm_response=None,
            indicators=indicators,
            score=score,
            prompt_version="algorithmic-v1",
            entry_point="",
            confidence_label=confidence,
            wyckoff_stop_loss=None,
            wyckoff_price_target=None,
            entry_point_price=None,
            llm_error="",
        )

    def is_entry_confirmed(self, phase: WyckoffPhase) -> bool:
        return phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.ABSORPTION)

    # ------------------------------------------------------------------ #
    # Component scoring
    # ------------------------------------------------------------------ #

    def _compute_components(
        self,
        price_data: list[dict[str, Any]],
        benchmark_data: list[dict[str, Any]] | None,
    ) -> dict[str, float]:
        closes = [p.get("close", 0) for p in price_data if p.get("close") is not None]
        volumes = [p.get("volume", 0) for p in price_data if p.get("volume") is not None]
        if not closes:
            return {"structure": 0, "supply_demand": 0, "relative_strength": 0, "volatility": 0}

        return {
            "structure": self._score_structure(closes),
            "supply_demand": self._score_supply_demand(closes, volumes),
            "relative_strength": self._score_relative_strength(closes, benchmark_data),
            "volatility": self._score_volatility(closes),
        }

    def _composite_score(self, components: dict[str, float]) -> int:
        score = 0.0
        for key, weight in self.weights.items():
            score += components.get(key, 0) * weight
        return int(round(min(max(score, 0), 100)))

    def _classify(self, score: int) -> WyckoffPhase:
        demand = self.bands.get("demand", 65)
        absorption = self.bands.get("absorption", 45)
        supply = self.bands.get("supply", 25)
        if score >= demand:
            return WyckoffPhase.ACCUMULATION
        if score >= absorption:
            return WyckoffPhase.ABSORPTION
        if score >= supply:
            return WyckoffPhase.MARKDOWN
        return WyckoffPhase.DISTRIBUTION

    def _confidence(self, score: int) -> str:
        if score >= self.bands.get("demand", 65):
            return "alta"
        if score >= self.bands.get("absorption", 45):
            return "media"
        return "baja"

    def _score_structure(self, closes: list[float]) -> float:
        """Estructura (0-100)."""
        if len(closes) < 20:
            return 0.0
        n = len(closes)
        current = closes[-1]
        ma50 = self._sma(closes, min(50, n))
        ma200 = self._sma(closes, min(200, n))

        score = 0.0

        # Price vs MA50/MA200
        if ma50:
            score += 20 if current >= ma50 else -5
        if ma200:
            score += 20 if current >= ma200 else -10

        # Fin de minimos decrecientes: ultimos 3 minimos crecientes
        window = closes[-min(60, n):]
        lows = self._rolling_lows(window, 10)
        if len(lows) >= 3:
            if lows[-1] >= lows[-2] >= lows[-3] and lows[-2] > lows[-3]:
                score += 20
            elif lows[-1] < lows[-2] < lows[-3]:
                score -= 20

        # Maximos crecientes / ruptura de base
        highs = self._rolling_highs(window, 10)
        if len(highs) >= 3:
            if highs[-1] >= highs[-2] >= highs[-3]:
                score += 15
            elif highs[-1] < highs[-2] < highs[-3]:
                score -= 10

        # Porcentaje sobre rango de 6 meses (ruptura de base relevante)
        range_low = min(closes[-min(126, n):])
        range_high = max(closes[-min(126, n):])
        if range_high > range_low:
            pos = (current - range_low) / (range_high - range_low) * 100
            if pos > 80:
                score += 15
            elif pos < 20:
                score -= 10

        return max(0.0, min(100.0, score))

    def _score_supply_demand(self, closes: list[float], volumes: list[float]) -> float:
        """Oferta/Demanda (0-100)."""
        if len(closes) < 20 or not volumes:
            return 0.0
        n = len(closes)
        recent = 60

        up_vol = 0.0
        down_vol = 0.0
        for i in range(max(1, n - recent), n):
            v = volumes[i] if i < len(volumes) else 0
            if closes[i] > closes[i - 1]:
                up_vol += v
            elif closes[i] < closes[i - 1]:
                down_vol += v

        score = 50.0
        if up_vol + down_vol > 0:
            ratio = up_vol / (up_vol + down_vol)
            # ratio ~0.5 = neutral, >0.6 = demand dominant
            score += (ratio - 0.5) * 160

        # Volumen climax: dia de mayor volumen reciente.
        # Si cierra al alza = demanda; al cierre del lado bajo = oferta.
        window = min(recent, n)
        vol_slice = volumes[-window:] if len(volumes) >= window else volumes
        close_slice = closes[-window:] if len(closes) >= window else closes
        if vol_slice:
            max_vol_idx = vol_slice.index(max(vol_slice))
            if max_vol_idx > 0 and max_vol_idx < len(close_slice):
                if close_slice[max_vol_idx] > close_slice[max_vol_idx - 1]:
                    score += 10
                else:
                    score -= 10

        # Sequia de volumen en retrocesos: volumen bajo en dias bajistas
        down_vols = [
            volumes[i] for i in range(max(1, n - recent), n)
            if i < len(volumes) and closes[i] < closes[i - 1] and volumes[i] > 0
        ]
        if down_vols and len(down_vols) >= 5:
            avg_down = mean(down_vols)
            avg_all = mean(volumes[-recent:]) if volumes[-recent:] else 1
            if avg_all > 0 and avg_down < avg_all * 0.6:
                score += 10

        return max(0.0, min(100.0, score))

    def _score_relative_strength(
        self,
        closes: list[float],
        benchmark_data: list[dict[str, Any]] | None,
    ) -> float:
        """Fuerza Relativa vs SPY (0-100). Neutral 50 si no hay benchmark."""
        if not benchmark_data:
            return 0.0
        bench_closes = [p.get("close", 0) for p in benchmark_data if p.get("close") is not None]
        if len(bench_closes) < 20:
            return 0.0

        def ret(data: list[float], days: int) -> float:
            if len(data) <= days:
                return 0.0
            base = data[-days - 1]
            return (data[-1] - base) / base * 100 if base else 0.0

        # Promedio ponderado de retornos 3m/1m (Weinstein)
        ticker_ret = 0.6 * ret(closes, 63) + 0.4 * ret(closes, 21)
        bench_ret = 0.6 * ret(bench_closes, 63) + 0.4 * ret(bench_closes, 21)
        rs = ticker_ret - bench_ret

        # rs ~ -5% = 0, 0 = 50, +5% = 100
        score = 50 + rs * 10
        return max(0.0, min(100.0, score))

    def _score_volatility(self, closes: list[float]) -> float:
        """Volatilidad (0-100). Contraccion de rango = condicion constructiva."""
        if len(closes) < 40:
            return 50.0
        n = len(closes)
        recent = closes[-min(20, n):]
        hist = closes[-min(120, n):]

        def avg_range(data: list[float]) -> float:
            if len(data) < 2:
                return 0.0
            diffs = [abs(data[i] - data[i - 1]) / data[i - 1] * 100 for i in range(1, len(data))]
            return mean(diffs) if diffs else 0.0

        recent_range = avg_range(recent)
        hist_range = avg_range(hist)
        if hist_range <= 0:
            return 50.0
        ratio = recent_range / hist_range
        if ratio < 0.7:
            return 85.0
        if ratio < 1.0:
            return 65.0
        if ratio > 1.4:
            return 30.0
        return 50.0

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _sma(self, data: list[float], period: int):
        if len(data) < period:
            return None
        return mean(data[-period:])

    def _rolling_lows(self, data: list[float], window: int) -> list[float]:
        if len(data) < window * 3:
            return []
        lows = []
        step = window
        for start in range(0, len(data) - window, step):
            lows.append(min(data[start:start + window]))
        return lows

    def _rolling_highs(self, data: list[float], window: int) -> list[float]:
        if len(data) < window * 3:
            return []
        highs = []
        step = window
        for start in range(0, len(data) - window, step):
            highs.append(max(data[start:start + window]))
        return highs

    # ------------------------------------------------------------------ #
    # Indicators (output) — keeps existing downstream fields
    # ------------------------------------------------------------------ #

    def _compute_indicators(
        self,
        price_data: list[dict[str, Any]],
        phase: WyckoffPhase,
        components: dict[str, float],
    ) -> dict[str, Any]:
        closes = [p.get("close", 0) for p in price_data if p.get("close") is not None]
        volumes = [p.get("volume", 0) for p in price_data if p.get("volume") is not None]

        if not closes:
            return {"algorithmic_phase": phase.value}

        current_price = closes[-1]
        high_52w = max(closes)
        low_52w = min(closes)

        ma_50d = self._sma(closes, min(50, len(closes)))
        ma_200d = self._sma(closes, min(200, len(closes)))

        recent = closes[-min(60, len(closes)):]
        recent_volumes = volumes[-min(60, len(volumes)):]

        return {
            "ticker": "",
            "current_price": round(current_price, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "ma_50d": round(ma_50d, 2) if ma_50d else 0,
            "ma_200d": round(ma_200d, 2) if ma_200d else 0,
            "pct_from_ma50": round((current_price / ma_50d - 1) * 100, 1) if ma_50d else 0,
            "pct_from_ma200": round((current_price / ma_200d - 1) * 100, 1) if ma_200d else 0,
            "pct_from_52w_high": round((current_price / high_52w - 1) * 100, 1),
            "pct_from_52w_low": round((current_price / low_52w - 1) * 100, 1),
            "recent_trend": self._describe_trend(recent),
            "bar_spread_description": self._describe_bar_spreads(recent),
            "volume_description": self._describe_volume(volumes, recent_volumes),
            "support_levels": self._find_support_levels(closes),
            "resistance_levels": self._find_resistance_levels(closes),
            "algorithmic_phase": phase.value,
            "composite_score": int(self._composite_score(components)),
            "component_scores": {k: round(v, 1) for k, v in components.items()},
        }

    def _describe_trend(self, prices: list[float]) -> str:
        if len(prices) < 5:
            return "datos insuficientes"

        recent_5 = prices[-5:]
        recent_20 = prices[-min(20, len(prices)):]
        recent_60 = prices[-min(60, len(prices)):]

        change_5 = (recent_5[-1] - recent_5[0]) / recent_5[0] * 100 if recent_5[0] else 0
        change_20 = (recent_20[-1] - recent_20[0]) / recent_20[0] * 100 if recent_20[0] else 0
        change_60 = (recent_60[-1] - recent_60[0]) / recent_60[0] * 100 if recent_60[0] else 0

        parts = []
        if change_60 > 15:
            parts.append(f"tendencia de 60d alcista fuerte ({change_60:+.0f}%)")
        elif change_60 > 5:
            parts.append(f"tendencia de 60d alcista moderada ({change_60:+.0f}%)")
        elif change_60 < -15:
            parts.append(f"tendencia de 60d bajista fuerte ({change_60:+.0f}%)")
        elif change_60 < -5:
            parts.append(f"tendencia de 60d bajista moderada ({change_60:+.0f}%)")
        else:
            parts.append(f"tendencia de 60d lateral ({change_60:+.0f}%)")

        if change_5 > 5:
            parts.append(f"aceleración alcista en últimos 5d ({change_5:+.0f}%)")
        elif change_5 < -5:
            parts.append(f"aceleración bajista en últimos 5d ({change_5:+.0f}%)")
        else:
            parts.append(f"últimos 5d estables ({change_5:+.0f}%)")

        return ". ".join(parts)

    def _describe_bar_spreads(self, prices: list[float]) -> str:
        if len(prices) < 10:
            return "datos insuficientes"
        ranges = [abs(prices[i] - prices[i - 1]) / prices[i - 1] * 100 for i in range(1, len(prices)) if prices[i - 1]]
        avg = mean(ranges)
        recent_avg = mean(ranges[-10:])
        if recent_avg > avg * 1.5:
            return f"spreads recientes ampliándose (promedio diario: {recent_avg:.1f}%, histórico: {avg:.1f}%)"
        if recent_avg < avg * 0.5:
            return f"spreads recientes estrechándose (promedio diario: {recent_avg:.1f}%, histórico: {avg:.1f}%)"
        return f"spreads estables (promedio diario reciente: {recent_avg:.1f}%)"

    def _describe_volume(self, all_volumes: list[float], recent_volumes: list[float]) -> str:
        if not all_volumes or not recent_volumes:
            return "datos insuficientes"
        avg_all = mean(all_volumes)
        avg_recent = mean(recent_volumes)
        if avg_all == 0:
            return "volumen no disponible"
        ratio = avg_recent / avg_all
        if ratio > 1.3:
            return f"volumen reciente superior al histórico ({ratio:.1f}x el promedio)"
        if ratio < 0.7:
            return f"volumen reciente inferior al histórico ({ratio:.1f}x el promedio)"
        return f"volumen reciente en línea con histórico ({ratio:.1f}x el promedio)"

    def _find_support_levels(self, prices: list[float]) -> str:
        if len(prices) < 20:
            return "no disponible"
        lows = sorted(prices)[:5]
        levels = [f"${lvl:.2f}" for lvl in lows]
        return f"soportes identificados: {', '.join(levels)} (basado en mínimos históricos)"

    def _find_resistance_levels(self, prices: list[float]) -> str:
        if len(prices) < 20:
            return "no disponible"
        highs = sorted(prices, reverse=True)[:5]
        levels = [f"${lvl:.2f}" for lvl in highs]
        return f"resistencias identificadas: {', '.join(levels)} (basado en máximos históricos)"
