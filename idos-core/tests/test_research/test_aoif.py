from idos.research.aoif import AOIFProtocol


def test_aoif_execution():
    aoif = AOIFProtocol()
    result = aoif.execute("OPP-001", "MELI", {
        "knowledge_base": {
            "static": {"business_model": "E-commerce", "moat_description": "Network effects"},
            "dynamic": {"metrics": {"roic": 25, "operating_margin": 22, "revenue_growth": 20}},
        },
        "competitors": ["AMZN", "BABA"],
    })
    assert result.opportunity_id == "OPP-001"
    assert result.completed is True
    assert len(result.steps) == 8
    assert result.score > 0


def test_aoif_get_result():
    aoif = AOIFProtocol()
    aoif.execute("OPP-002", "TEST", {"knowledge_base": {"dynamic": {"metrics": {}}}})
    result = aoif.get_result("OPP-002")
    assert result is not None
    assert aoif.get_result("UNKNOWN") is None
