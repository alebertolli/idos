from idos.research.ddd import DeepDueDiligenceWorker


def test_ddd_complete():
    worker = DeepDueDiligenceWorker()
    result = worker.run("MELI", {
        "knowledge_base": {
            "static": {"moat_description": "Network effects and brand",
                       "business_model": "E-commerce and fintech"},
            "dynamic": {"metrics": {
                "roic": 28, "operating_margin": 25, "revenue_growth": 22,
                "debt_to_equity": 0.3,
            }},
        },
        "catalysts": [{"description": "Logistics expansion", "impact": "high", "timeline": "short"}],
    })
    assert result.ticker == "MELI"
    assert result.score >= 80
    assert len(result.risks_identified) == 0
    assert result.business_quality == "EXCEPTIONAL"


def test_ddd_high_risk():
    worker = DeepDueDiligenceWorker()
    result = worker.run("RISKY", {
        "knowledge_base": {
            "dynamic": {"metrics": {
                "roic": 3, "operating_margin": 2, "revenue_growth": -5,
                "debt_to_equity": 4.5,
            }},
        },
    })
    assert len(result.risks_identified) >= 2
    assert result.score <= 50
