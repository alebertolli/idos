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
    scenario_financial_evidence_snapshot,
    scenario_source_urls_from_evidence,
    scenario_source_urls_from_research_financial_evidence,
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

        consensus = None if is_systematic else self._fetch_target_consensus(ticker, bp)

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
            requirements = (research_intake or {}).get("research_requirements", {})
            ratio_inputs = requirements.get("ratio_input_fields", {})
            allowed_input_fields = {
                field
                for metric in requirements.get("ratios_to_review", [])
                for field in ratio_inputs.get(metric, [])
            } if isinstance(ratio_inputs, dict) else None
            research_financial_evidence = self._research_financial_evidence(
                financial_data,
                allowed_input_fields=allowed_input_fields or None,
            )
            ddd_result = self._run_prompt("multibaggers", ticker, {
                "ticker": ticker,
                "name": company.get("name", ticker),
                "intake_package": json.dumps(research_intake, ensure_ascii=False, sort_keys=True),
                "financial_summary": json.dumps(
                    self._multibaggers_prompt_context(ddd_inputs),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
                "research_financial_evidence": json.dumps(
                    research_financial_evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            }, max_tokens=8192)
        else:
            ddd_result = self._run_prompt("ddd", ticker, ddd_inputs, max_tokens=8192)

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
        if is_multibaggers:
            trusted_scenario_urls.update(
                scenario_source_urls_from_research_financial_evidence(
                    research_financial_evidence
                )
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

        shape_validation_errors = (
            self._validate_multibaggers_research_shape(ddd_result)
            if is_multibaggers else []
        )
        if shape_validation_errors:
            failure_reason = "MULTIBAGGERS research output shape failed: " + "; ".join(shape_validation_errors)
            print(f"[RESEARCH] {ticker}: {failure_reason}")
            event_data = {"opp_id": opp_id, "ticker": ticker, "errors": shape_validation_errors}
            sqlite.log_event("research:output_shape_validation_failed", event_data)
            journal.log_event("research:output_shape_validation_failed", event_data, source="research_worker")
            return {
                "ticker": ticker,
                "opp_id": opp_id,
                "status": "ddd_failed",
                "error": failure_reason,
                "shape_validation_errors": shape_validation_errors,
            }

        ratio_requirements = (research_intake or {}).get("research_requirements", {})
        expected_ratio_units = ratio_requirements.get("ratio_units", {})
        if is_multibaggers:
            discarded_ratio_calculations = self._discard_calculated_ratios_without_inputs(
                ddd_result.get("ratios_investigados")
            )
            if discarded_ratio_calculations:
                event_data = {
                    "opp_id": opp_id,
                    "ticker": ticker,
                    "metrics": discarded_ratio_calculations,
                }
                sqlite.log_event("research:ratio_calculation_discarded", event_data)
                journal.log_event(
                    "research:ratio_calculation_discarded",
                    event_data,
                    source="research_worker",
                )
            self._normalize_multibaggers_ratio_units(
                ddd_result.get("ratios_investigados"), expected_ratio_units
            )
            self._bind_multibaggers_ratio_sources(
                ddd_result.get("ratios_investigados"), research_financial_evidence
            )
        ratio_validation_errors = (
            self._validate_multibaggers_ratio_review(
                ddd_result.get("ratios_investigados"),
                ratio_requirements.get("ratios_to_review", []),
                trusted_source_urls=set(
                    research_financial_evidence.get("trusted_source_urls", [])
                ) | {
                    str(item.get("source_url"))
                    for item in research_financial_evidence["source_observations"].values()
                    if isinstance(item, dict) and item.get("source_url")
                } | {
                    str(item.get("source_url"))
                    for observations in research_financial_evidence["validated_metric_observations"].values()
                    for item in observations
                    if isinstance(item, dict) and item.get("source_url")
                },
                available_input_fields=(
                    set(research_financial_evidence["source_observations"])
                    | set(research_financial_evidence["validated_metric_observations"])
                    | set(self._multibaggers_financial_input_aliases(research_financial_evidence))
                ),
                expected_units=expected_ratio_units,
            )
            if is_multibaggers else []
        )
        if ratio_validation_errors:
            failure_reason = "MULTIBAGGERS ratio review contract failed: " + "; ".join(ratio_validation_errors)
            print(f"[RESEARCH] {ticker}: {failure_reason}")
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

        if is_multibaggers:
            ddd_inputs["scenario_financial_evidence"] = scenario_financial_evidence_snapshot(
                research_financial_evidence
            )
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
                        {"condicion": "Señal por debajo del mínimo configurado", "metrica": "momentum_signal", "umbral": systematic_params["minimum_signal"]},
                        {"condicion": "Señal por encima del máximo configurado", "metrica": "momentum_signal", "umbral": systematic_params["maximum_signal"]},
                    ],
                }]
            }
        else:
            time.sleep(15)
            hypothesis_prompt_inputs = {
                "ticker": ticker,
                "name": company.get("name", ticker),
                "sector": company.get("sector", ""),
                "as_of_date": datetime.now(AR_TZ).date().isoformat(),
                "thesis_statement": thesis,
                "key_drivers": market_error.get("hipotesis_contraria", ""),
                "recent_events": financial_data.get("recent_events", ""),
                "validation_feedback": "",
            }
            hypothesis_result = self._run_hypothesis_prompt_with_repair(
                ticker, hypothesis_prompt_inputs
            )

        hypotheses = hypothesis_result.get("hipotesis", []) if isinstance(hypothesis_result, dict) else []
        if not is_systematic:
            hypothesis_errors = self._validate_hypothesis_contract(hypotheses)
            if hypothesis_errors:
                print("[HYPOTHESIS] Contract validation failed: " + "; ".join(hypothesis_errors))
                event_data = {
                    "opp_id": opp_id,
                    "ticker": ticker,
                    "errors": hypothesis_errors,
                    "event_type": event_type,
                    "event_evidence": event_evidence,
                }
                sqlite.log_event("research:hypothesis_validation_failed", event_data)
                journal.log_event("research:hypothesis_validation_failed", event_data, source="research_worker")
                return {
                    "ticker": ticker,
                    "opp_id": opp_id,
                    "status": "hypothesis_validation_failed",
                    "errors": hypothesis_errors,
                }

        # Persist a complete report only after its hypothesis contract passes.
        # Otherwise a failed re-research would replace the last usable report.
        report_path = bp / "idos-journal" / "companies" / ticker / "case_file" / "opportunities" / opp_id / "ddd_report.yml"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml as yaml_lib
        with open(report_path, "w", encoding="utf-8") as f:
            yaml_lib.dump(ddd_report, f, default_flow_style=False, allow_unicode=True)

        approval_invalidated = False
        if force_reprocess:
            invalidated_at = datetime.now(AR_TZ).isoformat()
            approval_invalidated = invalidate_manager_approval_after_research(
                bp, ticker, opp_id, invalidated_at=invalidated_at,
            )
            if approval_invalidated:
                opp["approved_for_buylist"] = False
                opp["manager_approval_invalidated_at"] = invalidated_at
                opp["manager_approval_invalidation_reason"] = "new_research_version"
                sqlite.save_opportunity(opp)
                journal.save_opportunity(ticker, opp)
                invalidation_event = {
                    "opp_id": opp_id,
                    "ticker": ticker,
                    "event_type": event_type,
                    "reason": "new_research_version",
                    "invalidated_at": invalidated_at,
                }
                sqlite.log_event("decision:manager_approval_invalidated", invalidation_event)
                journal.log_event(
                    "decision:manager_approval_invalidated",
                    invalidation_event,
                    source="research_worker",
                )

        if is_systematic:
            aoif_result = {
                "tipo_analisis": "systematic_momentum",
                "conclusion": "La decisión depende del ranking mensual y de la disciplina de rebalanceo; no se aplica valoración fundamental.",
                "riesgos": ddd_result.get("dominio_riesgos", []),
            }
        else:
            time.sleep(15)
            aoif_result = self._run_prompt("aoif", ticker, {
            "ticker": ticker,
            "name": company.get("name", ticker),
            "company_data": f"Sector: {company.get('sector', '')}\nBusiness: {company.get('business_model', '')}",
            "roic": financial_data.get("roic_pct"),
            "operating_margin": financial_data.get("operating_margin_pct"),
            "revenue_growth": financial_data.get("revenue_growth_pct"),
            "pe_ratio": financial_data.get("pe_ratio"),
            "ev_ebitda": financial_data.get("ev_ebitda", 0),
            "fcf_yield": financial_data.get("fcf_yield", 0),
            })

        if not is_systematic:
            self._build_knowledge_base(ticker, opp_id, company, financial_data, ddd_result, aoif_result, thesis, knowledge, ddd_empty)

        assessment_id = f"ass-{uuid4().hex[:8]}"
        assessment = {
            "id": assessment_id,
            "engine": "ResearchWorker",
            "version": "3.0",
            "status": "COMPLETED",
            "score": score,
            "confidence": "NOT_ASSESSED" if is_systematic else "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW",
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

        self._persist_hypotheses(ticker, opp_id, thesis, hypotheses, journal, sqlite)

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
        integridad = ddd_result.get("integridad_tesis", {}) or {}
        if "thesis_active" in integridad and integridad["thesis_active"] is not None:
            opp["thesis_active"] = bool(integridad["thesis_active"])
            if not opp["thesis_active"]:
                opp["thesis_invalidated_reason"] = integridad.get("reason", "Tesis invalidada en DDD")
        sqlite.save_opportunity(opp)

        # A forced run is a re-research of an existing opportunity. It must not
        # move a live portfolio lifecycle back to the discovery/research lane.
        # Initial research still promotes the candidate to UNDER_RESEARCH.
        final_status = current_status if force_reprocess else OpportunityStatus.UNDER_RESEARCH
        opp["status"] = final_status.value
        research_completed_at = datetime.now(AR_TZ)
        opp["last_research_at"] = research_completed_at.isoformat()
        next_review = self._next_thesis_review_at(opp, bp, research_completed_at)
        if next_review:
            opp["next_thesis_review_at"] = next_review
        sqlite.save_opportunity(opp)
        journal.save_opportunity(ticker, opp)
        if final_status != current_status:
            sqlite.record_transition(opp_id, current_status.value, final_status.value,
                                     cause="research_completed", worker="research_worker")
        event_data = {
            "opp_id": opp_id, "ticker": ticker,
            "score": score, "hypotheses": len(hypotheses),
            "classification": classification.get("categoria"),
            "event_type": event_type,
            "event_evidence": event_evidence,
            "strategy_version": opp.get("strategy_version", ""),
            "input_snapshot_sha256": input_snapshot_hash,
        }
        event_type_name = "research:completed"
        if force_reprocess:
            event_data.update({
                "event_type": event_type,
                "event_evidence": event_evidence,
                "original_status": current_status.value,
                "ddd_empty": ddd_empty,
            })
            event_type_name = "research:force_reprocess"
        sqlite.log_event(event_type_name, event_data)
        journal.log_event(event_type_name, event_data, source="research_worker")
        return {
            "ticker": ticker,
            "opp_id": opp_id,
            "status": "completed",
            "opportunity_status": final_status.value,
            "score": score,
            "classification": classification.get("categoria"),
            "market_error_conclusion": market_error.get("conclusion_error_valoracion"),
            "hypotheses_count": len(hypotheses),
            "assessment_id": assessment_id,
            "ddd_empty": False,
            "approval_invalidated": approval_invalidated,
            "target_consensus": consensus,
        }

    @staticmethod
    def _next_thesis_review_at(opp: dict[str, Any], base_path: Path, anchor: datetime) -> str | None:
        if str(opp.get("research_profile", "")).lower() == "systematic":
            return None
        catalog = StrategyCatalog(base_path / "idos-config" / "strategies.yml")
        profile = catalog.get(opp.get("strategy_id") or "COMPOUNDER")
        interval = interval_days_for(profile)
        return (anchor + timedelta(days=interval)).isoformat() if interval is not None else None

    @staticmethod
    def _load_prior_catalysts(ticker: str, journal: Any) -> list[dict]:
        """Recolecta los catalizadores de ddd_report previos del ticker (histórico OPP)."""
        import yaml as yaml_lib
        ticker = ticker.upper()
        opp_dir = journal.case_file_path(ticker) / "opportunities"
        prior: list[dict] = []
        if not opp_dir.exists():
            return prior
        for opp in sorted(opp_dir.iterdir()):
            if not opp.is_dir():
                continue
            ddd_file = opp / "ddd_report.yml"
            if not ddd_file.exists():
                continue
            try:
                with open(ddd_file, "r", encoding="utf-8") as f:
                    report = yaml_lib.safe_load(f)
            except Exception:
                continue
            if not report:
                continue
            generated_at = report.get("generated_at", "")
            catalysts = report.get("dominio_catalizadores", []) or []
            for cat in catalysts:
                if not isinstance(cat, dict):
                    continue
                item = {
                    "opp_id": opp.name,
                    "generated_at": generated_at,
                    "descripcion": cat.get("descripcion", ""),
                    "probabilidad_anterior": cat.get("probabilidad_pct"),
                    "impacto": cat.get("impacto", ""),
                    "horizonte": cat.get("horizonte", ""),
                    "nivel_confianza": cat.get("nivel_confianza", ""),
                }
                prior.append(item)
        return prior

    @staticmethod
    def _build_systematic_ddd(ticker: str, opportunity: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        """Build an auditable DDD-shaped report for a signal-driven strategy."""
        signal = opportunity.get("signal") or {}
        momentum = signal.get("momentum")
        minimum = parameters.get("minimum_signal")
        maximum = parameters.get("maximum_signal")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (momentum, minimum, maximum)) or not minimum < maximum or maximum <= 0:
            raise ValueError("Systematic research requires a finite signal and configured signal range")
        # Preserve the existing descriptive normalization, using the configured
        # maximum. This is neither conviction nor a calibrated probability.
        signal_score = max(0, min(100, round(momentum / maximum * 100)))
        within_policy = minimum <= momentum <= maximum
        thesis = f"{ticker}: exposición sistemática a momentum mensual; la señal actual es {momentum:.2f}."
        return {
            "clasificacion_oportunidad": {
                "categoria": "systematic_momentum",
                "categorias_descartadas": ["compounder", "deep_value", "growth_fundamental"],
                "justificacion": "La oportunidad se evalúa por señal, ranking y rebalanceo mensual; no por DDD corporativo.",
            },
            "error_mercado": {
                "conclusion_error_valoracion": "NO_APLICA",
                "hipotesis_contraria": "La persistencia del momentum puede romperse antes del próximo rebalanceo.",
                "consenso_actual": "No se utiliza consenso fundamental.",
                "razonamiento": "La señal cuantitativa y sus límites son la evidencia primaria.",
            },
            "tesis_inversion": thesis,
            "score_general": signal_score,
            "dominio_riesgos": [{
                "riesgo": "Reversión brusca del momentum",
                "probabilidad": "no evaluada",
                "impacto": "alto",
                "descripcion": "La señal puede deteriorarse entre rebalanceos; aplicar límites de peso y salida.",
            }],
            "dominio_catalizadores": [{
                "descripcion": "Persistencia del ranking relativo hasta el próximo rebalanceo",
                "horizonte": "corto",
                "impacto": "alto",
                "probabilidad_pct": None,
            }],
            "dominio_business_quality": {"rating": "no_aplica", "analisis": "No es un criterio de una estrategia sistemática."},
            "dominio_financial_health": {"rating": "no_aplica", "analisis": "No es un criterio de selección de la señal."},
            "dominio_management": {"rating": "no_aplica", "analisis": "No es un criterio de selección de la señal."},
            "dominio_growth": {"rating": "no_aplica", "analisis": "No es un criterio de selección de la señal."},
            "dominio_esg_supply_chain": {"rating": "no_aplica", "analisis": "No es un criterio de selección de la señal."},
            "opinion_valoracion": "No aplica: la entrada se decide por señal y rebalanceo.",
            "resumen_ejecutivo": f"Momentum mensual {momentum:.2f}; rango configurado {minimum:g}–{maximum:g}; índice descriptivo {signal_score}/100. Riesgo y probabilidad no evaluados.",
            "calidad_evidencia": {
                "hechos_verificados": [f"Señal momentum mensual: {momentum:.2f}", f"Fecha de señal: {signal.get('as_of_date', 'N/A')}"],
                "inferencias_llm": [],
                "preguntas_abiertas": ["¿La señal persistirá hasta el próximo rebalanceo?"] ,
            },
            "integridad_tesis": {"thesis_active": within_policy, "reason": "Señal dentro del rango configurado." if within_policy else "Señal fuera del rango configurado."},
            "strategy_context": {
                "strategy_id": opportunity.get("strategy_id"), "signal": signal,
                "risk_rating": "NOT_ASSESSED",
                "signal_policy": {"minimum_signal": minimum, "maximum_signal": maximum},
                "score_method": "momentum_div_max_v1",
                "probability_status": "NOT_ASSESSED",
                "report_method_version": "systematic_signal_v2",
            },
        }

    def _persist_hypotheses(self, ticker: str, opp_id: str, thesis: str,
                            raw: list[Any], journal: Any, sqlite: Any):
        from datetime import datetime
        now = datetime.now(AR_TZ).isoformat()
        for idx, item in enumerate(raw):
            if isinstance(item, str):
                hyp_data: Any = {"statement": item}
            elif isinstance(item, dict):
                hyp_data = item.get("hipotesis", item)
                if isinstance(hyp_data, str):
                    hyp_data = {"statement": hyp_data}
            else:
                continue
            statement = hyp_data.get("hipotesis") or hyp_data.get("statement") or hyp_data.get("enunciado") or ""
            if not statement:
                statement = hyp_data.get("statement_provisional", "")
            raw_id = hyp_data.get("id")
            base_id = raw_id or f"HYP-{idx+1}"
            hyp_id = f"{base_id}-{opp_id}"
            parent_raw = hyp_data.get("parent_id", "")
            parent_id = f"{parent_raw}-{opp_id}" if parent_raw else ""
            raw_dependencies = hyp_data.get("depende_de") or hyp_data.get("depends_on") or []
            if isinstance(raw_dependencies, str):
                raw_dependencies = [raw_dependencies]
            dependencies = [
                item if str(item).endswith(f"-{opp_id}") else f"{item}-{opp_id}"
                for item in raw_dependencies
                if item
            ]
            predictions = []
            raw_predictions = (
                hyp_data.get("predicciones")
                or hyp_data.get("predictions")
                or hyp_data.get("prediccion")
                or hyp_data.get("prediction")
                or []
            )
            if isinstance(raw_predictions, (str, dict)):
                raw_predictions = [raw_predictions]
            magnitude = hyp_data.get("magnitud") or hyp_data.get("magnitude") or {}
            if isinstance(magnitude, dict) and not raw_predictions and magnitude.get("metrica", magnitude.get("metric")):
                raw_predictions = [magnitude]
            for p in raw_predictions:
                if isinstance(p, str):
                    p = {
                        **(magnitude if isinstance(magnitude, dict) else {}),
                        "notes": p,
                    }
                if isinstance(p, dict):
                    expected = p.get("valor_esperado", p.get("expected_value", 0)) or 0
                    if isinstance(expected, str):
                        try:
                            expected = float(expected.replace(",", "."))
                        except ValueError:
                            expected = 0
                    predictions.append(Prediction(
                        metric=p.get("metrica") or p.get("metric", ""),
                        expected_value=expected,
                        unit=p.get("unidad", p.get("unit", "")),
                        deadline=(
                            p.get("fecha_objetivo") or p.get("target_date") or p.get("deadline")
                            or hyp_data.get("fecha_objetivo") or hyp_data.get("target_date")
                            or p.get("plazo") or hyp_data.get("plazo", "")
                        ),
                        notes=p.get("notes") or p.get("prediccion") or p.get("prediction", ""),
                    ))
            falsification = []
            raw_falsification = (
                hyp_data.get("condiciones_falsacion")
                or hyp_data.get("criterios_falsacion")
                or hyp_data.get("falsification_conditions")
                or hyp_data.get("falsification")
                or []
            )
            if isinstance(raw_falsification, (str, dict)):
                raw_falsification = [raw_falsification]
            for f in raw_falsification:
                if isinstance(f, str) and f.strip():
                    falsification.append(FalsificationCondition(condition=f.strip()))
                if isinstance(f, dict):
                    condition = f.get("condicion") or f.get("condition", "")
                    if condition:
                        falsification.append(FalsificationCondition(
                            condition=condition,
                            metric=f.get("metrica") or f.get("metric", ""),
                            threshold=f.get("umbral", f.get("threshold", 0)) or 0,
                        ))
            priority_raw = hyp_data.get("prioridad", "important")
            hypothesis = Hypothesis(
                id=hyp_id,
                opportunity_id=opp_id,
                ticker=ticker.upper(),
                statement=statement,
                status=HypothesisStatus.ACTIVE,
                priority=HypothesisPriority(priority_raw)
                if priority_raw in ("critical", "important", "informational")
                else HypothesisPriority.IMPORTANT,
                probability=(
                    None if "probabilidad" in hyp_data and hyp_data["probabilidad"] is None
                    else float(hyp_data["probabilidad"]) if isinstance(hyp_data.get("probabilidad"), (int, float))
                    else 0.5
                ),
                confidence=(
                    None if "confianza" in hyp_data and hyp_data["confianza"] is None
                    else float(hyp_data["confianza"]) if isinstance(hyp_data.get("confianza"), (int, float))
                    else 0.0
                ),
                parent_id=parent_id,
                rationale=hyp_data.get("por_que") or hyp_data.get("rationale") or hyp_data.get("why", ""),
                review_trigger=(
                    hyp_data.get("cuando_dejar_de_creerla")
                    or hyp_data.get("review_trigger")
                    or hyp_data.get("when_to_stop_believing", "")
                ),
                predictions=predictions,
                falsification=falsification,
                horizon=hyp_data.get("plazo") or hyp_data.get("horizon") or "24 months",
                secondary_hypotheses=dependencies,
            )
            journal.save_hypothesis(ticker.upper(), opp_id, hypothesis.to_dict())
            sqlite.save_hypothesis(hypothesis.to_dict())
            print(f"[HYP] {ticker} ({opp_id}): persistida hipótesis '{statement[:60]}' id={hypothesis.id}")
        if raw:
            print(f"[HYP] {ticker} ({opp_id}): {len(raw)} hipótesis persistidas en hypotheses.yml + SQLite")

    def _run_hypothesis_prompt_with_repair(
        self, ticker: str, prompt_inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Retry one invalid agent result with deterministic validation feedback."""
        result = self._run_prompt("hypothesis", ticker, dict(prompt_inputs))
        hypotheses = result.get("hipotesis", []) if isinstance(result, dict) else []
        errors = self._validate_hypothesis_contract(hypotheses)
        if not errors:
            return result

        retry_inputs = dict(prompt_inputs)
        retry_inputs["validation_feedback"] = (
            "La salida anterior fue rechazada por estos errores de validación: "
            + "; ".join(errors)
            + ". Corrige solo la estructura afectada, conserva la tesis y devuelve "
            "3-5 hipótesis completas con fechas futuras respecto de as_of_date. "
            "No inventes hechos para satisfacer el validador."
        )
        print(f"[HYPOTHESIS] Retrying once after deterministic validation: {'; '.join(errors)}")
        return self._run_prompt("hypothesis", ticker, retry_inputs)

    @staticmethod
    def _validate_hypothesis_contract(raw: Any, as_of_date: date | None = None) -> list[str]:
        """Validate the five HMF answers before a FULL_DDD result can advance."""
        if not isinstance(raw, list) or not raw:
            return ["hypotheses must be a non-empty list"]

        errors: list[str] = []
        today = as_of_date or datetime.now(AR_TZ).date()
        if not 3 <= len(raw) <= 5:
            errors.append("FULL_DDD requires 3 to 5 hypotheses")
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                errors.append(f"H{index}: hypothesis must be an object")
                continue
            statement = item.get("enunciado") or item.get("statement") or item.get("hipotesis")
            rationale = item.get("por_que") or item.get("rationale") or item.get("why")
            prediction = item.get("prediccion") or item.get("prediction")
            target_date = item.get("fecha_objetivo") or item.get("target_date") or item.get("deadline")
            magnitude = item.get("magnitud") or item.get("magnitude") or {}
            metric = magnitude.get("metrica") or magnitude.get("metric") if isinstance(magnitude, dict) else None
            expected = magnitude.get("valor_esperado", magnitude.get("expected_value")) if isinstance(magnitude, dict) else None
            falsification = (
                item.get("criterios_falsacion")
                or item.get("condiciones_falsacion")
                or item.get("falsification_conditions")
            )
            stop_condition = (
                item.get("cuando_dejar_de_creerla")
                or item.get("review_trigger")
                or item.get("when_to_stop_believing")
            )
            prefix = f"H{index}"
            if not isinstance(statement, str) or not statement.strip():
                errors.append(f"{prefix}: missing belief statement")
            if not isinstance(rationale, str) or not rationale.strip():
                errors.append(f"{prefix}: missing rationale (why)")
            if (
                not isinstance(prediction, str)
                or not prediction.strip()
                or not isinstance(metric, str)
                or not metric.strip()
                or isinstance(expected, bool)
                or not isinstance(expected, (int, float))
                or not math.isfinite(expected)
            ):
                errors.append(f"{prefix}: missing observable quantitative prediction")
            temporal_text = [value for value in (prediction, stop_condition) if isinstance(value, str)]
            if isinstance(falsification, str):
                temporal_text.append(falsification)
            elif isinstance(falsification, list):
                temporal_text.extend(
                    value if isinstance(value, str) else str(value.get("condicion") or value.get("condition") or "")
                    for value in falsification if isinstance(value, (str, dict))
                )
            year_tokens = re.findall(
                r"\b(?:FY\s*)?(20\d{2})\b", " ".join(temporal_text), flags=re.IGNORECASE
            )
            referenced_years = [int(year) for year in year_tokens]
            if any(year < today.year for year in referenced_years):
                errors.append(f"{prefix}: prediction or trigger references an expired year")
            try:
                valid_iso_shape = (
                    isinstance(target_date, str)
                    and len(target_date) == 10
                    and target_date[4] == "-"
                    and target_date[7] == "-"
                )
                if not valid_iso_shape:
                    raise ValueError("expected YYYY-MM-DD")
                parsed_target_date = date.fromisoformat(target_date)
                if parsed_target_date.isoformat() != target_date:
                    raise ValueError("expected canonical YYYY-MM-DD")
                if parsed_target_date <= today:
                    errors.append(f"{prefix}: target date must be after the as-of date ({today.isoformat()})")
            except ValueError:
                errors.append(f"{prefix}: missing valid ISO target date (YYYY-MM-DD)")
            has_falsification = (
                isinstance(falsification, str) and bool(falsification.strip())
            ) or (
                isinstance(falsification, list)
                and any(
                    isinstance(value, str) and value.strip()
                    or isinstance(value, dict) and bool(value.get("condicion") or value.get("condition"))
                    for value in falsification
                )
            )
            if not has_falsification:
                errors.append(f"{prefix}: missing falsification criteria")
            if not isinstance(stop_condition, str) or not stop_condition.strip():
                errors.append(f"{prefix}: missing stop-belief condition")
        return errors

    def _fetch_target_consensus(self, ticker: str, bp: Any) -> dict[str, Any] | None:
        try:
            from idos.valuation.target_consensus import fetch_target_consensus
            result = fetch_target_consensus(ticker, base_path=bp)
        except Exception as e:
            print(f"[WARN] {ticker}: no se pudo calcular target consensus: {e}")
            return None
        if result is None:
            print(f"[WARN] {ticker}: sin target consensus (ninguna fuente disponible)")
            return None
        print(f"[DDD] {ticker}: target consensus = ${result.promedio:.2f} "
              f"(median ${result.mediana:.2f}) de {result.n_fuentes} fuentes: "
              f"{', '.join(f'{k}=${v:.2f}' for k, v in result.fuentes.items())}")
        calculated_at = result.calculado_at
        observed_date = calculated_at[:10] if isinstance(calculated_at, str) else ""
        source_urls = {
            "yfinance": f"https://finance.yahoo.com/quote/{quote(ticker, safe='.-^')}/",
            "finviz": f"https://finviz.com/quote.ashx?t={quote(ticker, safe='.-^')}",
            "stockanalysis": f"https://stockanalysis.com/stocks/{quote(ticker.lower(), safe='.-')}/forecast/",
        }
        source_references = [
            {
                "name": source,
                "url": source_urls[source],
                "observed_at": calculated_at,
                "observed_date": observed_date,
                "as_of_date": observed_date,
                "target_price": value,
            }
            for source, value in sorted(result.fuentes.items())
            if source in source_urls and observed_date
        ]
        return {
            "promedio": result.promedio,
            "mediana": result.mediana,
            "fuentes": result.fuentes,
            "source_references": source_references,
            "n_fuentes": result.n_fuentes,
            "calculado_at": result.calculado_at,
            "target_low": result.target_low,
            "target_high": result.target_high,
        }

    @staticmethod
    def _merge_discovery_financial_evidence(
        financial_data: dict[str, Any],
        discovery_evidence: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Carry sourced Discovery observations into Research without inventing values."""
        merged = dict(financial_data)
        if not isinstance(discovery_evidence, dict):
            return merged

        discovery_observations = discovery_evidence.get("financial_observations")
        if isinstance(discovery_observations, dict):
            cached_observations = merged.get("financial_observations")
            cached_observations = cached_observations if isinstance(cached_observations, dict) else {}
            merged["financial_observations"] = {**cached_observations, **discovery_observations}

        discovery_provenance = discovery_evidence.get("data_provenance")
        if isinstance(discovery_provenance, dict):
            cached_provenance = merged.get("data_provenance")
            cached_provenance = cached_provenance if isinstance(cached_provenance, dict) else {}
            provenance = {**cached_provenance, **discovery_provenance}
            field_sources = dict(cached_provenance.get("field_sources", {}))
            field_sources.update(discovery_provenance.get("field_sources", {}))
            if field_sources:
                provenance["field_sources"] = field_sources
            sources = set(cached_provenance.get("sources_used", []))
            sources.update(discovery_provenance.get("sources_used", []))
            if sources:
                provenance["sources_used"] = sorted(str(source) for source in sources if source)
            merged["data_provenance"] = provenance

        return merged

    @staticmethod
    def _financial_evidence_context(data: dict[str, Any]) -> dict[str, Any]:
        provenance = data.get("data_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        observations = data.get("financial_observations")
        observations = observations if isinstance(observations, dict) else {}
        return {
            "observed_at": data.get("financial_data_observed_at"),
            "period_end": data.get("financial_data_as_of_date")
            or data.get("financial_period_end"),
            "currency": data.get("financial_currency") or data.get("currency"),
            "sources_used": provenance.get("sources_used", []),
            "field_sources": provenance.get("field_sources", {}),
            "conflicts": (
                provenance.get("conflicts", [])[:10]
                if isinstance(provenance.get("conflicts"), list)
                else provenance.get("conflicts", [])
            ),
            "observations": observations,
        }

    @staticmethod
    def _bound_multibaggers_prompt_value(value: Any, depth: int = 0) -> Any:
        """Bound nested company context before it is serialized into an LLM request."""
        if isinstance(value, str):
            return value[:500]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if depth >= 2:
            return None
        if isinstance(value, list):
            return [
                ResearchWorker._bound_multibaggers_prompt_value(item, depth + 1)
                for item in value[:5]
                if isinstance(item, (str, bool, int, float, list, dict)) or item is None
            ]
        if isinstance(value, dict):
            bounded = {}
            for key, item in list(value.items())[:8]:
                if not isinstance(key, str):
                    continue
                compact = ResearchWorker._bound_multibaggers_prompt_value(item, depth + 1)
                if compact is not None:
                    bounded[key[:100]] = compact
            return bounded
        return None

    @staticmethod
    def _multibaggers_prompt_context(data: dict[str, Any]) -> dict[str, Any]:
        """Keep Research context relevant and bounded while retaining sourced market context."""
        fields = (
            "analysis_as_of_date", "ticker", "name", "current_price",
            "current_price_as_of_date", "current_price_source", "quote_currency",
            "sector", "business_model", "products", "geography", "moat_description",
        )
        context: dict[str, Any] = {}
        for field in fields:
            value = data.get(field)
            value = ResearchWorker._bound_multibaggers_prompt_value(value)
            if value is not None:
                context[field] = value
        scenario_evidence = data.get("scenario_market_evidence")
        if isinstance(scenario_evidence, str):
            try:
                parsed_scenario_evidence = json.loads(scenario_evidence)
            except (TypeError, ValueError):
                parsed_scenario_evidence = None
            if isinstance(parsed_scenario_evidence, (dict, list)):
                scenario_evidence = parsed_scenario_evidence
        if isinstance(scenario_evidence, (dict, list)):
            encoded = json.dumps(scenario_evidence, ensure_ascii=False, sort_keys=True, default=str)
            if len(encoded) <= 5000:
                context["scenario_market_evidence"] = scenario_evidence
        elif isinstance(scenario_evidence, str) and len(scenario_evidence) <= 5000:
            context["scenario_market_evidence"] = scenario_evidence
        events = data.get("recent_events")
        if isinstance(events, list):
            context["recent_events"] = [
                {
                    key: item[key][:500] if isinstance(item.get(key), str) else item[key]
                    for key in ("date", "title", "summary", "url")
                    if key in item
                }
                for item in events[:5]
                if isinstance(item, dict)
            ]
        return context

    @staticmethod
    def _compact_research_financial_series(value: Any, limit: int = 5) -> tuple[list[Any], int]:
        """Keep the latest dated observations in the LLM context; source records stay intact."""
        if not isinstance(value, list):
            return [], 0
        indexed = list(enumerate(value))
        if any(isinstance(item, dict) and (item.get("period_end") or item.get("reported_at")) for item in value):
            indexed.sort(
                key=lambda pair: str(
                    pair[1].get("period_end") or pair[1].get("reported_at") or ""
                ) if isinstance(pair[1], dict) else "",
                reverse=True,
            )
        selected = [item for _, item in indexed[:limit]]
        return selected, max(0, len(value) - len(selected))

    @staticmethod
    def _research_financial_evidence(
        data: dict[str, Any],
        allowed_input_fields: set[str] | None = None,
    ) -> dict[str, Any]:
        """Expose configured, source-aware inputs for MULTIBAGGERS ratio analysis."""
        allowed_fields = (
            "revenue_ttm", "revenue", "revenue_growth_pct", "revenue_history",
            "eps_growth_pct", "roic_pct", "operating_margin_pct",
            "net_income_ttm", "net_income", "ebit", "ebitda", "interest_expense",
            "operating_cf", "operating_cash_flow", "capex", "capital_expenditures",
            "fcf", "free_cash_flow", "levered_fcf", "total_debt", "net_debt",
            "cash", "cash_and_equivalents", "current_assets", "current_liabilities",
            "current_ratio", "interest_coverage", "interest_coverage_ratio",
            "net_debt_ebitda", "gross_profit_ttm", "gross_margin_pct",
            "revenue_cagr_3y_pct", "fcf_growth_pct", "fcf_conversion_pct",
            "dilution_yoy_pct", "share_count_cagr_3y_pct", "fcf_runway_months",
            "shares_outstanding", "shares_outstanding_history", "diluted_shares",
            "diluted_shares_history", "fcf_history", "revenue_growth_history",
            "gross_profit_history", "operating_income_history", "net_income_history",
            "eps_history", "cash_and_investments_history", "total_debt_history",
            "net_cash_history", "operating_cash_flow_history", "capex_history",
            "fcf_growth_history", "gross_margin_history", "operating_margin_history",
            "fcf_margin_history",
        )
        if allowed_input_fields is not None:
            requested = set(allowed_input_fields)
            allowed_fields = tuple(field for field in allowed_fields if field in requested)
        provenance = data.get("data_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        field_sources = provenance.get("field_sources")
        field_sources = field_sources if isinstance(field_sources, dict) else {}
        field_urls = provenance.get("field_urls")
        field_urls = field_urls if isinstance(field_urls, dict) else {}
        raw_source_urls = provenance.get("source_urls")
        raw_source_urls = raw_source_urls if isinstance(raw_source_urls, list) else []
        trusted_source_urls = sorted({
            str(source_url)
            for source_url in [*raw_source_urls, *field_urls.values()]
            if isinstance(source_url, str) and source_url.startswith("https://")
        })
        metric_metadata = data.get("financial_metric_metadata")
        metric_metadata = metric_metadata if isinstance(metric_metadata, dict) else {}

        evidence: dict[str, Any] = {}
        for field in allowed_fields:
            value = data.get(field)
            omitted_points = 0
            if isinstance(value, list):
                value, omitted_points = ResearchWorker._compact_research_financial_series(value)
            if value is None or isinstance(value, bool):
                continue
            if not isinstance(value, (int, float, str, list, dict)):
                continue
            metadata = metric_metadata.get(field)
            metadata = metadata if isinstance(metadata, dict) else {}
            sources = field_sources.get(field)
            sources = sources if isinstance(sources, list) else []
            source_url = field_urls.get(field) or metadata.get("source_url")
            if not sources and data.get("source"):
                sources = [data["source"]]
            if not source_url and data.get("url"):
                source_url = data["url"]
            evidence[field] = {
                "value": value,
                "unit": metadata.get("unit"),
                "currency": metadata.get("currency") or data.get("financial_currency"),
                "period_type": metadata.get("period_type") or data.get("financial_period_type"),
                "period_end": metadata.get("period_end_date") or data.get("period_end_date"),
                "sources": sorted({str(source) for source in sources if source}),
                "source_url": source_url,
                "observed_at": data.get("financial_data_observed_at"),
                "omitted_points": omitted_points,
            }
        raw_metric_observations = data.get("metric_observations")
        raw_metric_observations = raw_metric_observations if isinstance(raw_metric_observations, dict) else {}
        validated_metric_observations: dict[str, list[dict[str, Any]]] = {}
        for metric, observations in raw_metric_observations.items():
            if metric not in allowed_fields or not isinstance(observations, list):
                continue
            safe_observations = []
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                value = observation.get("value")
                source_url = observation.get("source_url")
                required_text = ("source_id", "unit", "period", "reported_at", "observed_at")
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or any(not isinstance(observation.get(key), str) or not observation[key].strip() for key in required_text)
                    or not isinstance(source_url, str)
                    or not source_url.startswith("https://")
                ):
                    continue
                safe_observations.append({key: observation.get(key) for key in (
                    "source_id", "value", "unit", "currency", "period",
                    "reported_at", "observed_at", "source_url",
                )})
            if safe_observations:
                safe_observations.sort(key=lambda item: item["reported_at"], reverse=True)
                validated_metric_observations[metric] = safe_observations[:5]
        raw_exclusions = data.get("metric_observation_exclusions")
        raw_exclusions = raw_exclusions if isinstance(raw_exclusions, dict) else {}
        metric_observation_exclusions: dict[str, list[dict[str, Any]]] = {}
        for metric, exclusions in raw_exclusions.items():
            if metric not in allowed_fields or not isinstance(exclusions, list):
                continue
            safe_exclusions = [
                {key: item[key] for key in ("source_id", "reason_code", "missing_fields") if key in item}
                for item in exclusions
                if isinstance(item, dict)
            ]
            if safe_exclusions:
                metric_observation_exclusions[metric] = safe_exclusions[:5]
        raw_financial_observations = data.get("financial_observations")
        raw_financial_observations = raw_financial_observations if isinstance(raw_financial_observations, dict) else {}
        return {
            "reporting_period_end": data.get("financial_data_as_of_date")
            or data.get("financial_period_end") or data.get("period_end_date"),
            "currency": data.get("financial_currency") or data.get("currency"),
            "trusted_source_urls": trusted_source_urls,
            "source_observations": evidence,
            "reconciled_observations": {
                metric: (
                    ResearchWorker._compact_research_financial_series(raw_financial_observations[metric])[0]
                    if isinstance(raw_financial_observations[metric], list)
                    else raw_financial_observations[metric]
                )
                for metric in allowed_fields
                if metric in raw_financial_observations
            },
            "validated_metric_observations": validated_metric_observations,
            "metric_observation_exclusions": metric_observation_exclusions,
            "conflicts": provenance.get("conflicts", []),
        }

    @staticmethod
    def _validate_multibaggers_research_shape(result: Any) -> list[str]:
        """Reject structurally incomplete Research output before persistence."""
        if not isinstance(result, dict):
            return ["response must be a JSON object"]
        required_types = {
            "clasificacion_oportunidad": dict,
            "error_mercado": dict,
            "tesis_inversion": str,
            "dominio_riesgos": list,
            "dominio_catalizadores": list,
            "dominio_business_quality": dict,
            "calidad_evidencia": dict,
            "ratios_investigados": list,
            "risk_flags": list,
        }
        errors = [
            f"{field} must be {expected.__name__}"
            for field, expected in required_types.items()
            if not isinstance(result.get(field), expected)
        ]
        score = result.get("score_general")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            errors.append("score_general must be a finite number from 0 to 100")
        if result.get("scenario_analysis") is not None and not isinstance(result.get("scenario_analysis"), dict):
            errors.append("scenario_analysis must be an object or null")
        return errors

    @staticmethod
    def _multibaggers_financial_input_aliases(
        financial_evidence: dict[str, Any],
    ) -> dict[str, str]:
        """Map period-specific Research references to verified history fields."""
        source_observations = financial_evidence.get("source_observations")
        source_observations = source_observations if isinstance(source_observations, dict) else {}
        aliases: dict[str, str] = {}
        for field, observation in source_observations.items():
            if (
                not isinstance(field, str)
                or not field.endswith("_history")
                or not isinstance(observation, dict)
            ):
                continue
            sources = observation.get("sources")
            source_url = observation.get("source_url")
            points = observation.get("value")
            if (
                not isinstance(sources, list)
                or not any(isinstance(source, str) and source.strip() for source in sources)
                or not isinstance(source_url, str)
                or not source_url.startswith("https://")
                or not isinstance(points, list)
            ):
                continue
            stem = field[:-len("_history")]
            for point in points:
                if not isinstance(point, dict):
                    continue
                period = point.get("period")
                period_end = point.get("period_end")
                value = point.get("value")
                if (
                    not isinstance(period, str)
                    or not isinstance(period_end, str)
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    continue
                try:
                    parsed_period_end = date.fromisoformat(period_end[:10])
                except ValueError:
                    continue
                if parsed_period_end.isoformat() != period_end[:10]:
                    continue
                match = re.search(r"FY[\s:_-]*(\d{4})", period, re.IGNORECASE)
                if match:
                    aliases[f"{stem}_FY_{match.group(1)}"] = field
        return aliases

    @staticmethod
    def _bind_multibaggers_ratio_sources(
        raw_ratios: Any,
        financial_evidence: dict[str, Any],
    ) -> None:
        """Bind each ratio citation to source metadata for its declared input fields."""
        if not isinstance(raw_ratios, list) or not isinstance(financial_evidence, dict):
            return
        source_observations = financial_evidence.get("source_observations")
        source_observations = source_observations if isinstance(source_observations, dict) else {}
        validated_observations = financial_evidence.get("validated_metric_observations")
        validated_observations = validated_observations if isinstance(validated_observations, dict) else {}

        for ratio in raw_ratios:
            if not isinstance(ratio, dict) or ratio.get("status") not in {"reported", "calculated"}:
                continue
            input_fields = ratio.get("inputs")
            if not isinstance(input_fields, list) or not input_fields:
                continue
            citations: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()
            period_aliases = ResearchWorker._multibaggers_financial_input_aliases(financial_evidence)
            for field in input_fields:
                if not isinstance(field, str):
                    continue
                source_field = period_aliases.get(field, field)
                observation = source_observations.get(source_field)
                if isinstance(observation, dict):
                    sources = observation.get("sources")
                    source_url = observation.get("source_url")
                    if (
                        isinstance(sources, list)
                        and isinstance(source_url, str)
                        and source_url.startswith("https://")
                    ):
                        for source in sources:
                            if isinstance(source, str) and source.strip():
                                key = (source.strip(), source_url)
                                if key not in seen:
                                    seen.add(key)
                                    citations.append({"name": key[0], "url": key[1]})
                for item in validated_observations.get(source_field, []):
                    if not isinstance(item, dict):
                        continue
                    source = item.get("source_id")
                    source_url = item.get("source_url")
                    if (
                        isinstance(source, str) and source.strip()
                        and isinstance(source_url, str) and source_url.startswith("https://")
                    ):
                        key = (source.strip(), source_url)
                        if key not in seen:
                            seen.add(key)
                            citations.append({"name": key[0], "url": key[1]})
            if citations:
                ratio["sources"] = citations

    @staticmethod
    def _discard_calculated_ratios_without_inputs(raw_ratios: Any) -> list[str]:
        """Fail closed when the model labels a ratio calculated but omits its inputs."""
        if not isinstance(raw_ratios, list):
            return []
        discarded: list[str] = []
        for item in raw_ratios:
            if not isinstance(item, dict) or item.get("status") != "calculated":
                continue
            inputs = item.get("inputs")
            if isinstance(inputs, list) and inputs and all(
                isinstance(field, str) and field.strip() for field in inputs
            ):
                continue
            metric = item.get("metric")
            metric_name = metric if isinstance(metric, str) and metric.strip() else "unknown_metric"
            item["status"] = "unavailable"
            item["value"] = None
            item["limitations"] = (
                "Se descartó el cálculo porque Research no identificó referencias explícitas "
                "a sus inputs de evidencia."
            )
            item.pop("formula", None)
            item.pop("inputs", None)
            discarded.append(metric_name)
        return discarded

    @staticmethod
    def _normalize_multibaggers_ratio_units(
        raw_ratios: Any,
        configured_units: dict[str, str],
    ) -> None:
        """Fill an omitted unit label from strategy metadata without changing values."""
        if not isinstance(raw_ratios, list) or not isinstance(configured_units, dict):
            return
        for item in raw_ratios:
            if not isinstance(item, dict) or item.get("status") not in {"reported", "calculated"}:
                continue
            metric = item.get("metric")
            expected_unit = configured_units.get(metric)
            current_unit = item.get("unit")
            if (
                isinstance(expected_unit, str) and expected_unit.strip()
                and (not isinstance(current_unit, str) or not current_unit.strip())
            ):
                item["unit"] = expected_unit

    @staticmethod
    def _validate_multibaggers_ratio_review(
        raw_ratios: Any,
        required_metrics: list[str],
        trusted_source_urls: set[str] | None = None,
        available_input_fields: set[str] | None = None,
        expected_units: dict[str, str] | None = None,
    ) -> list[str]:
        """Require one auditable Research disposition per configured ratio."""
        if not isinstance(required_metrics, list) or not required_metrics:
            return ["research intake has no configured ratios_to_review"]
        trusted_source_urls = trusted_source_urls or set()
        expected_units = expected_units or {}
        if not isinstance(raw_ratios, list):
            return ["ratios_investigados must be a list"]
        by_metric: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for item in raw_ratios:
            if not isinstance(item, dict) or not isinstance(item.get("metric"), str):
                errors.append("each ratio entry must have a metric name")
                continue
            metric = item["metric"]
            if metric in by_metric:
                errors.append(f"duplicate ratio entry: {metric}")
            by_metric[metric] = item
        for metric in required_metrics:
            item = by_metric.get(metric)
            if item is None:
                errors.append(f"missing ratio disposition: {metric}")
                continue
            status = item.get("status")
            if status not in {"reported", "calculated", "unavailable"}:
                errors.append(f"invalid ratio status: {metric}")
                continue
            if status == "unavailable":
                if not isinstance(item.get("limitations"), str) or not item["limitations"].strip():
                    errors.append(f"unavailable ratio needs a limitation: {metric}")
                if item.get("value") is not None:
                    errors.append(f"unavailable ratio cannot have a value: {metric}")
                continue
            value = item.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                errors.append(f"reported/calculated ratio needs a finite numeric value: {metric}")
            unit = item.get("unit")
            expected_unit = expected_units.get(metric)
            if not isinstance(unit, str) or not unit.strip():
                errors.append(f"ratio needs a unit: {metric}")
            elif expected_unit and unit != expected_unit:
                errors.append(f"ratio unit conflicts with configured unit for {metric}: expected {expected_unit}")
            if not isinstance(item.get("period_end"), str) or not item["period_end"].strip():
                errors.append(f"ratio needs a reporting period: {metric}")
            sources = item.get("sources")
            if not isinstance(sources, list) or not sources or any(
                not isinstance(source, dict)
                or not isinstance(source.get("name"), str) or not source["name"].strip()
                or not isinstance(source.get("url"), str) or not source["url"].startswith("https://")
                for source in sources
            ):
                errors.append(f"ratio needs source names and https URLs: {metric}")
            elif any(source["url"] not in trusted_source_urls for source in sources):
                errors.append(f"ratio cites a URL absent from research evidence: {metric}")
            if status == "calculated":
                if not isinstance(item.get("formula"), str) or not item["formula"].strip():
                    errors.append(f"calculated ratio needs a formula: {metric}")
                inputs = item.get("inputs")
                if not isinstance(inputs, list) or not inputs or any(
                    not isinstance(field, str) or not field.strip() for field in inputs
                ):
                    errors.append(f"calculated ratio needs input references: {metric}")
                elif available_input_fields is not None:
                    unavailable_inputs = sorted(set(inputs) - available_input_fields)
                    if unavailable_inputs:
                        errors.append(
                            f"calculated ratio cites inputs absent from research evidence: {metric} "
                            f"({', '.join(unavailable_inputs)})"
                        )
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

    @staticmethod
    def _verified_facts(ddd_result: dict[str, Any]) -> list[str]:
        quality = ddd_result.get("calidad_evidencia")
        raw_facts = quality.get("hechos_verificados") if isinstance(quality, dict) else None
        if not isinstance(raw_facts, list):
            if raw_facts is not None:
                print("[KB] Ignoring malformed hechos_verificados from Research output")
            return []
        return [fact.strip() for fact in raw_facts if isinstance(fact, str) and fact.strip()]

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

        dd_claims = self._verified_facts(ddd_result)
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

    def _run_prompt(
        self,
        prompt_name: str,
        ticker: str,
        kwargs: dict[str, Any],
        *,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        template = self.registry.get(prompt_name, category="research")
        if not template:
            return {}
        system = self.registry.get_system(prompt_name, category="research") or ""
        formatted = template.format(**kwargs) if isinstance(template, str) else template
        request = {
            "prompt": formatted,
            "system_prompt": system,
            "temperature": 0.1,
        }
        if max_tokens != 4096:
            request["max_tokens"] = max_tokens
        return self.llm.generate_structured(**request)

