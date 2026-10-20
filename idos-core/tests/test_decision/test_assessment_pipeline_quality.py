import json

from idos.decision.assessment_pipeline import (
    _remove_buylist_entry,
    _authorization_rule_ids,
    _compute_asymmetry,
    _eval_asymmetry,
    _eval_financial_data_quality,
    _financial_data_quality,
    _load_financial_data,
    _normalize_decimal_pcts,
    _register_authorization_rules,
)
from idos.data.sqlite import SQLiteStore
from idos.decision.orchestrator import DecisionOrchestrator
from idos.rules.engine import RulesEngine


def test_catalyst_probability_estimate_is_provisional_and_cannot_pass_rule_008():
    asymmetry = _compute_asymmetry(
        [
            {"descripcion": "Crecimiento acelerado", "impacto": "alto", "probabilidad_pct": 70},
            {"descripcion": "Compresión de múltiplo", "impacto": "bajo", "probabilidad_pct": 30},
        ],
        current_price=100,
        target_low=70,
        target_mean=120,
        target_high=160,
    )

    assert asymmetry is not None
    assert asymmetry["benefit_risk_ratio"] >= 3
    assert asymmetry["validation_status"] == "provisional"
    assert asymmetry["authorization_eligible"] is False
    assert asymmetry["passes_threshold"] is False

    result = _eval_asymmetry({"asymmetry": asymmetry})
    assert not result.passed
    assert "autorización bloqueada" in result.details


def test_financial_data_quality_accepts_zero_as_a_valid_numeric_value():
    quality = _financial_data_quality({
        "roic_pct": 0,
        "operating_margin_pct": 0,
        "revenue_growth_pct": 0,
        "pe_ratio_ttm": 0,
        "debt_equity_ratio": 0,
        "source": "provider-x",
        "fundamentals_as_of": "2026-09-30",
    })

    assert quality["status"] == "good"
    assert quality["core_metric_coverage"] == "5/5"
    assert quality["missing_core_metrics"] == []


def test_financial_data_quality_exposes_missing_as_of_date():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "provider-x",
    })

    assert quality["status"] == "partial"
    assert quality["missing_provenance"] == ["as_of_date"]


def test_financial_data_quality_marks_sparse_core_metrics_poor():
    quality = _financial_data_quality({"source": "provider-x", "as_of_date": "2026-09-30"})

    assert quality["status"] == "poor"
    assert quality["core_metric_coverage"] == "0/5"
    assert set(quality["missing_core_metrics"]) == {
        "roic", "operating_margin", "revenue_growth", "pe_ratio", "debt_to_equity"
    }


def test_financial_quality_gate_blocks_conflicting_core_metric_sources():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 84.785,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "stockanalysis.com, yfinance",
        "fundamentals_as_of": "2026-09-30",
        "data_provenance": {
            "conflicts": [{
                "field": "revenue_growth_pct",
                "sources": {"stockanalysis.com": 65.07, "yfinance": 104.5},
                "deviation_pct": 23.3,
            }],
        },
    })

    result = _eval_financial_data_quality({"financial_data_quality": quality})

    assert quality["status"] == "poor"
    assert quality["conflicting_core_metrics"] == ["revenue_growth_pct"]
    assert not result.passed
    assert "cobertura de métricas insuficiente" not in result.details
    assert "conflicto entre fuentes" in result.details


def test_financial_quality_gate_blocks_unreconciled_core_metric_periods():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 104.5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "stockanalysis.com, yfinance",
        "fundamentals_as_of": "2026-09-30",
        "financial_observations": {
            "revenue_growth_pct": {
                "period_status": "PROVIDER_REPORTED_NOT_RECONCILED",
            },
        },
    })

    result = _eval_financial_data_quality({"financial_data_quality": quality})

    assert quality["status"] == "poor"
    assert quality["unreconciled_core_metrics"] == ["revenue_growth_pct"]
    assert not result.passed
    assert "periodo financiero no reconciliado" in result.details


def test_financial_quality_gate_blocks_unspecified_core_metric_period():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 104.5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "yfinance",
        "fundamentals_as_of": "2026-09-30",
        "financial_observations": {
            "revenue_growth_pct": {
                "period_status": "PERIOD_UNSPECIFIED",
            },
        },
    })

    result = _eval_financial_data_quality({"financial_data_quality": quality})

    assert quality["status"] == "poor"
    assert quality["unreconciled_core_metrics"] == ["revenue_growth_pct"]
    assert not result.passed


