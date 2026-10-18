from datetime import date
from pathlib import Path

from idos.decision.assessment_pipeline import _authorization_rule_ids, _eval_research_quality
from idos.research.quality_gate import evaluate_research_quality


def test_legacy_unstructured_research_is_blocked():
    result = evaluate_research_quality({
        "research_status": "COMPLETED",
        "calidad_evidencia": {"hechos_verificados": ["ROIC 15%"]},
        "dominio_catalizadores": [{"descripcion": "Hito 2025", "horizonte": "corto"}],
    }, as_of=date(2026, 10, 18))

    assert result["passed"] is False
    assert "fact_1_unstructured" in result["failures"]
    assert "catalyst_1_review_date_missing_or_invalid" in result["failures"]


def test_structured_sources_and_future_catalyst_pass_metadata_gate():
    source = {"title": "Annual report", "url": "https://example.com/report", "source_date": "2026-03-01"}
    report = {
        "research_status": "COMPLETED",
        "calidad_evidencia": {"hechos_reportados": [{
            "statement": "Revenue grew 12%", "period": "FY2025", "unit": "%", "sources": [source],
        }]},
        "dominio_catalizadores": [{
            "descripcion": "Commissioning milestone", "review_by": "2027-03-01", "sources": [source],
        }],
    }

    result = evaluate_research_quality(report, as_of=date(2026, 10, 18))

    assert result["passed"] is True
    assert result["scope"] == "metadata_and_freshness_only_not_source_relevance_or_truth"


def test_expired_catalyst_and_future_source_date_fail():
    report = {
        "research_status": "COMPLETED",
        "calidad_evidencia": {"hechos_reportados": [{
            "statement": "Revenue grew", "period": "FY2025", "unit": "%",
            "sources": [{"url": "https://example.com", "source_date": "2027-01-01"}],
        }]},
        "dominio_catalizadores": [{
            "descripcion": "Past milestone", "review_by": "2025-12-31",
            "sources": [{"url": "https://example.com", "source_date": "2025-01-01"}],
        }],
    }

    result = evaluate_research_quality(report, as_of=date(2026, 10, 18))

    assert result["passed"] is False
    assert "fact_1_source_metadata_missing_or_invalid" in result["failures"]
    assert "catalyst_1_expired" in result["failures"]


def test_quality_rule_is_mandatory_even_if_config_omits_it(tmp_path: Path):
    rules = tmp_path / "idos-config" / "rules"
    rules.mkdir(parents=True)
    (rules / "entry_rules.yml").write_text(
        "rules:\n  - id: RULE-001\n    active: true\n    stage: authorization\n",
        encoding="utf-8",
    )

    assert _authorization_rule_ids(tmp_path) == {"RULE-001", "RULE-010"}
    blocked = _eval_research_quality({"research_quality": {"passed": False, "failures": ["fact_1_unstructured"]}})
    passed = _eval_research_quality({"research_quality": {"passed": True, "failures": []}})
    assert blocked.passed is False
    assert "fact_1_unstructured" in blocked.details
    assert passed.passed is True
