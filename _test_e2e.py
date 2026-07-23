"""
Test E2E: Caso 1 (PENDING_REVIEW -> APPROVED) y Caso 2 (APPROVED -> ACCUMULATING via Entry Monitor + Wyckoff).
Ejecutar desde la raiz del repo: python _test_e2e.py
"""
import sys, json, yaml, math
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, "idos-core")

from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository
from idos.models.enums import OpportunityStatus
from idos.decision.engines.business import BusinessAssessmentEngine
from idos.decision.engines.valuation import ValuationAssessmentEngine
from idos.decision.engines.recovery import RecoveryAssessmentEngine
from idos.decision.engines.risk import RiskAssessmentEngine
from idos.decision.engines.portfolio import PortfolioAssessmentEngine
from idos.decision.orchestrator import DecisionOrchestrator
from idos.decision.conviction import ConvictionCalculator
from idos.decision.board import DecisionBoard
from idos.rules.engine import RulesEngine
from idos.decision.assessment_pipeline import build_context, _register_assessment_rules, _add_to_buylist
from idos.workers.portfolio.entry_monitor_worker import EntryMonitorWorker

TICKER1 = "TEST1"
TICKER2 = "TEST2"
OPP_ID1 = "OPP-TEST1-001"
OPP_ID2 = "OPP-TEST2-001"
BASE = Path(".").resolve()

# ─── helpers ──────────────────────────────────────

def _create_cache(ticker, price_target_avg, market_cap, shares_outstanding, **extra):
    cache_dir = BASE / "cache"
    cache_dir.mkdir(exist_ok=True)
    data = {
        "ticker": ticker,
        "source": "stockanalysis.com",
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
        "price_target_avg": price_target_avg,
        "revenue_growth_pct": 15.0,
        "operating_margin_pct": 25.0,
        "roic_pct": 20.0,
        "roe_pct": 25.0,
        "roa_pct": 10.0,
        "gross_margin_pct": 60.0,
        "net_margin_pct": 15.0,
        "fcf_yield_pct": 4.0,
        "fcf_margin_pct": 12.0,
        "fcf_per_share": 5.0,
        "pe_ratio_ttm": 22.0,
        "forward_pe": 20.0,
        "peg_ratio": 1.5,
        "pb_ratio": 4.0,
        "ps_ratio_ttm": 3.0,
        "ev_ebitda": 15.0,
        "ev_ebit": 18.0,
        "ev_sales": 3.5,
        "ev_fcf": 25.0,
        "debt_equity_ratio": 0.3,
        "current_ratio": 2.0,
        "quick_ratio": 1.5,
        "beta_5y": 1.1,
        "short_pct_of_float": 3.5,
        "short_ratio": 1.5,
        "analyst_consensus": "Strong Buy",
        "payout_ratio_pct": 20.0,
        "dividend_yield_pct": 0.5,
        "revenue_ttm": 10_000_000_000,
        "ebitda": 3_500_000_000,
        "ebit": 2_500_000_000,
        "fcf": 2_000_000_000,
        "enterprise_value": 150_000_000_000,
        "ma_50d": 145.0,
        "ma_200d": 135.0,
        "forward_ps": 2.8,
        "p_fcf_ratio": 30.0,
        "debt_ebitda": 0.5,
        "ebitda_margin_pct": 35.0,
        "pretax_margin_pct": 25.0,
        "volume_avg": 5_000_000,
        **extra,
    }
    (cache_dir / f"{ticker}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

def _create_ddd_report(ticker, opp_id):
    ddd_dir = BASE / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id
    ddd_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "ticker": ticker,
        "opp_id": opp_id,
        "version": "3.0",
        "tesis_inversion": f"{ticker} es un compounder con ROIC > 20% y crecimiento sostenible",
        "clasificacion_oportunidad": {"categoria": "compounder", "justificacion": "ROIC>20%, crecimiento 15%"},
        "error_mercado": {"conclusion_error_valoracion": "SI"},
        "score_general": 80,
        "dominio_business_quality": {"rating": "excepcional", "analisis": "Moat amplio, ROIC > 20%"},
        "dominio_financial_health": {"rating": "fuerte", "analisis": "D/E < 0.3"},
        "dominio_management": {"rating": "excepcional", "analisis": "CEO con track record solido"},
        "dominio_growth": {"rating": "fuerte", "analisis": "Crecimiento organico 15% anual"},
        "dominio_riesgos": [{"riesgo": "Desaceleracion macro", "probabilidad": "media", "impacto": "medio", "descripcion": "Riesgo de recesion"}],
        "dominio_catalizadores": [
            {"descripcion": "Earnings beat", "probabilidad_pct": 60, "impacto": "alto", "horizonte": "corto", "nivel_confianza": "alto"},
            {"descripcion": "Nuevo producto", "probabilidad_pct": 30, "impacto": "medio", "horizonte": "medio", "nivel_confianza": "medio"},
            {"descripcion": "Recompra de acciones", "probabilidad_pct": 10, "impacto": "bajo", "horizonte": "largo", "nivel_confianza": "bajo"},
        ],
        "dominio_esg_supply_chain": {"rating": "bajo_riesgo", "analisis": "Sin concentracion"},
        "opinion_valoracion": "infravalorado",
        "resumen_ejecutivo": f"Oportunidad asimetrica en {ticker} con catalizadores claros",
    }
    (ddd_dir / "ddd_report.yml").write_text(yaml.dump(report, default_flow_style=False, allow_unicode=True), encoding="utf-8")


