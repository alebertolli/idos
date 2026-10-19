from typing import Any


class KnowledgeBaseQueryEngine:
    def __init__(self):
        self._articles: dict[str, str] = {}

    def index_article(self, ticker: str, content: str):
        self._articles[ticker.upper()] = content

    def remove_article(self, ticker: str):
        self._articles.pop(ticker.upper(), None)

    def search(self, query: str) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for ticker, content in self._articles.items():
            score = 0
            if query_lower in ticker.lower():
                score += 10
            if query_lower in content.lower():
                score += content.lower().count(query_lower)
            if score > 0:
                results.append({"ticker": ticker, "score": score, "snippet": self._snippet(content, query_lower)})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def _snippet(self, content: str, query: str, context_chars: int = 80) -> str:
        idx = content.lower().find(query)
        if idx == -1:
            return content[:200]
        start = max(0, idx - context_chars)
        end = min(len(content), idx + len(query) + context_chars)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    def get_article(self, ticker: str) -> str | None:
        return self._articles.get(ticker.upper())

    def article_count(self) -> int:
        return len(self._articles)

    def clear(self):
        self._articles.clear()
