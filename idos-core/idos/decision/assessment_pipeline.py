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
from idos.portfolio.entry import EntryEngine
from idos.timezone import AR_TZ
from datetime import datetime

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
    margin_of_safety = 20.0
    if opp:
        cv = opp.get("conviction", {}) or {}
        margin_of_safety = cv.get("margin_of_safety", 20.0)

    return {
        "knowledge_base": {"dynamic": {"metrics": metrics}, "static": static},
        "portfolio": portfolio,
        "company": company_info,
        "margin_of_safety": margin_of_safety,
        "catalysts": [],
        "risk_events": [],
        "proposed_weight": 3.0,
        "themes": [],
        "opportunity_id": opp_id,
        "ticker": ticker,
        "force_relevance": True,
    }


def _normalize_decimal_pcts(data: dict[str, Any]) -> dict[str, Any]:
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


def _eval_business(ctx):
    s = ctx.get("assessments", {}).get("BusinessAssessmentEngine", 0)
    return RuleResult("RULE-001", s >= 70, f"Business quality: {s}/100")

def _eval_valuation(ctx):
    s = ctx.get("assessments", {}).get("ValuationAssessmentEngine", 0)
    return RuleResult("RULE-002", s >= 60, f"Valuation: {s}/100")

def _eval_recovery(ctx):
    s = ctx.get("assessments", {}).get("RecoveryAssessmentEngine", 0)
    return RuleResult("RULE-003", s >= 60, f"Rerating: {s}/100")

def _eval_risk(ctx):
    s = ctx.get("assessments", {}).get("RiskAssessmentEngine", 0)
    return RuleResult("RULE-004", s >= 50, f"Risk: {s}/100")

def _eval_conviction(ctx):
    c = ctx.get("conviction", {}).get("overall", 0)
    return RuleResult("RULE-005", c >= 65, f"Conviction: {c}/100")

def _eval_position_weight(ctx):
    port = ctx.get("portfolio", {})
    cur = port.get("position_weight", 0)
    new_ctx = ctx.get("proposed_weight", 3.0)
    return RuleResult("RULE-006", cur + new_ctx <= 3.0, f"Position weight: {cur + new_ctx:.1f}%")

def _eval_sector_exposure(ctx):
    port = ctx.get("portfolio", {})
    sec_exp = port.get("sector_exposure", {})
    company = ctx.get("company", {})
    sec = company.get("sector", "Unknown")
    cur = sec_exp.get(sec, 0)
    new_ctx = ctx.get("proposed_weight", 3.0)
    return RuleResult("RULE-007", cur + new_ctx <= 25.0, f"Sector exposure: {cur + new_ctx:.1f}%")

def _eval_asymmetry(ctx):
    return RuleResult("RULE-008", True, "No asymmetry data available")

ASSESSMENT_RULES = [
    (Rule(id="RULE-001", description="Minimum business quality score for entry", priority=100, condition="score >= 70", action="PASS"), _eval_business),
    (Rule(id="RULE-002", description="Minimum valuation score for entry", priority=90, condition="score >= 60", action="PASS"), _eval_valuation),
    (Rule(id="RULE-003", description="Minimum rerating probability score", priority=80, condition="score >= 60", action="PASS"), _eval_recovery),
    (Rule(id="RULE-004", description="Maximum risk score allowed", priority=100, condition="score >= 50", action="PASS"), _eval_risk),
    (Rule(id="RULE-005", description="Minimum overall conviction for entry", priority=95, condition="conviction >= 65", action="PASS"), _eval_conviction),
    (Rule(id="RULE-006", description="Maximum portfolio weight per position", priority=100, condition="weight <= 3.0", action="BLOCK"), _eval_position_weight),
    (Rule(id="RULE-007", description="Maximum sector exposure", priority=90, condition="sector <= 25.0", action="BLOCK"), _eval_sector_exposure),
    (Rule(id="RULE-008", description="Minimum asymmetry ratio 3:1", priority=100, condition="ratio >= 3.0", action="PASS"), _eval_asymmetry),
]

def _register_assessment_rules(engine: RulesEngine):
    for rule, fn in ASSESSMENT_RULES:
        engine.register_rule(rule, fn)

