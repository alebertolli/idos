"""Multi-source analyst price target consensus.

Computes the average analyst price target from several independent sources
(yfinance, Finviz, StockAnalysis.com forecast) so the intrinsic value used by
the decision pipeline is not tied to a single provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any, Optional

from idos.timezone import AR_TZ

DEFAULT_TTL_SECONDS = 43200  # 12h, alineado con data_sources.yml
DEFAULT_MIN_SOURCES = 1


@dataclass
class TargetConsensus:
    promedio: float
    mediana: float
    fuentes: dict[str, float] = field(default_factory=dict)
    n_fuentes: int = 0
    calculado_at: str = ""
    target_low: float = 0.0
    target_high: float = 0.0


def _load_valuation_config(base_path: Any | None) -> dict[str, Any]:
    try:
        from pathlib import Path
        from idos.config import load_config
        base = Path(base_path) if base_path else Path.cwd()
        cfg = load_config(base / "idos-config" / "portfolio.yml") or {}
        return cfg.get("valuation", {}) or {}
    except Exception:
        return {}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        try:
            num = float(str(value).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            return None
    return num if num > 0 else None


def _source_yfinance(ticker: str) -> float | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return _to_float(info.get("targetMeanPrice"))
    except Exception:
        return None


def _source_finviz(ticker: str) -> float | None:
    try:
        from idos.workers.data.finviz import FinvizWorker
        result = FinvizWorker().execute({"ticker": ticker})
        if getattr(result, "status", "") == "success":
            return _to_float(result.output.get("price_target_avg"))
        return None
    except Exception:
        return None


def _source_stockanalysis(ticker: str) -> dict[str, float] | None:
    try:
        from idos.workers.data.stockanalysis import StockAnalysisWorker
        data = StockAnalysisWorker().fetch_forecast(ticker)
        if not data:
            return None
        avg = _to_float(data.get("price_target_avg"))
        if avg is None:
            return None
        out = {"price_target_avg": avg}
        for key in ("price_target_low", "price_target_median", "price_target_high"):
            val = _to_float(data.get(key))
            if val is not None:
                out[key] = val
        return out
    except Exception:
        return None


def _cache_key(ticker: str) -> str:
    return f"target_consensus:{ticker.upper()}"


def fetch_target_consensus(
    ticker: str,
    base_path: Any | None = None,
    use_cache: bool = True,
) -> Optional[TargetConsensus]:
    """Fetch and average analyst price targets from yfinance, Finviz and
    StockAnalysis.com forecast. Returns None if no source is available."""
    ticker = ticker.upper().strip()
    cfg = _load_valuation_config(base_path)
    ttl = int(cfg.get("ttl_seconds", DEFAULT_TTL_SECONDS))
    min_sources = int(cfg.get("min_sources", DEFAULT_MIN_SOURCES))

    cache = None
    if use_cache:
        try:
            from idos.data.sqlite import SQLiteStore
            from idos.workers.data.cache import DataCache
            from pathlib import Path
            base = Path(base_path) if base_path else Path.cwd()
            cache = DataCache(str(base / "idos.db"))
            cached = cache.get(_cache_key(ticker))
            if cached:
                return TargetConsensus(
                    promedio=float(cached["promedio"]),
                    mediana=float(cached["mediana"]),
                    fuentes={k: float(v) for k, v in (cached.get("fuentes") or {}).items()},
                    n_fuentes=int(cached.get("n_fuentes", 0)),
                    calculado_at=cached.get("calculado_at", ""),
                    target_low=float(cached.get("target_low", 0) or 0),
                    target_high=float(cached.get("target_high", 0) or 0),
                )
        except Exception:
            cache = None

    fuentes: dict[str, float] = {}

    try:
        yf_target = _to_float(_source_yfinance(ticker))
    except Exception:
        yf_target = None
    if yf_target is not None:
        fuentes["yfinance"] = yf_target

    try:
        fz_target = _to_float(_source_finviz(ticker))
    except Exception:
        fz_target = None
    if fz_target is not None:
        fuentes["finviz"] = fz_target

    sa = None
    try:
        sa = _source_stockanalysis(ticker) or None
    except Exception:
        sa = None
    sa_avg = _to_float(sa.get("price_target_avg")) if sa else None
    if sa_avg is not None:
        fuentes["stockanalysis"] = sa_avg

    if len(fuentes) < min_sources:
        return None

    valores = list(fuentes.values())
    consenso = TargetConsensus(
        promedio=round(sum(valores) / len(valores), 2),
        mediana=round(median(valores), 2),
        fuentes=fuentes,
        n_fuentes=len(valores),
        calculado_at=datetime.now(AR_TZ).isoformat(),
        target_low=sa.get("price_target_low", 0.0) if sa else 0.0,
        target_high=sa.get("price_target_high", 0.0) if sa else 0.0,
    )

    if cache is not None:
        try:
            cache.set(
                _cache_key(ticker),
                {
                    "promedio": consenso.promedio,
                    "mediana": consenso.mediana,
                    "fuentes": consenso.fuentes,
                    "n_fuentes": consenso.n_fuentes,
                    "calculado_at": consenso.calculado_at,
                    "target_low": consenso.target_low,
                    "target_high": consenso.target_high,
                },
                source="target_consensus",
                ttl_seconds=ttl,
            )
        except Exception:
            pass

    return consenso