def test_financial_quality_accepts_single_source_metric_with_non_comparable_peer():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 38.55,
        "revenue_growth_pct": 22.54,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "stockanalysis.com, yfinance",
        "fundamentals_as_of": "2026-09-30",
        "financial_observations": {
            "operating_margin_pct": {
                "period_status": "SINGLE_SOURCE",
                "values": {"stockanalysis.com": 38.55},
                "non_comparable_values": {"yfinance": 44.356},
            },
            "revenue_growth_pct": {
                "period_status": "SINGLE_SOURCE",
                "values": {"stockanalysis.com": 22.54},
                "non_comparable_values": {"yfinance": 55.2},
            },
        },
    })

    result = _eval_financial_data_quality({"financial_data_quality": quality})

    assert quality["status"] == "good"
    assert quality["conflicting_core_metrics"] == []
    assert quality["unreconciled_core_metrics"] == []
    assert result.passed


def test_financial_quality_gate_blocks_missing_cutoff_and_passes_valid_partial_coverage():
    missing_cutoff = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "provider-x",
    })
    blocked = _eval_financial_data_quality({"financial_data_quality": missing_cutoff})
    assert not blocked.passed
    assert "fecha de corte ausente" in blocked.details

    partial_with_provenance = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "source": "provider-x",
        "fundamentals_as_of": "2026-09-30",
    })
    passed = _eval_financial_data_quality({"financial_data_quality": partial_with_provenance})
    assert partial_with_provenance["status"] == "partial"
    assert partial_with_provenance["core_metric_coverage"] == "4/5"
    assert passed.passed


def test_financial_quality_gate_rejects_malformed_or_future_cutoff():
    for cutoff in ("2026-02-30", "2027-01-01", "not-a-date"):
        quality = _financial_data_quality({
            "roic_pct": 25,
            "operating_margin_pct": 20,
            "revenue_growth_pct": 5,
            "pe_ratio_ttm": 18,
            "debt_equity_ratio": 0.5,
            "source": "provider-x",
            "as_of_date": cutoff,
        })
        result = _eval_financial_data_quality({"financial_data_quality": quality})
        assert quality["as_of_date"] is None
        assert not result.passed


def test_financial_quality_uses_provider_reported_unix_cutoff_and_its_source():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "source": "stockanalysis.com",
        "financial_period_end_timestamp": 1782518400,
        "data_provenance": {
            "field_sources": {"financial_period_end_timestamp": ["yfinance"]},
        },
    })

    assert quality["as_of_date"] == "2026-06-27"
    assert quality["as_of_date_source"] == "yfinance"
    assert quality["status"] == "partial"
    assert _eval_financial_data_quality({"financial_data_quality": quality}).passed

    for timestamp in (1782518400000, 1800000000):
        invalid = _financial_data_quality({
            "roic_pct": 25,
            "operating_margin_pct": 20,
            "revenue_growth_pct": 5,
            "pe_ratio_ttm": 18,
            "debt_equity_ratio": 0.5,
            "source": "provider-x",
            "financial_period_end_timestamp": timestamp,
            "data_provenance": {
                "field_sources": {"financial_period_end_timestamp": ["yfinance"]},
            },
        })
        assert invalid["as_of_date"] is None
        assert not _eval_financial_data_quality({"financial_data_quality": invalid}).passed


def test_financial_quality_uses_stockanalysis_provider_update_date_and_labels_basis():
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "stockanalysis.com",
        "provider_data_updated_date": "2026-10-19",
        "data_provenance": {
            "sources_used": ["stockanalysis.com"],
            "field_sources": {"provider_data_updated_date": ["stockanalysis.com"]},
        },
    })

    assert quality["as_of_date"] == "2026-10-19"
    assert quality["as_of_basis"] == "provider_data_updated_date"
    assert quality["as_of_date_source"] == "stockanalysis.com"
    assert _eval_financial_data_quality({"financial_data_quality": quality}).passed

    unstamped = _financial_data_quality({
        "operating_margin_pct": 20,
        "source": "stockanalysis.com",
        "provider_data_updated_date": "2026-10-19",
    })
    assert "as_of_date_source" in unstamped["missing_provenance"]
    assert not _eval_financial_data_quality({"financial_data_quality": unstamped}).passed


def test_percentage_normalization_uses_provider_units_instead_of_sparse_average():
    stockanalysis = _normalize_decimal_pcts({
        "source": "stockanalysis.com",
        "operating_margin_pct": 17.3,
        "revenue_growth_pct": 4.2,
    })
    yahoo = _normalize_decimal_pcts({
        "source": "yfinance",
        "gross_margin_pct": 0.45,
        "operating_margin_pct": 18.0,
        "data_provenance": {
            "field_sources": {
                "gross_margin_pct": ["yfinance"],
                "operating_margin_pct": ["yfinance"],
            },
        },
    })

    assert stockanalysis["operating_margin_pct"] == 17.3
    assert stockanalysis["revenue_growth_pct"] == 4.2
    assert yahoo["gross_margin_pct"] == 45.0
    assert yahoo["operating_margin_pct"] == 18.0


