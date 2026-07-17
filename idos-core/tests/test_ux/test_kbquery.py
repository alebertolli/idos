import pytest
from idos.ux.kbquery import KnowledgeBaseQueryEngine


class TestKnowledgeBaseQueryEngine:
    def test_index_and_search(self):
        kb = KnowledgeBaseQueryEngine()
        kb.index_article("AAPL", "Apple is a technology company with strong fundamentals and a wide moat.")
        kb.index_article("MSFT", "Microsoft is a leading software company with growing cloud business.")
        results = kb.search("technology")
        assert len(results) == 1
        assert results[0]["ticker"] == "AAPL"

    def test_search_multiple_matches(self):
        kb = KnowledgeBaseQueryEngine()
        kb.index_article("AAPL", "Apple makes iPhones. Apple has a strong brand. Apple is innovative.")
        kb.index_article("MSFT", "Microsoft makes software. Microsoft has Azure.")
        results = kb.search("Apple")
        assert len(results) == 1
        assert results[0]["score"] == 3

    def test_search_no_results(self):
        kb = KnowledgeBaseQueryEngine()
        kb.index_article("AAPL", "Apple is a company.")
        results = kb.search("nonexistent")
        assert len(results) == 0

    def test_remove_article(self):
        kb = KnowledgeBaseQueryEngine()
        kb.index_article("AAPL", "Content")
        kb.remove_article("AAPL")
        assert kb.article_count() == 0

    def test_get_article(self):
        kb = KnowledgeBaseQueryEngine()
        kb.index_article("AAPL", "Some content")
        assert kb.get_article("AAPL") == "Some content"
        assert kb.get_article("MSFT") is None
