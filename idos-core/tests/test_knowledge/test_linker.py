from pathlib import Path
import tempfile

import yaml
import pytest

from idos.knowledge.linker import CrossCompanyLinker


class TestCrossCompanyLinker:
    @pytest.fixture
    def linker(self):
        tmp = Path(tempfile.mkdtemp())
        companies = tmp / "companies"
        companies.mkdir()

        companies_a = {
            "name": "Company A Technology",
            "ticker": "TESTA",
            "sector": "Technology",
            "industry": "Software",
        }
        companies_b = {
            "name": "Company B Technology",
            "ticker": "TESTB",
            "sector": "Technology",
            "industry": "Software",
        }
        companies_c = {
            "name": "Company C Mining",
            "ticker": "TESTC",
            "sector": "Basic Materials",
            "industry": "Gold",
        }
        for ticker, data in [("TESTA", companies_a), ("TESTB", companies_b), ("TESTC", companies_c)]:
            company_dir = companies / ticker
            company_dir.mkdir()
            with open(company_dir / "company.yml", "w", encoding="utf-8") as f:
                yaml.dump(data, f)

        return CrossCompanyLinker(tmp)

    def test_find_related_by_sector(self, linker):
        related = linker.find_related("TESTA")
        assert "same_sector" in related
        assert "TESTB" in related["same_sector"]
        assert "TESTC" not in related["same_sector"]

    def test_find_related_by_industry(self, linker):
        related = linker.find_related("TESTA")
        assert "same_industry" in related
        assert "TESTB" in related["same_industry"]

    def test_no_related_for_isolated_company(self, linker):
        related = linker.find_related("TESTC")
        for key in related:
            assert "TESTA" not in related[key]
            assert "TESTB" not in related[key]

    def test_render_links_section(self, linker):
        section = linker.render_links_section("TESTA")
        assert section
        assert "[[TESTB" in section
        assert "## Related Companies" in section

    def test_inject_links(self, linker):
        wiki = "## Business Model\n\nTest content\n\n---\n\n## Investment Thesis\n\nGreat company"
        result = linker.inject_links("TESTA", wiki)
        assert "## Related Companies" in result
        assert "[[TESTB" in result
        assert "## Business Model" in result
        assert result.index("## Business Model") < result.index("## Related Companies")

    def test_inject_links_no_related(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "companies").mkdir()
        linker = CrossCompanyLinker(tmp)
        wiki = "## Business Model\n\nTest content"
        result = linker.inject_links("SOLO", wiki)
        assert result == wiki

    def test_inject_links_replaces_existing(self, linker):
        wiki = "## Business Model\n\nContent\n\n---\n\n## Related Companies\n\nOld links\n\n---\n\n## Catalysts\n\nStuff"
        result = linker.inject_links("TESTA", wiki)
        assert "## Related Companies" in result
        assert "Old links" not in result
        assert "[[TESTB" in result
