"""Builds a static HTML site from IDOS journal/knowledge artifacts.

Read-only against the repo (YAML/MD) plus the daily price cache in SQLite.
Output: `site/index.html`, `site/data.json`, `site/wiki/*.html`,
`site/assets/app.js`, `site/assets/style.css`.

The site is a single-page app with tabs:
  Dashboard · Discovery · Research · Decision · Buy List

No server required: publish `site/` to GitHub Pages.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml

from idos.decision.scenarios import (
    scenario_fingerprint,
    scenario_source_urls_from_report,
    validate_scenario_analysis,
)
from idos.decision.proposal_review import decision_proposal_fingerprint
from idos.research.thesis_schedule import schedule_for_opportunity
from idos.strategy.catalog import StrategyCatalog
from idos.timezone import AR_TZ


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_STALE_DAYS = 30

STATUS_ACTIVE = {
    "DISCOVERED", "SCREENED", "WATCHLIST", "UNDER_RESEARCH", "UNDER_DEEP_DD",
    "APPROVED", "ENTRY_PENDING",
}

WYCKOFF_PHASE_COLOR = {
    "accumulation": "#16a34a",
    "absorption": "#ca8a04",
    "markdown": "#ea580c",
    "distribution": "#dc2626",
}


# ---------------------------------------------------------------------------
# Small markdown renderer (no external deps)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\|(.*)\|\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_OLIST_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)
    return text


def _render_table(rows: list[list[str]]) -> str:
    header = rows[0]
    body = rows[1:]
    if body and all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in body[0]):
        body = body[1:]
    thead = "".join(f"<th>{_inline(c.strip())}</th>" for c in header)
    trows = []
    for r in body:
        tds = "".join(f"<td>{_inline(c.strip())}</td>" for c in r)
        trows.append(f"<tr>{tds}</tr>")
    return (
        f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(trows)}</tbody></table>"
    )


def markdown_to_html(text: str) -> str:
    out: list[str] = []
    in_list: str | None = None
    i = 0
    lines = text.splitlines()
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = _HEADING_RE.match(stripped)
        if m:
            out.append(_close_list(in_list))
            in_list = None
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if _TABLE_ROW_RE.match(stripped) and i + 1 < len(lines) and _TABLE_ROW_RE.match(lines[i + 1].strip()):
            out.append(_close_list(in_list))
            in_list = None
            rows: list[list[str]] = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                cells = [c for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            out.append(_render_table(rows))
            continue
        if stripped.startswith("```"):
            out.append(_close_list(in_list))
            in_list = None
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{''.join(code)}</code></pre>")
            continue
        mb = _BULLET_RE.match(line)
        mo = _OLIST_RE.match(line)
        if mb or mo:
            tag = "ul" if mb else "ol"
            if in_list != tag:
                out.append(_close_list(in_list))
                out.append(f"<{tag}>")
                in_list = tag
            content = mb.group(1) if mb else mo.group(1)
            out.append(f"<li>{_inline(content)}</li>")
            i += 1
            continue
        if not stripped:
            out.append(_close_list(in_list))
            in_list = None
            out.append("")
        else:
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    out.append(_close_list(in_list))
    return "\n".join(x for x in out if x)


def _close_list(in_list: str | None) -> str:
    return f"</{in_list}>" if in_list else ""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _load_all_yaml(path: Path, pattern: str = "*.yml") -> list[dict]:
    if not path.exists():
        return []
    out = []
    for f in sorted(path.glob(pattern)):
        data = _load_yaml(f)
        if isinstance(data, dict):
            out.append(data)
    return out


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except Exception:
            return None


def _public_research_ratios(value: Any) -> list[dict[str, Any]]:
    """Return a bounded, display-safe summary of Research ratio evidence."""
    if not isinstance(value, list):
        return []

    ratios: list[dict[str, Any]] = []
    for item in value[:40]:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()[:100]
        if not metric:
            continue

        raw_status = str(item.get("status") or "unavailable").strip().lower()
        raw_value = item.get("value")
        valid_value = False
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            try:
                valid_value = math.isfinite(float(raw_value))
            except (OverflowError, ValueError):
                valid_value = False
        status = raw_status if raw_status in {"reported", "unavailable"} else "needs_review"
        if status == "reported" and not valid_value:
            status = "needs_review"

        sources: list[dict[str, str | None]] = []
        raw_sources = item.get("sources")
        if isinstance(raw_sources, list):
            for source in raw_sources[:5]:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url") or "").strip()
                parsed_url = urlsplit(url)
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                    continue
                sources.append({
                    "name": str(source.get("name") or "Fuente")[:100],
                    "url": url[:1000],
                    "as_of_date": str(source.get("as_of_date") or "")[:30] or None,
                })

        ratios.append({
            "metric": metric,
            "status": status,
            "value": raw_value if valid_value and status == "reported" else None,
            "unit": str(item.get("unit") or "")[:40],
            "period_end": str(item.get("period_end") or item.get("as_of_date") or "")[:30] or None,
            "formula": str(item.get("formula") or "")[:300] or None,
            "limitations": str(item.get("limitations") or "")[:1000] or None,
            "sources": sources,
        })
    return ratios


def _is_valid_ticker(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9.\-]{1,10}", name or ""))


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class SiteData:
    generated_at: str = field(default_factory=lambda: datetime.now(AR_TZ).isoformat())
    config: dict = field(default_factory=dict)
    opportunities: list[dict] = field(default_factory=list)
    buylist: list[dict] = field(default_factory=list)
    watchlist: list[dict] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)
    portfolio: dict = field(default_factory=dict)
    wiki: list[dict] = field(default_factory=list)
    learning: list[dict] = field(default_factory=list)
    dashboard: dict = field(default_factory=dict)
    companies: dict = field(default_factory=dict)
    entry_rules: list[dict] = field(default_factory=list)
    universe_stats: dict = field(default_factory=dict)
    discovery_pool: list[dict] = field(default_factory=list)
    scout_policy: dict = field(default_factory=dict)


class SiteBuilder:
    def __init__(self, base_path: Path, stale_days: int = DEFAULT_STALE_DAYS):
        self.base = base_path
        self.journal = base_path / "idos-journal"
        self.knowledge = base_path / "idos-knowledge"
        self.config = base_path / "idos-config"
        self.strategy_catalog = StrategyCatalog(self.config / "strategies.yml")
        self.db_path = base_path / "idos.db"
        self.cache = base_path / "cache"
        self.stale_days = stale_days
        self._configured_scout = None
        self.prices: dict[str, dict[str, Any]] = self._load_prices()
        self.disc_min_score = self._load_disc_min_score()
        self.entry_rules = self._load_entry_rules()
        self.entry_cfg = self._load_entry_cfg()

    def _load_disc_min_score(self) -> int:
        cfg = _load_yaml(self.config / "scoring.yml")
        if isinstance(cfg, dict):
            v = cfg.get("scoring", {}).get("min_opportunity_score")
            if isinstance(v, int):
                return v
        return 70

    def _load_entry_rules(self) -> list[dict]:
        """Authorization entry rules that gate UNDER_DEEP_DD -> APPROVED."""
        cfg = _load_yaml(self.config / "rules" / "entry_rules.yml")
        rules = []
        if isinstance(cfg, dict):
            for r in cfg.get("rules") or []:
                if isinstance(r, dict) and r.get("stage") in ("authorization", None):
                    rules.append({
                        "id": r.get("id"),
                        "description": r.get("description"),
                        "condition": r.get("condition"),
                        "priority": r.get("priority"),
                        "action": r.get("action"),
                        "active": r.get("active", True),
                    })
        return rules

    def _load_entry_cfg(self) -> dict[str, Any]:
        """Entry-engine thresholds from idos-config/portfolio.yml (EntryEngine + Wyckoff)."""
        cfg = _load_yaml(self.config / "portfolio.yml")
        ind = (cfg.get("indicator") or {}) if isinstance(cfg, dict) else {}
        weights = (ind.get("weights") or {}) if isinstance(ind, dict) else {}
        bands = (ind.get("bands") or {}) if isinstance(ind, dict) else {}
        entry = (cfg.get("entry") or {}) if isinstance(cfg, dict) else {}
        return {
            "margin_of_safety_pct": (cfg.get("margin_of_safety") or 30) if isinstance(cfg, dict) else 30,
            "max_position_pct": (cfg.get("max_position_pct") or 3.0) if isinstance(cfg, dict) else 3.0,
            "max_total_weight_pct": 20.0,
            "min_wyckoff_score": (entry.get("min_score") or 45) if isinstance(entry, dict) else 45,
            "demand_band": (bands.get("demand") or 65) if isinstance(bands, dict) else 65,
            "absorption_band": (bands.get("absorption") or 45) if isinstance(bands, dict) else 45,
            "supply_band": (bands.get("supply") or 25) if isinstance(bands, dict) else 25,
            "weight_structure": (weights.get("structure") or 0.40) if isinstance(weights, dict) else 0.40,
            "weight_supply_demand": (weights.get("supply_demand") or 0.30) if isinstance(weights, dict) else 0.30,
            "weight_relative_strength": (weights.get("relative_strength") or 0.20) if isinstance(weights, dict) else 0.20,
            "weight_volatility": (weights.get("volatility") or 0.10) if isinstance(weights, dict) else 0.10,
            "entry_phases": ["ACCUMULATION", "ABSORPTION"],
        }

    # -- prices from daily cache (SQLite) --
    def _load_prices(self) -> dict[str, dict[str, Any]]:
        if not self.db_path.exists():
            return {}
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ticker, date, close FROM price_history "
                "WHERE close IS NOT NULL AND close > 0 "
                "ORDER BY date DESC"
            ).fetchall()
            conn.close()
        except Exception:
            return {}
        prices: dict[str, dict[str, Any]] = {}
        for r in rows:
            t = r["ticker"].upper()
            if t not in prices:
                prices[t] = {"date": r["date"], "price": r["close"]}
        return prices

    def _load_data_provenance(self, ticker: str, price_date: str | None = None) -> dict:
        """Expose only source metadata from the public market-data cache."""
        cache_path = self.cache / f"{ticker.upper()}.json"
        raw: dict[str, Any] = {}
        if cache_path.exists():
            try:
                parsed = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    raw = parsed
            except (OSError, ValueError):
                pass

        provenance = raw.get("data_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        raw_sources = provenance.get("sources_used")
        sources = sorted(
            {str(source) for source in raw_sources if source}
            if isinstance(raw_sources, list)
            else set()
        )
        field_sources: dict[str, list[str]] = {}
        raw_field_sources = provenance.get("field_sources")
        if isinstance(raw_field_sources, dict):
            for field_name, field_values in raw_field_sources.items():
                if isinstance(field_values, list):
                    field_sources[str(field_name)] = sorted({str(source) for source in field_values if source})

        raw_count = provenance.get("source_count")
        source_count = raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) else len(sources)
        conflicts = provenance.get("conflicts")
        conflict_count = len(conflicts) if isinstance(conflicts, (list, dict)) else 0

        refreshed_at = None
        refresh_path = self.cache / "last_refresh.json"
        if refresh_path.exists():
            try:
                refresh = json.loads(refresh_path.read_text(encoding="utf-8"))
                raw_tickers = refresh.get("tickers") if isinstance(refresh, dict) else None
                refreshed_tickers = {
                    str(item).upper() for item in raw_tickers if item
                } if isinstance(raw_tickers, list) else set()
                if ticker.upper() in refreshed_tickers:
                    refreshed_at = refresh.get("refreshed_at")
            except (OSError, ValueError, AttributeError):
                pass

        return {
            "price_as_of": price_date,
            "refreshed_at": refreshed_at,
            "source_count": source_count if provenance else None,
            "sources_used": sources,
            "field_sources": field_sources,
            "conflict_count": conflict_count,
        }

    def _load_universe_stats(self) -> dict:
        results_path = self.base / "cache" / "pipeline_results.json"
        if results_path.exists():
            try:
                import json as _json
                data = _json.loads(results_path.read_text(encoding="utf-8"))
                output = data.get("output", {})
                return {
                    "candidate_count": output.get("candidate_count", output.get("finviz_count", 0)),
                    "candidate_source": output.get("candidate_source", ""),
                    "operable_count": output.get("operable_count", 0),
                    "pre_score_count": output.get("pre_score_count", 0),
                    "scout_passed": output.get("scout_passed", 0),
                    "scout_rejected": output.get("scout_rejected", 0),
                    "opportunities_created": output.get("opportunities_created", 0),
                    "pipeline_date": output.get("finished_at"),
                }
            except Exception:
                pass
        return {
            "candidate_count": 0,
            "candidate_source": "",
            "operable_count": 0,
            "pre_score_count": 0,
            "scout_passed": 0,
            "scout_rejected": 0,
            "opportunities_created": 0,
            "pipeline_date": None,
        }

    def price_for(self, ticker: str) -> dict[str, Any]:
        p = self.prices.get(ticker.upper())
        if not p:
            return {"price": None, "date": None}
        return {"price": p["price"], "date": p["date"]}

    def _market_price(self, ticker: str) -> dict[str, Any]:
        """Latest market close from cache/{TICKER}.json — same source as the entry engine."""
        import json as _json
        p = self.cache / f"{ticker}.json"
        if not p.exists():
            return {"price": None, "date": None}
        try:
            raw = _json.loads(p.read_text(encoding="utf-8"))
            prices, volumes, dates = [], [], []
            if isinstance(raw, dict):
                if raw.get("price_history"):
                    prices, volumes, dates = raw["price_history"], raw.get("volume_history", []), raw.get("price_history_dates", [])
                elif "yfinance" in raw:
                    prices = raw["yfinance"].get("price_history", [])
                    volumes = raw["yfinance"].get("volume_history", [])
                    dates = raw["yfinance"].get("price_history_dates", [])
                elif raw.get("merged_data"):
                    prices = raw["merged_data"].get("price_history", [])
                    volumes = raw["merged_data"].get("volume_history", [])
                    dates = raw["merged_data"].get("price_history_dates", [])
            if prices and prices[-1] is not None:
                try:
                    v = float(prices[-1])
                except (TypeError, ValueError):
                    v = None
                if v is not None and (v != v or v in (float("inf"), float("-inf"))):
                    return {"price": None, "date": None}
                if v is not None:
                    return {"price": round(v, 2), "date": dates[-1] if dates else None}
        except Exception:
            pass
        return {"price": None, "date": None}

    # -- opportunities --
    def _load_opportunity(self, ticker: str, opp_dir: Path) -> dict | None:
        opp = _load_yaml(opp_dir / "opportunity.yml")
        if not isinstance(opp, dict):
            return None
        dp = _load_yaml(opp_dir / "decision_proposal.yml")
        dp = dp if isinstance(dp, dict) else {}
        br = _load_yaml(opp_dir / "board_resolution.yml")
        br = br if isinstance(br, dict) else {}
        decision_author = str(br.get("author") or "").strip()
        decision_resolved_at = br.get("resolved_at")
        decision_attributable = (
            bool(decision_author)
            and decision_author.lower() not in {"system", "board"}
            and _parse_dt(decision_resolved_at) is not None
        )
        ddd = _load_yaml(opp_dir / "ddd_report.yml")
        ddd = ddd if isinstance(ddd, dict) else {}
        hypotheses_doc = _load_yaml(opp_dir / "hypotheses.yml")
        hypotheses_doc = hypotheses_doc if isinstance(hypotheses_doc, dict) else {}
        raw_hypotheses = hypotheses_doc.get("hypotheses") or []

        scores: dict[str, Any] = {}
        findings: dict[str, list[str]] = {}
        assessment_recommendations: dict[str, str] = {}
        for engine, spec in (dp.get("assessments") or {}).items():
            if isinstance(spec, dict):
                scores[engine] = spec.get("score")
                recommendation = spec.get("recommendation")
                if recommendation:
                    assessment_recommendations[engine] = str(recommendation)
                findings[engine] = [
                    f.get("detail") or f"{f.get('dimension','')} {f.get('level','')}".strip()
                    for f in (spec.get("findings") or []) if isinstance(f, dict)
                ]

        conv = opp.get("conviction") or {}
        scores_conv = conv.get("scores") or {}
        # Real scores live in decision_proposal; opportunity.yml often has zeros.
        final_scores = {k: (v if v else scores.get(k)) for k, v in scores_conv.items()}
        final_scores.update({k: v for k, v in scores.items() if k not in final_scores})
        final_scores = {k: v for k, v in final_scores.items() if v is not None and v != 0}

        current_price = opp.get("current_price")
        intrinsic = opp.get("intrinsic_value")
        mkt = self._market_price(ticker)
        market_price = mkt["price"]
        price_date = mkt["date"]
        market_data = self._load_data_provenance(ticker, price_date)
        if market_price:
            current_price = market_price
        upside = None
        if current_price and intrinsic and current_price > 0:
            upside = round((intrinsic - current_price) / current_price * 100, 1)

        # last research date: prefer last_research_at (set by ResearchWorker),
        # then decision_proposal.generated_at, then updated_at
        last_research = (
            opp.get("last_research_at")
            or dp.get("generated_at")
            or opp.get("updated_at")
            or opp.get("created_at")
        )
        last_research_dt = _parse_dt(last_research)
        current_status = opp.get("status", "")
        stale_days = None
        is_stale = False
        if last_research_dt and current_status in {"UNDER_RESEARCH", "SCREENED"}:
            days = max(0, (datetime.now(AR_TZ).replace(tzinfo=None) - last_research_dt.replace(tzinfo=None)).days)
            stale_days = days
            is_stale = days > self.stale_days

        thesis_not_assessed_days = None
        is_thesis_stale = False
        thesis_review_status = "not_scheduled"
        next_thesis_review_at = None
        thesis_review_interval_days = None
        try:
            if str(opp.get("research_profile", "")).lower() == "systematic":
                thesis_review_status = "not_applicable"
            else:
                profile = self.strategy_catalog.get(opp.get("strategy_id") or "COMPOUNDER")
                schedule = schedule_for_opportunity(opp, profile)
                thesis_review_interval_days = schedule.interval_days
                next_thesis_review_at = (
                    schedule.next_review_at.isoformat()
                    if schedule.next_review_at
                    else opp.get("next_thesis_review_at") or None
                )
                if schedule.interval_days is None:
                    thesis_review_status = "not_applicable"
                elif schedule.next_review_at is None:
                    thesis_review_status = "due"
                else:
                    thesis_review_status = "due" if schedule.due else "scheduled"
        except ValueError:
            thesis_review_status = "configuration_error"
        if current_status in {"ACCUMULATING", "FULL_POSITION", "MONITORING", "REDUCING"}:
            lta = opp.get("last_thesis_assessment_at") or opp.get("updated_at")
            lta_dt = _parse_dt(lta)
            if lta_dt:
                days = max(0, (datetime.now(AR_TZ).replace(tzinfo=None) - lta_dt.replace(tzinfo=None)).days)
                thesis_not_assessed_days = days
                is_thesis_stale = thesis_review_status == "due"

        # Agent research is published as a provisional decision package. The
        # first human interaction is the single Decision Board review.
        evidence_review = ddd.get("evidence_review") or {}
        if not isinstance(evidence_review, dict):
            evidence_review = {}
        review_status = str(evidence_review.get("status") or "pending_decision_board").strip().lower()
        reviewer = str(evidence_review.get("reviewed_by") or "").strip()
        reviewed_at = evidence_review.get("reviewed_at")
        review_approved = (
            review_status == "manager_approved"
            and bool(reviewer)
            and _parse_dt(reviewed_at) is not None
        )
        scenario_analysis = ddd.get("scenario_analysis")
        trusted_scenario_sources = scenario_source_urls_from_report(ddd)
        scenario_validation_errors = (
            validate_scenario_analysis(
                scenario_analysis, trusted_source_urls=trusted_scenario_sources,
            )
            if scenario_analysis is not None else []
        )
        scenario_valid = scenario_analysis is not None and not scenario_validation_errors
        strategy_context = ddd.get("strategy_context") or {}
        opportunity_signal = opp.get("signal")
        systematic_report = (
            opp.get("research_profile") == "systematic"
            and opp.get("entry_policy") == "SIGNAL_REBALANCE"
            and bool(opp.get("strategy_id"))
            and strategy_context.get("strategy_id") == opp.get("strategy_id")
            and isinstance(strategy_context.get("signal"), dict)
            and isinstance(opportunity_signal, dict)
            and strategy_context.get("signal") == opportunity_signal
        )
        current_systematic_report = systematic_report and strategy_context.get("report_method_version") == "systematic_signal_v2"
        # Fundamental research is visible for Board review as a provisional
        # agent proposal; it does not itself approve a Buy List entry.
        # Legacy systematic reports remain hidden until regenerated.
        ddd_publishable = bool(ddd) and (not systematic_report or current_systematic_report)
        if systematic_report:
            # Corporate intrinsic value does not apply to a signal/rebalance case.
            intrinsic = None
            upside = None

        # Publish the agent-generated case with an explicit pending Board state;
        # only legacy systematic reports require refresh before display.
        ddd_summary = {
            "evidence_review": {
                "status": (
                    "manager_approved" if review_approved
                    else "systematic_report" if current_systematic_report
                    else "systematic_report_refresh_required" if systematic_report
                    else "board_approved" if decision_attributable and br.get("status") == "approved"
                    else "pending_decision_board"
                ),
                "reviewed_at": reviewed_at if review_approved else decision_resolved_at if decision_attributable else None,
            },
            "categoria": None,
            "clasificacion": {},
            "ratings": {},
            "riesgos": [],
            "resumen_ejecutivo": None,
            "tesis_inversion": None,
            "opinion_valoracion": None,
            "score_general": None,
            "error_mercado": {},
            "dominios": [],
            "catalizadores": [],
            "evidencia": {},
            "hipotesis": [],
            "financial_data_quality": dp.get("financial_data_quality") or {},
            "ratios_investigados": [],
            "scenario_analysis": None,
            "board_review": {
                "status": (
                    "not_applicable" if systematic_report
                    else "pending_decision_board"
                ),
                "reason": (
                    "La estrategia sistemática se evalúa mediante su señal y reglas de rebalanceo."
                    if systematic_report else "Research y Assessment completaron sus validaciones automáticas; la revisión humana ocurre una sola vez en Decision Board."
                ),
                "scenario_hash": scenario_fingerprint(scenario_analysis) if scenario_valid else None,
            },
            "scenario_validation": (
                {"status": "not_applicable", "errors": []}
                if systematic_report
                else {
                    "status": "valid_pending_decision_board" if scenario_valid else "invalid_pending_revision",
                    "errors": scenario_validation_errors,
                }
                if scenario_analysis is not None
                else ddd.get("scenario_validation") or {}
            ),
        }
        if ddd and ddd_publishable:
            if scenario_valid:
                ddd_summary["scenario_analysis"] = scenario_analysis
            cls = ddd.get("clasificacion_oportunidad") or {}
            ddd_summary["categoria"] = cls.get("categoria")
            cls_desc = cls.get("categorias_descartadas") or []
            if isinstance(cls_desc, str):
                cls_desc = [x.strip() for x in cls_desc.split(",") if x.strip()]
            ddd_summary["clasificacion"] = {
                "categoria": cls.get("categoria"),
                "categorias_descartadas": cls_desc,
                "justificacion": cls.get("justificacion"),
            }
            for dom, val in ddd.items():
                if isinstance(val, dict) and "rating" in val and dom.startswith("dominio_"):
                    ddd_summary["ratings"][dom.replace("dominio_", "")] = val["rating"]
            ddd_summary["dominios"] = [
                {
                    "dominio": dom.replace("dominio_", ""),
                    "rating": val.get("rating"),
                    "analisis": val.get("analisis"),
                }
                for dom, val in ddd.items()
                if isinstance(val, dict) and "rating" in val and dom.startswith("dominio_") and dom != "dominio_riesgos"
            ]
            ddd_summary["riesgos"] = [
                {
                    "riesgo": r.get("riesgo") or r.get("nombre") or r.get("descripcion"),
                    "descripcion": r.get("descripcion"),
                    "probabilidad": r.get("probabilidad"),
                    "impacto": r.get("impacto"),
                }
                for r in (ddd.get("dominio_riesgos") or []) if isinstance(r, dict)
            ]
            ddd_summary["resumen_ejecutivo"] = ddd.get("resumen_ejecutivo")
            ddd_summary["tesis_inversion"] = ddd.get("tesis_inversion")
            ddd_summary["ratios_investigados"] = _public_research_ratios(
                ddd.get("ratios_investigados")
            )
            ddd_summary["opinion_valoracion"] = ddd.get("opinion_valoracion")
            ddd_summary["score_general"] = ddd.get("score_general")
            err = ddd.get("error_mercado") or {}
            if isinstance(err, dict):
                cc = err.get("catalizador_cambio") or {}
                if isinstance(cc, str):
                    cc = {"descripcion": cc}
                elif not isinstance(cc, dict):
                    cc = {}
                ddd_summary["error_mercado"] = {
                    "conclusion_error_valoracion": err.get("conclusion_error_valoracion"),
                    "hipotesis_contraria": err.get("hipotesis_contraria"),
                    "consenso_actual": err.get("consenso_actual"),
                    "razonamiento": err.get("razonamiento"),
                    "catalizador_cambio": {
                        "descripcion": cc.get("descripcion"),
                        "horizonte": cc.get("horizonte"),
                        "impacto": cc.get("impacto"),
                        "probabilidad_pct": cc.get("probabilidad_pct"),
                    } if cc else {},
                }
            ddd_summary["catalizadores"] = [
                {
                    "descripcion": c.get("descripcion"),
                    "horizonte": c.get("horizonte"),
                    "impacto": c.get("impacto"),
                    "probabilidad_pct": c.get("probabilidad_pct"),
                }
                for c in (ddd.get("dominio_catalizadores") or []) if isinstance(c, dict)
            ]
            ev = ddd.get("calidad_evidencia") or {}
            if isinstance(ev, dict):
                ddd_summary["evidencia"] = {
                    "hechos_verificados": ev.get("hechos_verificados") or [],
                    "inferencias_llm": ev.get("inferencias_llm") or [],
                    "preguntas_abiertas": ev.get("preguntas_abiertas") or [],
                }
            ddd_summary["hipotesis"] = [
                {
                    "id": h.get("id"),
                    "statement": h.get("statement"),
                    "rationale": h.get("rationale"),
                    "horizon": h.get("horizon"),
                    "review_trigger": h.get("review_trigger"),
                    "predictions": h.get("predictions") or [],
                    "falsification_conditions": h.get("falsification_conditions") or [],
                }
                for h in raw_hypotheses if isinstance(h, dict)
            ]

        latest_discovery = opp.get("latest_discovery_evidence") or opp.get("discovery_evidence") or {}
        if not isinstance(latest_discovery, dict):
            latest_discovery = {}

        return {
            "opp_id": opp.get("id") or opp_dir.name,
            "ticker": ticker,
            "status": opp.get("status", "UNKNOWN"),
            "strategy_id": opp.get("strategy_id", "COMPOUNDER"),
            "strategy_version": opp.get("strategy_version", "legacy-compatible"),
            "discovery_score": (
                opp.get("discovery_score")
                if opp.get("discovery_score") is not None
                else latest_discovery.get("discovery_score")
            ),
            "research_priority": (
                opp.get("research_priority")
                if opp.get("research_priority") is not None
                else latest_discovery.get("research_priority")
            ),
            "discovery_type": (
                opp.get("discovery_type")
                if opp.get("discovery_type") is not None
                else latest_discovery.get("discovery_type")
            ),
            "position_limit_pct": opp.get("position_limit_pct"),
            "core": opp.get("core"),
            "sleeve": opp.get("sleeve"),
            "thesis_type": opp.get("thesis_type"),
            "entry_policy": opp.get("entry_policy"),
            "research_profile": opp.get("research_profile"),
            "origin": opp.get("origin", "legacy"),
            "signal": opp.get("signal", {}),
            "conviction_overall": None if systematic_report else conv.get("overall"),
            "confidence": conv.get("confidence"),
            "trend": conv.get("trend"),
            "scores": final_scores,
            "findings": findings,
            "assessment_recommendations": assessment_recommendations,
            "current_price": current_price,
            "intrinsic_value": intrinsic,
            "valuation_status": "NOT_APPLICABLE" if systematic_report else "AVAILABLE" if intrinsic else "NOT_ASSESSED",
            "upside_pct": upside,
            "price_date": price_date,
            "market_data": market_data,
            "latest_discovery_evidence": opp.get("latest_discovery_evidence") or {},
            "created_at": opp.get("created_at"),
            "updated_at": opp.get("updated_at"),
            "last_research": last_research,
            "stale_days": stale_days,
            "is_stale": is_stale,
            "thesis_not_assessed_days": thesis_not_assessed_days,
            "is_thesis_stale": is_thesis_stale,
            "thesis_active": opp.get("thesis_active", True),
            "thesis_invalidated_reason": opp.get("thesis_invalidated_reason"),
            "last_thesis_assessment_at": opp.get("last_thesis_assessment_at"),
            "thesis_review_interval_days": thesis_review_interval_days,
            "next_thesis_review_at": next_thesis_review_at,
            "thesis_review_status": thesis_review_status,
            "decision": {
                "approved": bool(br.get("approved")) if decision_attributable else False,
                "decision_type": br.get("decision_type") if decision_attributable else None,
                "decision_id": br.get("decision_id") if decision_attributable else None,
                "justification": br.get("justification") if decision_attributable else None,
                "author": decision_author if decision_attributable else None,
                "resolved_at": decision_resolved_at if decision_attributable else None,
            },
            "proposal": {
                "recommendation": dp.get("recommendation"),
                "status": dp.get("status"),
                "proposal_hash": decision_proposal_fingerprint(dp) if dp else None,
                "manager_review": dp.get("manager_review") or {},
                "decision": dp.get("decision"),
                "checks": dp.get("checks") or {},
                "conviction_score": dp.get("conviction_score"),
                "rules_passed": dp.get("rules_passed") or [],
                "rules_failed": dp.get("rules_failed") or [],
                "rules_details": dp.get("rules_details") or {},
                "reasoning": dp.get("reasoning"),
            },
            "ddd": ddd_summary,
            "has_wyckoff": bool((opp_dir / "wyckoff").exists()),
            "has_post_mortem": bool((opp_dir / "post_mortem").exists()),
        }

    def _load_opportunities(self) -> list[dict]:
        companies_dir = self.journal / "companies"
        if not companies_dir.exists():
            return []
        opps = []
        for ticker_dir in sorted(companies_dir.iterdir()):
            if not ticker_dir.is_dir() or not _is_valid_ticker(ticker_dir.name):
                continue
            opps_dir = ticker_dir / "case_file" / "opportunities"
            if not opps_dir.exists():
                continue
            for opp_dir in sorted(opps_dir.iterdir()):
                if opp_dir.is_dir():
                    o = self._load_opportunity(ticker_dir.name, opp_dir)
                    if o and o["status"] in STATUS_ACTIVE:
                        opps.append(o)
        opps.sort(key=lambda o: (o.get("updated_at") or ""), reverse=True)
        return opps

    # -- buylist / watchlist --
    def _load_buylist(self) -> list[dict]:
        data = _load_yaml(self.journal / "portfolio" / "buylist.yml")
        if not isinstance(data, dict):
            return []
        entries = data.get("entries") or []
        out = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            price = self.price_for(e.get("ticker", ""))
            mkt = self._market_price(e.get("ticker", ""))
            wyckoff = self._load_wyckoff_latest(e.get("ticker", ""), e.get("opp_id", ""))
            opp = self._find_opp(e.get("ticker", ""), e.get("opp_id", ""))
            recommendation_state = self._buylist_recommendation_state(opp)
            discovery_evidence = (opp or {}).get("latest_discovery_evidence") or {}
            if not isinstance(discovery_evidence, dict):
                discovery_evidence = {}
            discovery_status = str(discovery_evidence.get("eligibility_status") or "NOT_EVALUATED").upper()
            intrinsic = e.get("target_price") or (opp or {}).get("intrinsic_value") or 0
            current = mkt["price"] or price["price"] or (opp or {}).get("current_price")
            price_date = mkt["date"] or price["date"]
            buy_zone = e.get("buy_zone_top")
            target = e.get("target_price") or intrinsic
            entry_policy = e.get("entry_policy") or (opp or {}).get("entry_policy")
            strategy_signal = None
            if entry_policy == "SIGNAL_REBALANCE":
                strategy_signal = e.get("strategy_signal") or (opp or {}).get("signal")
            out.append({
                "ticker": e.get("ticker"),
                "strategy_id": (
                    e.get("strategy_id")
                    or (opp or {}).get("strategy_id")
                    or ("COMPOUNDER" if opp else None)
                ),
                "entry_policy": entry_policy,
                "strategy_signal": strategy_signal,
                "conviction_score": e.get("conviction_score"),
                "target_price": target or None,
                "buy_zone_top": buy_zone or None,
                "max_position_pct": e.get("max_position_pct"),
                "horizon": e.get("horizon"),
                "monitoring": e.get("monitoring", True),
                "opp_id": e.get("opp_id"),
                "added_at": e.get("added_at"),
                "kb_last_update": e.get("kb_last_update"),
                "catalysts": e.get("catalysts") or [],
                "current_price": current,
                "price_date": price_date,
                "market_data": self._load_data_provenance(e.get("ticker", ""), price_date),
                "latest_discovery_evidence": discovery_evidence,
                "discovery_status": discovery_status,
                "discovery_review_required": discovery_status in {"PENDING_DATA", "REJECTED"},
                "discovery_reason": discovery_evidence.get("reason"),
                "discovery_missing_metrics": discovery_evidence.get("missing_metrics") or [],
                "discovery_conflicting_metrics": discovery_evidence.get("conflicting_metrics") or [],
                "industry": (self.companies.get((e.get("ticker") or "").upper()) or {}).get("industry"),
                "wyckoff": wyckoff,
                "recommendation_state": recommendation_state,
                "thesis_review_status": (opp or {}).get("thesis_review_status", "not_available"),
                "thesis_active": (opp or {}).get("thesis_active"),
                "thesis_invalidated_reason": (opp or {}).get("thesis_invalidated_reason"),
                "last_thesis_assessment_at": (opp or {}).get("last_thesis_assessment_at"),
                "next_thesis_review_at": (opp or {}).get("next_thesis_review_at"),
            })
        return out

    @staticmethod
    def _buylist_recommendation_state(opportunity: dict | None) -> str:
        """Fail closed when a Buy List row lacks a current, active thesis."""
        if not opportunity:
            return "UNLINKED"
        if opportunity.get("thesis_active") is False:
            return "INVALIDATED"
        review_status = opportunity.get("thesis_review_status")
        if review_status == "due":
            return "REVIEW_DUE"
        if review_status == "configuration_error":
            return "CONFIGURATION_ERROR"
        if review_status == "not_applicable":
            return "NOT_APPLICABLE"
        if review_status == "scheduled":
            return "CURRENT"
        return "REVIEW_UNVERIFIED"

    def _find_opp(self, ticker: str, opp_id: str = "") -> dict | None:
        if opp_id:
            d = self.journal / "companies" / ticker / "case_file" / "opportunities" / opp_id
            o = self._load_opportunity(ticker, d)
            if o:
                return o
        seq = self._load_opportunities()
        for o in seq:
            if (o.get("ticker") or "").upper() == (ticker or "").upper():
                return o
        return None

    def _load_watchlist(self) -> list[dict]:
        data = _load_yaml(self.journal / "portfolio" / "watchlist.yml")
        if not isinstance(data, dict):
            return []
        entries = data.get("entries") or []
        out = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            e = dict(e)
            e["metrics"] = self._scout_metrics(e.get("ticker", ""))
            out.append(e)
        return out

    def _load_discovery_pool(self, universe_stats: dict = None) -> list[dict]:
        """Returns operable tickers from latest pipeline run, with their Scout scores.

        Reads the list of tickers from `candidate_tickers` if pipeline results include
        them, else falls back to walking the cache directory. Each entry is enriched with
        the same Scout breakdown shown in the watchlist table so the UI can show all 267
        with their scores and metrics.
        """
        from idos.discovery.operability import OperabilityFilter
        import json as _json

        tickers: list[str] = []
        results_path = self.base / "cache" / "pipeline_results.json"
        if results_path.exists():
            try:
                data = _json.loads(results_path.read_text(encoding="utf-8"))
                candidates = data.get("output", {}).get("candidate_tickers") or []
                tickers = list(candidates)
            except Exception:
                tickers = []
        if not tickers:
            for p in sorted(self.cache.glob("*.json")):
                t = p.stem
                if t in ("pipeline_results", "rebalance_result", "wyckoff_errors",
                         "data_errors", "weekly_digest", "last_refresh",
                         "ddd_results", "earnings_trigger", "entry_signals",
                         "exit_signals", "monthly_reassessment"):
                    continue
                tickers.append(t)

        operable_path = self.config / "universe" / "operable.yml"
        op_filter = OperabilityFilter(str(operable_path)) if operable_path.exists() else None
        operable_types = ({entry["ticker"].upper(): entry.get("type")
                           for entry in op_filter.list()} if op_filter is not None else {})

        out: list[dict] = []
        from datetime import datetime as _dt
        for ticker in tickers:
            if op_filter is not None and not op_filter.is_operable(ticker):
                continue
            cache_file = self.base / "cache" / f"{ticker}.json"
            if not cache_file.exists():
                continue
            try:
                raw = _json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            # Older caches may predate explicit asset_type. The operable registry
            # is authoritative for the configured instrument classification.
            if ticker.upper() in operable_types:
                raw["asset_type"] = operable_types[ticker.upper()]
            result = self._configured_scout_result(ticker, raw)
            added_at = None
            try:
                ts = cache_file.stat().st_mtime
                added_at = _dt.fromtimestamp(ts, AR_TZ).isoformat(timespec="seconds")
            except Exception:
                pass
            out.append({
                "ticker": ticker,
                "score": result.score,
                "added_at": added_at,
                "status": result.status,
                "reason": result.reason,
                "policy_version": result.policy_version,
                "metrics": result.observed_metrics,
                "filter_results": result.filter_results,
                "financial_observations": raw.get("financial_observations", {}),
                "data_provenance": raw.get("data_provenance", {}),
                "market_data_normalization": raw.get("market_data_normalization", {}),
            })
        out.sort(key=lambda e: e.get("score") or 0, reverse=True)
        if universe_stats and universe_stats.get("operable_count"):
            target = int(universe_stats["operable_count"])
            if len(out) > target:
                out = out[:target]
        return out

    def _configured_scout_result(self, ticker: str, raw: dict):
        from idos.discovery.configured_scout import configured_scout
        from idos.discovery.scout import ScoutResult
        try:
            engine = getattr(self, "_configured_scout", None)
            if engine is None:
                engine = configured_scout(self.config)
                self._configured_scout = engine
            return engine.scan_market_data(ticker, raw)
        except (OSError, ValueError) as exc:
            result = ScoutResult(ticker=ticker, score=0, passed=False,
                                 reason=f"Scout policy unavailable: {exc}")
            result.status = "PENDING_DATA"
            result.missing_metrics = ["versioned Scout policy"]
            return result

    def _scout_metrics(self, ticker: str) -> dict[str, Any]:
        path = self.cache / f"{ticker}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        return self._configured_scout_result(ticker, raw).details

    def _load_wyckoff_latest(self, ticker: str, opp_id: str) -> dict | None:
        w_dir = self.journal / "companies" / ticker / "case_file" / "opportunities" / opp_id / "wyckoff"
        files = sorted(w_dir.glob("*.yml")) if w_dir.exists() else []
        if not files:
            return None
        data = _load_yaml(files[-1])
        if not isinstance(data, dict):
            return None
        return {
            "phase": data.get("phase"),
            "score": data.get("score"),
            "composite_score": (data.get("indicators") or {}).get("composite_score"),
            "confidence": data.get("confidence"),
            "current_price": data.get("current_price"),
            "entry_point": data.get("entry_point"),
            "price_target": data.get("price_target"),
            "adjusted_weight": data.get("adjusted_weight"),
            "triggered_entry": data.get("triggered_entry", False),
            "analyzed_at": data.get("analyzed_at"),
        }

    def _attach_wyckoff(self, opps: list[dict]) -> list[dict]:
        for o in opps:
            if o["has_wyckoff"]:
                o["wyckoff"] = self._load_wyckoff_latest(o["ticker"], o["opp_id"])
        return opps

    def _latest_wyckoff_for_ticker(self, ticker: str) -> dict | None:
        opps_dir = self.journal / "companies" / ticker / "case_file" / "opportunities"
        if not opps_dir.exists():
            return None
        for d in sorted(opps_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            opp_id = d.name
            if (d / "wyckoff").exists():
                return self._load_wyckoff_latest(ticker, opp_id)
        return None

    # -- wiki --
    def _load_companies(self) -> dict:
        comp_dir = self.knowledge / "companies"
        if not comp_dir.exists():
            return {}
        out = {}
        for d in sorted(comp_dir.iterdir()):
            if not d.is_dir() or not _is_valid_ticker(d.name):
                continue
            comp = _load_yaml(d / "company.yml")
            if isinstance(comp, dict):
                comp["ticker"] = d.name
                out[d.name] = comp
        return out

    def _wiki_files(self, ticker: str) -> list[Path]:
        wiki_dir = self.knowledge / "companies" / ticker / "wiki"
        if not wiki_dir.exists():
            return []
        md = sorted(wiki_dir.glob("*.md"))
        return md

    def _load_wiki_index(self) -> list[dict]:
        out = []
        for ticker, comp in self.companies.items():
            files = self._wiki_files(ticker)
            has_wiki = len(files) > 0
            out.append({
                "ticker": ticker,
                "name": comp.get("name"),
                "sector": comp.get("sector"),
                "industry": comp.get("industry"),
                "has_wiki": has_wiki,
            })
        return sorted(out, key=lambda w: w["ticker"])

    # -- dashboard --
    def _build_dashboard(self, opps: list[dict], positions: list[dict],
                         buylist: list[dict], watchlist: list[dict], learning: list[dict],
                         universe_stats: dict = None,
                         discovery_pool: list[dict] = None,
                         portfolio: dict | None = None,
                         strategy_signals: dict | None = None) -> dict:
        funnel: dict[str, int] = {}
        for o in opps:
            funnel[o["status"]] = funnel.get(o["status"], 0) + 1

        group_defs = [
            ("discovery", "Discovery", "screening",
             {"DISCOVERED", "WATCHLIST", "SCREENED"}),
            ("research", "Research", "opp",
             {"UNDER_RESEARCH", "UNDER_DEEP_DD"}),
            ("buylist", "Buy List", "buylist",
             {"APPROVED", "ENTRY_PENDING"}),
        ]
        sections = []
        for key, label, tab, statuses in group_defs:
            count = sum(v for k, v in funnel.items() if k in statuses)
            if key == "discovery":
                count = len(discovery_pool) if discovery_pool else (universe_stats.get("operable_count", 0) if universe_stats else 0)
            if key == "research":
                count = sum(1 for o in opps if o.get("status") in {"UNDER_RESEARCH", "UNDER_DEEP_DD"})
            sections.append({
                "key": key, "label": label, "tab": tab,
                "count": count,
                "statuses": sorted(statuses),
            })

        for s in sections:
            if s["key"] == "buylist":
                s["count"] = len(buylist)

        stale = [o for o in opps if o.get("is_stale")]
        thesis_stale = [o for o in opps if o.get("is_thesis_stale")]
        alerts: list[dict[str, Any]] = []
        seen_alert_ids: set[str] = set()

        def add_alert(alert_type: str, ticker: str, severity: str, message: str,
                      source_id: str | None = None) -> None:
            normalized_ticker = str(ticker or "").upper().strip()
            normalized_source = str(source_id or normalized_ticker).strip()
            alert_id = f"{alert_type}:{normalized_ticker}:{normalized_source}"
            if alert_id in seen_alert_ids:
                return
            seen_alert_ids.add(alert_id)
            alerts.append({
                "id": alert_id,
                "type": alert_type,
                "status": "ACTIVE",
                "severity": severity,
                "ticker": normalized_ticker,
                "message": message,
            })

        for opportunity in stale:
            add_alert(
                "research_stale", opportunity.get("ticker", ""), "warn",
                f"Research stale ({opportunity.get('stale_days')}d sin actualizar)",
                str(opportunity.get("opp_id") or ""),
            )
        for opportunity in thesis_stale:
            add_alert(
                "thesis_not_assessed", opportunity.get("ticker", ""), "warn",
                f"Tesis sin evaluar ({opportunity.get('thesis_not_assessed_days')}d)",
                str(opportunity.get("opp_id") or ""),
            )
        for opportunity in opps:
            if (opportunity.get("thesis_review_status") == "due"
                    and opportunity.get("status") in {"SCREENED", "UNDER_RESEARCH", "UNDER_DEEP_DD", "APPROVED", "ENTRY_PENDING"}):
                add_alert(
                    "thesis_review_due", opportunity.get("ticker", ""), "warn",
                    "Revisión de tesis vencida; actualizar Research antes de usar la recomendación",
                    str(opportunity.get("opp_id") or ""),
                )
            discovery = opportunity.get("latest_discovery_evidence") or {}
            discovery_status = str(discovery.get("eligibility_status") or "").upper()
            if discovery_status in {"PENDING_DATA", "REJECTED"}:
                detail = str(discovery.get("reason") or "Revisar los datos críticos del último Scout.")
                if len(detail) > 240:
                    detail = detail[:237] + "..."
                add_alert(
                    "discovery_data_review", opportunity.get("ticker", ""), "high",
                    f"Último Scout: {discovery_status}. {detail} Revisar antes de usar la oportunidad.",
                    str(opportunity.get("opp_id") or ""),
                )
        seen_single_source: set[str] = set()
        for opportunity in opps:
            market_data = opportunity.get("market_data") or {}
            ticker = str(opportunity.get("ticker") or "").upper()
            if market_data.get("source_count") == 1 and ticker and ticker not in seen_single_source:
                add_alert(
                    "market_data_single_source", ticker, "warn",
                    "Datos de mercado con una sola fuente; revisar procedencia por campo.",
                )
                seen_single_source.add(ticker)
        for p in positions:
            if p.get("dist_to_stop_pct") is not None and p["dist_to_stop_pct"] <= 5:
                add_alert(
                    "stop_loss_proximity", p.get("ticker", ""), "high",
                    f"Precio a {abs(p['dist_to_stop_pct']):.1f}% del stop loss",
                    str(p.get("position_id") or p.get("opp_id") or ""),
                )
        intrinsic_by_opp = {o["opp_id"]: o.get("intrinsic_value")
                            for o in opps if o.get("intrinsic_value")}
        intrinsic_by_ticker = {o["ticker"]: v for o in opps
                               for v in [o.get("intrinsic_value")] if v}
        for p in positions:
            intrinsic = (intrinsic_by_opp.get(p.get("opp_id"))
                         or intrinsic_by_ticker.get(p.get("ticker")))
            if intrinsic and p.get("current_price") and p["current_price"] > intrinsic:
                over = (p["current_price"] - intrinsic) / intrinsic * 100
                add_alert(
                    "price_over_intrinsic", p.get("ticker", ""), "warn",
                    f"Precio {over:.1f}% sobre el valor intrínseco ({intrinsic:.2f})",
                    str(p.get("position_id") or p.get("opp_id") or ""),
                )
        for o in opps:
            if o.get("proposal", {}).get("status") == "PENDING_HUMAN_REVIEW":
                add_alert(
                    "decision_pending", o.get("ticker", ""), "warn",
                    "Propuesta pendiente de revisión humana en Decision Board",
                    str(o.get("opp_id") or ""),
                )
            if o.get("trend") == "DETERIORATING":
                add_alert(
                    "conviction_deteriorating", o.get("ticker", ""), "warn",
                    "Convicción deteriorándose",
                    str(o.get("opp_id") or ""),
                )

        score_totals: dict[str, list[float]] = {}
        convictions: list[float] = []
        for opportunity in opps:
            for engine, score in (opportunity.get("scores") or {}).items():
                if isinstance(score, (int, float)):
                    score_totals.setdefault(engine, []).append(float(score))
            conviction = opportunity.get("conviction_overall")
            if isinstance(conviction, (int, float)) and conviction > 0:
                convictions.append(float(conviction))
        ide = {
            "opportunities": len(opps),
            "engine_averages": {
                engine: round(sum(values) / len(values), 1)
                for engine, values in sorted(score_totals.items()) if values
            },
            "conviction_average": round(sum(convictions) / len(convictions), 1) if convictions else None,
            "research_stale": len(stale),
            "strategy_signals": strategy_signals or {},
        }
        return {
            "sections": sections,
            "alerts": alerts,
            "stats": {
                "active": len([o for o in opps if o["status"] in STATUS_ACTIVE]),
                "buylist": len(buylist),
            },
            "universe_stats": universe_stats if universe_stats else {},
            "ide": ide,
        }

    def _load_strategy_signals(self) -> dict[str, dict]:
        """Load the latest persisted signal report for each enabled strategy."""
        root = self.journal / "strategies"
        latest: dict[str, dict] = {}
        if not root.exists():
            return latest
        for strategy_dir in root.iterdir():
            if not strategy_dir.is_dir():
                continue
            reports = []
            for path in strategy_dir.glob("*.yml"):
                report = _load_yaml(path)
                if isinstance(report, dict):
                    reports.append((str(report.get("generated_at") or path.name), report))
            if not reports:
                continue
            _, report = max(reports, key=lambda item: item[0])
            latest[strategy_dir.name] = {
                "as_of_date": report.get("as_of_date"),
                "generated_at": report.get("generated_at"),
                "run_scope": report.get("run_scope", "unknown"),
                "action": report.get("action"),
                "selected": report.get("selected") or [],
                "eligible_count": len(report.get("eligible") or []),
                "ranking": report.get("ranking") or [],
                "candidate_count": report.get("candidate_count"),
                "eligible_universe_count": report.get("eligible_universe_count"),
                "coverage_complete": report.get("coverage_complete", False),
                "missing_history": report.get("missing_history") or [],
            }
        return latest

    # -- main build --
    def build(self) -> SiteData:
        from idos.strategy.catalog import StrategyCatalog
        scout_policy = self.strategy_catalog.get("COMPOUNDER").parameters.get("scout", {})
        ui_cfg = _load_yaml(self.config / "ui.yml")
        if isinstance(ui_cfg, dict):
            self.stale_days = int(ui_cfg.get("stale_days", self.stale_days))

        self.companies = self._load_companies()
        opps = self._load_opportunities()
        opps = self._attach_wyckoff(opps)
        buylist = self._load_buylist()
        watchlist = self._load_watchlist()
        # Public Pages publishes only the process before portfolio. These
        # fields remain empty for the serialized SiteData compatibility shape.
        positions: list[dict] = []
        ledger: list[dict] = []
        wiki = self._load_wiki_index()
        learning: list[dict] = []
        portfolio: dict = {}
        universe_stats = self._load_universe_stats()
        discovery_pool = self._load_discovery_pool(universe_stats)
        strategy_signals = self._load_strategy_signals()
        dashboard = self._build_dashboard(
            opps, positions, buylist, watchlist, learning, universe_stats, discovery_pool,
            portfolio=portfolio, strategy_signals=strategy_signals,
        )

        return SiteData(
            generated_at=datetime.now(AR_TZ).isoformat(),
            config={"stale_days": self.stale_days},
            opportunities=opps,
            buylist=buylist,
            watchlist=watchlist,
            positions=positions,
            ledger=ledger,
            portfolio=portfolio,
            wiki=wiki,
            learning=learning,
            dashboard=dashboard,
            companies=self.companies,
            entry_rules=self.entry_rules,
            universe_stats=universe_stats,
            discovery_pool=discovery_pool,
            scout_policy=scout_policy,
        )


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

PAGE_TPL = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IDOS — {title}</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
{body}
</body>
</html>"""


