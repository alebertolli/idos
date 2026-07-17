from pathlib import Path
from typing import Any
from idos.data.journal import JournalRepository


class PortfolioEngine:
    def __init__(self, journal_repo: JournalRepository):
        self.journal = journal_repo

    def get_positions(self) -> list[dict[str, Any]]:
        positions_path = self.journal.base / "portfolio" / "positions"
        if not positions_path.exists():
            return []
        positions = []
        for f in sorted(positions_path.glob("*.yml")):
            pos = self.journal.load_position(f.stem)
            if pos:
                positions.append(pos)
        return positions

    def get_watchlist(self) -> list[dict[str, Any]]:
        return self.journal.load_watchlist()

    def total_weight(self) -> float:
        return sum(p.get("weight_pct", 0.0) for p in self.get_positions())

    def sector_exposure(self) -> dict[str, float]:
        exposures: dict[str, float] = {}
        for pos in self.get_positions():
            sector = pos.get("sector", "Unknown")
            exposures[sector] = exposures.get(sector, 0.0) + pos.get("weight_pct", 0.0)
        return exposures
