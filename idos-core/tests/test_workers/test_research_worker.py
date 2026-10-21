from datetime import date
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from idos.models.enums import OpportunityStatus
from idos.workers.ai.research_worker import ResearchWorker, _has_sourced_financial_cutoff
from idos.workers.base import WorkerStatus
from idos.knowledge.wiki import AtomicWiki
from idos.research.wiki import WikiBuilder


def _write_multibaggers_profile(base_path: str, *, enabled: bool) -> None:
    import yaml

    config_dir = Path(base_path) / "idos-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "strategies.yml").write_text(yaml.safe_dump({
        "strategies": {
            "MULTIBAGGERS": {
                "enabled": enabled,
                "core": "CORE_4_ALPHA_ASYMMETRY",
                "sleeve": "ALPHA_ASYMMETRY",
                "thesis_type": "STRATEGIC",
                "discovery_profile": "multibaggers",
                "research_profile": "multibaggers",
                "entry_policy": "MANUAL_REVIEW",
                "strategy_version": "1.1",
            },
        },
    }), encoding="utf-8")


@pytest.fixture
def seeded_opportunity(tmp_sqlite, tmp_journal):
    """Research starts after Discovery qualifies an opportunity."""
    ticker, opp_id = "TEST", "OPP-2026-TEST-001"
    opp = {
        "id": opp_id, "ticker": ticker,
        "status": OpportunityStatus.SCREENED.value,
        "conviction": {"overall": 70},
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    tmp_sqlite.save_opportunity(opp)
    tmp_journal.save_opportunity(ticker, opp)
    return ticker, opp_id


def _mock_research_registry() -> MagicMock:
    registry = MagicMock()

    def get_side_effect(prompt_name: str, category: str = "research"):
        if prompt_name == "wiki":
            return None
        if prompt_name == "ddd":
            return "FASE 0 - clasificacion oportunidad for {ticker} ({name})"
        if prompt_name == "hypothesis":
            return "Genera hipotesis de inversion para {ticker}"
        if prompt_name == "aoif":
            return "AOIF 8-step protocol for {ticker} ({name})"
        return "template {ticker}"

    registry.get.side_effect = get_side_effect
    registry.get_system.return_value = "system"
    return registry


def test_current_price_context_uses_latest_aligned_close_with_provenance():
    context = ResearchWorker._current_price_context({
        "price_history": [100.0, None, 125.5],
        "price_history_dates": ["2026-10-15", "2026-10-16", "2026-10-19"],
        "data_provenance": {"field_sources": {"price_history": ["yfinance"]}},
    })

    assert context == {
        "price": 125.5,
        "as_of_date": "2026-10-19",
        "source": "yfinance",
    }


def test_financial_cutoff_requires_provider_date_and_source_not_retrieval_timestamp():
    assert _has_sourced_financial_cutoff({
        "source": "stockanalysis.com",
        "provider_data_updated_date": "2026-10-19",
        "data_provenance": {
            "field_sources": {"provider_data_updated_date": ["stockanalysis.com"]},
        },
    })
    assert not _has_sourced_financial_cutoff({
        "source": "stockanalysis.com",
        "financial_data_observed_at": "2026-10-19T12:00:00+00:00",
    })


def test_research_loader_refreshes_uncutoff_cache_from_stockanalysis(
    tmp_path, monkeypatch, tmp_sqlite
):
    from idos.workers.data.stockanalysis import StockAnalysisWorker

    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "TEST.json").write_text(json.dumps({
        "ticker": "TEST", "source": "stockanalysis.com", "operating_margin_pct": 10,
    }), encoding="utf-8")
    live = {
        "ticker": "TEST", "source": "stockanalysis.com", "operating_margin_pct": 17.3,
        "provider_data_updated_date": "2026-10-19",
        "data_provenance": {
            "sources_used": ["stockanalysis.com"],
            "field_sources": {"provider_data_updated_date": ["stockanalysis.com"]},
        },
    }
    monkeypatch.setattr(StockAnalysisWorker, "run", lambda self, context: live)
    worker = ResearchWorker({"llm_service": MagicMock()})

    financial = worker._load_financial_data("TEST", tmp_sqlite)

    assert financial["operating_margin_pct"] == 17.3
    assert financial["provider_data_updated_date"] == "2026-10-19"


def test_current_price_context_does_not_infer_from_unaligned_history():
    context = ResearchWorker._current_price_context({
        "price_history": [100.0, 125.5],
        "price_history_dates": ["2026-10-15"],
    })

    assert context == {"price": "N/D", "as_of_date": "N/D", "source": "N/D"}


def test_current_price_context_uses_committed_discovery_quote_when_cache_is_absent():
    context = ResearchWorker._current_price_context(
        {},
        {"market_quote": {
            "price": 125.5, "as_of_date": "2026-10-19", "currency": "USD", "source": "yfinance",
        }},
    )

    assert context == {"price": 125.5, "as_of_date": "2026-10-19", "source": "yfinance"}


def test_scenario_market_evidence_keeps_quote_and_analyst_target_provenance():
    evidence = ResearchWorker._scenario_market_evidence(
        ticker="BRK.B",
        price_context={"price": 500.0, "as_of_date": "2026-10-19", "source": "yfinance"},
        quote_currency="USD",
        target_consensus={
            "promedio": 520.0,
            "mediana": 515.0,
            "target_low": 450.0,
            "target_high": 600.0,
            "calculado_at": "2026-10-19T12:00:00-03:00",
            "source_references": [{
                "name": "stockanalysis",
                "url": "https://stockanalysis.com/stocks/brk.b/forecast/",
                "as_of_date": "2026-10-19",
            }],
        },
    )

    assert evidence["current_quote"] == {
        "price": 500.0,
        "currency": "USD",
        "as_of_date": "2026-10-19",
        "sources": [{
            "name": "yfinance",
            "url": "https://finance.yahoo.com/quote/BRK.B/",
        }],
    }
    assert evidence["analyst_target_consensus"]["low"] == 450.0
    assert evidence["analyst_target_consensus"]["sources"][0]["as_of_date"] == "2026-10-19"


def test_target_consensus_records_urls_and_observation_dates(monkeypatch):
    from types import SimpleNamespace

    import idos.valuation.target_consensus as target_consensus

    monkeypatch.setattr(target_consensus, "fetch_target_consensus", lambda ticker, **_: SimpleNamespace(
        promedio=520.0,
        mediana=515.0,
        fuentes={"stockanalysis": 520.0, "yfinance": 520.0},
        n_fuentes=2,
        calculado_at="2026-10-19T12:00:00-03:00",
        target_low=450.0,
        target_high=600.0,
    ))

    result = ResearchWorker()._fetch_target_consensus("BRK.B", Path.cwd())

    assert result is not None
    assert result["source_references"] == [
        {
            "name": "stockanalysis",
            "url": "https://stockanalysis.com/stocks/brk.b/forecast/",
            "observed_at": "2026-10-19T12:00:00-03:00",
            "observed_date": "2026-10-19",
            "as_of_date": "2026-10-19",
            "target_price": 520.0,
        },
        {
            "name": "yfinance",
            "url": "https://finance.yahoo.com/quote/BRK.B/",
            "observed_at": "2026-10-19T12:00:00-03:00",
            "observed_date": "2026-10-19",
            "as_of_date": "2026-10-19",
            "target_price": 520.0,
        },
    ]


