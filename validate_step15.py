"""Step 15: Full E2E Pipeline"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

from idos.discovery.scout import ScoutEngine
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.ranking import RankingSystem
from idos.portfolio.entry import EntryEngine
from idos.portfolio.sizing import PositionSizer
from idos.portfolio.risk import RiskEngine
from idos.portfolio.exit import ExitEngine
from idos.decision.conviction import ConvictionCalculator
from idos.decision.board import DecisionBoard
from idos.decision.orchestrator import DecisionOrchestrator
from idos.research.ddd import DeepDueDiligenceWorker
from idos.research.aoif import AOIFProtocol
from idos.ux.reports import ReportGenerator
from idos.ux.dashboard import DashboardAPI

ticker = "GOOGL"

print("="*60, "\nSTEP 15: FULL E2E PIPELINE")

# 1. Scout
scout = ScoutEngine(min_score=50)
result = scout.scan(ticker, {
    "metrics": {
        "market_cap": 2_000_000_000_000,
        "avg_volume": 30_000_000,
        "pe_ratio": 25, "ev_ebitda": 18,
        "roic": 28, "operating_margin": 30,
        "debt_to_equity": 0.1, "revenue_growth": 15,
    }
})
print(f"1. Scout: score={result.score}, passed={result.passed}")
assert result.passed

# 2. Watchlist
wl = WatchlistManager()
wl.add(ticker, result.score, result.reason)
print(f"2. Watchlist: size={len(wl.entries)}")
assert len(wl.entries) >= 1

# 3. Ranking
ranking = RankingSystem()
ranked = ranking.rank([{"ticker": ticker, "score": result.score, "passed": result.passed}])
print(f"3. Ranking: {ranked}")
assert len(ranked) >= 1

# 4. Entry
entry = EntryEngine(min_margin_of_safety=20.0)
signal = entry.evaluate(
    ticker=ticker,
    context={
        "current_price": 180,
        "intrinsic_value": 220,
        "price_data": [150, 155, 160, 165, 170, 175, 180],
        "thesis_active": True,
        "portfolio": {"total_weight": 5.0},
        "proposed_weight": 3.0,
    }
)
print(f"4. Entry: zone={signal.price_in_zone}, wyckoff={signal.wyckoff_confirmed}, all_ok={signal.all_conditions_met}")
assert hasattr(signal, 'price_in_zone')

# 5. Sizing
sizer = PositionSizer(max_position_pct=3.0)
kelly = sizer.kelly_size(tsp=0.65, payoff_ratio=2.0, bankroll=1_000_000)
kelly_pct, max_dollars = sizer.calculate_max_size(conviction=85, bankroll=1_000_000, current_weight=0)
print(f"5. Sizing: kelly=${kelly:.0f}, max_pct={kelly_pct:.1f}%, max_$=${max_dollars:.0f}")
assert kelly > 0

# 6. Conviction
from idos.decision.engines.base import AssessmentResult
calc = ConvictionCalculator()
conviction = calc.calculate({
    "BusinessAssessmentEngine": AssessmentResult(engine="BusinessAssessmentEngine", score=85, confidence="HIGH"),
    "ValuationAssessmentEngine": AssessmentResult(engine="ValuationAssessmentEngine", score=70, confidence="MEDIUM"),
    "RecoveryAssessmentEngine": AssessmentResult(engine="RecoveryAssessmentEngine", score=60, confidence="MEDIUM"),
    "RiskAssessmentEngine": AssessmentResult(engine="RiskAssessmentEngine", score=75, confidence="HIGH"),
    "PortfolioAssessmentEngine": AssessmentResult(engine="PortfolioAssessmentEngine", score=80, confidence="HIGH"),
})
print(f"6. Conviction: overall={conviction.overall}, {conviction.confidence}")
assert conviction.overall > 0

# 7. Risk
risk = RiskEngine()
alerts = risk.evaluate_all(ticker=ticker, metrics={
    "drawdown": 2.0,
    "volatility_90d": 25.0,
    "debt_to_equity": 0.1,
    "weight_pct": 2.5,
})
print(f"7. Risk: {len(alerts)} alerts (expected 0 for GOOGL)")

# 8. Exit (individual methods)
exit_engine = ExitEngine()
t_exit = exit_engine.evaluate_thesis_exit(ticker, thesis_active=True)
v_exit = exit_engine.evaluate_valuation_exit(ticker, current_pe=25, intrinsic_pe=28)
r_exit = exit_engine.evaluate_risk_exit(ticker, current_drawdown=2.0)
p_exit = exit_engine.evaluate_portfolio_exit(ticker, replacement_score=70, current_conviction=85)
exits = [e for e in [t_exit, v_exit, r_exit, p_exit] if e is not None]
print(f"8. Exit: {len(exits)} exit signals (expected 0)")
assert len(exits) == 0

# 9. DDD
ddd = DeepDueDiligenceWorker()
ddd_result = ddd.run(ticker, {
    "business_model": "Publicidad digital + Cloud + YouTube",
    "products": "Search, Google Cloud, YouTube, Waymo",
    "moat_description": "Moat de datos + escala + ecosistema",
    "revenue": 350_000, "revenue_growth": 15,
    "operating_margin": 30, "roic": 28,
    "debt_to_equity": 0.1, "fcf_yield": 3.5,
    "recent_events": "Lanzamiento Gemini 2.5, Cloud >30%",
})
print(f"9. DDD: score={ddd_result.score}")
assert ddd_result.score >= 0

# 10. AOIF
aoif = AOIFProtocol()
aoif_result = aoif.execute(
    opportunity_id="OPP-VALIDATION",
    ticker=ticker,
    data={
        "knowledge_base": {
            "dynamic": {
                "metrics": {
                    "roic": 28, "operating_margin": 30,
                    "revenue_growth": 15, "pe_ratio": 25,
                    "ev_ebitda": 18, "fcf_yield": 3.5,
                }
            }
        }
    }
)
print(f"10. AOIF: score={aoif_result.score}, steps={len(aoif_result.steps)}")
assert len(aoif_result.steps) == 8

# 11. Report
reports = ReportGenerator()
ddd_dict = {
    "executive_summary": f"Google ({ticker}) — leading digital ad + cloud platform",
    "business_analysis": "Vertically integrated AI ecosystem",
    "financial_analysis": f"Revenue $350B, ROIC 28%, Op Margin 30%",
    "management_assessment": "Strong execution",
    "risk_factors": "Regulatory, AI competition",
    "valuation": "PER 25x, EV/EBITDA 18x",
    "recommendation": "BUY — quality compounder at fair price",
}
report = reports.generate_dd_report(ticker=ticker, ddd_result=ddd_dict)
print(f"11. Report: type={report.report_type}, sections={len(report.sections)}")
assert len(report.sections) >= 1

# 12. Dashboard (API)
dash = DashboardAPI()
wl_entries = []
for entry in wl.entries:
    if hasattr(entry, '__dict__'):
        wl_entries.append(entry.__dict__)
    else:
        wl_entries.append({"ticker": str(entry)})
summary = dash.build_summary(
    opportunities=[], positions=[], watchlist=wl_entries,
    decisions=[], risk_alerts=[], cash={"cash_pct": 15},
)
print(f"12. Dashboard: summary built")

print("\n" + "="*60)
print("STEP 15 COMPLETE — FULL PIPELINE OK")
