from pathlib import Path
from typing import Any
import math
import json
import yaml

from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository
from idos.decision.orchestrator import DecisionOrchestrator, DecisionProposal
from idos.decision.scenarios import (
    calculate_scenario_asymmetry,
    validate_scenario_review,
)
from idos.decision.conviction import ConvictionCalculator
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine
from idos.rules.engine import RulesEngine, RuleResult
from idos.models.knowledge import Rule
from idos.models.enums import OpportunityStatus
from idos.config import load_settings
from idos.strategy.catalog import StrategyCatalog
from idos.strategy.signals import SignalEvidenceError, current_selection
from idos.timezone import AR_TZ
from datetime import date, datetime, timezone


_CORE_FINANCIAL_FIELDS = {
    "roic": ("roic_pct", "roic"),
    "operating_margin": ("operating_margin_pct", "operating_margin"),
    "revenue_growth": ("revenue_growth_pct", "revenue_growth"),
    "pe_ratio": ("pe_ratio", "pe_ratio_ttm"),
    "debt_to_equity": ("debt_equity_ratio", "debt_to_equity"),
}


def _financial_data_quality(financial: dict[str, Any]) -> dict[str, Any]:
    """Report core input coverage and provenance without treating zero as missing."""
    missing = []
    for field_name, source_keys in _CORE_FINANCIAL_FIELDS.items():
        value = next((financial.get(key) for key in source_keys if key in financial), None)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            missing.append(field_name)

    provenance = financial.get("data_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    sources = provenance.get("sources_used")
    sources = sources if isinstance(sources, list) else []
    source = financial.get("source") or (", ".join(map(str, sources)) if sources else "")
    cutoff_fields = (
        "fundamentals_as_of",
        "as_of_date",
        "period_end_date",
        "fiscal_period_end",
        "financial_period_end_timestamp",
    )
    cutoff_field = next((key for key in cutoff_fields if financial.get(key) is not None), None)
    raw_as_of_date = financial.get(cutoff_field) if cutoff_field else provenance.get("as_of_date")
    as_of_date = _valid_cutoff_date(raw_as_of_date)
    field_sources = provenance.get("field_sources")
    field_sources = field_sources if isinstance(field_sources, dict) else {}
    raw_cutoff_sources = field_sources.get(cutoff_field, []) if cutoff_field else []
    if isinstance(raw_cutoff_sources, str):
        raw_cutoff_sources = [raw_cutoff_sources]
    as_of_date_source = ", ".join(sorted({str(value) for value in raw_cutoff_sources if value})) or (source or None)
    missing_provenance = []
    if not source:
        missing_provenance.append("source")
    if not as_of_date:
        missing_provenance.append("as_of_date")

    coverage = len(_CORE_FINANCIAL_FIELDS) - len(missing)
    if coverage == len(_CORE_FINANCIAL_FIELDS) and not missing_provenance:
        status = "good"
    elif coverage >= math.ceil(len(_CORE_FINANCIAL_FIELDS) * 0.8):
        status = "partial"
    else:
        status = "poor"
    return {
        "status": status,
        "core_metric_coverage": f"{coverage}/{len(_CORE_FINANCIAL_FIELDS)}",
        "missing_core_metrics": missing,
        "source": source or None,
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "as_of_date_source": as_of_date_source if as_of_date else None,
        "missing_provenance": missing_provenance,
    }


def _valid_cutoff_date(value: Any) -> date | None:
    """Return an ISO-compatible financial cutoff date that is not in the future."""
    if isinstance(value, datetime):
        cutoff = value.date()
    elif isinstance(value, date):
        cutoff = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value) or not 946684800 <= value <= 4102444800:
            return None
        try:
            cutoff = datetime.fromtimestamp(value, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        normalized = value.strip()
        try:
            if len(normalized) == 10:
                cutoff = date.fromisoformat(normalized)
                if cutoff.isoformat() != normalized:
                    return None
            else:
                cutoff = datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    else:
        return None
    if cutoff > datetime.now(AR_TZ).date():
        return None
    return cutoff


def _remove_buylist_entry(ticker: str, opp_id: str, base_path: Path) -> bool:
    """Remove only a stale, version-specific public Buy List entry."""
    path = base_path / "idos-journal" / "portfolio" / "buylist.yml"
    if not path.exists():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
        return False
    entries = data.get("entries", [])
    filtered = [
        entry for entry in entries
        if not (
            isinstance(entry, dict)
            and str(entry.get("ticker", "")).upper() == ticker.upper()
            and entry.get("opp_id") == opp_id
        )
    ]
    if len(filtered) == len(entries):
        return False
    data["entries"] = filtered
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def build_context(
    opp_id: str, ticker: str, bp: Path, sqlite: SQLiteStore,
    knowledge: KnowledgeRepository, journal: JournalRepository,
) -> dict[str, Any]:
    financial = _load_financial_data(ticker, sqlite)
    financial_quality = _financial_data_quality(financial)
    company = knowledge.load_company(ticker) or {}

    positions = []
    pos_dir = bp / "idos-journal" / "portfolio" / "positions"
    if pos_dir.exists():
        for pf in sorted(pos_dir.iterdir()):
            if pf.suffix == ".yml":
                with open(pf, encoding="utf-8") as f:
                    d = yaml.safe_load(f) or {}
                    d["ticker"] = pf.stem
                    positions.append(d)

    metrics = {
        "roic": financial.get("roic_pct", 0),
        "revenue_growth": financial.get("revenue_growth_pct", 0),
        "operating_margin": financial.get("operating_margin_pct", 0),
        "recurring_revenue_pct": financial.get("recurring_revenue_pct", 0),
        "pe_ratio": financial.get("pe_ratio", 0),
        "pe_historical_avg": financial.get("pe_historical_avg", 0),
        "ev_ebitda": financial.get("ev_ebitda", 0),
        "sector_avg_ev_ebitda": financial.get("sector_avg_ev_ebitda", 0),
        "fcf_yield": financial.get("fcf_yield_pct", 0),
        "eps_growth": financial.get("eps_growth", 0),
        "fcf_growth": financial.get("fcf_growth", 0),
        "eps_revision_trend": financial.get("eps_revision_trend", 0),
        "short_interest_pct": financial.get("short_interest_pct", 0),
        "analyst_consensus": financial.get("analyst_consensus", 0),
        "wyckoff_phase": financial.get("wyckoff_phase", ""),
        "weinstein_stage": financial.get("weinstein_stage", ""),
        "relative_strength": financial.get("relative_strength", 0),
        "debt_to_equity": financial.get("debt_equity_ratio", 0),
        "litigation_risk": financial.get("litigation_risk", ""),
        "volatility_90d": financial.get("volatility_90d", 0),
        "current_ratio": financial.get("current_ratio", 0),
    }
    _core = {k: v for k, v in metrics.items() if k in ("roic", "operating_margin", "revenue_growth", "pe_ratio", "debt_to_equity")}
    _zero = sum(1 for v in _core.values() if isinstance(v, (int, float)) and v == 0)
    if _zero > len(_core) // 2:
        print(f"[WARN] {ticker}: {_zero}/{len(_core)} métricas CORE en 0 — evaluación será errónea")
    elif _zero > 0 and _zero <= len(_core) // 2:
        print(f"[INFO] {ticker}: {_zero}/{len(_core)} métricas core en 0 (parcial)")

    company_mgmt = company.get("management", {}) or {}
    mgmt = {
        "ceo_tenure_years": financial.get("ceo_tenure", company_mgmt.get("ceo_tenure_years", 0)),
        "insider_ownership_pct": financial.get("insider_ownership", company_mgmt.get("insider_ownership_pct", 0)),
        "capital_allocation_rating": financial.get("capital_allocation", company_mgmt.get("capital_allocation_rating", "")),
    }

    static = {
        "business_model": company.get("business_model", ""),
        "products": company.get("products", []),
        "moat_description": company.get("moat_description", ""),
        "moat_type": company.get("moat_type", ""),
        "competitive_advantages": company.get("competitive_advantages", []),
        "management": mgmt,
        "management_history": company.get("management_history", ""),
        "founder_info": company.get("founder_info", ""),
    }

    total_weight = sum(p.get("weight_pct", 0) for p in positions)
    sector_exposure = {}
    for p in positions:
        pc = knowledge.load_company(p.get("ticker", "")) or {}
        sec = pc.get("sector", "Unknown")
        sector_exposure[sec] = sector_exposure.get(sec, 0) + p.get("weight_pct", 0)

    existing = next((p for p in positions if p.get("ticker") == ticker), None)
    current_position_weight = existing.get("weight_pct", 0) if existing else 0

    portfolio = {
        "total_weight": total_weight,
        "sector_exposure": sector_exposure,
        "thematic_correlations": {},
        "num_positions": len(positions),
        "position_weight": current_position_weight,
    }

    company_info = {"sector": company.get("sector", "")}

    opp = sqlite.get_opportunity(opp_id)
    margin_of_safety = 30.0
    if opp:
        cv = opp.get("conviction", {}) or {}
        margin_of_safety = cv.get("margin_of_safety", 30.0)
    current_price = None
    quote_currency = None
    target_low = None
    target_mean = None
    target_high = None
    try:
        import yfinance as yf
        _s = yf.Ticker(ticker)
        _i = _s.info or {}
        current_price = _i.get("currentPrice") or _i.get("regularMarketPrice")
        quote_currency = _i.get("currency")
        target_mean = _i.get("targetMeanPrice")
        target_low = _i.get("targetLowPrice")
        target_high = _i.get("targetHighPrice")
        if current_price and target_mean:
            price_margin = round((target_mean - current_price) / current_price * 100, 1)
        else:
            price_margin = margin_of_safety
    except Exception:
        price_margin = margin_of_safety

    opp_dir = bp / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id
    ddd_report_path = opp_dir / "ddd_report.yml"
    thesis_active = False
    catalysts = []
    risk_events = []
    raw_catalysts = []
    report = {}
    if ddd_report_path.exists():
        try:
            report = yaml.safe_load(ddd_report_path.read_text(encoding="utf-8"))
            if report:
                if report.get("tesis_inversion"):
                    thesis_active = True
                raw_catalysts = report.get("dominio_catalizadores", [])
                _impact_map = {"alto": "high", "medio": "medium", "bajo": "low"}
                _timeline_map = {"corto": "short", "medio": "long", "largo": "long"}
                for c in raw_catalysts:
                    if isinstance(c, dict):
                        catalysts.append({
                            "impact": _impact_map.get(c.get("impacto", "").lower(), "low"),
                            "timeline": _timeline_map.get(c.get("horizonte", "").lower(), "long"),
                            "description": c.get("descripcion", ""),
                        })
                raw_risks = report.get("dominio_riesgos", [])
                for r in raw_risks:
                    if isinstance(r, dict):
                        risk_events.append({
                            "type": r.get("tipo", "regulatory"),
                            "description": r.get("descripcion", ""),
                            "resolution": r.get("resolucion", "unfavorable"),
                            "severity": r.get("severidad", "medium"),
                        })
        except Exception:
            pass

    target_consensus = report.get("target_consensus") or {}
    consensus_target = target_consensus.get("promedio", 0) or 0

    scenario_review = None
    scenario_review_path = opp_dir / "scenario_review.yml"
    if scenario_review_path.exists():
        try:
            scenario_review = yaml.safe_load(scenario_review_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            scenario_review = None
    # Catalyst-derived estimates may coexist and remain visible for context,
    # but only an approved, version-matched Bear/Base/Bull set can authorize.
    asymmetry = _calculate_report_asymmetry(
        report, raw_catalysts, current_price, target_low, target_mean, target_high,
        quote_currency, scenario_review,
    )

    return {
        "knowledge_base": {"dynamic": {"metrics": metrics}, "static": static},
        "financial_data_quality": financial_quality,
        "portfolio": portfolio,
        "company": company_info,
        "margin_of_safety": margin_of_safety,
        "price_margin": price_margin,
        "catalysts": catalysts,
        "risk_events": risk_events,
        "asymmetry": asymmetry,
        "current_price": current_price,
        "quote_currency": quote_currency,
        "intrinsic_value": consensus_target or target_mean,
        "target_consensus": target_consensus,
        "proposed_weight": 3.0,
        "themes": [],
        "opportunity_id": opp_id,
        "ticker": ticker,
        "force_relevance": True,
        "thesis_active": thesis_active,
        "strategy_id": (opp or {}).get("strategy_id", "COMPOUNDER") if opp else "COMPOUNDER",
        "research_profile": (opp or {}).get("research_profile", "") if opp else "",
        "signal": (opp or {}).get("signal", {}) if opp else {},
    }


def _coerce_numeric(data: dict[str, Any], keys: set[str]) -> None:
    for k in keys:
        v = data.get(k)
        if isinstance(v, str):
            try:
                data[k] = float(v)
            except (ValueError, TypeError):
                data[k] = 0
        elif v is None:
            data[k] = 0
        elif not isinstance(v, (int, float)):
            data[k] = 0

_NUMERIC_KEYS = {"pe_ratio", "pe_ratio_ttm", "pe_historical_avg", "peg_ratio", "peg_ratio_ttm", "ev_ebitda", "sector_avg_ev_ebitda",
    "debt_equity_ratio", "volatility_90d", "current_ratio", "relative_strength",
    "short_interest_pct", "analyst_consensus", "ceo_tenure", "insider_ownership",
    "target_price", "recurring_revenue_pct", "fcf_yield",
    "roic_pct", "roe_pct", "roa_pct", "revenue_growth_pct",
    "operating_margin_pct", "gross_margin_pct", "net_margin_pct",
    "fcf_yield_pct", "eps_growth", "fcf_growth", "revenue_growth",
    "operating_margin", "roic"}

def _normalize_decimal_pcts(data: dict[str, Any]) -> dict[str, Any]:
    _aliases = {"pe_ratio_ttm": "pe_ratio", "peg_ratio_ttm": "peg_ratio",
                "short_pct_of_float": "short_interest_pct",
                "eps_growth_this_year_pct": "eps_growth",
                "eps_growth_next_year_pct": "eps_growth",
                "eps_growth_5y_pct": "eps_growth"}
    for src, dst in _aliases.items():
        if src in data and (dst not in data or data[dst] is None):
            data[dst] = data[src]
    _consensus_map = {"strong buy": 5, "buy": 4, "hold": 3, "sell": 2, "strong sell": 1}
    ac = data.get("analyst_consensus")
    if isinstance(ac, str) and ac.lower() in _consensus_map:
        data["analyst_consensus"] = _consensus_map[ac.lower()]
    _coerce_numeric(data, _NUMERIC_KEYS)
    _pct_keys = {"roic_pct", "roe_pct", "roa_pct", "revenue_growth_pct",
                 "operating_margin_pct", "gross_margin_pct", "net_margin_pct",
                 "fcf_yield_pct", "eps_growth", "fcf_growth"}
    vals = [data[k] for k in _pct_keys if isinstance(data.get(k), (int, float))]
    is_yahoo_format = (sum(abs(v) for v in vals) / len(vals)) < 5 if vals else True
    for k in _pct_keys:
        v = data.get(k)
        if isinstance(v, (int, float)) and is_yahoo_format:
            data[k] = v * 100
    de = data.get("debt_equity_ratio")
    if isinstance(de, (int, float)):
        if de > 1:
            data["debt_equity_ratio"] = de / 100
    return data

def _enrich_roic(data: dict[str, Any]) -> dict[str, Any]:
    roic = data.get("roic_pct")
    if roic is not None and roic != 0:
        return data
    roe = data.get("roe_pct")
    de = data.get("debt_equity_ratio")
    if roe and isinstance(de, (int, float)):
        data["roic_pct"] = round(roe / (1 + de), 2)
    return data

_CRITICAL_METRICS = ["roic_pct", "operating_margin_pct", "revenue_growth_pct", "pe_ratio", "debt_equity_ratio"]

def _warn_missing_metrics(ticker: str, data: dict[str, Any], source: str = "financial") -> list[str]:
    warnings = []
    for key in _CRITICAL_METRICS:
        val = data.get(key)
        if val is None or val == 0:
            warnings.append(f"[WARN] {ticker}: {key} es 0 o None (fuente: {source})")
        elif key in ("pe_ratio", "debt_equity_ratio") and val < 0:
            warnings.append(f"[WARN] {ticker}: {key}={val} es negativo (fuente: {source})")
    if data.get("roic_pct") is None and data.get("roe_pct") is None:
        warnings.append(f"[WARN] {ticker}: No se pudo calcular ROIC (sin ROE ni D/E disponibles)")
    if not data:
        warnings.append(f"[WARN] {ticker}: No hay datos financieros de ninguna fuente")
    for w in warnings:
        print(w)
    return warnings

def _load_financial_data(ticker: str, sqlite: SQLiteStore) -> dict[str, Any]:
    try:
        row = sqlite.conn.execute(
            "SELECT data_json FROM events_log WHERE data_json LIKE ? OR correlation_id LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (f"%{ticker}%", f"%{ticker}%"),
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass
    import json
    from pathlib import Path
    for cache_path in [
        Path("cache") / f"{ticker}_financial.json",
        Path("cache") / f"{ticker}.json",
    ]:
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data:
                    if "merged_data" in data:
                        data = data["merged_data"]
                    data = _normalize_decimal_pcts(data)
                    data = _enrich_roic(data)
                    _warn_missing_metrics(ticker, data, "cache")
                    return data
            except Exception:
                pass
    try:
        from idos.workers.data.stockanalysis import StockAnalysisWorker
        sa = StockAnalysisWorker()
        result = sa.run({"ticker": ticker})
        if result:
            Path("cache").mkdir(parents=True, exist_ok=True)
            (Path("cache") / f"{ticker}.json").write_text(
                json.dumps(result, default=str, indent=2), encoding="utf-8"
            )
            result = _normalize_decimal_pcts(result)
            result = _enrich_roic(result)
            _warn_missing_metrics(ticker, result, "stockanalysis.com live")
            return result
    except Exception:
        pass
    _warn_missing_metrics(ticker, {}, "ninguna")
    return {}


def _compute_asymmetry(raw_catalysts, current_price, target_low, target_mean, target_high):
    if not raw_catalysts or not current_price:
        return None
    _horizon_years = {"corto": 0.5, "medio": 1.0, "largo": 2.0}
    _scenario_map = {"alto": "Optimista", "medio": "Base", "bajo": "Fracaso"}
    _price_map = {"Optimista": target_high, "Base": target_mean, "Fracaso": target_low}
    scenarios = {"Fracaso": [], "Base": [], "Optimista": []}
    for c in raw_catalysts:
        if not isinstance(c, dict):
            continue
        impacto = c.get("impacto", "").lower()
        scenario = _scenario_map.get(impacto)
        if not scenario:
            continue
        prob = c.get("probabilidad_pct", 0)
        if not isinstance(prob, (int, float)) or prob <= 0:
            continue
        horizon = _horizon_years.get(c.get("horizonte", "").lower(), 1.0)
        scenarios[scenario].append({"prob": prob, "horizon": horizon, "desc": c.get("descripcion", "")})
    total_prob = sum(sum(c["prob"] for c in sc_list) for sc_list in scenarios.values())
    if total_prob <= 0:
        return None
    total_normalized = 0.0
    rows = []
    for scenario in ["Fracaso", "Base", "Optimista"]:
        cat_list = scenarios[scenario]
        prob_raw = sum(c["prob"] for c in cat_list)
        prob_norm = (prob_raw / total_prob) * 100 if total_prob > 0 else 0
        total_normalized += prob_norm
        price = _price_map.get(scenario)
        if price and current_price:
            retorno = round((price / current_price - 1) * 100, 2)
        else:
            retorno = 0
        contribucion = round(prob_norm / 100 * price, 2) if price and prob_norm > 0 else 0
        horizon = round(sum(c["prob"] * c["horizon"] for c in cat_list) / prob_raw, 2) if prob_raw > 0 else 1.0
        rows.append({
            "escenario": scenario,
            "probabilidad_pct": round(prob_norm, 1),
            "precio_objetivo": price,
            "retorno_pct": retorno,
            "contribucion_ve": contribucion,
            "horizonte_years": horizon,
        })
    diff = round(100.0 - total_normalized, 1)
    if abs(diff) > 0.01 and rows:
        rows.sort(key=lambda r: r["probabilidad_pct"], reverse=True)
        rows[0]["probabilidad_pct"] = round(rows[0]["probabilidad_pct"] + diff, 1)
    valor_esperado = round(sum(r["contribucion_ve"] for r in rows), 2)
    retorno_esperado = round((valor_esperado / current_price - 1) * 100, 2) if current_price else 0
    total_pct = sum(r["probabilidad_pct"] for r in rows)
    horizon_avg = sum(r["probabilidad_pct"] * r["horizonte_years"] for r in rows) / total_pct if total_pct > 0 else 1.0
    if current_price and valor_esperado > 0:
        cagr = round((valor_esperado / current_price) ** (1 / horizon_avg) - 1, 4)
        cagr_pct = round(cagr * 100, 2)
    else:
        cagr_pct = 0
    upside = sum(r["probabilidad_pct"] * r["retorno_pct"] for r in rows if r["retorno_pct"] > 0) / 100
    downside = sum(r["probabilidad_pct"] * r["retorno_pct"] for r in rows if r["retorno_pct"] < 0) / 100
    abs_downside = abs(downside) if downside < 0 else 0
    br = round(abs(upside) / abs_downside, 2) if abs_downside > 0 else (float('inf') if upside > 0 else 0)
    return {
        "rows": rows,
        "valor_esperado": valor_esperado,
        "retorno_esperado_pct": retorno_esperado,
        "cagr_pct": cagr_pct,
        "upside_esperado_pct": round(upside, 2),
        "downside_esperado_pct": round(downside, 2),
        "benefit_risk_ratio": br,
        # Research catalysts can coexist, so their probabilities do not define
        # mutually exclusive price scenarios. Keep this estimate visible for
        # human review, but never use it to authorize an Opportunity.
        "validation_status": "provisional",
        "authorization_eligible": False,
        "validation_reason": (
            "Las probabilidades de catalizadores no son escenarios financieros "
            "mutuamente excluyentes validados."
        ),
        "passes_threshold": False,
        "horizonte_avg_years": round(horizon_avg, 2),
    }


def _calculate_report_asymmetry(
    report: Any,
    raw_catalysts: list,
    current_price: Any,
    target_low: Any,
    target_mean: Any,
    target_high: Any,
    quote_currency: str | None,
    scenario_review: Any,
) -> dict[str, Any] | None:
    """Prefer an approved explicit scenario contract; retain catalyst math only as provisional context."""
    report = report if isinstance(report, dict) else {}
    analysis = report.get("scenario_analysis")
    if analysis is None:
        return _compute_asymmetry(raw_catalysts, current_price, target_low, target_mean, target_high)
    asymmetry = calculate_scenario_asymmetry(
        analysis,
        current_price=current_price,
        quote_currency=quote_currency,
    )
    review_approved, review_reason = validate_scenario_review(analysis, scenario_review)
    asymmetry["authorization_eligible"] = review_approved and asymmetry.get("validation_status") == "validated"
    asymmetry["validation_reason"] = (
        asymmetry.get("validation_reason") if asymmetry.get("validation_status") != "validated"
        else review_reason
    )
    return asymmetry


def _eval_business(ctx):
    s = ctx.get("assessments", {}).get("business_quality", 0)
    t = ctx.get("_settings")
    limit = t.rule_min_score("RULE-001", 70) if t else 70
    return RuleResult("RULE-001", s >= limit, f"Business quality: {s}/{limit}")

def _eval_valuation(ctx):
    pm = ctx.get("price_margin", 0)
    t = ctx.get("_settings")
    limit = t.rule_price_margin("RULE-002", 20) if t else 20
    return RuleResult("RULE-002", pm > limit, f"Price target margin: {pm:.1f}% (min {limit})")

def _eval_recovery(ctx):
    s = ctx.get("assessments", {}).get("rerating", 0)
    t = ctx.get("_settings")
    limit = t.rule_min_score("RULE-003", 50) if t else 50
    return RuleResult("RULE-003", s >= limit, f"Rerating: {s}/{limit}")

def _eval_risk(ctx):
    s = ctx.get("assessments", {}).get("risk", 0)
    t = ctx.get("_settings")
    limit = t.rule_min_score("RULE-004", 50) if t else 50
    return RuleResult("RULE-004", s >= limit, f"Risk: {s}/{limit}")

def _eval_conviction(ctx):
    c = ctx.get("conviction", {}).get("overall", 0)
    t = ctx.get("_settings")
    limit = t.rule_min_score("RULE-005", 65) if t else 65
    return RuleResult("RULE-005", c >= limit, f"Conviction: {c}/{limit}")

def _eval_position_weight(ctx):
    port = ctx.get("portfolio", {})
    cur = port.get("position_weight", 0)
    t = ctx.get("_settings")
    new_ctx = ctx.get("proposed_weight", t.default_weight_pct if t else 3.0)
    limit = t.max_position_pct if t else 3.0
    return RuleResult("RULE-006", cur + new_ctx <= limit, f"Position weight: {cur + new_ctx:.1f}% (max {limit})")

def _eval_sector_exposure(ctx):
    port = ctx.get("portfolio", {})
    sec_exp = port.get("sector_exposure", {})
    company = ctx.get("company", {})
    sec = company.get("sector", "Unknown")
    cur = sec_exp.get(sec, 0)
    t = ctx.get("_settings")
    new_ctx = ctx.get("proposed_weight", t.default_weight_pct if t else 3.0)
    limit = t.max_sector_exposure_pct if t else 25.0
    return RuleResult("RULE-007", cur + new_ctx <= limit, f"Sector exposure: {cur + new_ctx:.1f}% (max {limit})")

def _eval_asymmetry(ctx):
    asym = ctx.get("asymmetry")
    if not asym:
        return RuleResult("RULE-008", False, "No hay datos de DDD para calcular asimetria")
    if asym.get("validation_status") != "validated" or asym.get("authorization_eligible") is not True:
        reason = asym.get(
            "validation_reason",
            "Falta un contrato validado de escenarios financieros mutuamente excluyentes.",
        )
        return RuleResult("RULE-008", False, f"Asimetría provisional; autorización bloqueada: {reason}")
    br = asym.get("benefit_risk_ratio", 0)
    upside = asym.get("upside_esperado_pct", 0)
    downside = asym.get("downside_esperado_pct", 0)
    t = ctx.get("_settings")
    limit = t.rule_min_ratio("RULE-008", 3.0) if t else 3.0
    passes = br >= limit
    if passes:
        detail = f"B/R {br:.1f}:1 ✅ (upside {upside:.1f}% / downside {abs(downside):.1f}%)"
    else:
        detail = f"B/R {br:.1f}:1 ❌ (upside {upside:.1f}% / downside {abs(downside):.1f}%)"
    return RuleResult("RULE-008", passes, detail)


def _eval_financial_data_quality(ctx):
    quality = ctx.get("financial_data_quality")
    if not isinstance(quality, dict):
        return RuleResult("RULE-010", False, "Falta el reporte de calidad financiera")

    issues = []
    if quality.get("status") not in {"good", "partial"}:
        issues.append("cobertura de métricas insuficiente")
    if not quality.get("source"):
        issues.append("fuente financiera ausente")
    if not _valid_cutoff_date(quality.get("as_of_date")):
        issues.append("fecha de corte ausente, inválida o futura")
    if quality.get("missing_provenance"):
        issues.append("procedencia incompleta")

    if issues:
        return RuleResult("RULE-010", False, "; ".join(issues))
    return RuleResult(
        "RULE-010",
        True,
        f"Fuente y fecha de corte verificadas; cobertura {quality.get('core_metric_coverage', 'n/d')}",
    )

def _eval_competition(ctx):
    port = ctx.get("portfolio", {})
    num_pos = port.get("num_positions", 0)
    t = ctx.get("_settings")
    limit = t.max_positions if t else 10
    return RuleResult("RULE-009", num_pos < limit, f"Posiciones activas: {num_pos}/{limit} max (competencia por capital)")

ASSESSMENT_RULES = [
    (Rule(id="RULE-001", description="Minimum business quality score for entry", priority=100, condition="score >= 70", action="PASS"), _eval_business),
    (Rule(id="RULE-002", description="Price target vs current price margin > 20%", priority=90, condition="price_margin > 20", action="PASS"), _eval_valuation),
    (Rule(id="RULE-003", description="Minimum rerating probability score", priority=80, condition="score >= 50", action="PASS"), _eval_recovery),
    (Rule(id="RULE-004", description="Maximum risk score allowed", priority=100, condition="score >= 50", action="PASS"), _eval_risk),
    (Rule(id="RULE-005", description="Minimum overall conviction for entry", priority=95, condition="conviction >= 65", action="PASS"), _eval_conviction),
    (Rule(id="RULE-006", description="Maximum portfolio weight per position", priority=100, condition="weight <= 3.0", action="BLOCK"), _eval_position_weight),
    (Rule(id="RULE-007", description="Maximum sector exposure", priority=90, condition="sector <= 25.0", action="BLOCK"), _eval_sector_exposure),
    (Rule(id="RULE-008", description="Minimum asymmetry ratio 3:1", priority=100, condition="ratio >= 3.0", action="PASS"), _eval_asymmetry),
    (Rule(id="RULE-009", description="Capital competition - max 10 positions", priority=80, condition="num_positions < 10", action="BLOCK"), _eval_competition),
    (Rule(id="RULE-010", description="Financial inputs include source and valid cutoff date", priority=110, condition="financial_data_quality has source and valid as_of_date", action="PASS"), _eval_financial_data_quality),
]

def _register_assessment_rules(engine: RulesEngine):
    for rule, fn in ASSESSMENT_RULES:
        engine.register_rule(rule, fn)


AUTHORIZATION_RULE_IDS = {"RULE-001", "RULE-003", "RULE-004", "RULE-005", "RULE-008", "RULE-010"}


def _authorization_rule_ids(base_path: str | Path) -> set[str]:
    """Ids de reglas ACTIVAS de stage=authorization desde entry_rules.yml.

    Las reglas de ejecución (RULE-002, RULE-006, RULE-007, RULE-009) se validan
    en ENTRY_PENDING/sizing, NO bloquean la autorización (UNDER_DEEP_DD → APPROVED).
    """
    rules_path = Path(base_path) / "idos-config" / "rules" / "entry_rules.yml"
    if not rules_path.exists():
        return set(AUTHORIZATION_RULE_IDS)
    try:
        data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    except Exception:
        return set(AUTHORIZATION_RULE_IDS)
    ids = {
        r.get("id") for r in (data or {}).get("rules", [])
        if r.get("active", True) and r.get("stage", "authorization") == "authorization"
    }
    return ids.union({"RULE-010"}) if ids else set(AUTHORIZATION_RULE_IDS)


def _register_authorization_rules(engine: RulesEngine, base_path: str | Path) -> None:
    """Registra solo reglas de AUTORIZACIÓN. Las de ejecución se aplican luego en el sizing."""
    rule_by_id = {rule.id: (rule, fn) for rule, fn in ASSESSMENT_RULES}
    for rid in sorted(_authorization_rule_ids(base_path)):
        entry = rule_by_id.get(rid)
        if entry:
            engine.register_rule(entry[0], entry[1])

def _assess_systematic(opp_id: str, ticker: str, bp: Path, sqlite: SQLiteStore,
                       journal: JournalRepository, context: dict[str, Any]) -> dict[str, Any]:
    """Record an evidence-based WAIT decision; never turn a signal into an order."""
    opp = sqlite.get_opportunity(opp_id) or journal.load_opportunity(ticker, opp_id)
    if not opp or opp.get("ticker") != ticker or opp.get("status") != OpportunityStatus.UNDER_RESEARCH.value:
        return {"ticker": ticker, "opp_id": opp_id, "status": "blocked", "reason": "research_not_completed"}
    strategy_id = opp.get("strategy_id", "")
    try:
        profile = StrategyCatalog(bp / "idos-config" / "strategies.yml").require(strategy_id)
    except ValueError:
        return {"ticker": ticker, "opp_id": opp_id, "status": "blocked", "reason": "unknown_strategy"}
    if not profile.enabled or profile.research_profile != "systematic":
        return {"ticker": ticker, "opp_id": opp_id, "status": "blocked", "reason": "strategy_not_enabled"}

    case_dir = bp / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id
    report_path = case_dir / "ddd_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    signal = opp.get("signal") or context.get("signal") or {}
    value = signal.get("momentum")
    minimum = profile.parameters.get("minimum_signal")
    maximum = profile.parameters.get("maximum_signal")
    snapshot = None
    snapshot_error = None
    try:
        snapshot = current_selection(bp, strategy_id, ticker, profile.parameters)
    except SignalEvidenceError as exc:
        snapshot_error = str(exc)
    report_context = report.get("strategy_context", {}) if isinstance(report, dict) else {}
    checks = {
        "research_evidence": isinstance(report, dict) and report.get("opp_id") == opp_id and report.get("ticker") == ticker,
        "research_matches_signal": isinstance(report_context, dict) and report_context.get("strategy_id") == strategy_id
        and report_context.get("signal") == signal and report_context.get("signal_policy") == {"minimum_signal": minimum, "maximum_signal": maximum}
        and report_context.get("report_method_version") == "systematic_signal_v2",
        "current_selection": snapshot is not None and snapshot["signal"] == signal,
        "signal_evidence": signal.get("ticker") == ticker and bool(signal.get("as_of_date")),
        "signal_within_policy": isinstance(value, (int, float)) and isinstance(minimum, (int, float))
        and isinstance(maximum, (int, float)) and minimum <= value <= maximum,
    }
    passed = all(checks.values())
    blocked_reason = {
        "not_selected_in_latest_snapshot": "El último Monthly que evaluó este activo no lo seleccionó.",
        "signal_snapshot_incomplete": "El último reporte mensual tiene datos incompletos.",
        "signal_policy_changed_or_unrecorded": "Ejecutar Monthly con los parámetros vigentes.",
        "signal_snapshot_unavailable": "Falta un reporte mensual vigente para este activo.",
    }.get(snapshot_error, "La señal o su Research no coinciden con la evidencia mensual vigente.")
    proposal = {
        "opportunity_id": opp_id, "strategy_id": strategy_id,
        "stage": "DECISION", "decision": "WAIT", "status": "PENDING_HUMAN_REVIEW" if passed else "BLOCKED",
        "checks": checks, "signal": signal,
        "reason": "Presupuesto de riesgo y contexto de cartera requieren revisión privada." if passed else blocked_reason,
        "reason_code": None if passed else snapshot_error or "systematic_evidence_superseded",
        "signal_snapshot": snapshot,
        "generated_at": datetime.now(AR_TZ).isoformat(),
    }
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "decision_proposal.yml").write_text(
        yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return {"ticker": ticker, "opp_id": opp_id,
            "status": "decision_pending" if passed else "blocked", "recommendation": "WAIT",
            "checks": checks, "board_approved": False}


def run_full_pipeline(opp_id: str, ticker: str, base_path: str | Path, force_reprocess: bool = False) -> dict[str, Any]:
    bp = Path(base_path)
    sqlite = SQLiteStore(bp / "idos.db")
    journal = JournalRepository(bp / "idos-journal")
    opportunity = sqlite.get_opportunity(opp_id) or journal.load_opportunity(ticker, opp_id) or {}
    if opportunity.get("research_profile") == "systematic":
        # This path needs selection evidence and human review, not corporate
        # analyst targets or reads of private portfolio positions.
        return _assess_systematic(opp_id, ticker, bp, sqlite, journal, opportunity)
    knowledge = KnowledgeRepository(bp / "idos-knowledge")
    settings = load_settings(bp / "idos-config")

    rules_engine = RulesEngine()

    orchestrator = DecisionOrchestrator(rules_engine=rules_engine)
    orchestrator.register_engine(BusinessAssessmentEngine())
    orchestrator.register_engine(ValuationAssessmentEngine())
    orchestrator.register_engine(RecoveryAssessmentEngine())
    orchestrator.register_engine(RiskAssessmentEngine())
    orchestrator.register_engine(PortfolioAssessmentEngine())
    orchestrator.conviction_calc = ConvictionCalculator(settings=settings)

    context = build_context(opp_id, ticker, bp, sqlite, knowledge, journal)
    context["_settings"] = settings
    context["proposed_weight"] = settings.default_weight_pct

    is_systematic = context.get("research_profile") == "systematic"
    if is_systematic:
        return _assess_systematic(opp_id, ticker, bp, sqlite, journal, context)

    _register_authorization_rules(rules_engine, bp)

    proposal = orchestrator.run_pipeline("opportunity:transitioned", context)
    if proposal is None:
        return {"ticker": ticker, "opp_id": opp_id, "status": "skipped", "reason": "Pipeline returned None"}

    # Assessment is a proposal. A passing ruleset is not a manager decision.
    opp_dir = bp / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id
    opp_dir.mkdir(parents=True, exist_ok=True)

    proposal_data = {
        "type": proposal.type,
        "opportunity_id": proposal.opportunity_id,
        "assessments": {k: v.to_assessment_dict(opp_id) for k, v in proposal.assessments.items()},
        "rules_passed": proposal.rules_passed,
        "rules_failed": proposal.rules_failed,
        "conviction_score": proposal.conviction_score,
        "recommendation": proposal.recommendation,
        "reasoning": proposal.reasoning,
        "rules_details": proposal.rules_details,
        "financial_data_quality": context.get("financial_data_quality", {}),
        "status": "PENDING_HUMAN_REVIEW"
        if proposal.recommendation in {"APPROVE", "PENDING_REVIEW"}
        else "BLOCKED" if proposal.recommendation == "BLOCKED" else "NOT_RECOMMENDED",
        "created_at": proposal.created_at,
        "generated_at": datetime.now(AR_TZ).isoformat(),
    }
    with open(opp_dir / "decision_proposal.yml", "w", encoding="utf-8") as f:
        yaml.dump(proposal_data, f, default_flow_style=False, allow_unicode=True)

    resolution_data = {
        "approved": False,
        "status": proposal_data["status"],
        "justification": "Propuesta pendiente de revisión explícita del gestor."
        if proposal_data["status"] == "PENDING_HUMAN_REVIEW"
        else proposal.reasoning,
        "author": "system",
    }
    with open(opp_dir / "board_resolution.yml", "w", encoding="utf-8") as f:
        yaml.dump(resolution_data, f, default_flow_style=False, allow_unicode=True)

    if not context.get("asymmetry"):
        new_status = OpportunityStatus.WATCHLIST
    else:
        new_status = OpportunityStatus.UNDER_DEEP_DD
    opp = sqlite.get_opportunity(opp_id)
    if opp:
        old = opp["status"]
        if proposal.rules_failed and old in (OpportunityStatus.SCREENED.value, OpportunityStatus.UNDER_RESEARCH.value):
            new_status = OpportunityStatus.UNDER_RESEARCH
        now_iso = datetime.now(AR_TZ).isoformat()
        opp["status"] = new_status.value
        opp["updated_at"] = now_iso
        opp["last_research_at"] = now_iso
        cp = context.get("current_price")
        iv = context.get("intrinsic_value")
        if cp:
            opp.setdefault("conviction", {})["current_price"] = cp
        if iv:
            opp.setdefault("conviction", {})["intrinsic_value"] = iv
        sqlite.save_opportunity(opp)
        sqlite.record_transition(
            opp_id, old, new_status.value,
            cause="assessment:manager_review_pending", worker="assessment_pipeline",
        )

    yaml_opp = journal.load_opportunity(ticker, opp_id)
    if yaml_opp:
        if yaml_opp.get("approved_for_buylist") is True:
            _remove_buylist_entry(ticker, opp_id, bp)
        yaml_opp["approved_for_buylist"] = False
        yaml_old_status = yaml_opp.get("status", "")
        if proposal.rules_failed and yaml_old_status in (OpportunityStatus.SCREENED.value, OpportunityStatus.UNDER_RESEARCH.value):
            final_yaml_status = OpportunityStatus.UNDER_RESEARCH.value
        else:
            final_yaml_status = new_status.value
        yaml_opp["status"] = final_yaml_status
        now_iso = datetime.now(AR_TZ).isoformat()
        yaml_opp["updated_at"] = now_iso
        yaml_opp["last_research_at"] = now_iso
        yaml_opp.setdefault("conviction", {})["overall"] = proposal.conviction_score
        cp = context.get("current_price")
        iv = context.get("intrinsic_value")
        if cp:
            yaml_opp["current_price"] = cp
        if iv:
            yaml_opp["intrinsic_value"] = iv
        journal.save_opportunity(ticker, yaml_opp)

    financial_quality = context.get("financial_data_quality", {})
    data_quality = financial_quality.get("status", "poor")

    return {
        "ticker": ticker,
        "opp_id": opp_id,
        "status": "completed",
        "conviction_score": proposal.conviction_score,
        "recommendation": proposal.recommendation,
        "board_approved": False,
        "decision_type": None,
        "decision_id": None,
        "assessments": {k: v.score for k, v in proposal.assessments.items()},
        "rules_passed": proposal.rules_passed,
        "rules_failed": proposal.rules_failed,
        "rules_details": proposal.rules_details,
        "data_quality": data_quality,
        "financial_data_quality": financial_quality,
    }


def build_digest(results: list[dict], total: int, errors: list[dict]) -> str:
    base_url = "https://github.com/alebertolli/idos/tree/main/idos-journal/companies"
    lines = [
        "# IDOS Full Decision Pipeline Digest",
        "",
        f"_Generado: {datetime.now(AR_TZ).strftime('%Y-%m-%d %H:%M AR')}_",
        "",
        "## Resumen",
        "",
        f"- 🟢 **Procesadas:** {len(results)}/{total}",
        f"- 🔴 **Errores:** {len(errors)}",
        f"- 📊 **Total oportunidades:** {total}",
        "",
    ]

    if results:
        lines.append("### Resultados por oportunidad")
        lines.append("")
        for r in results:
            emoji = "✅" if r.get("board_approved") else "⚠️"
            ticker = r["ticker"]
            opp_id = r["opp_id"]
            conv = r.get("conviction_score", "?")
            rec = r.get("recommendation", "?")
            dq = r.get("data_quality", "?")
            dq_flag = " ⚠️ datos pobres" if dq == "poor" else ""
            line = (
                f"- {emoji} **{ticker}** ({opp_id}) - "
                f"Conviction: {conv}/100, Recomendacion: {rec}"
                f"{dq_flag}"
            )
            if r.get("board_approved"):
                line += f", Dec: {r.get('decision_type', '?')}"
            assessments = r.get("assessments", {})
            if assessments:
                parts = [f"{k.replace('AssessmentEngine', '')}: {v}" for k, v in assessments.items()]
                line += f" | {' | '.join(parts)}"
            link = f"{base_url}/{ticker}/case_file/opportunities/{opp_id}"
            line += f"\n  [Ver detalle completo]({link})"
            lines.append(line)
        lines.append("")

    if errors:
        lines.append("### Errores")
        lines.append("")
        for e in errors:
            lines.append(f"- :x: **{e.get('ticker', '?')}**: {e.get('error', '?')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"Link al repositorio: https://github.com/alebertolli/idos")
    lines.append(f"Link a oportunidades: {base_url}")

    return "\n".join(lines)


def send_notifications(summary: str, base_path: str | Path):
    bp = Path(base_path) if base_path else Path.cwd()
    db = bp / "idos.db"
    try:
        from idos.workers.notifications.telegram import TelegramNotifier
        t = TelegramNotifier()
        t.execute({"message": summary[:4000]})
    except Exception as e:
        print(f"[NOTIFY] Telegram error: {e}")

    try:
        from idos.workers.notifications.email_notifier import EmailNotifier
        e = EmailNotifier()
        e.execute({
            "subject": "IDOS Decision Pipeline Report",
            "body": summary,
        })
    except Exception as e:
        print(f"[NOTIFY] Email error: {e}")
