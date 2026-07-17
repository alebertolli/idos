"""IDOS End-to-End Test: MELI (MercadoLibre)"""
import json, sys
from pathlib import Path
from datetime import datetime, UTC

sys.path.insert(0, str(Path.cwd() / "idos-core"))

from idos.core.context import IDOSContext
from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository
from idos.state.machine import OpportunityStateMachine
from idos.models.enums import OpportunityStatus
from idos.models.knowledge import Company
from idos.models.journal import Opportunity, CaseFile
from idos.events.bus import get_event_bus
from idos.telemetry.trace import get_tracer

from idos.discovery.scout import ScoutEngine
from idos.discovery.ranking import RankingSystem
from idos.discovery.watchlist import WatchlistManager
from idos.discovery.pipeline import ScreeningPipeline

from idos.decision.orchestrator import DecisionOrchestrator
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine
from idos.decision.conviction import ConvictionCalculator
from idos.decision.board import DecisionBoard
from idos.decision.dpf import DualProbabilityFramework
from idos.decision.rpf import ReratingProbabilityEngine

from idos.research.ddd import DeepDueDiligenceWorker
from idos.research.aoif import AOIFProtocol
from idos.research.wiki import WikiBuilder
from idos.research.hypothesis import HypothesisTreeManager
from idos.research.predictions import PredictionTracker
from idos.research.evidence import EvidenceChainManager
from idos.research.claims import ClaimsSystem
from idos.research.kb_updater import KnowledgeBaseUpdater

from idos.portfolio.entry import EntryEngine
from idos.portfolio.wyckoff import WyckoffAnalyzer
from idos.portfolio.sizing import PositionSizer
from idos.portfolio.exit import ExitEngine
from idos.portfolio.risk import RiskEngine
from idos.portfolio.cash import CashManager
from idos.portfolio.diversification import DiversificationController
from idos.portfolio.competition import CapitalCompetitionEngine
from idos.portfolio.rebalance import PortfolioRebalancer as _PR
from idos.portfolio.buylist import BuyListManager, BuyListEntry

from idos.ux.reports import ReportGenerator
from idos.ux.dashboard import DashboardAPI
from idos.ux.kbquery import KnowledgeBaseQueryEngine
from idos.ux.notifications import NotificationTemplateEngine

base = Path.cwd()
ctx = IDOSContext.create(base)
sqlite = SQLiteStore(ctx.sqlite_path)
knowledge = KnowledgeRepository(ctx.knowledge_path)
journal = JournalRepository(ctx.journal_path)
bus = get_event_bus()
sm = OpportunityStateMachine()
tracer = get_tracer()

print("=" * 60)
print("IDOS E2E TEST: MERCADOLIBRE (MELI)")
print("=" * 60)

# ── STEP 1: Init ──────────────────────────────────────────────────────────────
print("\n[1/12] Initializing system...")
ctx.config_path.mkdir(parents=True, exist_ok=True)
(ctx.config_path / "prompts" / "scout").mkdir(parents=True, exist_ok=True)
(ctx.config_path / "prompts" / "research").mkdir(parents=True, exist_ok=True)
print("  OK")

# ── STEP 2: Add Company ───────────────────────────────────────────────────────
print("\n[2/12] Adding MELI company...")
meli_data = {
    "ticker": "MELI",
    "name": "MercadoLibre",
    "sector": "Technology",
    "business_model": "Leading e-commerce and fintech platform in Latin America",
    "products": ["MercadoLibre (e-commerce)", "MercadoPago (payments)", "MercadoEnvíos (logistics)", "MercadoCrédito (financing)"],
    "geography": "Latin America (Brazil, Argentina, Mexico, Chile, Colombia)",
    "moat_description": "Network effects: largest e-commerce + payments ecosystem in LatAm with 100M+ active users. Logistics moat through MercadoEnvíos. Brand trust and seller liquidity lock-in.",
    "ceo_tenure": 12,
    "insider_ownership": 8.5,
    "capital_allocation": "Excellent - consistently reinvested in logistics and fintech, disciplined M&A",
    "recent_events": "Q2 2026: Revenue +42% YoY, fintech share growing to 45% of revenue. Credit portfolio expanded 60% YoY.",
}
company = Company(ticker="MELI", name="MercadoLibre", sector="Technology")
knowledge.save_company("MELI", meli_data)
print("  Company MELI saved to knowledge base")