def render_wiki_page(ticker: str, comp: dict, sections: list[tuple[str, str]]) -> str:
    body = [f'<div class="wrap"><a class="back" href="../index.html">&larr; Dashboard</a>']
    body.append(f"<h1>{comp.get('name', ticker)} <span class='tick'>{ticker}</span></h1>")
    meta = []
    if comp.get("sector"):
        meta.append(f"<span class='pill'>{comp['sector']}</span>")
    if comp.get("industry"):
        meta.append(f"<span class='pill'>{comp['industry']}</span>")
    if meta:
        body.append("<p class='meta'>" + " ".join(meta) + "</p>")
    body.append("<details class='company-card'><summary>Ficha de compañía</summary><pre class='yaml'>" +
                json.dumps(comp, ensure_ascii=False, indent=2) + "</pre></details>")
    for title, html in sections:
        body.append(f"<h2>{title}</h2>{html}")
    body.append("</div>")
    return PAGE_TPL.format(title=f"Wiki · {ticker}", body="\n".join(body))


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

STYLE_CSS = """\
:root{--bg:#0f1115;--card:#171b22;--border:#262c38;--text:#e6e9ef;--muted:#9aa4b2;--accent:#4f8cff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;font-size:14px;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:20px}
h1{font-size:22px;margin-bottom:6px}
h2{font-size:17px;margin:18px 0 8px}
.muted{color:var(--muted)}.tick{color:var(--accent)}
.tabs{display:flex;gap:4px;flex-wrap:wrap;margin:14px 0;border-bottom:1px solid var(--border);padding-bottom:8px}
.tab{background:none;border:1px solid var(--border);color:var(--muted);padding:6px 14px;border-radius:6px;cursor:pointer}
.tab:hover{color:var(--text)}
.tab.active{background:var(--accent);border-color:var(--accent);color:#fff}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin:10px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);font-size:13px}
th{background:#1c212b;color:var(--muted);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
tr:hover td{background:#1a1f28}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#222a38;color:var(--muted);font-size:12px;margin-right:4px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600}
.st{background:#222a38;color:var(--muted)}
.st-APPROVED{background:#102a1d;color:#4ade80}.st-UNDER_DEEP_DD{background:#10203a;color:#60a5fa}
.st-WATCHLIST{background:#2a1d10;color:#fbbf24}.st-EXITED,.st-POST_MORTEM,.st-ARCHIVED{background:#2a1010;color:#f87171}
.st-DISCOVERED,.st-SCREENED{background:#1f2024;color:#cbd5e1}
.score{font-weight:700}
.pos{color:#4ade80}.neg{color:#f87171}
.details{background:var(--card);border:1px solid var(--border);border-radius:10px;margin:8px 0;padding:10px 14px}
.details summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;background:#12151b;border:1px solid var(--border);border-radius:8px;padding:12px;font-size:12px;overflow-x:auto}
code{background:#1c212b;padding:1px 5px;border-radius:4px;font-size:12px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.toolbar{display:flex;gap:8px;margin:10px 0;flex-wrap:wrap}
input,select{background:#12151b;border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px}
.alert{background:#2a1d10;border:1px solid #4a3510;border-radius:8px;padding:8px 12px;margin:6px 0}
.alert.high{background:#2a1010;border-color:#4a1414}
.scenario-mobile-list{display:none}
.ratio-mobile-list{display:none}
.scenario-mobile-card{background:#12151b;border:1px solid var(--border);border-radius:8px;padding:12px}
.ratio-mobile-card{background:#12151b;border:1px solid var(--border);border-radius:8px;padding:12px;overflow-wrap:anywhere}
.ratio-mobile-card h4{font-size:14px;text-transform:capitalize;margin-bottom:8px}
.ratio-mobile-card p{margin-top:8px}
.scenario-mobile-card h4{font-size:14px;margin-bottom:8px}
.scenario-mobile-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:0 0 10px}
.scenario-mobile-facts dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.scenario-mobile-facts dd{font-weight:600;overflow-wrap:anywhere}
.scenario-mobile-card p,.scenario-mobile-card ul{margin:6px 0}
.scenario-mobile-card ul{padding-left:20px}
.scenario-mobile-card .scenario-sources a{display:inline-block;margin:2px 8px 2px 0}
.back{color:var(--muted);font-size:13px}
.yaml{white-space:pre-wrap}
@media(max-width:720px){.wrap{padding:12px}.tabs{flex-direction:column}.scenario-desktop-table{display:none}.ratio-desktop-table{display:none}.scenario-mobile-list{display:grid;gap:8px}.ratio-mobile-list{display:grid;gap:8px}}
"""