def _create_company_knowledge(ticker, knowledge):
    wiki = {
        "name": f"{ticker} Test Corp",
        "ticker": ticker,
        "sector": "Technology",
        "business_model": "Software platform con efectos de red",
        "products": ["Product A", "Product B"],
        "moat_description": "Moat de switching cost y efecto red",
        "moat_type": "network_effect",
        "competitive_advantages": ["Ventaja de escala", "Efecto red", "Alta retention"],
        "management_history": "CEO fundador con 15 anos de experiencia",
        "founder_info": "Fundada en 2010",
    }
    knowledge.save_company(ticker, wiki)


def _create_price_data_accumulation(length=90):
    """Genera datos sinteticos que simulan acumulacion Wyckoff."""
    prices, volumes = [], []
    # Fase 1: Markdown (1-30)
    for i in range(30):
        t = i / 30
        p = 100 - t * 28
        v = 150_000 + t * 50_000
        prices.append(round(p + (i % 5 - 2) * 0.3, 2))
        volumes.append(int(v))
    # Fase 2: Base building (31-60)
    for i in range(30):
        p = 72 + math.sin(i * 0.3) * 3
        v = 120_000 - i * 1500
        prices.append(round(p, 2))
        volumes.append(int(v))
    # Fase 3: Acumulacion (61-90) - price stabilizes, volume drops sharply
    for i in range(length - 60):
        p = 73 + math.sin(i * 0.15) * 2
        v = 70_000 - i * 1200
        v = max(v, 20_000)
        prices.append(round(p, 2))
        volumes.append(int(v))
    return prices, volumes