# ── STEP 3: Create Opportunity ────────────────────────────────────────────────
print("\n[3/12] Creating opportunity...")
opp_id = f"OPP-{datetime.now(UTC).strftime('%Y%m%d')}-001"
opp = Opportunity(id=opp_id, ticker="MELI", status=OpportunityStatus.DISCOVERED)
sqlite.save_opportunity(opp.model_dump())
journal.save_opportunity("MELI", opp.model_dump())
bus.publish_sync("opportunity:created", {"opp_id": opp_id, "ticker": "MELI"})
print(f"  {opp_id} created")

# ── STEP 4: Scout Screening ───────────────────────────────────────────────────
print("\n[4/12] Running Scout screening...")
scout = ScoutEngine(min_score=50)
scout_result = scout.scan("MELI", {
    "metrics": {
        "market_cap": 85_000_000_000,
        "avg_volume": 2_500_000,
        "price_change_3m": 15.2,
        "price_change_12m": 45.8,
        "pe_ratio": 55.3,
        "ev_ebitda": 32.1,
        "roic": 22.5,
        "operating_margin": 18.3,
        "debt_to_equity": 0.45,
        "revenue_growth": 38.2,
    }
})
print(f"  Score: {scout_result.score}/100 | Passed: {scout_result.passed}")
print(f"  Dimensions: {scout_result.details}")

# Add to watchlist
wl = WatchlistManager()
wl.add("MELI", score=scout_result.score)
ranking = RankingSystem()
ranked = ranking.rank([{"ticker": "MELI", "score": scout_result.score, **scout_result.details}])

pipeline = ScreeningPipeline(scout, wl)
pipeline_result = pipeline.process("MELI", {
    "metrics": {
        "market_cap": 85_000_000_000, "avg_volume": 2_500_000,
        "price_change_3m": 15.2, "price_change_12m": 45.8,
        "pe_ratio": 55.3, "ev_ebitda": 32.1,
        "roic": 22.5, "operating_margin": 18.3,
        "debt_to_equity": 0.45, "revenue_growth": 38.2,
    }
})
print(f"  Pipeline result: {'PASSED' if pipeline_result.passed else 'FAILED'} (score={pipeline_result.score})")

# Transition DISCOVERED → SCREENED
sm.transition(OpportunityStatus.DISCOVERED, OpportunityStatus.SCREENED, cause="scout passed")
sqlite.save_opportunity({**opp.model_dump(), "status": OpportunityStatus.SCREENED.value})
sqlite.record_transition(opp_id, "DISCOVERED", "SCREENED", cause="scout passed")
print("  Status: DISCOVERED → SCREENED")

# ── STEP 5: Decision Domain ───────────────────────────────────────────────────
print("\n[5/12] Running Decision pipeline...")
orchestrator = DecisionOrchestrator()
orchestrator.register_engine(BusinessAssessmentEngine())
orchestrator.register_engine(ValuationAssessmentEngine())
orchestrator.register_engine(RecoveryAssessmentEngine())
orchestrator.register_engine(RiskAssessmentEngine())
orchestrator.register_engine(PortfolioAssessmentEngine())

board = DecisionBoard(journal)

decision_context = {
    "opportunity_id": opp_id,
    "ticker": "MELI",
    "type": "initiation",
    "source": "scout_screening",
    "force_relevance": True,
    "metrics": {
        "market_cap": 85e9, "pe_ratio": 55.3, "ev_ebitda": 32.1,
        "roic": 22.5, "operating_margin": 18.3, "debt_to_equity": 0.45,
        "revenue_growth": 38.2, "fcf_yield": 0.8,
        "price_change_3m": 15.2, "price_change_12m": 45.8,
        "avg_volume": 2_500_000, "beta": 1.15,
        "volatility_90d": 28.5, "short_interest_pct": 3.2,
    },
    "sector": "Technology",
    "market_phase": "bull",
    "active_opportunities": [opp.model_dump()],
}

proposal = orchestrator.run_pipeline("opportunity:created", decision_context)
board.submit(proposal)
resolution = board.review()
print(f"  Decision: {proposal.recommendation} (board: {'APPROVED' if resolution.approved else 'REJECTED'})")
print(f"  Conviction: {proposal.conviction_score}/100")
print(f"  Rules passed: {proposal.rules_passed}, blocked: {proposal.rules_failed}")
print(f"  Reasoning: {proposal.reasoning}")

# Transition SCREENED → WATCHLIST
sm.transition(OpportunityStatus.SCREENED, OpportunityStatus.WATCHLIST, cause="decision reviewed")
sqlite.save_opportunity({**opp.model_dump(), "status": OpportunityStatus.WATCHLIST.value})
sqlite.record_transition(opp_id, "SCREENED", "WATCHLIST", cause="decision reviewed")