APP_JS = r"""// IDOS static UI
let DATA = null;
const colors = {accumulation:'#16a34a',absorption:'#ca8a04',markdown:'#ea580c',distribution:'#dc2626'};

async function boot(){
  const v = document.getElementById('gen-at') ? document.getElementById('gen-at').dataset.v : '';
  const r = await fetch('data.json?v='+v);
  DATA = await r.json();
  renderShell();
  renderAll();
}

function esc(s){ if(s===null||s===undefined) return '—'; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s){ return esc(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
function fmt(n, d=2){ if(n===null||n===undefined||isNaN(n)) return '—'; return n.toLocaleString('es-AR',{minimumFractionDigits:d, maximumFractionDigits:d}); }
function money(n){ if(n===null||n===undefined||isNaN(n)) return '—'; return '$'+fmt(n,2); }
function pct(n, sign=false){ if(n===null||n===undefined||isNaN(n)) return '—'; return (sign&&n>0?'+':'')+fmt(n,1)+'%'; }
function dt(s){ if(!s) return '—'; return s.slice(0,10); }
function badge(st){ return `<span class="badge st st-${esc(st)}">${esc(st)}</span>`; }
function staleBadge(o){
  if(o.is_stale) return `<span class="badge" style="background:#3a1010;color:#f87171">stale ${o.stale_days}d</span>`;
  if(o.stale_days!==null&&o.stale_days!==undefined) return `<span class="badge" style="background:#1a2436;color:#93a4c8">${o.stale_days}d</span>`;
  return '—';
}
function thesisBadge(o){
  if(o.is_thesis_stale) return `<span class="badge" style="background:#3a1010;color:#f87171">tesis stale ${o.thesis_not_assessed_days}d</span>`;
  if(o.thesis_not_assessed_days!==null&&o.thesis_not_assessed_days!==undefined) return `<span class="badge" style="background:#1a1f2e;color:#93a4c8">tesis ${o.thesis_not_assessed_days}d</span>`;
  return '—';
}
function wyPhase(p){ if(!p) return '—'; return `<span style="color:${colors[p]||'var(--muted)'}">${esc(p)}</span>`; }

// ---------- Sortable tables ----------
const TABLES = {};
function sortCol(view,key){
  const t = TABLES[view]; if(!t) return;
  if(t.sort.key===key) t.sort.dir = t.sort.dir==='asc'?'desc':'asc';
  else { t.sort.key=key; t.sort.dir='desc'; }
  const el = document.getElementById('tbl-'+view);
  if(!el) return;
  const th = el.querySelector('thead'); if(th) th.innerHTML = sortHeadRows(view);
  const tb = el.querySelector('tbody'); if(tb) tb.innerHTML = sortTbody(view);
}
function sortHeadRows(view){
  const t = TABLES[view]; if(!t) return '<tr></tr>';
  return '<tr>'+t.cols.map(c=>{
    const active = t.sort.key===c.key;
    const arrow = active ? (t.sort.dir==='asc'?' &#9650;':' &#9660;') : '';
    return `<th style="cursor:pointer;user-select:none;white-space:nowrap" onclick="sortCol('${view}','${c.key}')" title="Ordenar por ${esc(c.label)}">${esc(c.label)}${arrow}</th>`;
  }).join('')+'</tr>';
}
function sortValue(col,r){
  const v = col.value ? col.value(r) : r[col.key];
  return (v===null||v===undefined) ? null : v;
}
function sortTbody(view){
  const t = TABLES[view]; if(!t) return '';
  const q = (t.q||'').toLowerCase();
  let rows = (t.rows||[]).slice();
  if(q) rows = rows.filter(r => (t.searchText? t.searchText(r) : String(r.ticker||'')).toLowerCase().includes(q));
  const col = t.cols.find(c=>c.key===t.sort.key) || t.cols[0];
  const dir = t.sort.dir==='asc'?1:-1;
  rows.sort((a,b)=>{
    let va = sortValue(col,a), vb = sortValue(col,b);
    const na = (va===null||va===undefined), nb = (vb===null||vb===undefined);
    if(na&&nb) return 0;
    if(na) return 1;
    if(nb) return -1;
    if(typeof va==='string') va = va.toLowerCase();
    if(typeof vb==='string') vb = vb.toLowerCase();
    if(va===vb) return 0;
    const c = va<vb?-1:1;
    return dir===1? c : -c;
  });
  return rows.map(r=>{
    const rowAttr = t.tr ? t.tr(r) : '';
    return `<tr${rowAttr}>${t.cols.map(x=>x.cell(r)).join('')}</tr>`;
  }).join('');
}
function tableInput(view, id, ph){
  return `<input id="${id}" placeholder="${ph}" oninput="TABLES['${view}'].q=this.value;const tb=document.querySelector('#tbl-${view} tbody');if(tb)tb.innerHTML=sortTbody('${view}')" style="margin:8px 0">`;
}

function renderShell(){
  document.getElementById('tabs').innerHTML = [
    ['dashboard','Dashboard'],['screening','Discovery'],['opp','Research'],['strategies','Strategies'],['buylist','Buy List']
  ].map(([id,l])=>`<button class="tab" data-view="${id}">${l}</button>`).join('');
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{ document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); b.classList.add('active'); renderView(b.dataset.view); });
}

function renderAll(){ renderView('dashboard'); }

function renderView(id){
  id = id || 'dashboard';
  if(id==='dashboard') return renderDashboard();
  if(id==='opp') return renderOpp();
  if(id==='strategies') return renderStrategies();
  if(id==='buylist') return renderBuylist();
  if(id==='screening') return renderScreening();
  renderDashboard();
}

function renderStrategies(){
  const rows = DATA.opportunities||[];
  const groups = {};
  rows.forEach(o=>{ const k=o.strategy_id||'COMPOUNDER'; groups[k]=(groups[k]||0)+1; });
  let html = '<h2>Estrategias IDOS</h2><p class="muted">Discovery, Research y estado de cada estrategia sin alterar el lifecycle de oportunidades.</p>';
  html += '<table><thead><tr><th>Estrategia</th><th>Oportunidades</th><th>Core</th><th>Sleeves</th></tr></thead><tbody>';
  Object.keys(groups).sort().forEach(k=>{
    const sample=rows.find(o=>(o.strategy_id||'COMPOUNDER')===k)||{};
    const sleeves=[...new Set(rows.filter(o=>(o.strategy_id||'COMPOUNDER')===k).map(o=>o.sleeve).filter(Boolean))].join(', ')||'—';
    html += `<tr><td><b>${esc(k)}</b></td><td>${groups[k]}</td><td>${esc(sample.core||'—')}</td><td>${esc(sleeves)}</td></tr>`;
  });
  html += '</tbody></table>';
  setView('strategies', html);
}

function goTab(id){
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  const b = [...document.querySelectorAll('.tab')].find(x=>x.dataset.view===id);
  if(b) b.classList.add('active');
  renderView(id);
}

// ---------- Dashboard ----------
function renderDashboard(){
  const d = DATA.dashboard;
  const ide = d.ide||{};
  let html = '<div class="grid">';
  (d.sections||[]).forEach(s=>{
    html += `<div class="card" style="cursor:pointer" onclick="goTab('${s.tab}')" title="Ver ${esc(s.label)}">
      <div class="muted">${esc(s.label)}</div>
      <div style="font-size:26px;font-weight:700">${s.count}</div>
    </div>`;
  });
  html += '</div>';
  html += '<h2>Métricas del IDE</h2><div class="grid">';
  html += `<div class="card"><div class="muted">Oportunidades evaluadas</div><div style="font-size:24px;font-weight:700">${ide.opportunities??0}</div></div>`;
  html += `<div class="card"><div class="muted">Convicción media</div><div style="font-size:24px;font-weight:700">${ide.conviction_average!=null?fmt(ide.conviction_average,1):'—'}</div></div>`;
  html += `<div class="card"><div class="muted">Research stale</div><div style="font-size:24px;font-weight:700" class="${(ide.research_stale||0)>0?'neg':''}">${ide.research_stale??0}</div></div>`;
  Object.entries(ide.engine_averages||{}).forEach(([engine,score])=>{
    html += `<div class="card"><div class="muted">${esc(engine)}</div><div style="font-size:20px;font-weight:700">${fmt(score,1)}/100</div></div>`;
  });
  html += '</div>';
  const strategies = ide.strategy_signals||{};
  if(Object.keys(strategies).length){
    html += '<h2>Señales sistemáticas</h2><div class="grid">';
    Object.entries(strategies).forEach(([name,s])=>{
      const selected=(s.selected||[]).map(x=>`${esc(x.ticker)} (${fmt(x.momentum,2)})`).join(', ')||'Sin selección';
      const candidateCount=s.candidate_count;
      const universeCount=s.eligible_universe_count;
      const fullRun=s.run_scope==='full' && s.coverage_complete===true && candidateCount===universeCount;
      const scope=s.run_scope==='bounded'
        ? `Prueba parcial · ${candidateCount??0}/${universeCount??'?'} activos de la estrategia`
        : fullRun ? `Universo completo · ${candidateCount} activos analizados`
        : s.run_scope==='full' ? `Cobertura incompleta · ${candidateCount??0}/${universeCount??'?'} activos`
        : 'Alcance sin verificar · reporte anterior';
      const action=fullRun ? (s.action||'—') : `${s.action||'—'} · no interpretar como señal global`;
      html += `<div class="card"><div class="muted">${esc(name)} · ${esc(s.as_of_date||'')}</div><div class="muted">${esc(scope)}</div><div style="font-weight:700">${esc(action)}</div><div class="muted">${selected}</div><div class="muted">Elegibles: ${s.eligible_count??0}</div></div>`;
    });
    html += '</div>';
  }
  html += '<h2>Alertas</h2>';
  if(!d.alerts.length) html += '<p class="muted">Sin alertas.</p>';
  d.alerts.forEach(a=>html+=`<div class="alert ${a.severity==='high'?'high':''}"><b>${esc(a.ticker)}</b> — ${esc(a.message)}</div>`);
  setView('dashboard', html);
}

// ---------- Research ----------
function detailsEntryRules(){
  let h = '<details class="details" style="margin:10px 0"><summary>Umbrales de aprobación (Decision Board)</summary><table><thead><tr><th>Regla</th><th>Condición</th><th>Prioridad</th></tr></thead><tbody>';
  (ENTRY_RULES||[]).slice().sort((a,b)=>(b.priority||0)-(a.priority||0)).forEach(r=>{
    h += `<tr><td>${esc(r.id)}</td><td><code>${esc(r.condition)}</code></td><td>${r.priority??'—'}</td></tr>`;
  });
  h += '</tbody></table></details>';
  return h;
}
function detailsEntryThresholds(){
  const c = ENTRY_CFG||{};
  const rows = [
    ['Precio en zona', `Precio &le; Zona de compra (top). Si no hay zona, margen de seguridad &ge; ${c.margin_of_safety_pct??30}%.`, 'EntryEngine'],
    ['Wyckoff confirmado', `Fase en ${(c.entry_phases||['ACCUMULATION','ABSORPTION']).join(' / ')} y score compuesto &ge; ${c.min_wyckoff_score??45}.`, 'EntryEngine'],
    ['Tesis activa', `Thesis monitor sin invalidación (thesis_active = true).`, 'EntryEngine'],
    ['Fit de portfolio', `Peso total + nuevo &le; ${fmt(c.max_total_weight_pct,0)}% del bankroll.`, 'EntryEngine'],
    ['Target definido', `target_price > 0 en Buy List.`, 'EntryEngine'],
  ];
  let h = '<details class="details" style="margin:10px 0"><summary>Umbrales para pasar a ENTRY (Entry Engine y Wyckoff)</summary><table><thead><tr><th>Condición</th><th>Umbral</th><th>Fuente</th></tr></thead><tbody>';
  rows.forEach(([k,v,f])=>{ h += `<tr><td><b>${k}</b></td><td><code>${v}</code></td><td class="muted">${f}</td></tr>`; });
  h += '</tbody></table></details>';
  return h;
}
function buylistEntryFails(r){
  const c = ENTRY_CFG||{};
  const fails = [];
  const thesisState = r.recommendation_state||'REVIEW_UNVERIFIED';
  const thesisMessages = {
    REVIEW_DUE:'Tesis vencida; actualizar Research',
    INVALIDATED:'Tesis invalidada',
    UNLINKED:'Sin oportunidad vinculada',
    CONFIGURATION_ERROR:'Error en agenda de tesis',
    NOT_APPLICABLE:'Revisar vigencia de señal sistemática',
    REVIEW_UNVERIFIED:'Vigencia de tesis sin verificar'
  };
  if(thesisState!=='CURRENT') fails.push(thesisMessages[thesisState]||'Revisión de tesis requerida');
  if(r.discovery_review_required) fails.push('Scout: datos requieren revisión');
  if(!r.current_price || r.current_price<=0){
    fails.push('Precio sin datos');
  } else if(r.buy_zone_top && r.buy_zone_top>0){
    if(r.current_price > r.buy_zone_top) fails.push(`Precio fuera de zona (${fmt((r.current_price/r.buy_zone_top-1)*100,0)}% arriba)`);
  } else if(r.target_price && r.target_price>0){
    const margin = (r.target_price-r.current_price)/r.current_price*100;
    if(margin < (c.margin_of_safety_pct??30)) fails.push(`Margen de seguridad &lt; ${c.margin_of_safety_pct??30}%`);
  }
  if(!r.target_price || r.target_price<=0) fails.push('Target sin definir');
  const wy = r.wyckoff;
  const phases = (c.entry_phases||['ACCUMULATION','ABSORPTION']).map(p=>String(p).toUpperCase());
  const score = wy?.['score'] ?? null;
  const phase = wy?.['phase'] ? String(wy.phase).toUpperCase() : null;
  if(!phase || !phases.includes(phase)) fails.push(`Fase ${wyPhase(wy?.phase)} no es entrada`);
  if(score!==null && score < (c.min_wyckoff_score??45)) fails.push(`Score Wyckoff ${score} &lt; ${c.min_wyckoff_score??45}`);
  return fails;
}
function rulesBadge(failed){
  if(!failed||!failed.length) return '<span class="pos">OK</span>';
  const map = {};
  (ENTRY_RULES||[]).forEach(r=>{ if(r.description) map[r.id]=r.description.split(' for ')[0].replace(/[.:;-]+$/,''); });
  return failed.map(id=>`<span class="badge" title="${esc(map[id]||id)}" style="background:#2a1516;color:#f87171">${esc(id)}</span>`).join(' ');
}
function renderOpp(){
  const rows = DATA.opportunities.filter(o=>['UNDER_RESEARCH','UNDER_DEEP_DD'].includes(o.status));
  TABLES['opp'] = {
    rows,
    cols: [
      {key:'ticker', label:'Ticker', value:r=>r.ticker, cell:r=>`<td><b>${esc(r.ticker)}</b></td>`},
      {key:'conviction', label:'Conv.', value:r=>r.conviction_overall??null, cell:r=>`<td>${r.conviction_overall??'—'}</td>`},
      {key:'business', label:'Business', value:r=>r.scores?.BusinessAssessmentEngine??null, cell:r=>`<td>${r.scores?.BusinessAssessmentEngine??'—'}</td>`},
      {key:'valuation', label:'Valuation', value:r=>r.scores?.ValuationAssessmentEngine??null, cell:r=>`<td>${r.scores?.ValuationAssessmentEngine??'—'}</td>`},
      {key:'risk', label:'Risk', value:r=>r.scores?.RiskAssessmentEngine??null, cell:r=>`<td>${r.scores?.RiskAssessmentEngine??'—'}</td>`},
      {key:'recovery', label:'Recovery', value:r=>r.scores?.RecoveryAssessmentEngine??null, cell:r=>`<td>${r.scores?.RecoveryAssessmentEngine??'—'}</td>`},
      {key:'price', label:'Precio', value:r=>r.current_price??null, cell:r=>`<td>${money(r.current_price)}<div class="muted">${dt(r.price_date)}</div></td>`},
      {key:'intrinsic', label:'Intrínseco', value:r=>r.intrinsic_value??null, cell:r=>`<td>${r.valuation_status==='NOT_APPLICABLE'?'No aplica':money(r.intrinsic_value)}</td>`},
      {key:'upside', label:'Upside', value:r=>r.upside_pct??null, cell:r=>`<td class="${r.upside_pct>=0?'pos':'neg'}">${pct(r.upside_pct,true)}</td>`},
      {key:'rules', label:'Rules failed', value:r=>(r.proposal?.rules_failed||[]).length, cell:r=>`<td>${rulesBadge(r.proposal?.rules_failed)}</td>`},
      {key:'last', label:'Última inv.', value:r=>r.last_research||'', cell:r=>`<td>${dt(r.last_research)} ${staleBadge(r)}</td>`},
    ],
    tr: r=>` style="cursor:pointer" onclick="showCase('${r.opp_id}')"`,
    searchText: r=>`${r.ticker} ${r.opp_id} ${r.industry||''}`,
    sort: {key:'conviction', dir:'desc'},
    q:'',
  };
  let html = `<h2>Research (${rows.length})</h2>`;
  html += `<p class="muted">Oportunidades en <b>Research / UNDER_RESEARCH o UNDER_DEEP_DD</b>: casos que superaron el umbral de Discovery (<b>≥ ${DISC_MIN_SCORE}</b>) y fueron promovidos automáticamente. Aquí se ejecuta la due diligence en profundidad (DDD, assessments, valuation y risk). Hacé clic en un ticker para ver el detalle completo del activo. Clic en una columna para ordenar.</p>`;
  html += `<p class="muted">Los agentes completan Discovery, Research y Assessment y preparan un expediente con datos, tesis, escenarios, asimetría, riesgos y reglas. La primera intervención humana ocurre una sola vez en <b>Decision Board</b>: el gestor revisa el paquete completo y aprueba o rechaza. Una aprobación válida agrega el caso a la <b>Buy List</b>, sin crear posiciones ni órdenes.</p>`;
  html += detailsEntryRules();
  html += tableInput('opp','opp-search','Buscar ticker...');
  html += `<table id="tbl-opp"><thead>${sortHeadRows('opp')}</thead><tbody>${sortTbody('opp')}</tbody></table>`;
  setView('opp', html);
}

// ---------- Buy List ----------
function renderBuylist(){
  const rows = DATA.buylist.slice();
  const margin = r => (r.current_price&&r.target_price&&r.target_price>0)? (r.target_price-r.current_price)/r.current_price*100 : null;
  TABLES['buylist'] = {
    rows,
    cols: [
      {key:'ticker', label:'Ticker', value:r=>r.ticker, cell:r=>`<td><b>${esc(r.ticker)}</b></td>`},
      {key:'strategy', label:'Estrategia', value:r=>r.strategy_id||'UNKNOWN', cell:r=>`<td>${esc(r.strategy_id||'Sin identificar')}<div class="muted">${esc(r.entry_policy||'')}</div>${r.strategy_signal?`<div class="muted">Señal: ${esc(r.strategy_signal.signal_type||r.strategy_signal.type||'sistemática')} ${esc(r.strategy_signal.score??r.strategy_signal.momentum??'')}</div>`:''}</td>`},
      {key:'industry', label:'Industria', value:r=>r.industry||'', cell:r=>`<td class="muted">${esc(r.industry||'—')}</td>`},
      {key:'conviction', label:'Conv.', value:r=>r.conviction_score??null, cell:r=>`<td>${r.conviction_score??'—'}</td>`},
      {key:'price', label:'Último precio', value:r=>r.current_price??null, cell:r=>`<td>${money(r.current_price)}</td>`},
      {key:'zone', label:'Zona compra (top)', value:r=>r.buy_zone_top??null, cell:r=>`<td>${money(r.buy_zone_top)}</td>`},
      {key:'target', label:'Target', value:r=>r.target_price??null, cell:r=>`<td>${money(r.target_price)}</td>`},
      {key:'margin', label:'Margen a target', value:r=>margin(r), cell:r=>{const m=margin(r); return `<td class="${m>=0?'pos':'neg'}">${pct(m,true)}</td>`;}},
      {key:'thesis', label:'Vigencia de tesis', value:r=>r.recommendation_state||'REVIEW_UNVERIFIED', cell:r=>{const s=r.recommendation_state||'REVIEW_UNVERIFIED'; const labels={CURRENT:'Vigente',REVIEW_DUE:'Revisión vencida',INVALIDATED:'Invalidada',UNLINKED:'Sin vínculo',CONFIGURATION_ERROR:'Error de configuración',NOT_APPLICABLE:'No aplica',REVIEW_UNVERIFIED:'Sin verificar'}; return `<td><span class="badge" style="background:${s==='CURRENT'?'#12351f':'#2a1516'};color:${s==='CURRENT'?'#86efac':'#f87171'}">${labels[s]||'Revisión requerida'}</span><div class="muted">Próxima: ${dt(r.next_thesis_review_at)||'sin fecha'}</div></td>`;}},
      {key:'discovery', label:'Último Scout', value:r=>r.discovery_status||'NOT_EVALUATED', cell:r=>{const s=r.discovery_status||'NOT_EVALUATED'; const labels={PASSED:'Elegible',PENDING_DATA:'Datos pendientes',REJECTED:'No elegible',NOT_EVALUATED:'Sin evaluación'}; const bad=!!r.discovery_review_required; const title=r.discovery_reason?` title="${esc(r.discovery_reason)}"`:''; return `<td><span class="badge"${title} style="background:${bad?'#2a1516':'#12351f'};color:${bad?'#f87171':'#86efac'}">${labels[s]||'Revisar'}</span></td>`;}},
      {key:'wy', label:'Wyckoff', value:r=>r.wyckoff?.score??null, cell:r=>{const wy=r.wyckoff; return `<td>${wyPhase(wy?.phase)} ${wy?.score??''}</td>`;}},
      {key:'fails', label:'Cond. fallida', value:r=>buylistEntryFails(r).length, cell:r=>{const f=buylistEntryFails(r); return `<td>${f.length?f.map(x=>`<span class="badge" style="background:#2a1516;color:#f87171">${x}</span>`).join(' '):'<span class="pos">Listo</span>'}</td>`;}},
      {key:'data', label:'Dato / fuentes', value:r=>`${r.price_date||''} ${r.market_data?.source_count??''}`, cell:r=>`<td>${dt(r.price_date)} · ${r.market_data?.source_count??'sin dato'} fuente(s)</td>`},
      {key:'analyzed', label:'Últ. análisis', value:r=>r.wyckoff?.analyzed_at||'', cell:r=>`<td>${dt(r.wyckoff?.analyzed_at)}</td>`},
    ],
    tr: r=>` style="cursor:pointer" onclick="showOppFromBuylist('${r.opp_id||''}','${r.ticker}')"`,
    searchText: r=>`${r.ticker} ${r.industry||''}`,
    sort: {key:'wy', dir:'desc'},
    q:'',
  };
  let html = `<h2>Buy List (${rows.length})</h2>`;
  html += `<p class="muted">La lista conserva las entradas aprobadas. La vigencia de tesis y el último Scout se muestran por oportunidad: una tesis vencida o un Scout con datos pendientes requiere revisión antes de actuar.</p>`;
  html += detailsEntryThresholds();
  if(!rows.length) html += `<div class="card"><p class="muted">La Buy List está vacía.</p></div>`;
  html += tableInput('buylist','bl-search','Buscar ticker...');
  html += `<table id="tbl-buylist"><thead>${sortHeadRows('buylist')}</thead><tbody>${sortTbody('buylist')}</tbody></table>`;
  setView('buylist', html);
}

// ---------- Discovery ----------
function renderScreening(){
  const rows = (DATA.discovery_pool && DATA.discovery_pool.length) ? DATA.discovery_pool : DATA.watchlist;
  const filters = DATA.scout_policy?.filters||[];
  const mkeys = filters.map(f=>f.metric);
  const mlabels = filters.map(f=>`${f.label||f.metric} > ${f.value}`);
  TABLES['screening'] = {
    rows,
    cols: [
      {key:'ticker', label:'Ticker', value:r=>r.ticker, cell:r=>`<td><b>${esc(r.ticker)}</b></td>`},
      {key:'status', label:'Resultado actual', value:r=>r.status||'', cell:r=>`<td title="${esc(r.reason||'')}">${esc(r.status||'Histórico')}</td>`},
      ...mkeys.map((k,i)=>({key:k, label:mlabels[i], value:r=>r.metrics?r.metrics[k]:null, cell:r=>{const v=r.metrics?r.metrics[k]:null; const passed=r.filter_results?.[k]===100; const obs=r.financial_observations?.[k]||{}; const currency=obs.currency; const suffix=k==='operating_margin_pct'||k==='revenue_growth_pct'?'%':k==='fcf'?(currency?` ${currency}`:' (moneda no informada)'):''; const shown=v==null?'Pendiente':`${Number(v).toLocaleString('es-AR',{maximumFractionDigits:2})}${suffix} · ${passed?'Cumple':'No cumple'}`; return `<td class="${passed?'pos':''}" title="${esc(JSON.stringify({observation:obs, data_provenance:r.data_provenance?.field_sources?.[k]||[]}))}">${shown}</td>`;}})),
      {key:'added', label:'Agregado', value:r=>r.added_at||'', cell:r=>`<td>${dt(r.added_at)}</td>`},
    ],
    tr: r=>` style="cursor:pointer" onclick="showCaseFromOpp('${r.opp_id||''}','${r.ticker}')"`,
    searchText: r=>`${r.ticker} ${r.opp_id||''}`,
    sort: {key:'score', dir:'desc'},
    q:'',
  };
  const total = rows.length;
  const poolLabel = (DATA.discovery_pool && DATA.discovery_pool.length) ? 'Candidatos operables' : 'Watchlist';
  let html = `<h2>Discovery (${total})</h2>`;
  html += `<p class="muted"><b>${poolLabel}.</b> COMPOUNDER aplica los filtros configurados de la tabla (${esc(DATA.scout_policy?.version||"sin política")}), además del gate común de operabilidad y liquidez y capitalización para acciones. Los datos ausentes quedan pendientes. Cumplir los filtros habilita screening y Research; no representa convicción ni una recomendación de compra. ROIC y moat se evalúan en Research.</p>`;
  html += tableInput('screening','screen-search','Buscar ticker...');
  html += `<table id="tbl-screening"><thead>${sortHeadRows('screening')}</thead><tbody>${sortTbody('screening')}</tbody></table>`;
  setView('screening', html);
}

// ---------- Wiki ----------
// ---------- Case View ----------
function findOpp(oppId){ return DATA.opportunities.find(o=>o.opp_id===oppId) || {opp_id:oppId,ticker:'?',status:'?',scores:{}}; }
function showCase(oppId){
  const o = findOpp(oppId);
  const by = DATA.buylist.find(b=>b.ticker===o.ticker);
  const d = o.ddd||{};
  const discovery = o.latest_discovery_evidence||{};
  let html = `<button class="tab" onclick="renderAll()">← Volver</button>`;
  html += `<h1>${esc(o.ticker)} <span class="tick">${esc(o.opp_id)}</span> ${badge(o.status)}</h1>`;
  if(['PENDING_DATA','REJECTED'].includes(String(discovery.eligibility_status||'').toUpperCase())){
    html += `<div class="card" style="border-color:#5a2424"><b class="neg">Último Scout: ${esc(discovery.eligibility_status)}</b><p>${esc(discovery.reason||'Revisar la evidencia de Discovery antes de usar esta oportunidad.')}</p><p class="muted">Datos faltantes: ${esc((discovery.missing_metrics||[]).join(', ')||'ninguno')} · Conflictos: ${esc((discovery.conflicting_metrics||[]).join(', ')||'ninguno')}</p></div>`;
  }
  html += `<div class="grid">`;
  html += `<div class="card"><div class="muted">Convicción</div><div style="font-size:22px;font-weight:700">${o.conviction_overall??'—'}</div><div class="muted">${esc(o.confidence||'')} · ${esc(o.trend||'')}</div></div>`;
  if(o.strategy_id==='MULTIBAGGERS') html += `<div class="card"><div class="muted">Discovery Score · Prioridad Research</div><div style="font-size:20px;font-weight:700">${fmt(o.discovery_score,1)} · ${fmt(o.research_priority,1)}</div><div class="muted">${esc(o.discovery_type||'')} · no son probabilidad ni convicción</div></div>`;
  html += `<div class="card"><div class="muted">Precio / Intrínseco</div><div style="font-size:18px">${money(o.current_price)} / ${o.valuation_status==='NOT_APPLICABLE'?'No aplica':money(o.intrinsic_value)}</div><div class="${o.upside_pct>=0?'pos':'neg'}">${pct(o.upside_pct,true)}</div></div>`;
  html += `<div class="card"><div class="muted">Última investigación</div><div style="font-size:16px">${dt(o.last_research)}</div>${staleBadge(o)}</div>`;
  html += `<div class="card"><div class="muted">Evaluación / próxima revisión de tesis</div><div style="font-size:16px">${dt(o.last_thesis_assessment_at||o.last_research||o.updated_at)} / ${dt(o.next_thesis_review_at)||'Pendiente'}</div><div class="muted">Cadencia: ${o.thesis_review_interval_days?`${o.thesis_review_interval_days} días`:'No aplica'} · ${esc(o.thesis_review_status||'sin agenda')}</div>${thesisBadge(o)}</div>`;
  html += `<div class="card"><div class="muted">${o.decision?.decision_type?'Decisión':'Propuesta'}</div><div style="font-size:18px">${esc(o.decision?.decision_type||o.proposal?.decision||'—')}</div><div class="muted">${esc(o.decision?.author||o.proposal?.status||'')} ${dt(o.decision?.resolved_at)}</div></div>`;
  html += '</div>';
  if(o.proposal?.status==='PENDING_HUMAN_REVIEW' && o.proposal?.proposal_hash){
    html += `<div class="card"><b>Expediente listo para Decision Board</b><p>Discovery, Research y Assessment fueron procesados automáticamente. En Decision Board, revisa tesis, evidencia, casos Bear/Bull (Base opcional), asimetría y reglas; registra aprobar o rechazar con una justificación. Aprobar sólo agrega a Buy List, nunca crea posiciones ni órdenes. <a href="https://github.com/alebertolli/idos/actions/workflows/decision-review.yml" target="_blank" rel="noopener noreferrer">Abrir Decision Review</a></p><details><summary>Hash de la propuesta completa</summary><code>${esc(o.proposal.proposal_hash)}</code></details></div>`;
  }
  const marketData=o.market_data||by?.market_data||{};
  const sourceNames=(marketData.sources_used||[]).map(esc).join(', ')||'No registrada';
  html += `<h2>Datos de mercado</h2><div class="card"><div>Precio al: ${dt(marketData.price_as_of||o.price_date)}</div><div>Fuentes del cache: ${marketData.source_count??'no disponible'} (${sourceNames})</div>${marketData.refreshed_at?`<div>Cache actualizado: ${dt(marketData.refreshed_at)}</div>`:''}${marketData.source_count===1?'<p class="neg">Fuente única; revisar la cobertura por campo antes de usar el dato.</p>':''}${marketData.conflict_count?`<p class="neg">Conflictos de datos: ${marketData.conflict_count}</p>`:''}<details><summary>Procedencia por campo</summary>${Object.keys(marketData.field_sources||{}).length?`<table><thead><tr><th>Campo</th><th>Fuentes</th></tr></thead><tbody>${Object.entries(marketData.field_sources).map(([field,sources])=>`<tr><td>${esc(field)}</td><td>${sources.map(esc).join(', ')}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">El cache no registra procedencia por campo.</p>'}</details></div>`;

  // Tesis e informe
  const dddReviewed = ['manager_approved','board_approved'].includes(d.evidence_review?.status);
  const dddSystematic = d.evidence_review?.status==='systematic_report';
  if(d.evidence_review?.status==='systematic_report_refresh_required'){
    html += `<h2>Reporte sistemático</h2><div class="card"><b>Requiere actualización.</b><p class="muted">Regenerar Research con la política vigente antes de interpretar sus métricas. La señal y su fecha siguen disponibles en la estrategia.</p></div>`;
  } else {
  const dddProvisional = !dddReviewed && !dddSystematic;
  if(dddProvisional) html += `<h2>Análisis fundamental · propuesta de agentes</h2><div class="card"><b>Expediente generado automáticamente; pendiente del Decision Board.</b><p class="muted">Discovery, Research y Assessment completan el análisis y validan la estructura y procedencia disponible. Convicción, valor intrínseco, upside y scores son propuestas sujetas a la decisión del gestor. La revisión de fuentes y supuestos ocurre dentro del Decision Board.</p></div>`;
  if(dddSystematic) html += `<div class="card"><b>Reporte sistemático.</b><p class="muted">Señal y métricas generadas por reglas de estrategia; no representan una tesis fundamental ni una aprobación de compra.</p></div>`;
  const dddVerdict = d.conclusion_error_valoracion ?? d.error_mercado?.conclusion_error_valoracion;
  html += `<h2>${dddProvisional?'Tesis de inversión (provisional)':'Tesis de inversión'}</h2>`;
  if(d.resumen_ejecutivo) html += `<div class="card"><div class="muted">Resumen ejecutivo</div><p>${esc(d.resumen_ejecutivo)}</p></div>`;
  if(d.tesis_inversion) html += `<div class="card"><div class="muted">Tesis</div><p>${esc(d.tesis_inversion)}</p></div>`;
  const dq = d.financial_data_quality||{};
  if(Object.keys(dq).length) html += `<div class="card"><b>Calidad de datos financieros:</b> ${esc(dq.status||'sin evaluar')} · <b>Métricas core:</b> ${esc(dq.core_metric_coverage||'—')} · <b>Fuente:</b> ${esc(dq.source||'—')} · <b>Fecha de corte:</b> ${dt(dq.as_of_date)}${dq.as_of_date_source?` (${esc(dq.as_of_date_source)})`:''}${dq.as_of_basis?` · <b>Base de fecha:</b> ${esc(dq.as_of_basis==='provider_data_updated_date'?'última actualización publicada por la fuente':dq.as_of_basis)}`:''}${(dq.missing_core_metrics||[]).length?`<p class="neg">Métricas faltantes: ${dq.missing_core_metrics.map(esc).join(', ')}</p>`:''}${(dq.missing_provenance||[]).length?`<p class="neg">Procedencia faltante: ${dq.missing_provenance.map(esc).join(', ')}</p>`:''}${(dq.conflicting_core_metrics||[]).length?`<p class="neg">Conflictos entre fuentes: ${dq.conflicting_core_metrics.map(esc).join(', ')}</p>`:''}${(dq.unreconciled_core_metrics||[]).length?`<p class="neg">Periodos sin reconciliar: ${dq.unreconciled_core_metrics.map(esc).join(', ')}</p>`:''}</div>`;
  const ratios=d.ratios_investigados||[];
  if(ratios.length){
    const ratioDetails=r=>{
      const value=r.value==null?'—':`${fmt(r.value,2)}${r.unit==='percent'?'%':r.unit==='x'?'x':r.unit?` ${esc(r.unit)}`:''}`;
      const status=r.status==='reported'?'Informado':r.status==='unavailable'?'Sin dato':'Revisar';
      const sources=(r.sources||[]).map(s=>`<a href="${escAttr(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>${s.as_of_date?` · ${dt(s.as_of_date)}`:''}`).join('<br>')||'Sin fuente registrada';
      const note=r.status==='unavailable'?(r.limitations||'La fuente no entregó este dato.'):(r.formula?`Fórmula: ${esc(r.formula)}`:r.limitations||'');
      return {value,status,sources,note};
    };
    const ratioRows=ratios.map(r=>{const x=ratioDetails(r);return `<tr><td>${esc(r.metric.replace(/_/g,' '))}</td><td>${esc(x.value)}</td><td>${esc(x.status)}</td><td>${dt(r.period_end)}</td><td>${x.sources}</td><td>${esc(x.note||'—')}</td></tr>`;}).join('');
    const ratioCards=ratios.map(r=>{const x=ratioDetails(r);return `<article class="ratio-mobile-card"><h4>${esc(r.metric.replace(/_/g,' '))}</h4><dl class="scenario-mobile-facts"><div><dt>Resultado</dt><dd>${esc(x.value)}</dd></div><div><dt>Estado</dt><dd>${esc(x.status)}</dd></div><div><dt>Fecha de corte</dt><dd>${dt(r.period_end)}</dd></div></dl><div><b>Fuente</b><br>${x.sources}</div>${x.note?`<p class="muted">${esc(x.note)}</p>`:''}</article>`;}).join('');
    html += `<h3>Métricas financieras investigadas en Research</h3><div class="card"><p class="muted">Los valores informados incluyen fecha y fuente. Los datos no disponibles permanecen explícitos y no se estiman.</p><table class="ratio-desktop-table"><thead><tr><th>Métrica</th><th>Resultado</th><th>Estado</th><th>Fecha de corte</th><th>Fuente</th><th>Fórmula o motivo</th></tr></thead><tbody>${ratioRows}</tbody></table><div class="ratio-mobile-list">${ratioCards}</div></div>`;
  }
  const sa=d.scenario_analysis;
  if(sa?.scenarios?.length){
    const scenarioRows=sa.scenarios.map(s=>{
      const sources=(s.sources||[]).map(x=>`<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.name)}</a> (${dt(x.as_of_date)})`).join('<br>');
      const assumptions=(s.key_assumptions||[]).map(x=>`<li>${esc(x)}</li>`).join('');
      const rationale=s.rationale?`<p>${esc(s.rationale)}</p>`:'';
      const falsifiers=(s.falsifiers||[]).map(x=>`<li>${esc(x)}</li>`).join('');
      return `<tr><td>${esc(s.id)}</td><td>${esc(sa.currency)} ${money(s.target_price)}</td><td>${rationale}${assumptions?`<b>Supuestos</b><ul>${assumptions}</ul>`:''}${falsifiers?`<b>Falsadores</b><ul>${falsifiers}</ul>`:''}</td><td>${sources}</td></tr>`;
    }).join('');
    const scenarioCards=sa.scenarios.map(s=>{
      const sources=(s.sources||[]).map(x=>`<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.name)}</a> · ${dt(x.as_of_date)}`).join('<br>');
      const assumptions=(s.key_assumptions||[]).map(x=>`<li>${esc(x)}</li>`).join('');
      const falsifiers=(s.falsifiers||[]).map(x=>`<li>${esc(x)}</li>`).join('');
      return `<article class="scenario-mobile-card" aria-label="Caso ${esc(s.id)}"><h4>${esc(s.id)}</h4><dl class="scenario-mobile-facts"><div><dt>Precio objetivo</dt><dd>${esc(sa.currency||'—')} ${money(s.target_price)}</dd></div></dl>${s.rationale?`<p>${esc(s.rationale)}</p>`:''}${assumptions?`<b>Supuestos</b><ul>${assumptions}</ul>`:''}${falsifiers?`<b>Falsadores</b><ul>${falsifiers}</ul>`:''}<div class="scenario-sources"><b>Fuentes</b><br>${sources||'Sin fuente registrada'}</div></article>`;
    }).join('');
    html += `<h3>Asimetría · casos Bear/Bull</h3><div class="card"><b>${d.scenario_validation?.status==='valid_pending_decision_board'?'Validación automática completa · pendiente Decision Board':'Propuesta pendiente de evaluación'}</b><p class="muted">Base es opcional. Horizonte: ${dt(sa.horizon_date)} · Fecha de análisis: ${dt(sa.as_of_date)} · Moneda: ${esc(sa.currency||'—')}</p><table class="scenario-desktop-table"><thead><tr><th>Caso</th><th>Precio objetivo</th><th>Lectura, supuestos y falsadores</th><th>Fuentes</th></tr></thead><tbody>${scenarioRows}</tbody></table><div class="scenario-mobile-list">${scenarioCards}</div><p class="muted">Los agentes validan la estructura, fechas y correspondencia de fuentes con la evidencia de entrada. Assessment compara el upside del caso Bull con el downside del caso Bear sin ponderarlos por probabilidades. No se calcula retorno esperado. En Decision Board, el gestor revisa las fuentes y los supuestos junto con el expediente completo; ningún escenario autoriza por sí solo una compra.</p>${d.board_review?.scenario_hash?`<details><summary>Hash de escenarios incluido en la propuesta</summary><code>${esc(d.board_review.scenario_hash)}</code></details>`:''}</div>`;
  } else if(d.scenario_validation?.errors?.length){
    html += `<h3>Casos Bear / Bull (Base opcional)</h3><div class="card"><b class="neg">Propuesta incompleta o inválida; RULE-008 permanece bloqueada.</b><ul>${d.scenario_validation.errors.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  } else if(d.scenario_validation?.status==='not_applicable'){
    html += `<h3>Asimetría</h3><div class="card"><b>Los casos Bear/Bull no aplican a esta estrategia sistemática.</b><p class="muted">La señal y las reglas de rebalanceo determinan su evaluación; no se presenta como valoración fundamental.</p></div>`;
  }
  if(d.clasificacion){
    const cl = d.clasificacion||{};
    html += `<p><b>Categoría:</b> ${esc(cl.categoria||d.categoria)}${(cl.categorias_descartadas||[]).length?' <span class="muted">· descartadas: '+cl.categorias_descartadas.map(esc).join(', ')+'</span>':''}</p>`;
    if(cl.justificacion) html += `<p class="muted">${esc(cl.justificacion)}</p>`;
  }
  if(d.score_general!==null && d.score_general!==undefined) html += `<p><b>${d.evidence_review?.status==='systematic_report'?'Índice descriptivo de señal':'Score DDD'}:</b> <span class="score">${esc(d.score_general)}</span> · <b>Opinión:</b> ${esc(d.opinion_valoracion||'—')}${dddVerdict!=null?` · <b>Error de valoración:</b> <span class="${String(dddVerdict).toUpperCase()==='SI'?'pos':'neg'}">${esc(dddVerdict)}</span>`:''}</p>`;
  if(d.hipotesis?.length){
    html += `<h3>Hipótesis de inversión</h3><table><thead><tr><th>Hipótesis</th><th>Por qué</th><th>Predicción</th><th>Falsación</th><th>Cuándo abandonarla</th></tr></thead><tbody>`;
    d.hipotesis.forEach(h=>{
      const predictions=(h.predictions||[]).map(p=>`${p.prediction?`${esc(p.prediction)} · `:''}${esc(p.metric||'')}: ${esc(p.expected??'—')}${p.unit?` ${esc(p.unit)}`:''} · ${esc(p.deadline||'sin plazo')}`).join('<br>')||'—';
      const falsification=(h.falsification_conditions||[]).map(esc).join('<br>')||'—';
      html += `<tr><td>${esc(h.statement||'—')}</td><td>${esc(h.rationale||'—')}</td><td>${predictions}</td><td>${falsification}</td><td>${esc(h.review_trigger||'—')}</td></tr>`;
    });
    html += '</tbody></table>';
  }
  if(d.catalizadores?.length){
    html += `<h3>Catalizadores</h3><table><thead><tr><th>Catalizador</th><th>Horizonte</th><th>Impacto</th><th>Prob.</th></tr></thead><tbody>`;
    d.catalizadores.forEach(c=>html+=`<tr><td>${esc(c.descripcion)}</td><td>${esc(c.horizonte)}</td><td>${esc(c.impacto)}</td><td>${c.probabilidad_pct!=null?pct(c.probabilidad_pct):'—'}</td></tr>`);
    html += '</tbody></table>';
  }

  // Error de mercado
  const em = d.error_mercado||{};
  if(em.hipotesis_contraria || em.consenso_actual || em.razonamiento){
    html += `<h2>Error de mercado</h2>`;
    if(em.conclusion_error_valoracion) html += `<p><b>Conclusión:</b> <span class="${esc(em.conclusion_error_valoracion)?'':'neg'}">${esc(em.conclusion_error_valoracion)}</span></p>`;
    if(em.consenso_actual) {
      const consensus=em.consenso_actual;
      let consensusHtml=esc(consensus);
      if(typeof consensus==='object' && !Array.isArray(consensus)){
        const values=[['Media',consensus.mean],['Mediana',consensus.median],['Mínimo',consensus.low],['Máximo',consensus.high]]
          .filter(([,value])=>value!=null && Number.isFinite(Number(value)))
          .map(([label,value])=>`${esc(label)}: ${money(value)} ${esc(consensus.currency||'')}`);
        const sources=Array.isArray(consensus.sources)?consensus.sources.map(source=>
          source?.url?`<a href="${escAttr(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.name||'Fuente')}</a>${source.as_of_date?` · ${dt(source.as_of_date)}`:''}`:esc(source?.name||'Fuente')
        ).join('<br>'):'';
        consensusHtml=`${values.length?`<p>${values.join(' · ')}</p>`:'<p>Consenso estructurado disponible.</p>'}${sources?`<p class="muted">Fuentes:<br>${sources}</p>`:''}`;
      }
      html += `<div class="card"><div class="muted">Consenso del mercado</div>${consensusHtml}</div>`;
    }
    if(em.hipotesis_contraria) html += `<div class="card"><div class="muted">Hipótesis contraria</div><p>${esc(em.hipotesis_contraria)}</p></div>`;
    if(em.razonamiento) html += `<div class="card"><div class="muted">Razonamiento</div><p>${esc(em.razonamiento)}</p></div>`;
    if(em.catalizador_cambio?.descripcion) html += `<p><b>Catalizador de cambio:</b> ${esc(em.catalizador_cambio.descripcion)} <span class="muted">(${esc(em.catalizador_cambio.horizonte||'')} · impacto ${esc(em.catalizador_cambio.impacto||'')}${em.catalizador_cambio.probabilidad_pct!=null?' · '+pct(em.catalizador_cambio.probabilidad_pct):''})</span></p>`;
  }

  // Dominios
  const doms = d.dominios?.length ? d.dominios : Object.entries(d.ratings||{}).map(([k,v])=>({dominio:k,rating:v}));
  if(doms.length){
    html += `<h2>Dominios (DDD)</h2><table><thead><tr><th>Dominio</th><th>Rating</th><th>Análisis</th></tr></thead><tbody>`;
    doms.forEach(x=>html+=`<tr><td>${esc(x.dominio)}</td><td class="score">${esc(x.rating)}</td><td>${esc(x.analisis||'—')}</td></tr>`);
    html += '</tbody></table>';
  }

  // Acción requerida (si está en Buy List o Research)
  const actRow = by || {
    ticker: o.ticker,
    current_price: o.current_price,
    target_price: o.wyckoff?.price_target ?? null,
    buy_zone_top: null,
    wyckoff: o.wyckoff || null,
  };
  const actionFails = buylistEntryFails(actRow);
  const actionResolved = actionFails.length===0;
  html += `<h2>Indicador de acción</h2>`;
  html += (o.proposal?.status==='BLOCKED'
    ? `<div class="card"><b>Decisión bloqueada.</b> ${esc(o.proposal?.reason||'Evidencia incompleta o no vigente.')} La señal no autoriza una entrada.</div>`
    : o.proposal?.status==='PENDING_HUMAN_REVIEW'
    ? `<div class="card"><b>Decisión pendiente de revisión humana.</b> La señal no autoriza una entrada.</div>`
    : actionResolved
    ? `<div class="card" style="border-color:#1c4731"><b class="pos">Listo para entrada</b> — no hay condiciones fallidas frente a los umbrales de ENTRY.</div>`
    : `<div class="card" style="border-color:#3a2a10"><b class="neg">No listo para entrada</b> — condiciones fallidas:</div><ul>${actionFails.map(f=>`<li class="neg">${f}</li>`).join('')}</ul>`);
  html += detailsEntryThresholds();

  // Riesgos + evidencia
  if(d.riesgos?.length){ html += `<h2>Riesgos (DDD)</h2><ul>`; d.riesgos.forEach(r=>{const details=[r.probabilidad,r.impacto].filter(Boolean).map(esc).join(' · ');const description=r.descripcion&&r.descripcion!==r.riesgo?` <span class="muted">${esc(r.descripcion)}</span>`:'';html+=`<li><b>${esc(r.riesgo||'Riesgo')}</b>${description}${details?` <span class="muted">(${details})</span>`:''}</li>`;}); html += '</ul>'; }
  if(d.evidencia?.hechos_verificados?.length){ html += `<h3>Hechos verificados</h3><ul>`; d.evidencia.hechos_verificados.forEach(x=>html+=`<li>${esc(x)}</li>`); html += '</ul>'; }
  if(d.evidencia?.inferencias_llm?.length){ html += `<h3>Inferencias LLM</h3><ul>`; d.evidencia.inferencias_llm.forEach(x=>html+=`<li>${esc(x)}</li>`); html += '</ul>'; }
  if(d.evidencia?.preguntas_abiertas?.length){ html += `<h3>Preguntas abiertas</h3><ul>`; d.evidencia.preguntas_abiertas.forEach(x=>html+=`<li>${esc(x)}</li>`); html += '</ul>'; }
  }

  // Decisión del board + scores
  html += `<h2>Decisión del board</h2>`;
  if(o.decision?.justification) html += `<p class="muted">Justificación: ${esc(o.decision.justification)}</p>`;
  if((o.proposal?.rules_passed||[]).length) html += `<p>Reglas superadas: ${o.proposal.rules_passed.map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</p>`;
  if((o.proposal?.rules_failed||[]).length) html += `<p class="neg">Reglas falladas: ${o.proposal.rules_failed.map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</p>`;
  const ruleDetails=o.proposal?.rules_details||{};
  const asymmetryRuleState=(o.proposal?.rules_passed||[]).includes('RULE-008')?'superó':(o.proposal?.rules_failed||[]).includes('RULE-008')?'falló':null;
  if(asymmetryRuleState){
    html += `<div class="card"><b>Asimetría del modelo (RULE-008 · ${asymmetryRuleState})</b>${ruleDetails['RULE-008']?`<p>${esc(ruleDetails['RULE-008'])}</p>`:'<p class="muted">El detalle cuantitativo no fue persistido en esta evaluación.</p>'}<p class="muted">B/R compara el upside Bull con el downside Bear sin ponderación probabilística. Validar los casos, fuentes y fechas junto con la tesis; el ratio por sí solo no autoriza una compra.</p></div>`;
  }
  const explainedRules=[...(o.proposal?.rules_passed||[]),...(o.proposal?.rules_failed||[])].filter(id=>ruleDetails[id]);
  if(explainedRules.length) html += `<details><summary>Detalles de reglas</summary><ul>${[...new Set(explainedRules)].map(id=>`<li><b>${esc(id)}</b>: ${esc(ruleDetails[id])}</li>`).join('')}</ul></details>`;
  html += `<table><thead><tr><th>Engine</th><th>Score</th><th>Assessment</th><th>Findings</th></tr></thead><tbody>`;
  Object.entries(o.scores||{}).forEach(([k,v])=>html+=`<tr><td>${esc(k)}</td><td class="score">${v??'—'}</td><td>${esc(o.assessment_recommendations?.[k]||'Not recorded')}</td><td>${(o.findings?.[k]||[]).map(esc).join(' · ')||'—'}</td></tr>`);
  html += '</tbody></table>';

  // Wyckoff
  if(o.wyckoff){
    html += `<h2>Wyckoff (último análisis)</h2><table><thead><tr><th>Fase</th><th>Score</th><th>Confianza</th><th>Precio</th><th>Entry point</th><th>Target</th><th>Triggered</th></tr></thead><tbody>`;
    html += `<tr><td>${wyPhase(o.wyckoff.phase)}</td><td>${esc(o.wyckoff.score)}</td><td>${esc(o.wyckoff.confidence)}</td><td>${money(o.wyckoff.current_price)}</td><td>${esc(o.wyckoff.entry_point)}</td><td>${money(o.wyckoff.price_target)}</td><td>${o.wyckoff.triggered_entry?'<span class="pos">sí</span>':'no'}</td></tr></tbody></table>`;
    html += `<p class="muted">Analizado: ${dt(o.wyckoff.analyzed_at)}</p>`;
  }
  html += `<p><a href="wiki/${esc(o.ticker)}.html">Abrir wiki completa de ${esc(o.ticker)}</a></p>`;
  setView('case', html);
}
function showOppFromBuylist(oppId, ticker){ if(oppId){ showCase(oppId); } else { showCase(ticker); } }
function showCaseFromPos(oppId, ticker){ if(oppId){ showCase(oppId); } else { showCase(ticker); } }
function showCaseFromOpp(oppId, ticker){
  if(oppId && DATA.opportunities.some(o=>o.opp_id===oppId)){ showCase(oppId); return; }
  const byTicker = DATA.opportunities.filter(o=>o.ticker===ticker);
  if(byTicker.length) showCase(byTicker[0].opp_id); else showCase(ticker);
}

function setView(id, html){ document.getElementById('view').innerHTML = `<div id="${id}">${html}</div>`; }


boot();
"""