def _seed_opportunity(sqlite, journal, ticker, opp_id, status, conviction_overall=70, intrinsic=150, current=120, margin_of_safety=30):
    opp = {
        "id": opp_id, "ticker": ticker,
        "status": status.value,
        "conviction": {"overall": conviction_overall, "intrinsic_value": intrinsic, "current_price": current, "margin_of_safety": margin_of_safety},
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    sqlite.save_opportunity(opp)
    journal.save_opportunity(ticker, opp)

# ===================================================
# CASO 1: DISCOVERED -> PENDING_REVIEW -> APPROVED
# ===================================================

print("=" * 60)
print("CASO 1: Oportunidad DISCOVERED -> Evaluacion -> PENDING_REVIEW -> Aprobacion Manual")
print("=" * 60)

# Setup: cache + knowledge + ddd_report + opportunity
print("\n[1/6] Preparando datos...")
_create_cache(TICKER1, price_target_avg=170.0, market_cap=150_000_000_000, shares_outstanding=1_000_000_000)
knowledge = KnowledgeRepository(BASE / "idos-knowledge")
_create_company_knowledge(TICKER1, knowledge)
_create_ddd_report(TICKER1, OPP_ID1)

sqlite = SQLiteStore(BASE / "idos.db")
journal = JournalRepository(BASE / "idos-journal")
_seed_opportunity(sqlite, journal, TICKER1, OPP_ID1, OpportunityStatus.DISCOVERED)

print("  [OK] Cache, knowledge, ddd_report, opportunity creados")

# Run assessment pipeline
print("\n[2/6] Ejecutando assessment engines + reglas + board...")
rules_engine = RulesEngine()
_register_assessment_rules(rules_engine)

orchestrator = DecisionOrchestrator(rules_engine=rules_engine)
orchestrator.register_engine(BusinessAssessmentEngine())
orchestrator.register_engine(ValuationAssessmentEngine())
orchestrator.register_engine(RecoveryAssessmentEngine())
orchestrator.register_engine(RiskAssessmentEngine())
orchestrator.register_engine(PortfolioAssessmentEngine())
orchestrator.conviction_calc = ConvictionCalculator()

# Mock yfinance since TEST1/TEST2 are not real tickers
mock_price = 120.0
mock_info = {
    "currentPrice": mock_price,
    "regularMarketPrice": mock_price,
    "targetMeanPrice": 170.0,
    "targetLowPrice": 140.0,
    "targetHighPrice": 200.0,
}

with patch("yfinance.Ticker") as mock_ticker_cls:
    mock_ticker = MagicMock()
    mock_ticker.info = mock_info
    mock_ticker_cls.return_value = mock_ticker

    ctx = build_context(OPP_ID1, TICKER1, BASE, sqlite, knowledge, journal)
    proposal = orchestrator.run_pipeline("opportunity:transitioned", ctx)

board = DecisionBoard(journal_repo=journal)
board.submit(proposal)
resolution = board.review()

scores = {k: v.score for k, v in proposal.assessments.items()}
print(f"  Scores: Bus={scores['BusinessAssessmentEngine']} Val={scores['ValuationAssessmentEngine']} "
      f"Rec={scores['RecoveryAssessmentEngine']} Risk={scores['RiskAssessmentEngine']} "
      f"Port={scores['PortfolioAssessmentEngine']}")
print(f"  Conviction: {proposal.conviction_score}")
print(f"  Recommendation: {proposal.recommendation}")
print(f"  Rules passed: {proposal.rules_passed}")
print(f"  Rules failed: {proposal.rules_failed}")
print(f"  Board approved: {resolution.approved}")
print(f"  Asymmetry B/R: {ctx.get('asymmetry', {}).get('benefit_risk_ratio', 'N/A')}")

# Update status based on result
new_status = OpportunityStatus.APPROVED if resolution.approved else OpportunityStatus.UNDER_DEEP_DD
if new_status == OpportunityStatus.UNDER_DEEP_DD:
    print("\n[3/6] La oportunidad quedo en UNDER_DEEP_DD (BLOCKED por reglas)")
    print("  Simulando aprobacion manual del board...")
    # Manual approval: change status to APPROVED
    new_status = OpportunityStatus.APPROVED

# Update SQLite + journal
opp = sqlite.get_opportunity(OPP_ID1)
opp["status"] = new_status.value
opp["updated_at"] = "2026-07-23T12:00:00"
sqlite.save_opportunity(opp)
sqlite.record_transition(OPP_ID1, opp["status"], new_status.value, cause="board:approved", worker="test")

yaml_opp = journal.load_opportunity(TICKER1, OPP_ID1)
yaml_opp["status"] = new_status.value
yaml_opp["updated_at"] = "2026-07-23T12:00:00"
yaml_opp.setdefault("conviction", {})["overall"] = proposal.conviction_score
journal.save_opportunity(TICKER1, yaml_opp)

print(f"  [OK] Oportunidad ahora en estado: {new_status.value}")

# Add to persistent buylist
print("\n[4/6] Agregando a Buy List persistente...")
_add_to_buylist(TICKER1, proposal, ctx, OPP_ID1, BASE, knowledge)
buylist_path = BASE / "idos-journal" / "portfolio" / "buylist.yml"
if buylist_path.exists():
    bl = yaml.safe_load(buylist_path.read_text(encoding="utf-8"))
    entries = bl.get("entries", [])
    print(f"  [OK] Buy List actualizada: {len(entries)} entradas")
    for e in entries:
        print(f"       {e['ticker']}: target={e['target_price']}, zone_top={e['buy_zone_top']}, "
              f"conviction={e['conviction_score']}")
else:
    print("  [WARN] Buy List no persiste")

print(f"\n  >>> CASO 1 COMPLETADO: Oportunidad {OPP_ID1} en estado {new_status.value}")
print(f"      Buy List: {'CREADA' if buylist_path.exists() else 'FALLO'}")

# ===================================================
# CASO 2: APPROVED -> ENTRY_PENDING -> ACCUMULATING (via Entry Monitor + Wyckoff)
# ===================================================

print("\n\n" + "=" * 60)
print("CASO 2: Oportunidad APPROVED -> Entry Monitor (Wyckoff) -> ACCUMULATING")
print("=" * 60)

print("\n[1/4] Preparando datos para Entry Monitor...")
# Create price data with Wyckoff accumulation pattern + targetLow/High for asymmetry
prices, volumes = _create_price_data_accumulation(90)
cache_data = {
    "price_history": prices,
    "volume_history": volumes,
    "price_history_dates": [f"2026-0{i//30+1}-{(i%30)+1:02d}" for i in range(90)],
}
# Append to existing cache file
existing = json.loads((BASE / "cache" / f"{TICKER2}.json").read_text(encoding="utf-8")) if (BASE / "cache" / f"{TICKER2}.json").exists() else {}
existing.update(cache_data)
(BASE / "cache" / f"{TICKER2}.json").write_text(json.dumps(existing, indent=2), encoding="utf-8")
print(f"  [OK] Cache con price_history ({len(prices)} datos, fase Wyckoff: acumulacion)")

# Create ddd_report + knowledge
_create_ddd_report(TICKER2, OPP_ID2)
_create_company_knowledge(TICKER2, knowledge)

# Seed opportunity in APPROVED status with intrinsic > current (margin of safety)
intrinsic_val = 150.0
current_val = 120.0
_seed_opportunity(sqlite, journal, TICKER2, OPP_ID2, OpportunityStatus.APPROVED,
                  conviction_overall=75, intrinsic=intrinsic_val, current=current_val)
print(f"  [OK] Oportunidad {OPP_ID2} en estado APPROVED (intrinsic={intrinsic_val}, current={current_val})")

# Run EntryMonitorWorker
print("\n[2/4] Ejecutando EntryMonitorWorker...")
worker = EntryMonitorWorker(config={})  # sin LLM, usa deteccion algoritmica
result = worker.run({
    "ticker": TICKER2,
    "opp_id": OPP_ID2,
    "base_path": str(BASE),
})

print(f"  Status: {result.get('status')}")
print(f"  Price in zone: {result.get('price_in_zone')}")
print(f"  Wyckoff confirmed: {result.get('wyckoff_confirmed')}")
print(f"  Thesis active: {result.get('thesis_active')}")
print(f"  Portfolio fit: {result.get('portfolio_fit')}")
print(f"  All conditions met: {result.get('entry_executed')}")
print(f"  Wyckoff phase: {result.get('wyckoff_phase')}")
print(f"  Margin of safety: {result.get('margin_of_safety_pct')}%")
print(f"  Current price: {result.get('current_price')}")
print(f"  Target price: {result.get('target_price')}")

# Check final state
opp_check = sqlite.get_opportunity(OPP_ID2)
final_status = OpportunityStatus(opp_check["status"]) if opp_check else None
print(f"\n[4/4] Estado final en SQLite: {final_status}")
if final_status == OpportunityStatus.ACCUMULATING:
    print("  >>> CASO 2 COMPLETADO: Oportunidad en ACCUMULATING (senal de entrada ejecutada)")
else:
    print("  >>> CASO 2: Oportunidad NO entro en acumulacion (revisar condiciones)")

print("\n" + "=" * 60)
print("FIN DE TEST E2E")
print("=" * 60)
