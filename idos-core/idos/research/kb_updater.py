from datetime import datetime, UTC
from typing import Any


class KnowledgeBaseUpdater:
    def update_metrics(self, kb: dict[str, Any], new_metrics: dict[str, Any]) -> dict[str, Any]:
        kb = kb or {}
        dynamic = kb.setdefault("dynamic", {})
        old_metrics = dynamic.setdefault("metrics", {})
        old_metrics.update(new_metrics)
        dynamic["last_updated"] = datetime.now(UTC).isoformat()
        return kb

    def update_financials(self, kb: dict[str, Any], period: str, financials: dict[str, Any]) -> dict[str, Any]:
        kb = kb or {}
        dynamic = kb.setdefault("dynamic", {})
        fin = dynamic.setdefault("financials", {})
        fin[period] = financials
        dynamic["last_updated"] = datetime.now(UTC).isoformat()
        return kb

    def add_earnings_transcript(self, kb: dict[str, Any], period: str, transcript: str) -> dict[str, Any]:
        kb = kb or {}
        dynamic = kb.setdefault("dynamic", {})
        earnings = dynamic.setdefault("earnings", [])
        earnings.append({"period": period, "transcript": transcript, "added_at": datetime.now(UTC).isoformat()})
        dynamic["last_updated"] = datetime.now(UTC).isoformat()
        return kb

    def add_event(self, kb: dict[str, Any], event_type: str, description: str) -> dict[str, Any]:
        gen = kb.setdefault("generated", {})
        events = gen.setdefault("events", [])
        events.append({"type": event_type, "description": description,
                       "timestamp": datetime.now(UTC).isoformat()})
        return kb