INDEX_TPL = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IDOS — Investment Decision Operating System</title>
<link rel="stylesheet" href="assets/style.css?v=GENV">
</head>
<body>
<div class="wrap">
<h1>IDOS <span class="muted">· Family Office</span></h1>
<div class="tabs" id="tabs"></div>
<div id="view"></div>
<hr style="border-color:var(--border);margin:24px 0 12px">
<p class="muted">Generado <span id="gen-at" data-v="GENV"></span></p>
</div>
<script src="assets/app.js?v=GENV"></script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_site(base_path: Path, out_dir: Path | None = None, stale_days: int = DEFAULT_STALE_DAYS) -> Path:
    builder = SiteBuilder(base_path, stale_days=stale_days)
    data = builder.build()

    out = out_dir or base_path / "site"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "wiki").mkdir(parents=True, exist_ok=True)
    (out / "learning.html").unlink(missing_ok=True)

    (out / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (out / "assets" / "app.js").write_text(
        f"const DISC_MIN_SCORE = {builder.disc_min_score};\n"
        f"const ENTRY_RULES = {json.dumps(builder.entry_rules, ensure_ascii=False)};\n"
        f"const ENTRY_CFG = {json.dumps(builder.entry_cfg, ensure_ascii=False)};\n"
        + APP_JS, encoding="utf-8"
    )
    (out / "data.json").write_text(
        json.dumps(_to_jsonable(data), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )

    genv = data.generated_at[:16].replace(" ", "_")
    index_html = (
        INDEX_TPL.replace("GENV", genv)
        .replace('<span id="gen-at" data-v="' + genv + '"></span>',
                 f'<span id="gen-at" data-v="{genv}">{data.generated_at[:16]}</span>')
    )
    (out / "index.html").write_text(index_html, encoding="utf-8")

    # wiki pages
    for w in data.wiki:
        comp = data.companies.get(w["ticker"]) or {}
        sections = []
        for f in builder._wiki_files(w["ticker"]):
            title = f.stem
            md = f.read_text(encoding="utf-8", errors="replace")
            sections.append((title, markdown_to_html(md)))
        if not sections:
            sections = [("Wiki", "<p class='muted'>Sin contenido de wiki todavía.</p>")]
        (out / "wiki" / f"{w['ticker']}.html").write_text(
            render_wiki_page(w["ticker"], comp, sections), encoding="utf-8"
        )

    wiki_index_body = ['<div class="wrap"><a class="back" href="../index.html">&larr; Dashboard</a>',
                       "<h1>Wiki — índice</h1><table><thead><tr><th>Ticker</th><th>Nombre</th><th>Sector</th></tr></thead><tbody>"]
    for w in data.wiki:
        wiki_index_body.append(f"<tr><td><a href='{w['ticker']}.html'><b>{w['ticker']}</b></a></td><td>{w.get('name') or '—'}</td><td>{w.get('sector') or '—'}</td></tr>")
    wiki_index_body.append("</tbody></table></div>")
    (out / "wiki" / "index.html").write_text(PAGE_TPL.format(title="Wiki", body="\n".join(wiki_index_body)), encoding="utf-8")


    (out / ".nojekyll").write_text("", encoding="utf-8")

    return out


def _to_jsonable(data: SiteData) -> dict:
    d = data.__dict__
    for k in ("companies",):
        d[k] = {tk: c for tk, c in data.companies.items()}
    return _sanitize_json(d)


def _sanitize_json(obj):
    """Recursively drop NaN/Infinity (invalid JSON) so the UI never fails to parse."""
    import math
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    stale = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_STALE_DAYS
    out = write_site(base, stale_days=stale)
    print(f"[site] Built {out} ({len(_to_jsonable(SiteBuilder(base).build()).get('opportunities', []))} opps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