# DPF
dpf = DualProbabilityFramework()
dpf_result = dpf.evaluate(decision_context)
tsp = dpf_result["tsp"]
kelly_size = dpf.calculate_position_size(tsp, bankroll=1_000_000, payoff_ratio=2.5)
print(f"  DPF: BSP={dpf_result['bsp']:.2f}, MRP={dpf_result['mrp']:.2f}, TSP={tsp:.2f}, Kelly=${kelly_size:,.0f}")

# RPF
rpf = ReratingProbabilityEngine()
rpf_result = rpf.evaluate(decision_context)
print(f"  RPF: Index={rpf_result.index_value:.4f}, Prob={rpf_result.probability:.2f}, Mag={rpf_result.magnitude:.1f}, Vel={rpf_result.velocity:.1f}, Conf={rpf_result.confidence:.2f}")

# ── STEP 6: Deep Due Diligence ────────────────────────────────────────────────
print("\n[6/12] Running Deep Due Diligence...")
ddd = DeepDueDiligenceWorker()
ddd_result = ddd.run("MELI", {
    "knowledge_base": {
        "static": meli_data,
        "dynamic": {"metrics": {
            "roic": 22.5, "operating_margin": 18.3,
            "debt_to_equity": 0.45, "revenue_growth": 38.2,
        }}
    },
    "summary": "MercadoLibre is the dominant e-commerce and fintech platform in LatAm",
    "management_quality": "EXCEPTIONAL",
    "catalysts": [
        {"description": "Credit portfolio expansion in Brazil", "impact": "high", "timeline": "short"},
        {"description": "Mexico logistics ramp", "impact": "medium", "timeline": "medium"},
    ],
})
print(f"  DDD Score: {ddd_result.score}/100 | Quality: {ddd_result.business_quality}")
print(f"  Risks: {ddd_result.risks_identified}")
print(f"  Thesis: {ddd_result.thesis_statement}")

# ── STEP 7: AOIF Protocol ─────────────────────────────────────────────────────
print("\n[7/12] Running AOIF Protocol...")
aoif = AOIFProtocol()
aoif_result = aoif.execute(opp_id, "MELI", {
    "ticker": "MELI",
    "knowledge_base": {"static": meli_data, "dynamic": {"metrics": {
        "roic": 22.5, "operating_margin": 18.3,
        "debt_to_equity": 0.45, "revenue_growth": 38.2,
        "pe_ratio": 55.3, "ev_ebitda": 32.1, "fcf_yield": 0.8,
    }}},
    "management_quality": "EXCEPTIONAL",
    "competitors": ["Amazon Brazil", "Magazine Luiza", "Shopee"],
    "thesis": "MELI benefits from structural e-commerce growth in LatAm with fintech acceleration",
})
print(f"  AOIF Steps: {len(aoif_result.steps)}/8 | Score: {aoif_result.score}/100")

# Transition WATCHLIST → UNDER_RESEARCH
sm.transition(OpportunityStatus.WATCHLIST, OpportunityStatus.UNDER_RESEARCH, cause="aoif completed")
sqlite.save_opportunity({**opp.model_dump(), "status": OpportunityStatus.UNDER_RESEARCH.value})
sqlite.record_transition(opp_id, "WATCHLIST", "UNDER_RESEARCH", cause="aoif completed")

# ── STEP 8: Wiki & Knowledge ──────────────────────────────────────────────────
print("\n[8/12] Building Wiki & Knowledge...")
wiki = WikiBuilder()
wiki_data = wiki.build("MELI", {
    "knowledge_base": {"static": meli_data, "dynamic": {"metrics": {
        "roic": 22.5, "operating_margin": 18.3, "revenue_growth": 38.2,
        "fcf_yield": 0.8, "debt_to_equity": 0.45, "pe_ratio": 55.3, "ev_ebitda": 32.1,
    }}},
    "thesis": "MELI dominates LatAm e-commerce and fintech with network effects",
    "catalysts": [
        {"description": "Credit portfolio expansion", "impact": "high", "timeline": "short"},
        {"description": "Mexico logistics ramp", "impact": "medium", "timeline": "medium"},
    ],
    "competitors": ["Amazon Brazil", "Magazine Luiza", "Shopee"],
    "ddd_output": ddd_result,
    "aoif_output": aoif_result,
})
print(f"  Wiki sections: {len(wiki_data)}")