def test_ddd_prompt_renders_the_scenario_evidence_contract():
    from idos.ai.prompts import PromptRegistry

    repo_root = Path(__file__).resolve().parents[3]
    registry = PromptRegistry(repo_root / "idos-config" / "prompts")
    kwargs = {
        "ticker": "VIST", "name": "Vista", "existing_wiki": "", "prior_catalysts": "[]",
        "sector": "Energy", "business_model": "", "products": "", "geography": "",
        "moat_description": "", "revenue": 1, "revenue_growth": 2, "operating_margin": 3,
        "roic": 4, "excess_return_roic_wacc": 0, "fcf_adjusted": None, "debt_to_equity": 0.1,
        "debt_maturity_profile": "N/A", "interest_coverage_ratio": 4, "ceo_tenure": 1,
        "insider_ownership": 0, "capital_allocation": "N/A", "recent_events": "",
        "analysis_as_of_date": "2026-10-19", "current_price": 100,
        "current_price_as_of_date": "2026-10-19", "current_price_source": "yfinance",
        "quote_currency": "USD", "scenario_market_evidence": '{"current_quote": {}}',
        "financial_data_evidence": '{"conflicts": []}',
    }

    prompt = registry.load("ddd", category="research").user_prompt.format(**kwargs)

    assert prompt is not None
    assert '{"current_quote": {}}' in prompt
    assert '{"conflicts": []}' in prompt
    assert '"rationale"' in prompt
    assert '"key_assumptions"' in prompt


def test_current_price_context_rejects_invalid_discovery_quote():
    context = ResearchWorker._current_price_context(
        {}, {"market_quote": {"price": 125.5, "as_of_date": "2024-01-01", "source": ""}},
    )

    assert context == {"price": "N/D", "as_of_date": "N/D", "source": "N/D"}