def test_financial_loader_prefers_normalized_cache_with_cutoff_over_unstamped_event(tmp_path):
    sqlite = SQLiteStore(tmp_path / "idos.db")
    sqlite.log_event(
        "market_data:refreshed",
        {"ticker": "ARM", "source": "stockanalysis.com", "operating_margin_pct": 17.3},
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "ARM.json").write_text(
        json.dumps({
            "ticker": "ARM",
            "source": "stockanalysis.com",
            "operating_margin_pct": 17.3,
            "financial_period_end_timestamp": 1782518400,
            "data_provenance": {
                "field_sources": {"financial_period_end_timestamp": ["yfinance"]},
            },
        }),
        encoding="utf-8",
    )

    financial = _load_financial_data("ARM", sqlite)
    quality = _financial_data_quality(financial)

    assert financial["financial_period_end_timestamp"] == 1782518400
    assert quality["as_of_date"] == "2026-06-27"
    assert quality["as_of_date_source"] == "yfinance"


def test_financial_loader_refreshes_uncutoff_cache_from_stockanalysis(tmp_path, monkeypatch):
    from idos.workers.data.stockanalysis import StockAnalysisWorker

    monkeypatch.chdir(tmp_path)
    sqlite = SQLiteStore(tmp_path / "idos.db")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "ARM.json").write_text(json.dumps({
        "ticker": "ARM", "source": "stockanalysis.com", "operating_margin_pct": 10,
    }), encoding="utf-8")
    live = {
        "ticker": "ARM", "source": "stockanalysis.com", "operating_margin_pct": 17.3,
        "provider_data_updated_date": "2026-10-19",
        "data_provenance": {
            "sources_used": ["stockanalysis.com"],
            "field_sources": {"provider_data_updated_date": ["stockanalysis.com"]},
        },
    }
    monkeypatch.setattr(StockAnalysisWorker, "run", lambda self, context: live)

    financial = _load_financial_data("ARM", sqlite)

    assert financial["operating_margin_pct"] == 17.3
    assert financial["provider_data_updated_date"] == "2026-10-19"


def test_financial_quality_rule_cannot_be_disabled_by_custom_authorization_config(tmp_path):
    rules_path = tmp_path / "idos-config" / "rules" / "entry_rules.yml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        "rules:\n  - id: RULE-005\n    active: true\n    stage: authorization\n",
        encoding="utf-8",
    )

    assert "RULE-010" in _authorization_rule_ids(tmp_path)


def test_missing_cutoff_blocks_orchestrated_decision_even_with_high_conviction(tmp_path):
    rules_path = tmp_path / "idos-config" / "rules" / "entry_rules.yml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        "rules:\n"
        "  - id: RULE-005\n    active: true\n    stage: authorization\n"
        "  - id: RULE-008\n    active: true\n    stage: authorization\n",
        encoding="utf-8",
    )
    engine = RulesEngine()
    _register_authorization_rules(engine, tmp_path)
    orchestrator = DecisionOrchestrator(rules_engine=engine)
    quality = _financial_data_quality({
        "roic_pct": 25,
        "operating_margin_pct": 20,
        "revenue_growth_pct": 5,
        "pe_ratio_ttm": 18,
        "debt_equity_ratio": 0.5,
        "source": "provider-x",
    })
    provisional_asymmetry = _compute_asymmetry(
        [
            {"descripcion": "Crecimiento acelerado", "impacto": "alto", "probabilidad_pct": 70},
            {"descripcion": "Compresión de múltiplo", "impacto": "bajo", "probabilidad_pct": 30},
        ],
        current_price=100,
        target_low=70,
        target_mean=120,
        target_high=160,
    )

    proposal = orchestrator.run_pipeline("opportunity:transitioned", {
        "opportunity_id": "OPP-QUALITY-001",
        "ticker": "AAPL",
        "force_relevance": True,
        "financial_data_quality": quality,
        "asymmetry": provisional_asymmetry,
        "precomputed_assessments": {
            "BusinessAssessmentEngine": 90,
            "ValuationAssessmentEngine": 90,
            "RecoveryAssessmentEngine": 90,
            "RiskAssessmentEngine": 90,
            "PortfolioAssessmentEngine": 90,
        },
    })

    assert proposal is not None
    assert proposal.conviction_score >= 70
    assert proposal.recommendation == "BLOCKED"
    assert "RULE-010" in proposal.rules_failed
    assert "RULE-008" in proposal.rules_failed


def test_reassessment_removes_only_the_stale_manager_approved_buylist_entry(tmp_path):
    import yaml

    path = tmp_path / "idos-journal/portfolio/buylist.yml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"entries": [
        {"ticker": "VIST", "opp_id": "OPP-OLD"},
        {"ticker": "VIST", "opp_id": "OPP-CURRENT"},
        {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
    ]}), encoding="utf-8")

    assert _remove_buylist_entry("VIST", "OPP-CURRENT", tmp_path)
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["entries"]
    assert entries == [
        {"ticker": "VIST", "opp_id": "OPP-OLD"},
        {"ticker": "AAPL", "opp_id": "OPP-AAPL"},
    ]

