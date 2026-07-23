from pathlib import Path
import tempfile

import pytest
import yaml

from idos.knowledge.wiki import AtomicWiki, WikiSection, WikiMetadata
from idos.workers.knowledge.lint_worker import WikiLintWorker


class TestWikiLintWorker:
    @pytest.fixture
    def worker(self):
        return WikiLintWorker({})

    @pytest.fixture
    def wiki_env(self):
        tmp = Path(tempfile.mkdtemp())
        knowledge_base = tmp / "idos-knowledge"
        companies = knowledge_base / "companies"
        companies.mkdir(parents=True)

        wiki = AtomicWiki(knowledge_base)

        for ticker, sections_data in [
            ("TESTA", {"business": "Content with [[TESTB]] link", "catalysts": "No links here"}),
            ("TESTB", {"business": "Content with [[TESTC]] link", "catalysts": "Also has [[TESTA]] link"}),
            ("TESTC", {"business": "No links in this section", "catalysts": "Has broken [[NONEXISTENT]] link"}),
            ("ORPHAN", {"business": "No links at all, no one links here either"}),
        ]:
            company_dir = companies / ticker
            company_dir.mkdir()
            with open(company_dir / "company.yml", "w", encoding="utf-8") as f:
                yaml.dump({"name": f"Company {ticker}", "ticker": ticker}, f)
            for section_name, content in sections_data.items():
                section = WikiSection(name=section_name, content=content, metadata=WikiMetadata.fresh())
                wiki.set_section(ticker, section)

        return tmp, wiki

    def test_find_wikilinks(self, worker):
        content = "Some text [[TESTA]] and [[TESTB|Company B]] and [[TESTC#heading]]"
        links = worker._find_wikilinks(content)
        assert "TESTA" in links
        assert "TESTB" in links
        assert "TESTC" in links

    def test_broken_links(self, worker, wiki_env):
        tmp, wiki = wiki_env
        sections = wiki.all_sections("TESTC")
        broken = worker._check_broken_links("TESTC", sections, wiki)
        assert len(broken) >= 1
        assert any("NONEXISTENT" in b["broken_link"] for b in broken)

    def test_no_broken_links(self, worker, wiki_env):
        tmp, wiki = wiki_env
        sections = wiki.all_sections("TESTA")
        broken = worker._check_broken_links("TESTA", sections, wiki)
        testc_broken = [b for b in broken if "NONEXISTENT" in b.get("broken_link", "")]
        assert len(testc_broken) == 0

    def test_orphans(self, worker, wiki_env):
        tmp, wiki = wiki_env
        orphans = worker._find_orphans(wiki)
        assert "ORPHAN" in orphans
        assert "TESTA" not in orphans

    def test_run_produces_report(self, worker, wiki_env):
        tmp, wiki = wiki_env
        context = {"base_path": str(tmp)}
        report = worker.run(context)
        assert report["tickers_scanned"] == 4
        assert report["summary"]["broken_links_found"] >= 1
        assert report["summary"]["orphan_pages_found"] >= 1
        assert "wiki_health_score" in report["summary"]

    def test_health_score(self):
        assert WikiLintWorker._health_score(5, 0, 0) == 100
        assert WikiLintWorker._health_score(5, 2, 1) == 65
        assert WikiLintWorker._health_score(0, 0, 0) == 100
