from datetime import datetime
from typing import Any
from uuid import uuid4

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.data.sqlite import SQLiteStore
from idos.models.enums import OpportunityStatus
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ

class ResearchWorker(BaseWorker):
    """Orchestrates the full research pipeline: DDD -> AOIF -> Hypothesis.

    Triggers: manual (CLI) or automatic when an opportunity is promoted from WATCHLIST.
    Transitions: WATCHLIST -> UNDER_DEEP_DD
    """
    name = "research_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.llm = LLMClient(
            provider=config.get("provider", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
        )
        prompts_path = config.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()
        self.state_machine = OpportunityStateMachine()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        base_path = context.get("base_path", "")
        force_reprocess = context.get("force_reprocess", False)
        event_type = context.get("event_type", "manual")
        if not ticker or not opp_id:
            msg = "Both ticker and opp_id are required"
            raise ValueError(msg)

        from pathlib import Path
        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        knowledge = KnowledgeRepository(bp / "idos-knowledge")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            msg = f"Opportunity {opp_id} not found"
            raise ValueError(msg)

        current_status = OpportunityStatus(opp["status"])
        if not force_reprocess:
            if not self.state_machine.can_transition(current_status, OpportunityStatus.UNDER_DEEP_DD):
                return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                        "reason": f"Cannot transition from {current_status} to UNDER_DEEP_DD"}
        else:
            print(f"[FORCE] Reprocessing {ticker} ({opp_id}) from {current_status}, event={event_type}")

        company = knowledge.load_company(ticker) or {}
        wiki = knowledge.get_wiki_text(ticker)
        financial_data = self._load_financial_data(ticker, sqlite)

        ddd_result = self._run_prompt("ddd", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "sector": company.get("sector", ""),
            "business_model": company.get("business_model", ""),
            "products": company.get("products", ""),
            "geography": company.get("geography", ""),
            "moat_description": company.get("moat_description", ""),
            "revenue": financial_data.get("revenue_ttm", 0),
            "revenue_growth": financial_data.get("revenue_growth_pct", 0),
            "operating_margin": financial_data.get("operating_margin_pct", 0),
            "roic": financial_data.get("roic_pct", 0),
            "excess_return_roic_wacc": financial_data.get("excess_return_roic_wacc", 0),
            "fcf_adjusted": financial_data.get("fcf_adjusted", 0),
            "debt_to_equity": financial_data.get("debt_equity_ratio", 0),
            "debt_maturity_profile": financial_data.get("debt_maturity_profile", "N/A"),
            "interest_coverage_ratio": financial_data.get("interest_coverage_ratio", 0),
            "ceo_tenure": financial_data.get("ceo_tenure", 0),
            "insider_ownership": financial_data.get("insider_ownership", 0),
            "capital_allocation": financial_data.get("capital_allocation", "N/A"),
            "recent_events": financial_data.get("recent_events", wiki[:500]),
        })

        classification = ddd_result.get("clasificacion_oportunidad", {})
        market_error = ddd_result.get("error_mercado", {})
        thesis = ddd_result.get("tesis_inversion", "")
        score = ddd_result.get("score_general", 50)

        ddd_report = {
            "ticker": ticker,
            "opp_id": opp_id,
            "version": "3.0",
            "generated_at": datetime.now(AR_TZ).isoformat(),
            "clasificacion_oportunidad": classification,
            "error_mercado": market_error,
            "tesis_inversion": thesis,
            "score_general": score,
            "dominio_riesgos": ddd_result.get("dominio_riesgos", []),
            "analisis_competitivo": ddd_result.get("analisis_competitivo", {}),
            "analisis_financiero": ddd_result.get("analisis_financiero", {}),
            "analisis_gestion": ddd_result.get("analisis_gestion", {}),
            "catalizadores": ddd_result.get("catalizadores", []),
            "escenarios": ddd_result.get("escenarios", {}),
            "plan_inversion": ddd_result.get("plan_inversion", {}),
            "raw_prompt_inputs": {
                "ticker": ticker,
                "name": company.get("name", ticker),
                "sector": company.get("sector", ""),
                "business_model": company.get("business_model", ""),
                "products": company.get("products", ""),
                "revenue": financial_data.get("revenue_ttm", 0),
                "revenue_growth": financial_data.get("revenue_growth_pct", 0),
                "operating_margin": financial_data.get("operating_margin_pct", 0),
                "roic": financial_data.get("roic_pct", 0),
                "fcf_adjusted": financial_data.get("fcf_adjusted", 0),
                "debt_to_equity": financial_data.get("debt_equity_ratio", 0),
                "pe_ratio": financial_data.get("pe_ratio", 0),
            },
        }
        report_path = bp / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id / "ddd_report.yml"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml as yaml_lib
        with open(report_path, "w", encoding="utf-8") as f:
            yaml_lib.dump(ddd_report, f, default_flow_style=False, allow_unicode=True)

        hypothesis_result = self._run_prompt("hypothesis", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "sector": company.get("sector", ""),
            "thesis_statement": thesis,
            "key_drivers": market_error.get("hipotesis_contraria", ""),
            "recent_events": financial_data.get("recent_events", ""),
        })

        aoif_result = self._run_prompt("aoif", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "company_data": f"Sector: {company.get('sector', '')}\nBusiness: {company.get('business_model', '')}\nWiki: {wiki[:2000]}",
            "roic": financial_data.get("roic_pct", 0),
            "operating_margin": financial_data.get("operating_margin_pct", 0),
            "revenue_growth": financial_data.get("revenue_growth_pct", 0),
            "pe_ratio": financial_data.get("pe_ratio", 0),
            "ev_ebitda": financial_data.get("ev_ebitda", 0),
            "fcf_yield": financial_data.get("fcf_yield", 0),
        })

        assessment_id = f"ass-{uuid4().hex[:8]}"
        assessment = {
            "id": assessment_id,
            "engine": "ResearchWorker",
            "version": "3.0",
            "status": "COMPLETED",
            "score": score,
            "confidence": "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW",
            "findings": [
                f"Classification: {classification.get('categoria', 'unknown')}",
                f"Market error: {market_error.get('conclusion_error_valoracion', 'N/A')}",
                f"Thesis: {thesis[:200]}",
            ],
            "risks": ddd_result.get("dominio_riesgos", []),
            "recommendation": "REVIEW",
            "generated_at": datetime.now(AR_TZ).isoformat(),
        }
        journal.save_assessment(ticker, opp_id, assessment)

        hypotheses = hypothesis_result.get("hipotesis", [])
        case_file = journal.load_case_file(ticker) or {
            "ticker": ticker,
            "company_name": company.get("name", ticker),
            "created_at": datetime.now(AR_TZ).isoformat(),
            "opportunities": [],
        }
        case_file.setdefault("opportunities", [])
        if opp_id not in case_file["opportunities"]:
            case_file["opportunities"].append(opp_id)
        case_file["last_updated"] = datetime.now(AR_TZ).isoformat()
        journal.save_case_file(ticker, case_file)

        opp["updated_at"] = datetime.now(AR_TZ).isoformat()
        sqlite.save_opportunity(opp)

        if not force_reprocess:
            opp["status"] = OpportunityStatus.UNDER_DEEP_DD.value
            sqlite.save_opportunity(opp)
            sqlite.record_transition(opp_id, current_status.value, "UNDER_DEEP_DD",
                                     cause="research_completed", worker="research_worker")
            event_data = {
                "opp_id": opp_id, "ticker": ticker,
                "score": score, "hypotheses": len(hypotheses),
                "classification": classification.get("categoria"),
            }
            sqlite.log_event("research:completed", event_data)
            journal.log_event("research:completed", event_data, source="research_worker")
        else:
            event_data = {
                "opp_id": opp_id, "ticker": ticker,
                "score": score, "hypotheses": len(hypotheses),
                "classification": classification.get("categoria"),
                "event_type": event_type,
                "original_status": current_status.value,
            }
            sqlite.log_event("research:force_reprocess", event_data)
            journal.log_event("research:force_reprocess", event_data, source="research_worker")

        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "score": score,
            "classification": classification.get("categoria"),
            "market_error_conclusion": market_error.get("conclusion_error_valoracion"),
            "hypotheses_count": len(hypotheses),
            "assessment_id": assessment_id,
        }

    def _load_financial_data(self, ticker: str, sqlite: SQLiteStore) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for row in sqlite.conn.execute(
            "SELECT data_json FROM events_log WHERE event_type LIKE ? AND data_json LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (f"%{ticker}%", f"%{ticker}%"),
        ):
            import json
            try:
                data = json.loads(row[0])
            except (json.JSONDecodeError, IndexError):
                pass
        return data

    def _run_prompt(self, prompt_name: str, ticker: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        template = self.registry.get(prompt_name, category="research")
        if not template:
            return {}
        system = self.registry.get_system(prompt_name, category="research") or ""
        formatted = template.format(**kwargs) if isinstance(template, str) else template
        return self.llm.generate_structured(
            prompt=formatted,
            system_prompt=system,
            temperature=0.1,
        )