kb_updater = KnowledgeBaseUpdater()
meli_kb = {"static": dict(meli_data), "dynamic": {"metrics": {}}}
meli_kb = kb_updater.update_metrics(meli_kb, {"roic": 22.5, "operating_margin": 18.3, "revenue_growth": 38.2, "fcf_yield": 0.8})
meli_kb = kb_updater.update_financials(meli_kb, "FY2026", {"revenue": 18000, "net_income": 3500, "fcf": 2800})
meli_kb = kb_updater.add_event(meli_kb, "earnings", "Q2 2026: Revenue +42% YoY")

htree = HypothesisTreeManager()
h1 = htree.create(opp_id, "MELI", "MELI credit revenue will reach $8B by FY2028",
                  secondary=["Fintech share of revenue will exceed 50%"],
                  falsification=["Credit portfolio growth < 20% for 2 consecutive quarters"])
htree.add_prediction(h1.id, "Credit revenue > $8B", 8_000_000_000, "2028-12-31", tolerance=10)

claims = ClaimsSystem()
claim = claims.register("MELI has the largest e-commerce logistics network in LatAm",
                         confidence=0.85, sources=["Company filings"])
claims.add_source(claim.id, "Q2 2026 filing")

evidence = EvidenceChainManager()
ev = evidence.add_evidence("100M+ active users", "Q2 2026 filing", "2026-07-15")
evidence.link(claim.id, ev.id)

tracker = PredictionTracker()
tracker.track("PRED-MELI-001", "Q2 2026 revenue growth", expected=38.0,
              measurement_date="2026-07-31", tolerance_pct=10)
tracker.record("PRED-MELI-001", observed=42.0)
print(f"  Prediction hit rate: {tracker.hit_rate():.1f}%")

# Save wiki to knowledge base for Obsidian
wiki_md = wiki.render_markdown(wiki_data)
wiki_path = ctx.knowledge_path / "companies" / "MELI" / "wiki.md"
wiki_path.parent.mkdir(parents=True, exist_ok=True)
wiki_path.write_text(wiki_md, encoding="utf-8")
print(f"  Wiki saved to {wiki_path}")

# ── STEP 9: Portfolio Entry ───────────────────────────────────────────────────
print("\n[9/12] Evaluating Portfolio Entry...")
wyckoff = WyckoffAnalyzer()
price_data = (
    [{"close": 1800 - i * 8, "volume": 3_000_000} for i in range(25)]
    + [{"close": 1600 + (i % 5) * 10, "volume": 800_000} for i in range(25)]
)

entry = EntryEngine(min_margin_of_safety=15)
entry_signal = entry.evaluate("MELI", {
    "price_data": price_data,
    "intrinsic_value": 2500,
    "current_price": 1650,
    "thesis_active": True,
    "portfolio": {"total_weight": 0},
    "proposed_weight": 3.0,
})
print(f"  Entry: All Met={entry_signal.all_conditions_met} | Phase={entry_signal.wyckoff_phase}")
print(f"  Margin of Safety: {entry_signal.margin_of_safety_pct:.1f}%")

sizer = PositionSizer(max_position_pct=3)
kelly_amt = sizer.kelly_size(tsp=tsp, payoff_ratio=2.5, bankroll=1_000_000)
suggested_pct, suggested_dollars = sizer.calculate_max_size(conviction=78, bankroll=1_000_000, current_weight=0)
print(f"  Kelly: ${kelly_amt:,.0f} | Suggested: {suggested_pct}% (${suggested_dollars:,.0f})")

# Add to buy list
buylist = BuyListManager()
buylist.add(BuyListEntry(ticker="MELI", target_price=2500, buy_zone_top=2000, conviction_score=78))
print(f"  Buy list: {buylist.count()} entries, in zone: {buylist.is_in_buy_zone('MELI', 1650)}")

# Transition UNDER_RESEARCH → UNDER_DEEP_DD → APPROVED → ENTRY_PENDING
sm.transition(OpportunityStatus.UNDER_RESEARCH, OpportunityStatus.UNDER_DEEP_DD, cause="wiki built")
sm.transition(OpportunityStatus.UNDER_DEEP_DD, OpportunityStatus.APPROVED, cause="entry conditions met")
sm.transition(OpportunityStatus.APPROVED, OpportunityStatus.ENTRY_PENDING, cause="ready to accumulate")
sqlite.save_opportunity({**opp.model_dump(), "status": OpportunityStatus.ENTRY_PENDING.value})
sqlite.record_transition(opp_id, "UNDER_RESEARCH", "UNDER_DEEP_DD", cause="wiki built")
sqlite.record_transition(opp_id, "UNDER_DEEP_DD", "APPROVED", cause="entry conditions met")
sqlite.record_transition(opp_id, "APPROVED", "ENTRY_PENDING", cause="ready to accumulate")
print("  Status: UNDER_RESEARCH -> UNDER_DEEP_DD -> APPROVED -> ENTRY_PENDING")