class TestResearchWorker:
    def test_multibaggers_research_requires_matching_intake_and_uses_strategy_prompt(
        self, seeded_opportunity, tmp_sqlite, tmp_journal, base_path: str
    ):
        import yaml

        _write_multibaggers_profile(base_path, enabled=True)
        ticker, opp_id = seeded_opportunity
        opportunity = tmp_sqlite.get_opportunity(opp_id)
        opportunity.update({
            "strategy_id": "MULTIBAGGERS",
            "strategy_version": "1.1",
            "research_profile": "multibaggers",
            "entry_policy": "MANUAL_REVIEW",
        })
        tmp_sqlite.save_opportunity(opportunity)
        tmp_journal.save_opportunity(ticker, opportunity)
        opportunity_dir = tmp_journal.opportunity_path(ticker, opp_id)
        opportunity_dir.mkdir(parents=True, exist_ok=True)
        evidence_hash = "a" * 64
        (opportunity_dir / "discovery_snapshot.yml").write_text(
            yaml.safe_dump({"snapshot_hash": evidence_hash}), encoding="utf-8"
        )
        (opportunity_dir / "research_intake.yml").write_text(
            yaml.safe_dump({
                "ticker": ticker,
                "strategy_id": "MULTIBAGGERS",
                "strategy_version": "1.1",
                "research_profile": "multibaggers",
                "snapshot_hash": evidence_hash,
            }),
            encoding="utf-8",
        )

        worker = ResearchWorker({"provider": "test"})
        worker._load_financial_data = MagicMock(return_value={
            "current_ratio": 1.4,
            "financial_currency": "USD",
            "period_end_date": "2026-09-30",
            "financial_data_observed_at": "2026-10-15T12:00:00+00:00",
            "source": "stockanalysis.com",
            "url": "https://stockanalysis.com/stocks/test/statistics/",
            "data_provenance": {
                "field_sources": {"current_ratio": ["stockanalysis.com"]},
                "field_urls": {"current_ratio": "https://stockanalysis.com/stocks/test/statistics/"},
            },
            "metric_observations": {
                "revenue_growth_pct": [{
                    "source_id": "sec_edgar",
                    "value": 18.5,
                    "unit": "percent",
                    "currency": "USD",
                    "period": "FY:2025-01-01/2025-12-31",
                    "reported_at": "2026-02-15",
                    "observed_at": "2026-10-15T12:00:00+00:00",
                    "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                }],
            },
        })
        worker._enrich_company_info = MagicMock(return_value={"name": "Test", "sector": "Technology"})
        worker._fetch_target_consensus = MagicMock(return_value={
            "promedio": 520.0,
            "mediana": 515.0,
            "fuentes": {"stockanalysis": 520.0},
            "source_references": [{
                "name": "stockanalysis",
                "url": "https://stockanalysis.com/stocks/test/forecast/",
                "as_of_date": "2026-10-20",
            }],
            "n_fuentes": 1,
            "calculado_at": "2026-10-20T12:00:00-03:00",
            "target_low": 450.0,
            "target_high": 600.0,
        })
        worker._run_prompt = MagicMock(return_value={})

        result = worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result["status"] == "ddd_failed"
        assert worker._run_prompt.call_args.args[0] == "multibaggers"
        import json
        prompt_inputs = worker._run_prompt.call_args.args[2]
        financial_evidence = json.loads(prompt_inputs["research_financial_evidence"])
        scenario_evidence = json.loads(prompt_inputs["financial_summary"])["scenario_market_evidence"]
        assert financial_evidence["source_observations"]["current_ratio"]["value"] == 1.4
        assert financial_evidence["source_observations"]["current_ratio"]["period_end"] == "2026-09-30"
        assert financial_evidence["source_observations"]["current_ratio"]["source_url"].startswith("https://")
        assert financial_evidence["validated_metric_observations"]["revenue_growth_pct"][0]["value"] == 18.5
        assert scenario_evidence["analyst_target_consensus"]["mean"] == 520.0
        assert scenario_evidence["analyst_target_consensus"]["low"] == 450.0
        assert scenario_evidence["analyst_target_consensus"]["high"] == 600.0
        assert scenario_evidence["analyst_target_consensus"]["sources"][0]["url"].endswith("/forecast/")
        worker._fetch_target_consensus.assert_called_once()

    def test_multibaggers_research_blocks_mismatched_snapshot_before_llm(
        self, seeded_opportunity, tmp_sqlite, tmp_journal, base_path: str
    ):
        import yaml

        _write_multibaggers_profile(base_path, enabled=True)
        ticker, opp_id = seeded_opportunity
        opportunity = tmp_sqlite.get_opportunity(opp_id)
        opportunity.update({
            "strategy_id": "MULTIBAGGERS",
            "strategy_version": "1.1",
            "research_profile": "multibaggers",
            "entry_policy": "MANUAL_REVIEW",
        })
        tmp_sqlite.save_opportunity(opportunity)
        tmp_journal.save_opportunity(ticker, opportunity)
        opportunity_dir = tmp_journal.opportunity_path(ticker, opp_id)
        opportunity_dir.mkdir(parents=True, exist_ok=True)
        (opportunity_dir / "discovery_snapshot.yml").write_text(
            yaml.safe_dump({"snapshot_hash": "snapshot-a"}), encoding="utf-8"
        )
        (opportunity_dir / "research_intake.yml").write_text(
            yaml.safe_dump({
                "ticker": ticker,
                "strategy_id": "MULTIBAGGERS",
                "strategy_version": "1.1",
                "research_profile": "multibaggers",
                "snapshot_hash": "snapshot-b",
            }),
            encoding="utf-8",
        )
        worker = ResearchWorker({"provider": "test"})
        worker._run_prompt = MagicMock()

        with pytest.raises(ValueError, match="does not match its Discovery snapshot"):
            worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        worker._run_prompt.assert_not_called()

    def test_multibaggers_research_rejects_disabled_strategy_before_llm(
        self, seeded_opportunity, tmp_sqlite, base_path: str
    ):
        _write_multibaggers_profile(base_path, enabled=False)
        ticker, opp_id = seeded_opportunity
        opportunity = tmp_sqlite.get_opportunity(opp_id)
        opportunity.update({
            "strategy_id": "MULTIBAGGERS",
            "strategy_version": "1.1",
            "research_profile": "multibaggers",
        })
        tmp_sqlite.save_opportunity(opportunity)

        worker = ResearchWorker({"provider": "test"})
        worker._run_prompt = MagicMock()

        with pytest.raises(ValueError, match="requires a matching enabled strategy profile"):
            worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        worker._run_prompt.assert_not_called()

    def test_event_research_persists_evidence_and_prompt_snapshot(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        import yaml

        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()
        evidence = {
            "ticker": ticker,
            "event_type": "quarterly_results",
            "occurred_at": "2026-10-14",
            "source_name": "Investor Relations",
            "source_url": "https://example.com/ir/results",
            "summary": "Quarterly results published; verify the primary source.",
        }

        result = worker.run({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
            "force_reprocess": True,
            "event_type": "quarterly_results",
            "event_evidence": evidence,
        })

        assert result["status"] == "completed"
        report_path = tmp_journal.opportunity_path(ticker, opp_id) / "ddd_report.yml"
        report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
        trigger = report["research_trigger"]
        assert trigger["event_evidence"]["source_url"] == evidence["source_url"]
        assert trigger["strategy_version"] == "legacy-compatible"
        assert len(trigger["input_snapshot_ref"]["sha256"]) == 64
        assert report["research_input_snapshot"]["recent_events"].find("Evento disparador validado") >= 0
        actual_hash = hashlib.sha256(
            json.dumps(
                report["research_input_snapshot"],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        assert trigger["input_snapshot_ref"]["sha256"] == actual_hash

    def test_invalid_ddd_preserves_previous_report_and_stops_partial_writes(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        report_path = (
            Path(base_path) / "idos-journal" / "companies" / ticker / "case_file"
            / "opportunities" / opp_id / "ddd_report.yml"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        previous_report = "ticker: TEST\nstatus: reviewed\n"
        report_path.write_text(previous_report, encoding="utf-8")

        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.registry = _mock_research_registry()
        worker._run_prompt = MagicMock(return_value={"error": "Failed to parse JSON"})

        result = worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result["status"] == "ddd_failed"
        assert result["error"] == "Failed to parse JSON"
        assert report_path.read_text(encoding="utf-8") == previous_report
        assert not (tmp_journal.opportunity_path(ticker, opp_id) / "assessments").exists()
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.SCREENED.value

    def test_research_uses_injected_llm_service(self):
        service = MagicMock()
        service.generate_structured.return_value = {"ok": True}
        worker = ResearchWorker({"llm_service": service})
        worker.registry = MagicMock()
        worker.registry.get.return_value = "Research prompt for {ticker}"
        worker.registry.get_system.return_value = "System contract"

        result = worker._run_prompt("ddd", "VIST", {"ticker": "VIST"}, max_tokens=8192)

        assert result == {"ok": True}
        service.generate_structured.assert_called_once_with(
            prompt="Research prompt for VIST",
            system_prompt="System contract",
            temperature=0.1,
            max_tokens=8192,
        )

    def test_systematic_ddd_is_signal_specific(self):
        report = ResearchWorker._build_systematic_ddd(
            "XLE",
            {"strategy_id": "MOMENTUM_ETF", "signal": {"momentum": 1.8, "as_of_date": "2026-09-01"}},
            {"minimum_signal": 0.6, "maximum_signal": 2.7},
        )
        assert report["clasificacion_oportunidad"]["categoria"] == "systematic_momentum"
        assert report["score_general"] == 67
        assert report["strategy_context"]["signal"]["momentum"] == 1.8
        assert report["calidad_evidencia"]["inferencias_llm"] == []
        assert report["strategy_context"]["risk_rating"] == "NOT_ASSESSED"
        assert report["dominio_catalizadores"][0]["probabilidad_pct"] is None
        assert "volatilidad" not in report["resumen_ejecutivo"].lower()

    def test_systematic_report_uses_configured_range_and_invalidates_outside_signal(self):
        report = ResearchWorker._build_systematic_ddd(
            "XLF", {"signal": {"momentum": 1.8}},
            {"minimum_signal": 2.0, "maximum_signal": 3.6},
        )
        assert report["score_general"] == 50
        assert report["integridad_tesis"]["thesis_active"] is False
        with pytest.raises(ValueError, match="finite signal"):
            ResearchWorker._build_systematic_ddd(
                "XLF", {"signal": {"momentum": float("nan")}},
                {"minimum_signal": 0.6, "maximum_signal": 2.7},
            )

    def test_research_completes(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
        })

        assert result.status == WorkerStatus.SUCCESS
        output = result.output
        assert output["status"] == "completed"
        assert output["score"] > 0
        assert output["hypotheses_count"] >= 1
        assert output["classification"] == "compounder_castigado"
        assert output["market_error_conclusion"] == "SI"

    def test_research_transition(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        opp = tmp_sqlite.get_opportunity(opp_id)
        assert opp is not None
        assert opp["status"] == OpportunityStatus.UNDER_RESEARCH.value

    def test_forced_research_preserves_active_portfolio_status(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        opportunity = tmp_sqlite.get_opportunity(opp_id)
        opportunity["status"] = OpportunityStatus.FULL_POSITION.value
        tmp_sqlite.save_opportunity(opportunity)
        tmp_journal.save_opportunity(ticker, opportunity)

        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
            "force_reprocess": True,
            "event_type": "thesis_reassessment",
        })

        assert result.status == WorkerStatus.SUCCESS
        assert result.output["opportunity_status"] == OpportunityStatus.FULL_POSITION.value
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.FULL_POSITION.value
        assert tmp_journal.load_opportunity(ticker, opp_id)["status"] == OpportunityStatus.FULL_POSITION.value
        transitions = list(tmp_sqlite.conn.execute(
            "SELECT from_status, to_status FROM state_transitions WHERE opportunity_id = ?",
            (opp_id,),
        ))
        assert transitions == []

    def test_forced_research_invalidates_old_buylist_approval_and_preserves_history(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        import yaml

        ticker, opp_id = seeded_opportunity
        opportunity = tmp_sqlite.get_opportunity(opp_id)
        opportunity.update({
            "status": OpportunityStatus.UNDER_DEEP_DD.value,
            "approved_for_buylist": True,
        })
        tmp_sqlite.save_opportunity(opportunity)
        tmp_journal.save_opportunity(ticker, opportunity)

        opportunity_dir = tmp_journal.opportunity_path(ticker, opp_id)
        (opportunity_dir / "decision_proposal.yml").write_text(yaml.safe_dump({
            "opportunity_id": opp_id, "status": "MANAGER_APPROVED",
        }), encoding="utf-8")
        (opportunity_dir / "board_resolution.yml").write_text(yaml.safe_dump({
            "approved": True, "status": "approved", "decision_id": "DEC-OLD",
        }), encoding="utf-8")
        decisions_dir = opportunity_dir / "decisions"
        decisions_dir.mkdir()
        decision_path = decisions_dir / "DEC-OLD.yml"
        prior_decision = "approved: true\nstatus: approved\ndecision_id: DEC-OLD\n"
        decision_path.write_text(prior_decision, encoding="utf-8")
        buylist_path = Path(base_path) / "idos-journal/portfolio/buylist.yml"
        buylist_path.parent.mkdir(parents=True, exist_ok=True)
        buylist_path.write_text(yaml.safe_dump({"entries": [
            {"ticker": ticker, "opp_id": opp_id},
            {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
        ]}), encoding="utf-8")

        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()
        result = worker.execute({
            "ticker": ticker,
            "opp_id": opp_id,
            "base_path": base_path,
            "force_reprocess": True,
            "event_type": "thesis_reassessment",
        })

        assert result.status == WorkerStatus.SUCCESS
        assert result.output["approval_invalidated"] is True
        assert tmp_journal.load_opportunity(ticker, opp_id)["approved_for_buylist"] is False
        proposal = yaml.safe_load((opportunity_dir / "decision_proposal.yml").read_text(encoding="utf-8"))
        assert proposal["status"] == "INVALIDATED_BY_NEW_RESEARCH"
        resolution = yaml.safe_load((opportunity_dir / "board_resolution.yml").read_text(encoding="utf-8"))
        assert resolution["status"] == "invalidated_by_new_research"
        assert yaml.safe_load(buylist_path.read_text(encoding="utf-8"))["entries"] == [
            {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
        ]
        assert decision_path.read_text(encoding="utf-8") == prior_decision

    def test_research_saves_assessment(
        self,
        seeded_opportunity: tuple[str, str],
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_journal,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        ass_path = tmp_journal.opportunity_path(ticker, opp_id) / "assessments"
        assert ass_path.exists()
        yml_files = list(ass_path.glob("*.yml"))
        assert len(yml_files) >= 1

    def test_research_rejects_invalid_state(
        self,
        tmp_sqlite,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker = "TEST"
        opp_id = "OPP-INVALID"
        opp = {
            "id": opp_id,
            "ticker": ticker,
            "status": OpportunityStatus.APPROVED.value,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        tmp_sqlite.save_opportunity(opp)

        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result.status == WorkerStatus.SUCCESS
        assert result.output["status"] == "skipped"

    def test_research_creates_wiki_with_all_sections(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        bp = Path(base_path)
        atomic = AtomicWiki(bp / "idos-knowledge")
        sections = atomic.all_sections(ticker)

        section_names = {s.name for s in sections}
        print(f"[DEBUG] Secciones encontradas: {section_names}")

        expected = {"business", "products", "moat", "management", "competition",
                     "financial_highlights", "catalysts", "investment_thesis"}
        missing = expected - section_names
        extra = section_names - expected
        assert not missing, f"Faltan secciones wiki: {missing}"
        if extra:
            print(f"[TEST] Secciones extra: {extra}")

        md_path = bp / "idos-knowledge" / "companies" / ticker / "knowledge_base" / "static" / "wiki.md"
        assert md_path.exists(), "wiki.md no encontrado"
        content = md_path.read_text(encoding="utf-8")
        assert "## Business Model" in content
        assert "## Products & Services" in content
        assert "## Competitive Moat" in content
        assert "## Investment Thesis" in content
        assert "## Financial Highlights" in content
        assert "## Catalysts" in content

    def test_research_creates_claims_and_lifecycle(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        mock_llm_client: MagicMock,
        base_path: str,
        tmp_path: Path,
    ):
        ticker, opp_id = seeded_opportunity
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.llm = mock_llm_client
        worker.registry = _mock_research_registry()

        result = worker.execute({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})
        assert result.status == WorkerStatus.SUCCESS

        bp = Path(base_path)
        claim_store = type("obj", (object,), {"_claims_dir": bp / "idos-knowledge" / ".claims"})()
        claims_dir = bp / "idos-knowledge" / ".claims"
        assert claims_dir.exists(), ".claims directory no creado"
        claim_files = list(claims_dir.glob("CLAIM-TEST-DDD-*.json"))
        assert len(claim_files) >= 1, "No se crearon claims desde DDD"

        from idos.knowledge.claims import ClaimStore as CS
        store = CS(str(bp / "idos-knowledge"))
        claims = store.search(tag=ticker)
        assert len(claims) >= 1
        assert any("ROIC" in c.statement for c in claims), "Claim de ROIC no encontrado"

    def test_research_requires_ticker_and_opp(
        self,
        base_path: str,
        tmp_path: Path,
    ):
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})

        with pytest.raises(ValueError, match="Both ticker and opp_id"):
            worker.run({"ticker": "", "opp_id": "", "base_path": base_path})

    def test_persist_hypotheses_ids_unicos_entre_opps(self, tmp_sqlite, tmp_journal):
        worker = ResearchWorker({"provider": "test"})
        worker._persist_hypotheses(
            "AAA", "OPP-AAA-1", "tesis",
            [{"id": "H1", "enunciado": "h1"},
             {"id": "H2", "enunciado": "h2", "parent_id": "H1"}],
            tmp_journal, tmp_sqlite,
        )
        worker._persist_hypotheses(
            "BBB", "OPP-BBB-1", "tesis",
            [{"id": "H1", "enunciado": "h1"}],
            tmp_journal, tmp_sqlite,
        )

        rows = list(tmp_sqlite.conn.execute(
            "SELECT id, parent_id FROM hypotheses ORDER BY opportunity_id"))
        assert len(rows) == 3
        ids = [dict(r)["id"] for r in rows]
        assert len(ids) == len(set(ids)), "los IDs colisionan entre oportunidades"
        parents = {dict(r)["id"]: dict(r)["parent_id"] for r in rows}
        assert parents["H1-OPP-AAA-1"] == ""
        assert parents["H2-OPP-AAA-1"] == "H1-OPP-AAA-1"
        assert parents["H1-OPP-BBB-1"] == ""

    def test_persist_hypotheses_reproceso_no_duplica(self, tmp_sqlite, tmp_journal):
        worker = ResearchWorker({"provider": "test"})
        raw = [{"id": "H1", "enunciado": "h1"}]
        worker._persist_hypotheses("AAA", "OPP-AAA-1", "tesis", raw, tmp_journal, tmp_sqlite)
        worker._persist_hypotheses("AAA", "OPP-AAA-1", "tesis", raw, tmp_journal, tmp_sqlite)

        rows = list(tmp_sqlite.conn.execute("SELECT id FROM hypotheses"))
        assert len(rows) == 1

    def test_persist_hypotheses_maps_configured_spanish_prompt_schema(self, tmp_sqlite, tmp_journal):
        worker = ResearchWorker({"provider": "test"})
        raw = [{
            "id": "H1",
            "enunciado": "La demanda de iPhone se recuperará durante el próximo ejercicio.",
            "por_que": "La renovación de dispositivos y los servicios sostienen la demanda.",
            "prediccion": "Los ingresos de iPhone crecerán al menos 8% en FY2027.",
            "fecha_objetivo": "2027-09-30",
            "magnitud": {"metrica": "iphone_revenue_growth", "valor_esperado": 8, "unidad": "%"},
            "criterios_falsacion": "Ingresos de iPhone crecen menos de 3% en FY2027.",
            "cuando_dejar_de_creerla": "Dejar de creerla si los ingresos crecen menos de 3% al cierre de FY2027.",
            "plazo": "largo",
            "depende_de": ["H2"],
        }]

        worker._persist_hypotheses("AAPL", "OPP-AAPL-1", "tesis", raw, tmp_journal, tmp_sqlite)

        [hypothesis] = tmp_journal.load_hypotheses("AAPL", "OPP-AAPL-1")
        assert hypothesis["predictions"] == [{
            "metric": "iphone_revenue_growth",
            "prediction": "Los ingresos de iPhone crecerán al menos 8% en FY2027.",
            "expected": 8,
            "unit": "%",
            "deadline": "2027-09-30",
            "actual": None,
            "met": None,
        }]
        assert hypothesis["falsification_conditions"] == [
            "Ingresos de iPhone crecen menos de 3% en FY2027."
        ]
        assert hypothesis["falsification"][0]["condition"] == hypothesis["falsification_conditions"][0]
        assert hypothesis["horizon"] == "largo"
        assert hypothesis["secondary_hypotheses"] == ["H2-OPP-AAPL-1"]
        assert hypothesis["rationale"] == "La renovación de dispositivos y los servicios sostienen la demanda."
        assert hypothesis["review_trigger"].startswith("Dejar de creerla")

    def test_full_ddd_hypothesis_contract_requires_each_hmf_answer(self):
        valid = [{
            "enunciado": "Creemos que el margen operativo crecerá.",
            "por_que": "La mezcla de servicios aumenta.",
            "prediccion": "El margen supera 34% en FY2027.",
            "fecha_objetivo": "2027-09-30",
            "magnitud": {"metrica": "operating_margin", "valor_esperado": 34},
            "criterios_falsacion": ["El margen queda debajo de 32%"],
            "cuando_dejar_de_creerla": "Si queda debajo de 32% en FY2027.",
        }] * 3
        assert ResearchWorker._validate_hypothesis_contract(valid, date(2026, 10, 19)) == []

        expired = [dict(item, fecha_objetivo="2025-09-30") for item in valid]
        expired_errors = ResearchWorker._validate_hypothesis_contract(expired, date(2026, 10, 19))
        assert sum("target date must be after" in error for error in expired_errors) == 3

        stale_year = [dict(item, prediccion="El resultado ocurrirá durante FY2025.") for item in valid]
        stale_year_errors = ResearchWorker._validate_hypothesis_contract(stale_year, date(2026, 10, 19))
        assert sum("references an expired year" in error for error in stale_year_errors) == 3

        stale_trigger = [dict(item, cuando_dejar_de_creerla="Tras el resultado de Q2-FY2025.") for item in valid]
        stale_trigger_errors = ResearchWorker._validate_hypothesis_contract(stale_trigger, date(2026, 10, 19))
        assert sum("references an expired year" in error for error in stale_trigger_errors) == 3

        missing_date = [dict(item) for item in valid]
        del missing_date[0]["fecha_objetivo"]
        missing_date_errors = ResearchWorker._validate_hypothesis_contract(missing_date, date(2026, 10, 19))
        assert any("missing valid ISO target date" in error for error in missing_date_errors)

        incomplete = [{"enunciado": "Creemos que el margen crecerá."}]
        errors = ResearchWorker._validate_hypothesis_contract(incomplete)
        assert any("rationale" in error for error in errors)
        assert any("prediction" in error for error in errors)
        assert any("falsification" in error for error in errors)
        assert any("stop-belief" in error for error in errors)

    def test_expired_hypothesis_keeps_previous_report_and_stops_before_assessment(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        base_path: str,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ):
        ticker, opp_id = seeded_opportunity
        report_path = tmp_journal.opportunity_path(ticker, opp_id) / "ddd_report.yml"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        previous_report = "ticker: TEST\nstatus: reviewed\n"
        report_path.write_text(previous_report, encoding="utf-8")

        expired_hypothesis = {
            "enunciado": "El margen operativo mejorará.",
            "por_que": "La mejora del mix de producto sostiene el margen.",
            "prediccion": "El margen superará 30%.",
            "fecha_objetivo": "2025-09-30",
            "magnitud": {"metrica": "operating_margin", "valor_esperado": 30, "unidad": "%"},
            "criterios_falsacion": ["El margen queda por debajo de 28%."],
            "cuando_dejar_de_creerla": "Si el margen cae debajo de 28%.",
        }
        worker = ResearchWorker({"provider": "test", "prompts_path": str(tmp_path)})
        worker.registry = _mock_research_registry()
        worker._run_prompt = MagicMock(side_effect=[
            {"tesis_inversion": "Tesis", "score_general": 75},
            {"hipotesis": [dict(expired_hypothesis) for _ in range(3)]},
            {"hipotesis": [dict(expired_hypothesis) for _ in range(3)]},
        ])
        worker._load_financial_data = MagicMock(return_value={})
        worker._enrich_company_info = MagicMock(return_value={"name": "Test", "sector": "Technology"})
        worker._fetch_target_consensus = MagicMock(return_value=None)
        worker._load_prior_catalysts = MagicMock(return_value=[])
        monkeypatch.setattr("idos.workers.ai.research_worker.time.sleep", lambda _: None)

        result = worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result["status"] == "hypothesis_validation_failed"
        assert any("target date must be after" in error for error in result["errors"])
        assert "[HYPOTHESIS] Contract validation failed" in capsys.readouterr().out
        assert report_path.read_text(encoding="utf-8") == previous_report
        assert not (tmp_journal.opportunity_path(ticker, opp_id) / "assessments").exists()
        assert not (tmp_journal.opportunity_path(ticker, opp_id) / "hypotheses.yml").exists()
        assert tmp_sqlite.get_opportunity(opp_id)["status"] == OpportunityStatus.SCREENED.value


    def test_systematic_report_persists_authoritative_strategy_context(
        self,
        seeded_opportunity: tuple[str, str],
        tmp_sqlite,
        tmp_journal,
        base_path: str,
        systematic_snapshot,
    ):
        import yaml

        ticker, opp_id = seeded_opportunity
        signal = {"ticker": ticker, "momentum": 0.9, "as_of_date": "2026-10-01"}
        opportunity = tmp_sqlite.get_opportunity(opp_id)
        opportunity.update({
            "strategy_id": "MOMENTUM_ETF",
            "strategy_version": "1.0",
            "research_profile": "systematic",
            "entry_policy": "SIGNAL_REBALANCE",
            "signal": signal,
        })
        tmp_sqlite.save_opportunity(opportunity)
        tmp_journal.save_opportunity(ticker, opportunity)

        worker = ResearchWorker({"llm_service": MagicMock()})
        worker._load_financial_data = MagicMock(return_value={"volatility_90d": 30})
        worker._enrich_company_info = MagicMock(return_value={"name": "Test ETF", "sector": "Financials"})
        worker._fetch_target_consensus = MagicMock(return_value={})
        config_path = Path(base_path) / "idos-config" / "strategies.yml"
        config_path.write_text(yaml.safe_dump({"strategies": {"MOMENTUM_ETF": {
            "enabled": True, "core": "CORE_3_GROWTH", "sleeve": "SYSTEMATIC_RETURN",
            "thesis_type": "SYSTEMATIC", "discovery_profile": "momentum_monthly",
            "research_profile": "systematic", "entry_policy": "SIGNAL_REBALANCE",
            "parameters": {"minimum_signal": 0.8, "maximum_signal": 3.6, "select_top": 2},
        }}}), encoding="utf-8")
        snapshot_path = systematic_snapshot(signal, {"minimum_signal": 0.8, "maximum_signal": 3.6, "select_top": 2})

        result = worker.run({"ticker": ticker, "opp_id": opp_id, "base_path": base_path})

        assert result["status"] == "completed"
        report_path = tmp_journal.opportunity_path(ticker, opp_id) / "ddd_report.yml"
        report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
        assert report["strategy_context"] == {
            "strategy_id": "MOMENTUM_ETF",
            "signal": signal,
            "risk_rating": "NOT_ASSESSED",
            "signal_policy": {"minimum_signal": 0.8, "maximum_signal": 3.6},
            "score_method": "momentum_div_max_v1",
            "probability_status": "NOT_ASSESSED",
            "report_method_version": "systematic_signal_v2",
            "signal_snapshot": {
                "signal": signal,
                "signal_policy": {"minimum_signal": 0.8, "maximum_signal": 3.6, "select_top": 2},
                "source": snapshot_path.relative_to(Path(base_path)).as_posix(),
                "generated_at": "2026-10-18T12:00:00-03:00", "run_scope": "bounded",
            },
        }
        assert report["score_general"] == 25
        worker._fetch_target_consensus.assert_not_called()
        hypotheses = tmp_journal.load_hypotheses(ticker, opp_id)
        assert len(hypotheses) == 1
        assert hypotheses[0]["statement"]
        assert hypotheses[0]["probability"] is None
        assert hypotheses[0]["confidence"] is None
        assert [item["threshold"] for item in hypotheses[0]["falsification"]] == [0.8, 3.6]
        assert len(hypotheses[0]["falsification_conditions"]) == 2
        stored = tmp_sqlite.conn.execute("SELECT probability, confidence FROM hypotheses WHERE opportunity_id=?", (opp_id,)).fetchone()
        assert stored["probability"] is None and stored["confidence"] is None




def test_hypothesis_generation_retries_once_with_validation_feedback(monkeypatch):
    from unittest.mock import MagicMock
    from idos.workers.ai.research_worker import ResearchWorker

    first = {"hipotesis": [{"id": "H1", "fecha_objetivo": "2025-01-01"}]}
    corrected = {"hipotesis": [{"id": "H1", "fecha_objetivo": "2027-01-01"}]}
    worker = object.__new__(ResearchWorker)
    worker._run_prompt = MagicMock(side_effect=[first, corrected])
    validator = MagicMock(side_effect=[["H1: prediction or trigger references an expired year"], []])
    monkeypatch.setattr(ResearchWorker, "_validate_hypothesis_contract", staticmethod(validator))

    result = worker._run_hypothesis_prompt_with_repair("ALAB", {
        "ticker": "ALAB",
        "as_of_date": "2026-10-20",
        "validation_feedback": "",
    })

    assert result is corrected
    assert worker._run_prompt.call_count == 2
    assert "expired year" in worker._run_prompt.call_args_list[1].args[2]["validation_feedback"]


def test_financial_evidence_context_preserves_observations_and_source_metadata():
    from idos.workers.ai.research_worker import ResearchWorker

    observations = {
        "fcf": {
            "selected_source": "stockanalysis.com",
            "values": {"stockanalysis.com": 276680000.0},
            "period_type": "TTM",
            "period_end_date": "2026-06-30",
            "unit": "provider_financial_currency",
            "currency": None,
            "source_metadata": {
                "stockanalysis.com": {
                    "period_type": "TTM",
                    "period_end_date": "2026-06-30",
                    "unit": "provider_financial_currency",
                    "source_url": "https://stockanalysis.com/stocks/alab/statistics/",
                }
            },
        }
    }

    context = ResearchWorker._financial_evidence_context({
        "financial_observations": observations,
        "data_provenance": {
            "sources_used": ["stockanalysis.com"],
            "field_sources": {"fcf": ["stockanalysis.com"]},
            "conflicts": [],
        },
    })

    assert context["observations"]["fcf"]["values"]["stockanalysis.com"] == 276680000.0
    assert context["observations"]["fcf"]["period_end_date"] == "2026-06-30"
    assert context["observations"]["fcf"]["source_metadata"]["stockanalysis.com"]["source_url"].startswith("https://")
    assert context["currency"] is None


def test_discovery_financial_observations_are_merged_into_research_data():
    from idos.workers.ai.research_worker import ResearchWorker

    cache_data = {
        "financial_observations": {"revenue": {"values": {"cache": 1.0}}},
        "data_provenance": {"sources_used": ["cache-source"]},
    }
    discovery = {
        "financial_observations": {
            "fcf": {
                "values": {"stockanalysis.com": 276680000.0},
                "period_type": "TTM",
                "period_end_date": "2026-06-30",
                "unit": "provider_financial_currency",
                "source_metadata": {
                    "stockanalysis.com": {
                        "source_url": "https://stockanalysis.com/stocks/alab/statistics/",
                    }
                },
            }
        },
        "data_provenance": {
            "sources_used": ["stockanalysis.com"],
            "field_sources": {"fcf": ["stockanalysis.com"]},
        },
    }

    merged = ResearchWorker._merge_discovery_financial_evidence(cache_data, discovery)

    assert merged["financial_observations"]["revenue"] == {"values": {"cache": 1.0}}
    fcf = merged["financial_observations"]["fcf"]
    assert fcf["values"]["stockanalysis.com"] == 276680000.0
    assert fcf["period_type"] == "TTM"
    assert fcf["period_end_date"] == "2026-06-30"
    assert fcf["unit"] == "provider_financial_currency"
    assert fcf["source_metadata"]["stockanalysis.com"]["source_url"].startswith("https://")
    assert merged["data_provenance"]["sources_used"] == ["cache-source", "stockanalysis.com"]
    assert merged["data_provenance"]["field_sources"]["fcf"] == ["stockanalysis.com"]


def test_multibaggers_research_evidence_excludes_unlisted_fields_and_preserves_source_period():
    from idos.workers.ai.research_worker import ResearchWorker

    context = ResearchWorker._research_financial_evidence({
        "current_ratio": 1.2,
        "private_account_balance": 123456,
        "financial_data_observed_at": "2026-10-15T12:00:00+00:00",
        "period_end_date": "2026-09-30",
        "source": "stockanalysis.com",
        "url": "https://stockanalysis.com/stocks/test/statistics/",
        "data_provenance": {
            "sources_used": ["stockanalysis.com"],
            "source_urls": [
                "https://stockanalysis.com/stocks/test/statistics/",
                "https://stockanalysis.com/stocks/test/financials/",
                "http://untrusted.test/metrics",
            ],
            "field_sources": {"current_ratio": ["stockanalysis.com"]},
            "field_urls": {"current_ratio": "https://stockanalysis.com/stocks/test/statistics/"},
        },
        "metric_observations": {
            "revenue_growth_pct": [{
                "source_id": "sec_edgar",
                "value": 18.5,
                "unit": "percent",
                "currency": "USD",
                "period": "FY:2025-01-01/2025-12-31",
                "reported_at": "2026-02-15",
                "observed_at": "2026-10-15T12:00:00+00:00",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                "internal_private_field": "must not reach the prompt",
            }],
            "private_account_balance": [{"value": 123456}],
        },
        "metric_observation_exclusions": {
            "revenue_growth_pct": [{"source_id": "yfinance", "reason_code": "MISSING_REPORT_DATE"}],
            "private_account_balance": [{"reason_code": "PRIVATE"}],
        },
        "financial_observations": {
            "current_ratio": {"status": "observed", "value": 1.2},
            "private_account_balance": {"status": "observed", "value": 123456},
        },
    })

    assert context["trusted_source_urls"] == [
        "https://stockanalysis.com/stocks/test/financials/",
        "https://stockanalysis.com/stocks/test/statistics/",
    ]
    evidence = context["source_observations"]["current_ratio"]
    assert evidence["value"] == 1.2
    assert evidence["period_end"] == "2026-09-30"
    assert evidence["sources"] == ["stockanalysis.com"]
    assert "private_account_balance" not in context["source_observations"]
    metric_observation = context["validated_metric_observations"]["revenue_growth_pct"][0]
    assert metric_observation["value"] == 18.5
    assert metric_observation["source_url"].startswith("https://data.sec.gov/")
    assert "internal_private_field" not in metric_observation
    assert "private_account_balance" not in context["validated_metric_observations"]
    assert context["metric_observation_exclusions"]["revenue_growth_pct"][0]["reason_code"] == "MISSING_REPORT_DATE"
    assert "private_account_balance" not in context["metric_observation_exclusions"]
    assert "private_account_balance" not in context["reconciled_observations"]



def test_multibaggers_prompt_context_is_bounded_and_omits_duplicate_blobs():
    import json
    from idos.workers.ai.research_worker import ResearchWorker

    context = ResearchWorker._multibaggers_prompt_context({
        "ticker": "TEST",
        "business_model": "business " * 2000,
        "products": [{"name": "product " * 1000, "details": "detail " * 1000} for _ in range(20)],
        "geography": {"regions": ["region " * 1000 for _ in range(20)]},
        "existing_wiki": "wiki " * 10000,
        "financial_data_evidence": "duplicate " * 10000,
        "recent_events": [{"date": "2026-10-21", "title": "title " * 1000, "summary": "summary " * 1000, "url": "https://example.com"}] * 9,
        "scenario_market_evidence": {"source": "https://example.com/quote", "price": 10},
    })

    assert len(json.dumps(context, ensure_ascii=False)) < 15_000
    assert len(context["products"]) == 5
    assert len(context["products"][0]["name"]) == 500
    assert len(context["geography"]["regions"]) == 5
    assert len(context["geography"]["regions"][0]) == 500
    assert "existing_wiki" not in context
    assert "financial_data_evidence" not in context
    assert len(context["recent_events"]) == 5
    assert len(context["recent_events"][0]["summary"]) == 500


def test_multibaggers_research_evidence_honors_configured_ratio_inputs():
    from idos.workers.ai.research_worker import ResearchWorker

    context = ResearchWorker._research_financial_evidence(
        {
            "current_assets": 100,
            "current_liabilities": 50,
            "interest_expense": 12,
            "financial_observations": {
                "current_assets": {"status": "observed", "value": 100},
                "interest_expense": {"status": "observed", "value": 12},
            },
        },
        allowed_input_fields={"current_assets", "current_liabilities"},
    )

    assert set(context["source_observations"]) == {"current_assets", "current_liabilities"}
    assert set(context["reconciled_observations"]) == {"current_assets"}


def test_multibaggers_prompt_requires_source_backed_ratio_statuses():
    from idos.ai.prompts import PromptRegistry

    repo_root = Path(__file__).resolve().parents[3]
    prompt = PromptRegistry(repo_root / "idos-config" / "prompts").load(
        "multibaggers", category="research"
    ).user_prompt

    rendered = prompt.format(
        ticker="TEST", name="Test Inc.", intake_package="{}", financial_summary="{}",
        research_financial_evidence="{}",
    )
    assert "unavailable" in rendered
    assert "No inventes cifras, URLs" in rendered
    assert "ni valores derivados" in rendered
    assert "ratios_investigados" in rendered
    assert "ratio_input_fields" in rendered
    assert "ratio_units" in rendered
    assert "unit" in rendered
    assert "scenario_analysis" in rendered
    assert "mutuamente excluyentes" in rendered
    assert "estimación analítica" in rendered
    assert "propuestas preliminares" in rendered
    assert "fuentes citadas deben respaldar esos inputs" in rendered
    assert "Copia cada URL exactamente" in rendered
    assert "calidad_evidencia" in rendered
    assert '"categoria": string' in rendered


def test_multibaggers_prompt_can_raise_output_budget_for_complete_ratio_json():
    class Registry:
        def get(self, _name, category=None):
            return "Valid JSON for {ticker}"

        def get_system(self, _name, category=None):
            return "Only JSON"

    class LLM:
        def __init__(self):
            self.kwargs = None

        def generate_structured(self, **kwargs):
            self.kwargs = kwargs
            return {"ok": True}

    worker = object.__new__(ResearchWorker)
    worker.registry = Registry()
    worker.llm = LLM()

    result = worker._run_prompt("multibaggers", "TEST", {"ticker": "TEST"}, max_tokens=8192)

    assert result == {"ok": True}
    assert worker.llm.kwargs["max_tokens"] == 8192


def test_multibaggers_research_shape_requires_downstream_types():
    valid = {
        "clasificacion_oportunidad": {"categoria": "multibaggers"},
        "error_mercado": {},
        "tesis_inversion": "Tesis",
        "score_general": 70,
        "dominio_riesgos": [],
        "dominio_catalizadores": [],
        "dominio_business_quality": {},
        "calidad_evidencia": {},
        "ratios_investigados": [],
        "risk_flags": [],
        "scenario_analysis": None,
    }
    assert ResearchWorker._validate_multibaggers_research_shape(valid) == []

    invalid = {**valid, "clasificacion_oportunidad": ["mal tipo"], "score_general": "alto"}
    errors = ResearchWorker._validate_multibaggers_research_shape(invalid)
    assert "clasificacion_oportunidad must be dict" in errors
    assert "score_general must be a finite number from 0 to 100" in errors


def test_multibaggers_ratio_contract_accepts_unavailable_with_reason_and_rejects_uncited_values():
    from idos.workers.ai.research_worker import ResearchWorker

    unavailable = [{"metric": "fcf_growth_pct", "status": "unavailable", "value": None,
                    "limitations": "No hay FCF comparable para dos períodos."}]
    assert ResearchWorker._validate_multibaggers_ratio_review(
        unavailable, ["fcf_growth_pct"]
    ) == []

    uncited = [{"metric": "fcf_growth_pct", "status": "calculated", "value": 12.0,
                "unit": "percent", "period_end": "2026-09-30", "formula": "x/y - 1",
                "inputs": ["fcf_current", "fcf_prior"], "sources": []}]
    errors = ResearchWorker._validate_multibaggers_ratio_review(
        uncited, ["fcf_growth_pct"], trusted_source_urls={"https://stockanalysis.com/fcf"}
    )
    assert "ratio needs source names and https URLs: fcf_growth_pct" in errors

    invented_source = [{**uncited[0], "sources": [{"name": "StockAnalysis", "url": "https://stockanalysis.com/invented"}]}]
    errors = ResearchWorker._validate_multibaggers_ratio_review(
        invented_source, ["fcf_growth_pct"], trusted_source_urls={"https://stockanalysis.com/fcf"}
    )
    assert "ratio cites a URL absent from research evidence: fcf_growth_pct" in errors

    sourced_but_unavailable_input = [{**invented_source[0], "sources": [
        {"name": "StockAnalysis", "url": "https://stockanalysis.com/fcf"}
    ]}]
    errors = ResearchWorker._validate_multibaggers_ratio_review(
        sourced_but_unavailable_input,
        ["fcf_growth_pct"],
        trusted_source_urls={"https://stockanalysis.com/fcf"},
        available_input_fields={"fcf"},
    )
    assert any("inputs absent from research evidence" in error for error in errors)




def test_multibaggers_ratio_units_are_normalized_from_strategy_config():
    from idos.workers.ai.research_worker import ResearchWorker

    url = "https://finance.yahoo.com/quote/ASML/balance-sheet/"
    ratio = [{
        "metric": "current_ratio", "status": "reported", "value": 1.4,
        "period_end": "2026-09-30", "sources": [{"name": "Yahoo Finance", "url": url}],
    }]
    configured_units = {"current_ratio": "x"}
    ResearchWorker._normalize_multibaggers_ratio_units(ratio, configured_units)
    assert ratio[0]["unit"] == "x"
    assert ResearchWorker._validate_multibaggers_ratio_review(
        ratio, ["current_ratio"], trusted_source_urls={url}, expected_units=configured_units
    ) == []

    ratio[0]["unit"] = "percent"
    errors = ResearchWorker._validate_multibaggers_ratio_review(
        ratio, ["current_ratio"], trusted_source_urls={url}, expected_units=configured_units
    )
    assert "ratio unit conflicts with configured unit for current_ratio: expected x" in errors


def test_ddd_prompt_never_converts_missing_financial_metrics_to_zero():
    from idos.ai.prompts import PromptRegistry

    repo_root = Path(__file__).resolve().parents[3]
    registry = PromptRegistry(repo_root / "idos-config" / "prompts")
    prompt = registry.load("ddd", category="research").user_prompt

    assert "No se rellenan métricas ausentes con cero" in prompt
    assert "Un dato ausente no significa cero" in prompt
    assert "No llames ajustado al flujo de caja libre reportado" in prompt
    assert "FCF Ajustado: {fcf_adjusted" not in prompt


def test_ddd_verified_facts_discards_malformed_llm_claims():
    from idos.workers.ai.research_worker import ResearchWorker

    assert ResearchWorker._verified_facts({"calidad_evidencia": {"hechos_verificados": 7}}) == []
    assert ResearchWorker._verified_facts({"calidad_evidencia": 7}) == []
    assert ResearchWorker._verified_facts({"calidad_evidencia": {
        "hechos_verificados": ["  dato con fuente  ", 4, None, ""]
    }}) == ["dato con fuente"]


def test_multibaggers_research_evidence_exposes_configured_statement_history():
    evidence = ResearchWorker._research_financial_evidence(
        {
            "revenue_history": [{
                "value": 39474.0, "unit": "source_reported_amount",
                "period": "TTM", "period_end": "2026-09-27",
            }],
            "data_provenance": {
                "field_sources": {"revenue_history": ["stockanalysis.com"]},
                "field_urls": {"revenue_history": "https://stockanalysis.com/stocks/asml/financials/"},
            },
            "financial_data_observed_at": "2026-10-21T12:00:00+00:00",
        },
        allowed_input_fields={"revenue_history"},
    )
    row = evidence["source_observations"]["revenue_history"]
    assert row["value"][0]["period_end"] == "2026-09-27"
    assert row["sources"] == ["stockanalysis.com"]
    assert row["source_url"] == "https://stockanalysis.com/stocks/asml/financials/"


def test_multibaggers_research_evidence_bounds_financial_history():
    from idos.workers.ai.research_worker import ResearchWorker

    history = [
        {
            "value": float(year),
            "unit": "source_reported_amount",
            "period": f"FY {year}",
            "period_end": f"{year}-12-31",
        }
        for year in range(2014, 2027)
    ]
    evidence = ResearchWorker._research_financial_evidence(
        {"revenue_history": history},
        allowed_input_fields={"revenue_history"},
    )

    row = evidence["source_observations"]["revenue_history"]
    assert [point["period_end"] for point in row["value"]] == [
        "2026-12-31", "2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31",
    ]
    assert row["omitted_points"] == 8
    assert len(history) == 13


def test_multibaggers_ratio_sources_bind_to_declared_input_provenance():
    from idos.workers.ai.research_worker import ResearchWorker

    ratio = {
        "metric": "gross_margin_pct",
        "status": "calculated",
        "inputs": ["gross_profit_history", "revenue_history"],
        "sources": [{"name": "stockanalysis.com", "url": "https://stockanalysis.com/stocks/asml/forecast/"}],
    }
    evidence = {
        "source_observations": {
            "gross_profit_history": {
                "sources": ["stockanalysis.com"],
                "source_url": "https://stockanalysis.com/stocks/asml/financials/",
            },
            "revenue_history": {
                "sources": ["stockanalysis.com"],
                "source_url": "https://stockanalysis.com/stocks/asml/financials/",
            },
        },
        "validated_metric_observations": {},
    }

    ResearchWorker._bind_multibaggers_ratio_sources([ratio], evidence)

    assert ratio["sources"] == [
        {"name": "stockanalysis.com", "url": "https://stockanalysis.com/stocks/asml/financials/"},
    ]


def test_multibaggers_ratio_sources_do_not_accept_unmapped_inputs():
    from idos.workers.ai.research_worker import ResearchWorker

    ratio = {
        "metric": "gross_margin_pct",
        "status": "calculated",
        "inputs": ["unlisted_private_field"],
        "sources": [{"name": "stockanalysis.com", "url": "https://example.com/unverified"}],
    }

    ResearchWorker._bind_multibaggers_ratio_sources(
        [ratio],
        {"source_observations": {}, "validated_metric_observations": {}},
    )

    assert ratio["sources"] == [
        {"name": "stockanalysis.com", "url": "https://example.com/unverified"},
    ]



def test_multibaggers_ratio_accepts_only_verified_fiscal_year_history_aliases():
    from idos.workers.ai.research_worker import ResearchWorker

    url = "https://stockanalysis.com/stocks/asml/financials/"
    evidence = {
        "source_observations": {
            "revenue_history": {
                "value": [
                    {"value": 100.0, "period": "FY 2023", "period_end": "2023-12-31"},
                    {"value": 80.0, "period": "FY 2022", "period_end": "2022-12-31"},
                ],
                "sources": ["stockanalysis.com"],
                "source_url": url,
            },
        },
        "validated_metric_observations": {},
    }
    aliases = ResearchWorker._multibaggers_financial_input_aliases(evidence)
    assert aliases == {
        "revenue_FY_2023": "revenue_history",
        "revenue_FY_2022": "revenue_history",
    }

    ratio = [{
        "metric": "revenue_cagr_3y_pct",
        "status": "calculated",
        "value": 25.0,
        "unit": "percent",
        "period_end": "2023-12-31",
        "formula": "(revenue_FY_2023 / revenue_FY_2022) - 1",
        "inputs": ["revenue_FY_2023", "revenue_FY_2022"],
        "sources": [{"name": "stockanalysis.com", "url": url}],
    }]
    available = set(evidence["source_observations"]) | set(aliases)
    assert ResearchWorker._validate_multibaggers_ratio_review(
        ratio,
        ["revenue_cagr_3y_pct"],
        trusted_source_urls={url},
        available_input_fields=available,
        expected_units={"revenue_cagr_3y_pct": "percent"},
    ) == []

    ResearchWorker._bind_multibaggers_ratio_sources(ratio, evidence)
    assert ratio[0]["sources"] == [{"name": "stockanalysis.com", "url": url}]

    ratio[0]["inputs"] = ["revenue_FY_2021"]
    errors = ResearchWorker._validate_multibaggers_ratio_review(
        ratio,
        ["revenue_cagr_3y_pct"],
        trusted_source_urls={url},
        available_input_fields=available,
        expected_units={"revenue_cagr_3y_pct": "percent"},
    )
    assert any("inputs absent from research evidence" in error for error in errors)