def run_full_pipeline(opp_id: str, ticker: str, base_path: str | Path, force_reprocess: bool = False) -> dict[str, Any]:
    bp = Path(base_path)
    sqlite = SQLiteStore(bp / "idos.db")
    knowledge = KnowledgeRepository(bp / "idos-knowledge")
    journal = JournalRepository(bp / "idos-journal")

    rules_engine = RulesEngine()
    _register_assessment_rules(rules_engine)

    orchestrator = DecisionOrchestrator(rules_engine=rules_engine)
    orchestrator.register_engine(BusinessAssessmentEngine())
    orchestrator.register_engine(ValuationAssessmentEngine())
    orchestrator.register_engine(RecoveryAssessmentEngine())
    orchestrator.register_engine(RiskAssessmentEngine())
    orchestrator.register_engine(PortfolioAssessmentEngine())
    orchestrator.conviction_calc = ConvictionCalculator()

    context = build_context(opp_id, ticker, bp, sqlite, knowledge, journal)

    proposal = orchestrator.run_pipeline("opportunity:transitioned", context)
    if proposal is None:
        return {"ticker": ticker, "opp_id": opp_id, "status": "skipped", "reason": "Pipeline returned None"}

    board = DecisionBoard(journal_repo=journal)
    board.submit(proposal)
    resolution = board.review()

    entry_signal = None
    if resolution.approved:
        try:
            entry_ctx = {
                "price_data": [],
                "intrinsic_value": 0,
                "current_price": 0,
                "thesis_active": True,
                "portfolio": context["portfolio"],
                "proposed_weight": 3.0,
            }
            entry_engine = EntryEngine()
            entry_signal = entry_engine.evaluate(ticker, entry_ctx)
        except Exception as e:
            entry_signal = type("obj", (), {"all_conditions_met": False, "reason": str(e)})()

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

    if entry_signal:
        entry_data = {
            "all_conditions_met": entry_signal.all_conditions_met,
            "price_in_zone": entry_signal.price_in_zone,
            "wyckoff_confirmed": entry_signal.wyckoff_confirmed,
            "thesis_active": entry_signal.thesis_active,
            "portfolio_fit": entry_signal.portfolio_fit,
            "current_price": entry_signal.current_price,
            "target_price": entry_signal.target_price,
            "margin_of_safety_pct": entry_signal.margin_of_safety_pct,
            "wyckoff_phase": entry_signal.wyckoff_phase,
            "reason": entry_signal.reason,
        }
        with open(opp_dir / "entry_evaluation.yml", "w", encoding="utf-8") as f:
            yaml.dump(entry_data, f, default_flow_style=False, allow_unicode=True)

    if not force_reprocess:
        new_status = OpportunityStatus.APPROVED if resolution.approved else OpportunityStatus.UNDER_DEEP_DD
        opp = sqlite.get_opportunity(opp_id)
        if opp:
            old = opp["status"]
            opp["status"] = new_status.value
            opp["updated_at"] = datetime.now(AR_TZ).isoformat()
            sqlite.save_opportunity(opp)
            sqlite.record_transition(
                opp_id, old, new_status.value,
                cause=f"board:{resolution.decision_type.value.lower()}", worker="assessment_pipeline",
            )

    yaml_opp = journal.load_opportunity(ticker, opp_id)
    if yaml_opp:
        if not force_reprocess:
            yaml_opp["status"] = new_status.value
        yaml_opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        yaml_opp.setdefault("conviction", {})["overall"] = proposal.conviction_score
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
        f"- :green_circle: **Procesadas:** {len(results)}/{total}",
        f"- :red_circle: **Errores:** {len(errors)}",
        f"- :bar_chart: **Total oportunidades:** {total}",
        "",
    ]

    if results:
        lines.append("### Resultados por oportunidad")
        lines.append("")
        for r in results:
            emoji = ":white_check_mark:" if r.get("board_approved") else ":warning:"
            ticker = r["ticker"]
            opp_id = r["opp_id"]
            conv = r.get("conviction_score", "?")
            rec = r.get("recommendation", "?")
            dq = r.get("data_quality", "?")
            dq_flag = " :warning: datos pobres" if dq == "poor" else ""
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
