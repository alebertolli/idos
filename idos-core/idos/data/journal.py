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
