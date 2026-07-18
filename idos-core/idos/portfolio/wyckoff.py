from enum import StrEnum
from statistics import mean
from typing import Any, Optional

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry


class WyckoffPhase(StrEnum):
    ACCUMULATION = "accumulation"
    MARKUP = "markup"
    DISTRIBUTION = "distribution"
    MARKDOWN = "markdown"
    ABSORPTION = "absorption"
    UNKNOWN = "unknown"


class WyckoffAnalyzer:
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        prompt_registry: Optional[PromptRegistry] = None,
    ):
        self.llm_client = llm_client
        self.prompt_registry = prompt_registry

    def analyze(self, price_data: list[dict[str, Any]]) -> WyckoffPhase:
        if not price_data or len(price_data) < 20:
            return WyckoffPhase.UNKNOWN

        algorithmic_phase = self._analyze_algorithmic(price_data)

        if self._can_use_llm():
            try:
                llm_phase = self._analyze_llm(price_data, algorithmic_phase)
                if llm_phase != WyckoffPhase.UNKNOWN:
                    return llm_phase
            except Exception:
                pass

        return algorithmic_phase

    def _can_use_llm(self) -> bool:
        return self.llm_client is not None and self.prompt_registry is not None

    def _analyze_llm(
        self,
        price_data: list[dict[str, Any]],
        algorithmic_phase: WyckoffPhase,
    ) -> WyckoffPhase:
        indicators = self._compute_indicators(price_data, algorithmic_phase)

        prompt_text = self.prompt_registry.get(
            "wyckoff",
            category="portfolio",
            **indicators,
        )
        system_prompt = self.prompt_registry.get_system(
            "wyckoff", category="portfolio"
        )
        if not prompt_text or not system_prompt:
            return WyckoffPhase.UNKNOWN

        result = self.llm_client.generate_structured(
            prompt=prompt_text,
            system_prompt=system_prompt,
            temperature=0.1,
        )

        return self._parse_phase(result)

    def is_entry_confirmed(self, phase: WyckoffPhase) -> bool:
        return phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.ABSORPTION)

    def _compute_indicators(
        self,
        price_data: list[dict[str, Any]],
        algorithmic_phase: WyckoffPhase,
    ) -> dict[str, Any]:
        closes = [p.get("close", 0) for p in price_data if p.get("close") is not None]
        volumes = [p.get("volume", 0) for p in price_data if p.get("volume") is not None]

        if not closes:
            return {"algorithmic_phase": algorithmic_phase.value}

        current_price = closes[-1]
        high_52w = max(closes)
        low_52w = min(closes)

        def sma(data: list[float], period: int) -> Optional[float]:
            if len(data) < period:
                return None
            return mean(data[-period:])

        ma_50d = sma(closes, min(50, len(closes)))
        ma_200d = sma(closes, min(200, len(closes)))

        recent = closes[-min(60, len(closes)):]
        recent_volumes = volumes[-min(60, len(volumes)):]

        recent_trend = self._describe_trend(recent)
        bar_spread_desc = self._describe_bar_spreads(recent)
        vol_desc = self._describe_volume(volumes, recent_volumes)
        support = self._find_support_levels(closes)
        resistance = self._find_resistance_levels(closes)

        result: dict[str, Any] = {
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
            "recent_trend": recent_trend,
            "bar_spread_description": bar_spread_desc,
            "volume_description": vol_desc,
            "support_levels": support,
            "resistance_levels": resistance,
            "algorithmic_phase": algorithmic_phase.value,
        }
        return result

    def _describe_trend(self, prices: list[float]) -> str:
        if len(prices) < 5:
            return "datos insuficientes"

        recent_5 = prices[-5:]
        recent_20 = prices[-min(20, len(prices)):]
        recent_60 = prices[-min(60, len(prices)):]

        change_5 = (recent_5[-1] - recent_5[0]) / recent_5[0] * 100
        change_20 = (recent_20[-1] - recent_20[0]) / recent_20[0] * 100
        change_60 = (recent_60[-1] - recent_60[0]) / recent_60[0] * 100

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

        ranges = [abs(prices[i] - prices[i - 1]) / prices[i - 1] * 100 for i in range(1, len(prices))]
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

    def _parse_phase(self, llm_result: Any) -> WyckoffPhase:
        phase_map: dict[str, WyckoffPhase] = {
            "acumulacion": WyckoffPhase.ACCUMULATION,
            "markup": WyckoffPhase.MARKUP,
            "distribucion": WyckoffPhase.DISTRIBUTION,
            "markdown": WyckoffPhase.MARKDOWN,
            "absorcion": WyckoffPhase.ABSORPTION,
            "desconocida": WyckoffPhase.UNKNOWN,
        }

        if isinstance(llm_result, dict):
            raw = (llm_result.get("fase_wyckoff") or "").lower().strip()
            for key, phase in phase_map.items():
                if key in raw:
                    return phase

        if hasattr(llm_result, "fase_wyckoff"):
            raw = (getattr(llm_result, "fase_wyckoff") or "").lower().strip()
            for key, phase in phase_map.items():
                if key in raw:
                    return phase

        return WyckoffPhase.UNKNOWN

    def _analyze_algorithmic(self, price_data: list[dict[str, Any]]) -> WyckoffPhase:
        closes = [p.get("close", 0) for p in price_data]
        volumes = [p.get("volume", 0) for p in price_data]

        n = len(closes)
        third = n // 3

        early = closes[:third]
        mid = closes[third:2*third]
        late = closes[2*third:]

        avg_early = sum(early) / len(early)
        avg_mid = sum(mid) / len(mid)
        avg_late = sum(late) / len(late)

        early_vol = sum(volumes[:third]) / len(early)
        mid_vol = sum(volumes[third:2*third]) / len(mid)
        late_vol = sum(volumes[2*third:]) / len(late)

        late_trend = (late[-1] - late[0]) / late[0] * 100 if late[0] else 0

        if avg_late > avg_mid * 1.1 and avg_late > avg_early * 1.05:
            if late_vol > mid_vol * 1.3 and late_vol > early_vol * 1.3:
                return WyckoffPhase.DISTRIBUTION
            return WyckoffPhase.MARKUP

        if avg_late < avg_mid * 0.9 and avg_late < avg_early * 0.9:
            if late_trend > -10 and late_vol < mid_vol * 0.7 and mid_vol:
                return WyckoffPhase.ACCUMULATION
            return WyckoffPhase.MARKDOWN

        if avg_late < avg_early * 0.9 and -5 <= late_trend <= 5:
            if late_vol < mid_vol * 0.7 and mid_vol:
                return WyckoffPhase.ACCUMULATION

        if -5 <= late_trend <= 5 and late_vol < mid_vol * 0.6:
            return WyckoffPhase.ABSORPTION

        return WyckoffPhase.UNKNOWN