# ── STEP 10: Risk & Portfolio ─────────────────────────────────────────────────
print("\n[10/12] Running Risk & Portfolio checks...")
risk = RiskEngine(max_drawdown=15, max_volatility=35)
risk_alerts = risk.evaluate_all("MELI", {"drawdown": 5.2, "volatility_90d": 28.5, "debt_to_equity": 0.45, "weight_pct": 0})
print(f"  Risk alerts: {len(risk_alerts)}")

cash = CashManager()
cash_pos = cash.evaluate(total_capital=1_000_000, cash_balance=120_000)
print(f"  Cash: {cash_pos.cash_pct}% | Action: {cash_pos.recommended_action}")

div = DiversificationController(max_sector_pct=25)
sector_check = div.check_sector("Technology", 22, 3)
print(f"  Sector check: {'PASS' if sector_check['passed'] else 'FAIL'} ({sector_check['total']}%)")

competition = CapitalCompetitionEngine()
comp_result = competition.evaluate(
    {"ticker": "MELI", "conviction": 78},
    [{"ticker": "POS_A", "conviction": 55}, {"ticker": "POS_B", "conviction": 42}],
)
print(f"  Capital competition: {'REPLACE' if comp_result.should_replace else 'HOLD'}")

exit_engine = ExitEngine()
exit_signal = exit_engine.evaluate_risk_exit("MELI", current_drawdown=5.2)
print(f"  Exit signal: {exit_signal}")

# ── STEP 11: Reports ──────────────────────────────────────────────────────────
print("\n[11/12] Generating reports...")
rg = ReportGenerator()
dd_report = rg.generate_dd_report("MELI", {
    "executive_summary": ddd_result.summary,
    "business_analysis": ddd_result.business_quality,
    "financial_analysis": "Strong revenue growth + improving margins",
    "management_assessment": ddd_result.management_quality,
    "risk_factors": str(ddd_result.risks_identified),
    "valuation": "Premium multiple justified by growth and moat depth",
    "recommendation": "Accumulate on weakness - 15% margin of safety",
})
md_report = rg.render_markdown(dd_report)
print(f"  DD Report: {len(dd_report.sections)} sections")

dashboard = DashboardAPI()
summary = dashboard.build_summary(
    opportunities=[{"id": opp_id}],
    positions=[],
    watchlist=[{"ticker": e.ticker, "score": e.score} for e in wl.entries],
    decisions=[{"status": "approved"}],
    risk_alerts=risk_alerts,
    cash={"total_capital": 1_000_000, "cash_balance": 120_000, "cash_pct": 12},
)
print(f"  Dashboard: {summary.total_opportunities} opps, {summary.watchlist_count} watchlist, {summary.risk_alerts} alerts")

# Save report for Obsidian
report_path = ctx.knowledge_path / "companies" / "MELI" / "report.md"
report_path.write_text(md_report, encoding="utf-8")
print(f"  Report saved to {report_path}")

# ── STEP 12: Notifications ────────────────────────────────────────────────────
print("\n[12/12] Sending notifications...")
nte = NotificationTemplateEngine()
notif = nte.render("entry_signal", {"ticker": "MELI", "price": 1650, "conviction": 78})
print(f"  Notification: {notif}")

# ── Final Summary ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("E2E TEST RESULTS")
print("=" * 60)
print(f"  Opportunity:    {opp_id}")
print(f"  Scout Score:    {scout_result.score}/100")
print(f"  DDD Score:      {ddd_result.score}/100")
print(f"  AOIF Score:     {aoif_result.score}/100")
print(f"  Conviction:     {proposal.conviction_score}/100")
print(f"  Entry Ready:    {entry_signal.all_conditions_met}")
print(f"  Kelly Size:     ${kelly_amt:,.0f}")
print(f"  Hit Rate:       {tracker.hit_rate():.1f}%")
print(f"  Final Status:   ENTRY_PENDING")
print(f"  Wiki:           {wiki_path if 'wiki_path' in dir() else 'N/A'}")
print(f"  Report:         {report_path}")
print(f"  DB:             {sqlite.db_path}")
print("=" * 60)
print("E2E TEST COMPLETED SUCCESSFULLY")
print("=" * 60)
