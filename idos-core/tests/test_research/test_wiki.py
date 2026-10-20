from idos.research.wiki import WikiBuilder


def test_wiki_build():
    builder = WikiBuilder()
    data = {
        "knowledge_base": {
            "static": {"business_model": "E-commerce platform",
                       "moat_description": "Strong brand",
                       "products": ["Marketplace", "Payments"]},
            "dynamic": {"metrics": {"roic": 25, "operating_margin": 20, "revenue_growth": 15}},
        },
        "competitors": ["AMZN"],
        "catalysts": [{"description": "New market entry", "impact": "high", "timeline": "short"}],
    }
    wiki = builder.build("MELI", data)
    assert len(wiki) == len(builder.SECTIONS)
    assert "Business Model" in wiki["business_model"]
    assert "Marketplace" in wiki["products"]


def test_wiki_render_markdown():
    builder = WikiBuilder()
    wiki = builder.build("MELI", {
        "knowledge_base": {"static": {"business_model": "E-commerce"},
                          "dynamic": {"metrics": {}}},
    })
    md = builder.render_markdown(wiki)
    assert "## Business Model" in md
    assert "## Investment Thesis" in md
