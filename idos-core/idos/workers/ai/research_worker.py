Warning: truncated output (original token count: 21956)
Total output lines: 1697

import time
import math
import re
import hashlib
import json
from urllib.parse import quote
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.data.journal import JournalRepository
from idos.data.knowledge import KnowledgeRepository
from idos.data.sqlite import SQLiteStore
from idos.data.financial_metrics import normalize_percentage_units
from idos.models.enums import OpportunityStatus, HypothesisStatus, HypothesisPriority
from idos.models.knowledge import Hypothesis, Prediction, FalsificationCondition
from idos.state.machine import OpportunityStateMachine
from idos.workers.base import BaseWorker
from idos.timezone import AR_TZ
from idos.strategy.catalog import StrategyCatalog
from idos.strategy.signals import SignalEvidenceError, current_selection
from idos.decision.scenarios import (
    scenario_source_urls_from_evidence,
    canonicalize_scenario_ticker_url_case,
    validate_scenario_analysis,
)
from idos.decision.manager_approval import invalidate_manager_approval_after_research
from idos.research.thesis_schedule import interval_days_for
from idos.research.events import canonical_event_type, normalize_event_evidence


_FINANCIAL_CUTOFF_FIELDS = (
    "fundamentals_as_of",
    "period_end_date",
    "fiscal_period_end",
    "financial_period_end_timestamp",
    "provider_data_updated_date",
    "as_of_date",
)


