from pathlib import Path
from typing import Any
import json
import yaml

from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository
from idos.decision.orchestrator import DecisionOrchestrator, DecisionProposal
from idos.decision.board import DecisionBoard, BoardResolution
from idos.decision.conviction import ConvictionCalculator
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine
from idos.rules.engine import RulesEngine, RuleResult
from idos.models.knowledge import Rule
from idos.models.enums import OpportunityStatus
from idos.portfolio.buylist import BuyListManager, BuyListEntry
from idos.config import load_settings
from idos.timezone import AR_TZ
from datetime import datetime

def _add_to_buylist(ticker: str, proposal: DecisionProposal, context: dict[str, Any],
                     opp_id: str, bp: Path, knowledge: KnowledgeRepository):
    target_price = context.get("intrinsic_value", 0) or 0
    margin = context.get("margin_of_safety", 30.0)
    buy_zone_top = target_price / (1 + margin / 100) if target_price else 0
    entry = BuyListEntry(
        ticker=ticker,
        target_price=target_price,
        buy_zone_top=buy_zone_top,
        max_position_pct=context.get("proposed_weight", 3.0),
        conviction_score=proposal.conviction_score,
        horizon="12-36 months",
        catalysts=context.get("catalysts", []),
        kb_last_update=proposal.created_at,
    )
    buylist_path = bp / "idos-journal" / "portfolio" / "buylist.yml"
    buylist_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    existing = {}
    if buylist_path.exists():
        existing = yaml.safe_load(buylist_path.read_text(encoding="utf-8")) or {}
    entries = existing.get("entries", [])
    entries = [e for e in entries if e.get("ticker") != ticker]
    entries.append({
        "ticker": ticker,
        "opp_id": opp_id,
        "target_price": target_price,
        "buy_zone_top": buy_zone_top,
        "max_position_pct": entry.max_position_pct,
        "conviction_score": proposal.conviction_score,
        "horizon": "12-36 months",
        "catalysts": context.get("catalysts", []),
        "kb_last_update": proposal.created_at,
        "added_at": entry.added_at,
        "monitoring": True,
    })
    buylist_path.write_text(yaml.dump({"entries": entries}, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    print(f"[BUYLIST] {ticker} added to persistent Buy List (target={target_price}, zone={buy_zone_top})")


def build_context(
    opp_id: str, ticker: str, bp: Path, sqlite: SQLiteStore,
    knowledge: KnowledgeRepository, journal: JournalRepository,
) -> dict[str, Any]:
    financial = _load_financial_data(ticker, sqlite)
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
    target_low = None
    target_mean = None
    target_high = None
    try:
        import yfinance as yf
        _s = yf.Ticker(ticker)
        _i = _s.info or {}
        current_price = _i.get("currentPrice") or _i.get("regularMarketPrice")
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

    asymmetry = _compute_asymmetry(raw_catalysts, current_price, target_low, target_mean, target_high)

    return {
        "knowledge_base": {"dynamic": {"metrics": metrics}, "static": static},
        "portfolio": portfolio,
        "company": company_info,
        "margin_of_safety": margin_of_safety,
        "price_margin": price_margin,
        "catalysts": catalysts,
        "risk_events": risk_events,
        "asymmetry": asymmetry,
        "current_price": current_price,
        "intrinsic_value": consensus_target or target_mean,
        "target_consensus": target_consensus,
        "proposed_weight": 3.0,
        "themes": [],
        "opportunity_id": opp_id,
        "ticker": ticker,
        "force_relevance": True,
        "thesis_active": thesis_active,
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
        "passes_threshold": br >= 3.0,
        "horizonte_avg_years": round(horizon_avg, 2),
    }


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
]

def _register_assessment_rules(engine: RulesEngine):
    for rule, fn in ASSESSMENT_RULES:
        engine.register_rule(rule, fn)


AUTHORIZATION_RULE_IDS = {"RULE-001", "RULE-003", "RULE-004", "RULE-005", "RULE-008"}


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
    return ids or set(AUTHORIZATION_RULE_IDS)


def _register_authorization_rules(engine: RulesEngine, base_path: str | Path) -> None:
    """Registra solo reglas de AUTORIZACIÓN. Las de ejecución se aplican luego en el sizing."""
    rule_by_id = {rule.id: (rule, fn) for rule, fn in ASSESSMENT_RULES}
    for rid in sorted(_authorization_rule_ids(base_path)):
        entry = rule_by_id.get(rid)
        if entry:
            engine.register_rule(entry[0], entry[1])

def run_full_pipeline(opp_id: str, ticker: str, base_path: str | Path, force_reprocess: bool = False) -> dict[str, Any]:
    bp = Path(base_path)
    sqlite = SQLiteStore(bp / "idos.db")
    knowledge = KnowledgeRepository(bp / "idos-knowledge")
    journal = JournalRepository(bp / "idos-journal")
    settings = load_settings(bp / "idos-config")

    rules_engine = RulesEngine()
    _register_authorization_rules(rules_engine, bp)

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

    proposal = orchestrator.run_pipeline("opportunity:transitioned", context)
    if proposal is None:
        return {"ticker": ticker, "opp_id": opp_id, "status": "skipped", "reason": "Pipeline returned None"}

    board = DecisionBoard(journal_repo=journal, ticker=ticker)
    board.submit(proposal)
    resolution = board.review()

    if resolution.approved:
        _add_to_buylist(ticker, proposal, context, opp_id, bp, knowledge)

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
        "created_at": proposal.created_at,
        "generated_at": datetime.now(AR_TZ).isoformat(),
    }
    with open(opp_dir / "decision_proposal.yml", "w", encoding="utf-8") as f:
        yaml.dump(proposal_data, f, default_flow_style=False, allow_unicode=True)

    resolution_data = {
        "approved": resolution.approved,
        "decision_id": resolution.decision_id,
        "decision_type": resolution.decision_type.value,
        "justification": resolution.justification,
        "author": resolution.author,
        "resolved_at": resolution.resolved_at,
    }
    with open(opp_dir / "board_resolution.yml", "w", encoding="utf-8") as f:
        yaml.dump(resolution_data, f, default_flow_style=False, allow_unicode=True)

    if resolution.approved:
        new_status = OpportunityStatus.APPROVED
    elif not context.get("asymmetry"):
        new_status = OpportunityStatus.WATCHLIST
    else:
        new_status = OpportunityStatus.UNDER_DEEP_DD
    opp = sqlite.get_opportunity(opp_id)
    if opp:
        old = opp["status"]
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
            cause=f"board:{resolution.decision_type.value.lower()}", worker="assessment_pipeline",
        )

    yaml_opp = journal.load_opportunity(ticker, opp_id)
    if yaml_opp:
        yaml_opp["status"] = new_status.value
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

    _all_metrics = context.get("knowledge_base", {}).get("dynamic", {}).get("metrics", {})
    _core_metrics = {k: v for k, v in _all_metrics.items() if k in ("roic", "operating_margin", "revenue_growth", "pe_ratio", "debt_to_equity")}
    _zero_core = sum(1 for v in _core_metrics.values() if isinstance(v, (int, float)) and v == 0)
    _data_quality = "poor" if _zero_core > len(_core_metrics) // 2 else "good"

    return {
        "ticker": ticker,
        "opp_id": opp_id,
        "status": "completed",
        "conviction_score": proposal.conviction_score,
        "recommendation": proposal.recommendation,
        "board_approved": resolution.approved,
        "decision_type": resolution.decision_type.value,
        "decision_id": resolution.decision_id,
        "assessments": {k: v.score for k, v in proposal.assessments.items()},
        "rules_passed": proposal.rules_passed,
        "rules_failed": proposal.rules_failed,
        "rules_details": proposal.rules_details,
        "data_quality": _data_quality,
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
