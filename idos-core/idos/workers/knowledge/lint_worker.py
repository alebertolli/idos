import re
from pathlib import Path
from typing import Any

from idos.knowledge.claims import ClaimStore, Claim
from idos.knowledge.contradiction import ContradictionDetector
from idos.knowledge.wiki import AtomicWiki, WikiSection
from idos.data.knowledge import KnowledgeRepository
from idos.workers.base import BaseWorker


class WikiLintWorker(BaseWorker):
    name = "wiki_lint_worker"

    def _list_tickers_with_wiki(self, atomic: AtomicWiki) -> list[str]:
        return atomic.list_tickers()

    def _find_wikilinks(self, content: str) -> list[str]:
        raw = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)
        result = []
        for link in raw:
            link = link.split("#")[0].strip()
            if link:
                result.append(link)
        return result

    def _check_broken_links(self, ticker: str, sections: list[WikiSection], atomic: AtomicWiki) -> list[dict]:
        broken = []
        all_tickers = set(self._list_tickers_with_wiki(atomic))
        for section in sections:
            links = self._find_wikilinks(section.content)
            for link in links:
                link_upper = link.upper().strip()
                if link_upper not in all_tickers:
                    broken.append({
                        "ticker": ticker,
                        "section": section.name,
                        "broken_link": link,
                        "error": f"Page '{link}' not found in any company wiki",
                    })
        return broken

    def _find_orphans(self, atomic: AtomicWiki) -> list[str]:
        tickers = set(self._list_tickers_with_wiki(atomic))
        linked: set[str] = set()
        for t in tickers:
            sections = atomic.all_sections(t)
            for section in sections:
                for link in self._find_wikilinks(section.content):
                    linked.add(link.upper().strip())
        orphans = [t for t in sorted(tickers) if t not in linked]
        return orphans

    def _check_cross_company_contradictions(self, knowledge: KnowledgeRepository) -> list[dict]:
        contradictions = []
        claim_store = ClaimStore(str(knowledge.base))
        all_claims = claim_store.all()
        detector = ContradictionDetector()
        for i, c1 in enumerate(all_claims):
            for c2 in all_claims[i + 1:]:
                if c1.tags == c2.tags:
                    continue
                result = detector.evaluate(
                    ticker=c1.claim_id,
                    claim_statement=c1.statement,
                    new_evidence=c2.statement,
                    source=f"{c2.claim_id}",
                )
                if result:
                    contradictions.append({
                        "claim_a": c1.claim_id,
                        "claim_b": c2.claim_id,
                        "statement_a": c1.statement[:100],
                        "statement_b": c2.statement[:100],
                        "severity": result.severity.value,
                    })
        return contradictions

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        base_path = Path(context.get("base_path", "."))
        knowledge = KnowledgeRepository(base_path / "idos-knowledge")
        atomic = AtomicWiki(knowledge.base)

        report: dict[str, Any] = {
            "tickers_scanned": 0,
            "sections_scanned": 0,
            "broken_links": [],
            "orphan_tickers": [],
            "contradictions": [],
            "summary": {},
        }

        tickers = self._list_tickers_with_wiki(atomic)
        report["tickers_scanned"] = len(tickers)

        for t in tickers:
            sections = atomic.all_sections(t)
            report["sections_scanned"] += len(sections)
            broken = self._check_broken_links(t, sections, atomic)
            report["broken_links"].extend(broken)

        report["orphan_tickers"] = self._find_orphans(atomic)
        report["contradictions"] = self._check_cross_company_contradictions(knowledge)

        total_broken = len(report["broken_links"])
        total_orphans = len(report["orphan_tickers"])
        total_contradictions = len(report["contradictions"])
        report["summary"] = {
            "tickers_scanned": len(tickers),
            "sections_scanned": report["sections_scanned"],
            "broken_links_found": total_broken,
            "orphan_pages_found": total_orphans,
            "cross_company_contradictions": total_contradictions,
            "wiki_health_score": self._health_score(len(tickers), total_broken, total_orphans),
        }

        if total_broken:
            print(f"[LINT] {total_broken} broken wikilinks found")
            for bl in report["broken_links"][:10]:
                print(f"  {bl['ticker']}/{bl['section']}: [[{bl['broken_link']}]] - {bl['error']}")
        if total_orphans:
            print(f"[LINT] {total_orphans} orphan pages (no inbound links): {', '.join(report['orphan_tickers'])}")
        if total_contradictions:
            print(f"[LINT] {total_contradictions} cross-company contradictions found")
            for c in report["contradictions"][:5]:
                print(f"  {c['claim_a']} vs {c['claim_b']}: {c['severity']}")
        print(f"[LINT] Wiki health score: {report['summary']['wiki_health_score']}/100")

        return report

    @staticmethod
    def _health_score(ticker_count: int, broken: int, orphans: int) -> int:
        if ticker_count == 0:
            return 100
        broken_penalty = min(broken * 10, 50)
        orphan_penalty = min(orphans * 15, 40)
        score = 100 - broken_penalty - orphan_penalty
        return max(score, 0)