def _has_sourced_financial_cutoff(data: dict[str, Any]) -> bool:
    provenance = data.get("data_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    sources = provenance.get("sources_used")
    has_source = bool(data.get("source") or (isinstance(sources, list) and sources))
    if not has_source:
        return False
    cutoff_field = next((key for key in _FINANCIAL_CUTOFF_FIELDS if data.get(key) is not None), None)
    raw_date = data.get(cutoff_field) if cutoff_field else None
    if cutoff_field == "provider_data_updated_date":
        field_sources = provenance.get("field_sources")
        if not isinstance(field_sources, dict) or not field_sources.get(cutoff_field):
            return False
    if isinstance(raw_date, (int, float)) and not isinstance(raw_date, bool):
        if not 946684800 <= raw_date <= 4102444800:
            return False
        cutoff = datetime.fromtimestamp(raw_date, timezone.utc).date()
    elif isinstance(raw_date, datetime):
        cutoff = raw_date.date()
    elif isinstance(raw_date, date):
        cutoff = raw_date
    elif isinstance(raw_date, str):
        try:
            cutoff = date.fromisoformat(raw_date[:10])
        except ValueError:
            return False
    else:
        return False
    return cutoff <= datetime.now(AR_TZ).date()

class ResearchWorker(BaseWorker):
    """Orchestrates the full research pipeline: DDD -> AOIF -> Hypothesis.

    Triggers: manual (CLI), monthly DDD pipeline (SCREENED), or 30-day re-research (UNDER_RESEARCH with force=true).
    Transitions:
      - SCREENED -> UNDER_RESEARCH (first research)
      - UNDER_RESEARCH -> UNDER_RESEARCH (re-research with force=true)
    """
    name = "research_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        cfg = config or {}
        self.llm = cfg.get("llm_service") or LLMClient(
            provider=cfg.get("provider", ""),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", ""),
            fallback_model=cfg.get("fallback_model", ""),
            fallback_providers=cfg.get("fallback_providers", []),
        )
        prompts_path = cfg.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()
        self.state_machine = OpportunityStateMachine()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "").upper().strip()
        opp_id = context.get("opp_id", "")
        base_path = context.get("base_path", "")
        force_reprocess = context.get("force_reprocess", False)
        event_type = context.get("event_type", "manual")
        event_evidence = context.get("event_evidence")
        if not ticker or not opp_id:
            msg = "Both ticker and opp_id are required"
            raise ValueError(msg)
        if canonical_event_type(event_type):
            event_evidence = normalize_event_evidence(event_type, ticker, event_evidence)
        elif event_evidence is not None:
            raise ValueError("event_evidence sólo se admite para triggers materiales")

        bp = Path(base_path) if base_path else Path.cwd()
        sqlite = SQLiteStore(bp / "idos.db")
        knowledge = KnowledgeRepository(bp / "idos-knowledge")
        journal = JournalRepository(bp / "idos-journal")

        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            yaml_opp = journal.load_opportunity(ticker, opp_id)
            if yaml_opp:
                sqlite.save_opportunity(yaml_opp)
                opp = sqlite.get_opportunity(opp_id)
                # Keep strategy-specific fields that older SQLite schemas did
                # not persist (notably the raw Momentum signal).
                if opp is not None:
                    for key in (
                        "signal", "strategy_id", "strategy_version", "research_profile", "entry_policy",
                        "discovery_evidence", "latest_discovery_evidence",
                    ):
                        if key in yaml_opp:
                            opp[key] = yaml_opp[key]
                print(f"[RESEARCH] {ticker}: restored from journal YAML -> SQLite")
        else:
            yaml_opp = journal.load_opportunity(ticker, opp_id)
            if yaml_opp:
                for key in (
                    "signal", "strategy_id", "strategy_version", "research_profile", "entry_policy",
                    "discovery_evidence", "latest_discovery_evidence",
                ):
                    if not opp.get(key) and yaml_opp.get(key):
                        opp[key] = yaml_opp[key]
        if not opp:
            msg = f"Opportunity {opp_id} not found"
            raise ValueError(msg)

        current_status = OpportunityStatus(opp["status"])
        research_profile = str(opp.get("research_profile", "")).lower()
        is_systematic = research_profile == "systematic"
        is_multibaggers = research_profile == "multibaggers"
        systematic_params = {}
        signal_snapshot = None
        research_intake = None
        if is_systematic:
            profile = StrategyCatalog(bp / "idos-config" / "strategies.yml").require(opp.get("strategy_id", ""))
            if not profile.enabled or profile.research_profile != "systematic":
                raise ValueError("Systematic research requires an enabled systematic strategy")
            systematic_params = profile.parameters
            if current_status not in {OpportunityStatus.SCREENED, OpportunityStatus.UNDER_RESEARCH}:
                return {"ticker": ticker, "opp_id": opp_id, "status": "skipped", "reason": "reviewed_opportunity_signal_locked"}
            try:
                signal_snapshot = current_selection(bp, profile.strategy_id, ticker, systematic_params)
            except SignalEvidenceError as exc:
                return {"ticker": ticker, "opp_id": opp_id, "status": "blocked", "reason": str(exc)}
            opp["signal"] = signal_snapshot["signal"]
        if is_multibaggers:
            profile = StrategyCatalog(bp / "idos-config" / "strategies.yml").require(
                opp.get("strategy_id", "")
            )
            if (
                not profile.enabled
                or profile.research_profile != "multibaggers"
                or profile.strategy_version != str(opp.get("strategy_version", ""))
            ):
                raise ValueError("MULTIBAGGERS research requires a matching enabled strategy profile")
            opportunity_dir = journal.opportunity_path(ticker, opp_id)
            intake_path = opportunity_dir / "research_intake.yml"
            snapshot_path = opportunity_dir / "discovery_snapshot.yml"
            if not intake_path.is_file() or not snapshot_path.is_file():
                raise ValueError(f"MULTIBAGGERS Discovery evidence is missing for {ticker}/{opp_id}")
            import yaml
            research_intake = yaml.safe_load(intake_path.read_text(encoding="utf-8")) or {}
            discovery_snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8")) or {}
            if (
                research_intake.get("strategy_id") != profile.strategy_id
                or research_intake.get("research_profile") != "multibaggers"
                or str(research_intake.get("ticker", "")).upper() != ticker
                or research_intake.get("strategy_version") != profile.strategy_version
                or not research_intake.get("snapshot_hash")
                or discovery_snapshot.get("snapshot_hash") != research_intake.get("snapshot_hash")
                or (opp.get("snapshot_hash") and opp.get("snapshot_hash") != research_intake.get("snapshot_hash"))
            ):
                raise ValueError("MULTIBAGGERS Research Intake Package does not match its Discovery snapshot")
        if not force_reprocess:
            if not self.state_machine.can_transition(current_status, OpportunityStatus.UNDER_RESEARCH):
                return {"ticker": ticker, "opp_id": opp_id, "status": "skipped",
                        "reason": f"Cannot transition from {current_status} to UNDER_RESEARCH"}
        else:
            print(f"[FORCE] Reprocessing {ticker} ({opp_id}) from {current_status}, event={event_type}")

        company = knowledge.load_company(ticker) or {}
        financial_data = self._load_financial_data(ticker, sqlite)
        if not company.get("sector"):
            company = self._enrich_company_info(ticker, company, knowledge)

        consensus = None if is_systematic or is_multibaggers else self._fetch_target_consensus(ticker, bp)

        previous_wiki = knowledge.get_wiki_text(ticker)
        prior_catalysts = self._load_prior_catalysts(ticker, journal)

        recent_events = financial_data.get("recent_events", company.get("business_model", "")[:500])
        if event_evidence:
            event_context = json.dumps(event_evidence, ensure_ascii=False, sort_keys=True)
            recent_events = f"{recent_events}\n\nEvento disparador validado para revisar: {event_context}"
        latest_discovery = opp.get("latest_discovery_evidence")
        initial_discovery = opp.get("discovery_evidence")
        discovery_evidence = latest_discovery if isinstance(latest_discovery, dict) else initial_discovery
        financial_data = self._merge_discovery_financial_evidence(financial_data, discovery_evidence)
        latest_quote = latest_discovery.get("market_quote") if isinstance(latest_discovery, dict) else None
        initial_quote = initial_discovery.get("market_quote") if isinstance(initial_discovery, dict) else None
        quote_evidence = {"market_quote": latest_quote or initial_quote}
        price_context = self._current_price_context(financial_data, quote_evidence)

        ddd_inputs = {
            "analysis_as_of_date": datetime.now(AR_TZ).date().isoformat(),
            "ticker": ticker,
            "name": company.get("name", ticker),
            "current_price": price_context["price"],
            "current_price_as_of_date": price_context["as_of_date"],
            "current_price_source": price_context["source"],
            "quote_currency": (
                financial_data.get("quote_currency") or financial_data.get("currency")
                or (quote_evidence.get("market_quote", {}).get("currency")
                    if isinstance(quote_evidence.get("market_quote"), dict) else None)
                or "N/D"
            ),
            "existing_wiki": previous_wiki,
            "prior_catalysts": prior_catalysts,
            "sector": company.get("sector", ""),
            "business_model": company.get("business_model", ""),
            "products": company.get("products", ""),
            "geography": company.get("geography", ""),
            "moat_description": company.get("moat_description", ""),
            "revenue": financial_data.get("revenue_ttm"),
            "revenue_growth": financial_data.get("revenue_growth_pct"),
            "operating_margin": financial_data.get("operating_margin_pct"),
            "roic": financial_data.get("roic_pct"),
            "excess_return_roic_wacc": financial_data.get("excess_return_roic_wacc"),
            "fcf_adjusted": financial_data.get("fcf_adjusted"),
            "debt_to_equity": financial_data.get("debt_equity_ratio"),
            "debt_maturity_profile": financial_data.get("debt_maturity_profile", "N/A"),
            "interest_coverage_ratio": financial_data.get("interest_coverage_ratio"),
            "ceo_tenure": financial_data.get("ceo_tenure"),
            "insider_ownership": financial_data.get("insider_ownership"),
            "capital_allocation": financial_data.get("capital_allocation", "N/A"),
            "recent_events": recent_events,
            "financial_data_evidence": json.dumps(
                self._financial_evidence_context(financial_data),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            "scenario_market_evidence": json.dumps(
                self._scenario_market_evidence(
                    ticker=ticker,
                    price_context=price_context,
                    quote_currency=(
                        financial_data.get("quote_currency")
                        or financial_data.get("currency")
                        or (quote_evidence.get("market_quote", {}).get("currency")
                            if isinstance(quote_evidence.get("market_quote"), dict) else None)
                        or "N/D"
                    ),
                    target_consensus=consensus,
                ),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
        }
        # Systematic strategies have a signal thesis, not a corporate fundamental
        # thesis. Running them through the generic DDD prompt produced the same
        # boilerplate report for every ETF and left the lifecycle dependent on
        # fundamental rules that do not apply to this strategy.
        if is_systematic:
            ddd_result = self._build_systematic_ddd(ticker, opp, systematic_params)
        elif is_multibaggers:
            ddd_result = self._run_prompt("multibaggers", ticker, {
                "ticker": ticker,
                "name": company.get("name", ticker),
                "intake_package": json.dumps(research_intake, ensure_ascii=False, sort_keys=True),
                "financial_summary": json.dumps(ddd_inputs, ensure_ascii=False, sort_keys=True, default=str),
                "research_financial_evidence": json.dumps(
                    self._research_financial_evidence(financial_data),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            })
        else:
            ddd_result = self._run_prompt("ddd", ticker, ddd_inputs)

        classification = ddd_result.get("clasificacion_oportunidad", {})
        if signal_snapshot is not None:
            ddd_result["strategy_context"]["signal_snapshot"] = signal_snapshot
        market_error = ddd_result.get("error_mercado", {})
        thesis = ddd_result.get("tesis_inversion", "")
        score = ddd_result.get("score_general", 50)
        scenario_analysis = None if is_systematic else ddd_result.get("scenario_analysis")
        trusted_scenario_urls = scenario_source_urls_from_evidence(
            ddd_inputs.get("scenario_market_evidence")
        )
        if not is_systematic:
            scenario_analysis = canonicalize_scenario_ticker_url_case(
                scenario_analysis,
                ticker=ticker,
                trusted_source_urls=trusted_scenario_urls,
            )
            if scenario_analysis is not None:
                ddd_result["scenario_analysis"] = scenario_analysis
        scenario_validation_errors = [] if is_systematic else validate_scenario_analysis(
            scenario_analysis,
            trusted_source_urls=trusted_scenario_urls,
        )

        ddd_empty = not any(ddd_result.get(k) for k in ["clasificacion_oportunidad", "tesis_inversion", "dominio_riesgos", "dominio_business_quality"])
        if ddd_empty:
            print(f"[WARN] {ticker}: DDD del LLM vacío — score={score}, clasificacion={classification}, error={ddd_result.get('error','')}")
        elif not ddd_empty and score == 50 and not classification and not thesis:
            print(f"[WARN] {ticker}: DDD con valores por defecto (score=50) — LLM no generó análisis real, error={ddd_result.get('error','')}")

        if ddd_empty:
            failure_reason = ddd_result.get("error") or "DDD returned no usable analysis"
            event_data = {
                "opp_id": opp_id,
                "ticker": ticker,
                "error": failure_reason,
                "event_type": event_type,
                "event_evidence": event_evidence,
                "forced": bool(force_reprocess),
            }
            sqlite.log_event("research:failed", event_data)
            journal.log_event("research:failed", event_data, source="research_worker")
            return {
                "ticker": ticker,
                "opp_id": opp_id,
                "status": "ddd_failed",
                "error": failure_reason,
                "ddd_empty": True,
            }

        ratio_validation_errors = (
            self._validate_multibaggers_ratio_review(
                ddd_result.get("ratios_investigados"),
                (research_intake or {}).get("research_requirements", {}).get("ratios_to_review", []),
                trusted_source_urls={
                    str(item.get("source_url"))
                    for item in self._research_financial_evidence(financial_data)["source_observations"].values()
                    if isinstance(item, dict) and item.get("source_url")
                },
            )
            if is_multibaggers else []
        )
        if ratio_validation_errors:
            failure_reason = "MULTIBAGGERS ratio review contract failed: " + "; ".join(ratio_validation_errors)
            event_data = {"opp_id": opp_id, "ticker": ticker, "errors": ratio_validation_errors}
            sqlite.log_event("research:ratio_review_validation_failed", event_data)
            journal.log_event("research:ratio_review_validation_failed", event_data, source="research_worker")
            return {
                "ticker": ticker,
                "opp_id": opp_id,
                "status": "ddd_failed",
                "error": failure_reason,
                "ratio_validation_errors": ratio_validation_errors,
            }

        generated_at = datetime.now(AR_TZ).isoformat()
        input_snapshot_hash = hashlib.sha256(
            json.dumps(ddd_inputs, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        ddd_report = {
            "ticker": ticker,
            "opp_id": opp_id,
            "version": "3.0",
            "generated_at": generated_at,
            "research_trigger": {
                "trigger_type": event_type,
                "triggered_at": generated_at,
                "strategy_id": opp.get("strategy_id", ""),
                "strategy_version": opp.get("strategy_version", ""),
                "discovery_snapshot_hash": (research_intake or {}).get("snapshot_hash"),
                "event_evidence": event_evidence,
                "input_snapshot_ref": {
                    "path": "research_input_snapshot",
                    "sha256": input_snapshot_hash,
                },
            },
            "research_input_snapshot": ddd_inputs,
            "clasificacion_oportunidad": classification,
            "error_mercado": market_error,
            "tesis_inversion": thesis,
            "score_general": score,
            "strategy_context": ddd_result.get("strategy_context", {}),
            "dominio_riesgos": ddd_result.get("dominio_riesgos", []),
            "dominio_catalizadores": ddd_result.get("dominio_catalizadores", []),
            "dominio_business_quality": ddd_result.get("dominio_business_quality", {}),
            "ratios_investigados": ddd_result.get("ratios_investigados", []),
            "risk_flags": ddd_result.get("risk_flags", []),
            "dominio_financial_health": ddd_result.get("dominio_financial_health", {}),
            "dominio_management": ddd_result.get("dominio_management", {}),
            "dominio_growth": ddd_result.get("dominio_growth", {}),
            "dominio_esg_supply_chain": ddd_result.get("dominio_esg_supply_chain", {}),
            "opinion_valoracion": ddd_result.get("opinion_valoracion", ""),
            "resumen_ejecutivo": ddd_result.get("resumen_ejecutivo", ""),
            "calidad_evidencia": ddd_result.get("calidad_evidencia", {}),
            "integridad_tesis": ddd_result.get("integridad_tesis", {}),
            "target_consensus": consensus,
            "catalizadores_previos": prior_catalysts,
            "comparativa_catalizadores": ddd_result.get("comparativa_catalizadores", []),
            "scenario_analysis": scenario_analysis,
            "scenario_validation": {
                "status": "not_applicable" if is_systematic else "valid_pending_decision_board"
                if not scenario_validation_errors else "invalid_pending_revision",
                "errors": scenario_validation_errors,
            },
            "prompt_inputs": {
                "ticker": ticker,
                "name": company.get("name", ticker),
                "sector": company.get("sector", ""),
                "business_model": company.get("business_model", ""),
                "products": company.get("products", ""),
                "revenue": financial_data.get("revenue_ttm"),
                "revenue_growth": financial_data.get("revenue_growth_pct"),
                "operating_margin": financial_data.get("operating_margin_pct"),
                "roic": financial_data.get("roic_pct"),
                "fcf_adjusted": financial_data.get("fcf_adjusted"),
                "debt_to_equity": financial_data.get("debt_equity_ratio"),
                "pe_ratio": financial_data.get("pe_ratio"),
                "ceo_tenure": financial_data.get("ceo_tenure"),
                "insider_ownership": financial_data.get("insider_ownership"),
            },
        }
        if is_systematic:
            hypothesis_result = {
                "hipotesis": [{
                    "id": "H-MOMENTUM-1",
                    "enunciado": f"La señal mensual de {ticker} permanece entre {systematic_params['minimum_signal']} y {systematic_params['maximum_signal']} hasta el próximo rebalanceo; la asignación requiere revisión privada de riesgo.",
                    "probabilidad": None,
                    "confianza": None,
                    "condiciones_falsacion": [
                        {"condicion": "Señal por debajo del mínimo configurado", "metrica": "momentum_signal", "umbral": systematic_params["minimum_signal"]},…9956 tokens truncated…ource["url"] not in trusted_source_urls for source in sources):
                errors.append(f"ratio cites a URL absent from research evidence: {metric}")
            if status == "calculated":
                if not isinstance(item.get("formula"), str) or not item["formula"].strip():
                    errors.append(f"calculated ratio needs a formula: {metric}")
                if not isinstance(item.get("inputs"), list) or not item["inputs"]:
                    errors.append(f"calculated ratio needs input references: {metric}")
        unexpected = sorted(set(by_metric) - set(required_metrics))
        if unexpected:
            errors.append("unexpected ratio entries: " + ", ".join(unexpected))
        return errors

    @staticmethod
    def _scenario_market_evidence(
        *,
        ticker: str,
        price_context: dict[str, Any],
        quote_currency: str,
        target_consensus: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source_urls = {
            "yfinance": f"https://finance.yahoo.com/quote/{quote(ticker, safe='.-^')}/",
            "finviz": f"https://finviz.com/quote.ashx?t={quote(ticker, safe='.-^')}",
            "stockanalysis": f"https://stockanalysis.com/stocks/{quote(ticker.lower(), safe='.-')}/",
        }
        source_names = [
            source.strip()
            for source in str(price_context.get("source") or "").split(",")
            if source.strip()
        ]
        quote_references = [
            {"name": source, "url": source_urls[source]}
            for source in source_names if source in source_urls
        ]
        consensus = target_consensus if isinstance(target_consensus, dict) else {}
        return {
            "current_quote": {
                "price": price_context.get("price"),
                "currency": quote_currency,
                "as_of_date": price_context.get("as_of_date"),
                "sources": quote_references,
            },
            "analyst_target_consensus": {
                "currency": quote_currency,
                "mean": consensus.get("promedio"),
                "median": consensus.get("mediana"),
                "low": consensus.get("target_low"),
                "high": consensus.get("target_high"),
                "observed_at": consensus.get("calculado_at"),
                "sources": consensus.get("source_references", []),
            } if consensus else None,
        }

    def _build_knowledge_base(
        self,
        ticker: str,
        opp_id: str,
        company: dict[str, Any],
        financial_data: dict[str, Any],
        ddd_result: dict[str, Any],
        aoif_result: dict[str, Any],
        thesis: str,
        knowledge: Any,
        ddd_empty: bool = False,
    ):
        from idos.research.wiki import WikiBuilder
        from idos.knowledge.wiki import AtomicWiki, WikiSection, WikiMetadata
        from idos.knowledge.lifecycle import KnowledgeLifecycle, KnowledgeObject, KnowledgeStatus
        from idos.knowledge.contradiction import ContradictionDetector
        from idos.knowledge.claims import ClaimStore, Claim, EvidenceCategory

        products = company.get("products") or []
        if isinstance(products, str):
            products = [p.strip() for p in products.split(",") if p.strip()]

        wiki_data = {
            "knowledge_base": {
                "static": {
                    "business_model": company.get("business_model", ""),
                    "products": products,
                    "moat_description": company.get("moat_description", ""),
                    "management_history": company.get("management_history", ""),
                },
                "dynamic": {
                    "metrics": {
                        "roic": financial_data.get("roic_pct"),
                        "operating_margin": financial_data.get("operating_margin_pct"),
                        "revenue_growth": financial_data.get("revenue_growth_pct"),
                        "fcf_yield": financial_data.get("fcf_yield", 0),
                        "debt_to_equity": financial_data.get("debt_equity_ratio"),
                        "pe_ratio": financial_data.get("pe_ratio"),
                        "ev_ebitda": financial_data.get("ev_ebitda", 0),
                    }
                }
            },
            "competitors": company.get("competitors", []),
            "catalysts": ddd_result.get("dominio_catalizadores", []),
            "thesis": thesis,
        }
        wiki_builder = WikiBuilder()
        wiki_sections = wiki_builder.build(ticker, wiki_data)
        wiki_md = wiki_builder.render_markdown(wiki_sections)

        ddd_ok = not ddd_empty and not ddd_result.get("error")
        wiki_template = self.registry.get("wiki", category="research")
        if wiki_template and ddd_ok:
            existing = knowledge.get_wiki_text(ticker) or wiki_md
            import json
            ddd_json = json.dumps(ddd_result, indent=2, ensure_ascii=False)
            aoif_json = json.dumps(aoif_result, indent=2, ensure_ascii=False)
            from idos.knowledge.linker import CrossCompanyLinker
            linker = CrossCompanyLinker(knowledge.base)
            related = linker.find_related(ticker)
            related_strs = []
            for cat, tickers in related.items():
                for t in tickers:
                    related_strs.append(f"[[{t}]]")
            related_tickers = ", ".join(related_strs) if related_strs else "Ninguna"
            formatted = wiki_template.format(
                ticker=ticker,
                name=company.get("name", ticker),
                ddd_output=ddd_json,
                aoif_output=aoif_json,
                evidence_chain=f"DDD:\n{ddd_json[:1500]}\n\nAOIF:\n{aoif_json[:1500]}",
                existing_wiki=existing,
                related_tickers=related_tickers,
            )
            wiki_system = self.registry.get_system("wiki", category="research") or ""
            llm_resp = self.llm.generate(
                prompt=formatted,
                system_prompt=wiki_system,
                temperature=0.1,
                max_tokens=4096,
            )
            if llm_resp.success and len(llm_resp.content or "") > 100:
                wiki_md = llm_resp.content

        knowledge.save_wiki(ticker, wiki_md)

        from idos.knowledge.linker import CrossCompanyLinker
        linker = CrossCompanyLinker(knowledge.base)
        wiki_md = linker.inject_links(ticker, wiki_md)
        if wiki_md:
            knowledge.save_wiki(ticker, wiki_md)

        atomic = AtomicWiki(knowledge.base)
        monolith_path = knowledge.knowledge_base_path(ticker) / "static" / "wiki.md"
        if monolith_path.exists():
            atomic.migrate_from_monolith(ticker, monolith_path)

        index_path = knowledge.base / "INDEX.md"
        index_content = knowledge.generate_index()
        index_path.write_text(index_content, encoding="utf-8")

        lifecycle = KnowledgeLifecycle()
        contradiction_detector = ContradictionDetector()
        claim_store = ClaimStore(str(knowledge.base))

        for section in atomic.all_sections(ticker):
            obj = KnowledgeObject(
                object_id=f"wiki-{ticker}-{section.name}",
                object_type="wiki_section",
                ticker=ticker,
                content={"section": section.name, "content": section.content[:500]},
                status=KnowledgeStatus.CREATED,
                confidence=section.metadata.confidence,
            )
            lifecycle.register(obj)
            lifecycle.verify(obj.object_id)
            lifecycle.publish(obj.object_id)

        dd_claims = ddd_result.get("calidad_evidencia", {}).get("hechos_verificados", [])
        for i, fact in enumerate(dd_claims):
            claim = Claim(
                claim_id=f"CLAIM-{ticker}-DDD-{i+1}",
                statement=fact,
                confidence=0.85,
                category=EvidenceCategory.FACT,
                tags=["ddd", ticker],
            )
            claim_store.put(claim)
            contradiction = contradiction_detector.evaluate(
                ticker=ticker,
                claim_statement=fact,
                new_evidence=wiki_md[:2000],
                source=f"DDD {opp_id}",
            )
            if contradiction:
                print(f"[KB] {ticker}: Contradicción: {contradiction.claim_statement} vs {contradiction.conflicting_evidence[:100]}")

        unresolved = contradiction_detector.unresolved()
        if unresolved:
            print(f"[KB] {ticker}: {len(unresolved)} contradicciones sin resolver registradas")

        registered = lifecycle.count()
        if registered:
            print(f"[KB] {ticker}: {registered} secciones wiki registradas en KnowledgeLifecycle")

    def _load_financial_data(self, ticker: str, sqlite: SQLiteStore) -> dict[str, Any]:
        event_data: dict[str, Any] = {}
        try:
            for row in sqlite.conn.execute(
                "SELECT data_json FROM events_log WHERE data_json LIKE ? OR correlation_id LIKE ? ORDER BY timestamp DESC LIMIT 1",
                (f"%{ticker}%", f"%{ticker}%"),
            ):
                import json
                try:
                    candidate = json.loads(row[0])
                    if isinstance(candidate, dict):
                        event_data = candidate
                except (json.JSONDecodeError, IndexError):
                    pass
        except Exception:
            pass
        import json
        cache_data: dict[str, Any] = {}
        for cache_path in [
            Path.cwd() / "cache" / f"{ticker}_financial.json",
            Path.cwd() / "cache" / f"{ticker}.json",
        ]:
            if cache_path.exists():
                try:
                    raw = json.loads(cache_path.read_text(encoding="utf-8"))
                    if raw:
                        if "merged_data" in raw:
                            raw = raw["merged_data"]
                        raw = self._normalize_decimal_pcts(raw)
                        raw = self._enrich_roic(raw)
                        if not isinstance(raw, dict):
                            continue
                        if not cache_data:
                            cache_data = raw
                        if _has_sourced_financial_cutoff(raw):
                            self._warn_missing_financial(ticker, raw, "cache")
                            return raw
                except Exception:
                    pass
        try:
            from idos.workers.data.stockanalysis import StockAnalysisWorker
            sa = StockAnalysisWorker()
            result = sa.run({"ticker": ticker})
            if result:
                cache_dir = Path.cwd() / "cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / f"{ticker}.json").write_text(
                    json.dumps(result, default=str, indent=2), encoding="utf-8"
                )
                result = self._normalize_decimal_pcts(result)
                result = self._enrich_roic(result)
                self._warn_missing_financial(ticker, result, "stockanalysis live")
                return result
        except Exception:
            pass
        if cache_data:
            self._warn_missing_financial(ticker, cache_data, "cache without valid cutoff")
            return cache_data
        if event_data:
            self._warn_missing_financial(ticker, event_data, "SQLite without valid cutoff")
            return event_data
        self._warn_missing_financial(ticker, {}, "ninguna")
        return {}

    @staticmethod
    def _current_price_context(
        data: dict[str, Any], discovery_evidence: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return a sourced quote, falling back only to the latest aligned close."""
        price = data.get("price") or data.get("current_price")
        quote_date = data.get("price_as_of_date") or data.get("current_price_as_of_date")
        if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
            price = None

        prices = data.get("price_history")
        dates = data.get("price_history_dates")
        if price is None and isinstance(prices, list) and isinstance(dates, list) and len(prices) == len(dates):
            for candidate, candidate_date in reversed(list(zip(prices, dates))):
                if (
                    isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                    and math.isfinite(candidate) and candidate > 0
                    and isinstance(candidate_date, str)
                ):
                    try:
                        if date.fromisoformat(candidate_date).isoformat() != candidate_date:
                            continue
                    except ValueError:
                        continue
                    price, quote_date = candidate, candidate_date
                    break

        provenance = data.get("data_provenance")
        field_sources = provenance.get("field_sources", {}) if isinstance(provenance, dict) else {}
        sources = field_sources.get("price_history", []) if isinstance(field_sources, dict) else []
        if not sources:
            quote_provenance = data.get("price_provenance")
            if isinstance(quote_provenance, dict) and quote_provenance.get("source"):
                sources = [quote_provenance["source"]]
        if price is None:
            market_quote = discovery_evidence.get("market_quote") if isinstance(discovery_evidence, dict) else None
            if isinstance(market_quote, dict):
                candidate = market_quote.get("price")
                candidate_date = market_quote.get("as_of_date")
                candidate_source = market_quote.get("source")
                try:
                    valid_date = isinstance(candidate_date, str) and date.fromisoformat(candidate_date).isoformat() == candidate_date
                except ValueError:
                    valid_date = False
                if (
                    isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
                    and math.isfinite(candidate) and candidate > 0
                    and valid_date and isinstance(candidate_source, str) and candidate_source.strip()
                    and isinstance(market_quote.get("currency"), str)
                    and len(market_quote["currency"]) == 3
                    and market_quote["currency"].isalpha()
                    and market_quote["currency"] == market_quote["currency"].upper()
                ):
                    price, quote_date, sources = candidate, candidate_date, [candidate_source]
        source = ", ".join(sorted({str(item) for item in sources if item})) if isinstance(sources, list) else ""
        return {
            "price": price if price is not None else "N/D",
            "as_of_date": quote_date if isinstance(quote_date, str) else "N/D",
            "source": source or "N/D",
        }

    @staticmethod
    def _normalize_decimal_pcts(data: dict[str, Any]) -> dict[str, Any]:
        _aliases = {"pe_ratio_ttm": "pe_ratio", "peg_ratio_ttm": "peg_ratio"}
        for src, dst in _aliases.items():
            if src in data and (dst not in data or data[dst] is None):
                data[dst] = data[src]
        _coerce_keys = {"pe_ratio", "pe_historical_avg", "ev_ebitda", "sector_avg_ev_ebitda",
            "debt_equity_ratio", "volatility_90d", "current_ratio", "relative_strength",
            "short_interest_pct", "analyst_consensus", "ceo_tenure", "insider_ownership",
            "target_price", "recurring_revenue_pct", "fcf_yield",
            "roic_pct", "roe_pct", "roa_pct", "revenue_growth_pct",
            "operating_margin_pct", "gross_margin_pct", "net_margin_pct",
            "fcf_yield_pct", "eps_growth", "fcf_growth", "revenue_growth",
            "operating_margin", "roic", "interest_coverage_ratio"}
        for k in _coerce_keys:
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
        data = normalize_percentage_units(data)
        de = data.get("debt_equity_ratio")
        if isinstance(de, (int, float)):
            if de > 1:
                data["debt_equity_ratio"] = de / 100
        return data

    @staticmethod
    def _enrich_roic(data: dict[str, Any]) -> dict[str, Any]:
        roic = data.get("roic_pct")
        if roic is not None and roic != 0:
            return data
        roe = data.get("roe_pct")
        de = data.get("debt_equity_ratio")
        if roe and isinstance(de, (int, float)):
            data["roic_pct"] = round(roe / (1 + de), 2)
        return data

    @staticmethod
    def _enrich_company_info(ticker: str, company: dict[str, Any], knowledge: Any) -> dict[str, Any]:
        if company.get("sector"):
            return company
        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)
            info = tk.info or {}
            resolved = (info.get("symbol") or ticker).upper().strip()
            if resolved != ticker:
                print(f"[WARN] {ticker}: yfinance resolved to {resolved}, skipping enrich")
                return company
            changed = False
            for k, src in [("sector", "sector"), ("industry", "industry"),
                           ("business_model", "longBusinessSummary")]:
                if not company.get(k) and info.get(src):
                    company[k] = info[src]
                    changed = True
            if not company.get("name") and info.get("longName"):
                company["name"] = info["longName"]
                changed = True
            if changed:
                try:
                    knowledge.save_company(ticker, company)
                    print(f"[INFO] {ticker}: company info enriched from YahooFinance")
                except Exception:
                    pass
        except Exception as e:
            print(f"[WARN] {ticker}: no se pudo enriquecer info corporativa: {e}")
        return company

    @staticmethod
    def _warn_missing_financial(ticker: str, data: dict[str, Any], source: str):
        _critical = ["roic_pct", "operating_margin_pct", "revenue_growth_pct", "pe_ratio", "debt_equity_ratio"]
        for key in _critical:
            val = data.get(key)
            if val is None or val == 0:
                print(f"[WARN] {ticker}: {key} es 0 o None (fuente: {source})")
            elif key in ("pe_ratio", "debt_equity_ratio") and val < 0:
                print(f"[WARN] {ticker}: {key}={val} es negativo (fuente: {source})")
        if not data:
            print(f"[WARN] {ticker}: No hay datos financieros — DDD se generará sin fundamentos")

    def reassess_thesis(self, ticker: str, opp_id: str, sqlite: SQLiteStore,
                        journal: JournalRepository, base_path: Path,
                        trigger_source: str = "manual") -> dict[str, Any]:
        """Run a thesis review as a Research task using the shared LLM service."""
        thesis_statement = ""
        case_summary = ""
        ddd_file = journal.opportunity_path(ticker, opp_id) / "ddd_report.yml"
        if ddd_file.exists():
            import yaml
            try:
                report = yaml.safe_load(ddd_file.read_text(encoding="utf-8")) or {}
                thesis_statement = report.get("tesis_inversion", "")
                integrity = report.get("integridad_tesis", {}) or {}
                if integrity.get("thesis_active") is not None and trigger_source == "manual":
                    case_summary = f"Evaluación DDD previa: {integrity.get('reason', 'sin detalle')}"
            except (OSError, ValueError, TypeError):
                pass

        case_file = journal.load_case_file(ticker)
        if case_file:
            case_summary = (case_summary + "\n" if case_summary else "") + \
                f"Case file: {case_file.get('last_updated', '')} con {len(case_file.get('opportunities', []))} oportunidades"

        financial = self._load_thesis_review_financial_data(ticker, sqlite, base_path)
        financial_summary = self._format_financial_summary(financial)
        opportunity = sqlite.get_opportunity(opp_id) or {}
        conviction = (opportunity.get("conviction") or {}).get("overall", 0)
        return self._run_prompt("thesis_monitor", ticker, {
            "ticker": ticker,
            "name": ticker,
            "thesis_statement": thesis_statement or "No disponible",
            "financial_summary": financial_summary,
            "recent_events": "",
            "case_file_summary": case_summary or "Sin conocimiento acumulado",
            "conviction": conviction,
            "trigger_source": trigger_source,
        })

    @staticmethod
    def _format_financial_summary(data: dict[str, Any]) -> str:
        if not data:
            return "Sin datos financieros disponibles"
        keys = ["revenue_ttm", "revenue_growth_pct", "operating_margin_pct", "roic_pct",
                "debt_equity_ratio", "fcf_adjusted", "pe_ratio", "interest_coverage_ratio"]
        parts = []
        for key in keys:
            value = data.get(key)
            if value is not None and value != "":
                parts.append(f"{key}={value:.1f}" if isinstance(value, float) else f"{key}={value}")
        return ", ".join(parts) or "Sin datos financieros disponibles"

    @staticmethod
    def _load_thesis_review_financial_data(ticker: str, sqlite: SQLiteStore,
                                           base_path: Path) -> dict[str, Any]:
        """Load already available evidence without starting a new provider fetch."""
        import json

        try:
            rows = sqlite.conn.execute(
                "SELECT data_json FROM events_log WHERE event_type LIKE ? AND data_json LIKE ? ORDER BY timestamp DESC LIMIT 1",
                (f"%{ticker}%", f"%{ticker}%"),
            )
            for row in rows:
                try:
                    data = json.loads(row[0])
                    if isinstance(data, dict) and data:
                        return data
                except (json.JSONDecodeError, IndexError, TypeError):
                    continue
        except Exception:
            pass

        cache_file = base_path / "cache" / f"{ticker}.json"
        try:
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        data = raw.get("merged_data", raw)
        return data if isinstance(data, dict) else {}

    def _run_prompt(self, prompt_name: str, ticker: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        template = self.registry.get(prompt_name, category="research")
        if not template:
            return {}
        system = self.registry.get_system(prompt_name, category="research") or ""
        formatted = template.format(**kwargs) if isinstance(template, str) else template
        result = self.llm.generate_structured(
            prompt=formatted,
            system_prompt=system,
            temperature=0.1,
        )
        return result


