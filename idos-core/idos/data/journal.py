from pathlib import Path
from typing import Any
import yaml


class JournalRepository:
    def __init__(self, base_path: Path):
        self.base = base_path

    def case_file_path(self, ticker: str) -> Path:
        return self.base / "companies" / ticker.upper() / "case_file"

    def opportunity_path(self, ticker: str, opp_id: str) -> Path:
        return self.case_file_path(ticker) / "opportunities" / opp_id

    def save_case_file(self, ticker: str, data: dict[str, Any]):
        path = self.case_file_path(ticker)
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / "case_file.yml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_case_file(self, ticker: str) -> dict[str, Any] | None:
        filepath = self.case_file_path(ticker) / "case_file.yml"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_opportunity(self, ticker: str, opp_data: dict[str, Any]):
        path = self.opportunity_path(ticker, opp_data["id"])
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / "opportunity.yml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(opp_data, f, default_flow_style=False, allow_unicode=True)

    def load_opportunity(self, ticker: str, opp_id: str) -> dict[str, Any] | None:
        filepath = self.opportunity_path(ticker, opp_id) / "opportunity.yml"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save_assessment(self, ticker: str, opp_id: str, assessment: dict[str, Any]):
        path = self.opportunity_path(ticker, opp_id) / "assessments"
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / f"{assessment['id']}.yml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(assessment, f, default_flow_style=False, allow_unicode=True)

    def list_all_opportunities(self, status: str | None = None) -> list[dict[str, Any]]:
        results = []
        companies_dir = self.base / "companies"
        if not companies_dir.exists():
            return results
        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name
            opp_dir = d / "case_file" / "opportunities"
            if not opp_dir.exists():
                continue
            for opp in sorted(opp_dir.iterdir()):
                if not opp.is_dir():
                    continue
                yf = opp / "opportunity.yml"
                if not yf.exists():
                    continue
                try:
                    data = yaml.safe_load(yf.read_text(encoding="utf-8"))
                    if data:
                        if status is None or data.get("status") == status:
                            data["ticker"] = ticker
                            results.append(data)
                except Exception:
                    pass
        return results

    def hypothesis_path(self, ticker: str, opp_id: str) -> Path:
        return self.opportunity_path(ticker, opp_id) / "hypotheses.yml"

    def save_hypothesis(self, ticker: str, opp_id: str, hypothesis: dict[str, Any]):
        path = self.hypothesis_path(ticker, opp_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if path.exists():
            try:
                existing = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("hypotheses", []) or []
            except Exception:
                existing = []
        existing = [h for h in existing if h.get("id") != hypothesis.get("id")]
        existing.append(hypothesis)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump({"hypotheses": existing}, f, default_flow_style=False, allow_unicode=True)

    def load_hypotheses(self, ticker: str, opp_id: str) -> list[dict[str, Any]]:
        path = self.hypothesis_path(ticker, opp_id)
        if not path.exists():
            return []
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data.get("hypotheses", []) or []
        except Exception:
            return []

    def list_all_hypotheses(self, status: str | None = None,
                            opp_id: str | None = None) -> list[dict[str, Any]]:
        results = []
        companies_dir = self.base / "companies"
        if not companies_dir.exists():
            return results
        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name
            opp_dir = d / "case_file" / "opportunities"
            if not opp_dir.exists():
                continue
            for opp in sorted(opp_dir.iterdir()):
                if not opp.is_dir():
                    continue
                if opp_id and opp.name != opp_id:
                    continue
                hyp_file = opp / "hypotheses.yml"
                if not hyp_file.exists():
                    continue
                try:
                    data = yaml.safe_load(hyp_file.read_text(encoding="utf-8")) or {}
                    for h in data.get("hypotheses", []) or []:
                        h["ticker"] = ticker
                        h["opportunity_id"] = opp.name
                        if status is None or h.get("status") == status:
                            results.append(h)
                except Exception:
                    pass
        return results

    def save_decision(self, ticker: str, opp_id: str, decision: dict[str, Any]):
        path = self.opportunity_path(ticker, opp_id) / "decisions"
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / f"{decision['id']}.yml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(decision, f, default_flow_style=False, allow_unicode=True)

    def save_position(self, ticker: str, position: dict[str, Any]):
        path = self.base / "portfolio" / "positions"
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / f"{ticker}.yml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(position, f, default_flow_style=False, allow_unicode=True)

    def load_position(self, ticker: str) -> dict[str, Any] | None:
        filepath = self.base / "portfolio" / "positions" / f"{ticker}.yml"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def log_event(self, event_type: str, data: dict[str, Any], source: str = "system"):
        logs_dir = self.base / "events"
        logs_dir.mkdir(parents=True, exist_ok=True)
        from datetime import date, datetime
        today = date.today().isoformat()
        filepath = logs_dir / f"{today}.yml"
        if filepath.exists():
            existing = yaml.safe_load(filepath.read_text(encoding="utf-8")) or {"events": []}
        else:
            existing = {"events": []}
        existing["events"].append({
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "source": source,
            "data": data,
        })
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        logs_dir = self.base / "events"
        if not logs_dir.exists():
            return []
        events = []
        for f in sorted(logs_dir.iterdir(), reverse=True):
            if f.suffix != ".yml":
                continue
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                if data and "events" in data:
                    for e in data["events"]:
                        e["_file"] = f.name
                        events.append(e)
            except Exception:
                pass
        return events[:limit]

    def save_watchlist(self, entries: list[dict[str, Any]]):
        filepath = self.base / "portfolio" / "watchlist.yml"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump({"entries": entries}, f, default_flow_style=False, allow_unicode=True)

    def load_watchlist(self) -> list[dict[str, Any]]:
        filepath = self.base / "portfolio" / "watchlist.yml"
        if not filepath.exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("entries", []) if data else []
