"""Builds a static HTML site from IDOS journal/knowledge artifacts.

Read-only against the repo (YAML/MD) plus the daily price cache in SQLite.
Output: `site/index.html`, `site/data.json`, `site/wiki/*.html`,
`site/assets/app.js`, `site/assets/style.css`.

The site is a single-page app with tabs:
  Dashboard · Discovery · Research · Buy List · Portfolio · Learning

No server required: publish `site/` to GitHub Pages.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Iterable

import yaml

from idos.timezone import AR_TZ


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_STALE_DAYS = 30

STATUS_ACTIVE = {
    "DISCOVERED", "SCREENED", "WATCHLIST", "UNDER_RESEARCH", "UNDER_DEEP_DD",
    "APPROVED", "ENTRY_PENDING", "ACCUMULATING", "FULL_POSITION", "MONITORING",
    "REDUCING",
}
STATUS_CLOSED = {"EXITED", "POST_MORTEM", "ARCHIVED"}

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


class SiteBuilder:
    def __init__(self, base_path: Path, stale_days: int = DEFAULT_STALE_DAYS):
        self.base = base_path
        self.journal = base_path / "idos-journal"
        self.knowledge = base_path / "idos-knowledge"
        self.config = base_path / "idos-config"
        self.db_path = base_path / "idos.db"
        self.cache = base_path / "cache"
        self.stale_days = stale_days
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
            if prices and prices[-1]:
                return {"price": round(float(prices[-1]), 2), "date": dates[-1] if dates else None}
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
        ddd = _load_yaml(opp_dir / "ddd_report.yml")
        ddd = ddd if isinstance(ddd, dict) else {}

        scores: dict[str, Any] = {}
        findings: dict[str, list[str]] = {}
        for engine, spec in (dp.get("assessments") or {}).items():
            if isinstance(spec, dict):
                scores[engine] = spec.get("score")
                findings[engine] = [
                    f.get("detail") or f"{f.get('dimension','')} {f.get('level','')}".strip()
                    for f in (spec.get("findings") or []) if isinstance(f, dict)
                ]

        conv = opp.get("conviction") or {}
        scores_conv = conv.get("scores") or {}
        # Real scores live in decision_proposal; opportunity.yml often has zeros.
        final_scores = {k: (v if v else scores.get(k)) for k, v in scores_conv.items()}
        final_scores.update({k: v for k, v in scores.items() if k not in final_scores})

        current_price = opp.get("current_price")
        intrinsic = opp.get("intrinsic_value")
        mkt = self._market_price(ticker)
        market_price = mkt["price"]
        price_date = mkt["date"]
        if market_price:
            current_price = market_price
        upside = None
        if current_price and intrinsic and current_price > 0:
            upside = round((intrinsic - current_price) / current_price * 100, 1)

        # last research date: prefer decision_proposal.generated_at
        last_research = dp.get("generated_at") or opp.get("updated_at") or opp.get("created_at")
        last_research_dt = _parse_dt(last_research)
        stale_days = None
        if last_research_dt:
            stale_days = max(0, (datetime.now(AR_TZ).replace(tzinfo=None) - last_research_dt.replace(tzinfo=None)).days)

        # ddd report summary
        ddd_summary = {
            "categoria": None,
            "ratings": {},
            "riesgos": [],
        }
        if ddd:
            cls = ddd.get("clasificacion_oportunidad") or {}
            ddd_summary["categoria"] = cls.get("categoria")
            for dom, val in ddd.items():
                if isinstance(val, dict) and "rating" in val and dom.startswith("dominio_"):
                    ddd_summary["ratings"][dom.replace("dominio_", "")] = val["rating"]
            ddd_summary["riesgos"] = [
                {"riesgo": r.get("riesgo"), "probabilidad": r.get("probabilidad"), "impacto": r.get("impacto")}
                for r in (ddd.get("dominio_riesgos") or []) if isinstance(r, dict)
            ]

        return {
            "opp_id": opp.get("id") or opp_dir.name,
            "ticker": ticker,
            "status": opp.get("status", "UNKNOWN"),
            "conviction_overall": conv.get("overall"),
            "confidence": conv.get("confidence"),
            "trend": conv.get("trend"),
            "scores": final_scores,
            "findings": findings,
            "current_price": current_price,
            "intrinsic_value": intrinsic,
            "upside_pct": upside,
            "price_date": price_date,
            "created_at": opp.get("created_at"),
            "updated_at": opp.get("updated_at"),
            "last_research": last_research,
            "stale_days": stale_days,
            "is_stale": bool(stale_days is not None and stale_days > self.stale_days),
            "decision": {
                "approved": br.get("approved"),
                "decision_type": br.get("decision_type"),
                "decision_id": br.get("decision_id"),
                "justification": br.get("justification"),
                "author": br.get("author"),
            },
            "proposal": {
                "recommendation": dp.get("recommendation"),
                "conviction_score": dp.get("conviction_score"),
                "rules_passed": dp.get("rules_passed") or [],
                "rules_failed": dp.get("rules_failed") or [],
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
                    if o:
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
            intrinsic = e.get("target_price") or (opp or {}).get("intrinsic_value") or 0
            current = mkt["price"] or price["price"] or (opp or {}).get("current_price")
            price_date = mkt["date"] or price["date"]
            buy_zone = e.get("buy_zone_top")
            if not buy_zone and intrinsic:
                buy_zone = round(intrinsic * 0.7070, 2)
            target = e.get("target_price") or intrinsic
            out.append({
                "ticker": e.get("ticker"),
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
                "industry": (self.companies.get((e.get("ticker") or "").upper()) or {}).get("industry"),
                "wyckoff": wyckoff,
            })
        return out

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

    # -- scout metric breakdown (recompute from cache, mirrors ScoutEngine) --
    def _scout_num(self, v: Any, default: float = 0.0) -> float:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", "").replace("$", "").replace("%", ""))
            except (ValueError, TypeError):
                pass
        return default

    def _scout_metrics(self, ticker: str) -> dict[str, Any]:
        cache_file = self.base / "cache" / f"{ticker}.json"
        raw: dict[str, Any] = {}
        if cache_file.exists():
            try:
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        if not raw:
            return {"size_score": None, "liquidity_score": None,
                    "momentum_score": None, "value_score": None, "quality_score": None}

        metrics = {
            "market_cap": self._scout_num(raw.get("market_cap")),
            "avg_volume": self._scout_num(raw.get("volume_avg")) or self._scout_num(raw.get("avg_volume")),
            "pe_ratio": self._scout_num(raw.get("pe_ratio_ttm")) or self._scout_num(raw.get("pe_ratio")),
            "ev_ebitda": self._scout_num(raw.get("ev_ebitda")),
            "roic": self._scout_num(raw.get("roic_pct")),
            "operating_margin": self._scout_num(raw.get("operating_margin_pct")),
            "debt_to_equity": self._scout_num(raw.get("debt_equity_ratio")),
            "revenue_growth": self._scout_num(raw.get("revenue_growth_pct")),
        }

        # momentum from price history (approx 3m / 12m trading days)
        ph = raw.get("price_history") if isinstance(raw.get("price_history"), list) else []
        if len(ph) >= 2 and ph[-1]:
            n = len(ph)
            # last close vs ~64 trading days ago (3m) and n ago relative (12m)
            base3 = ph[n-64] if n >= 64 else ph[0]
            base12 = ph[0]
            chg3 = (ph[-1] - base3) / base3 * 100 if base3 else 0.0
            chg12 = (ph[-1] - base12) / base12 * 100 if base12 else 0.0
            metrics["price_change_3m"] = chg3
            metrics["price_change_12m"] = chg12

        # reuse the exact ScoutEngine scorer
        from idos.discovery.scout import ScoutEngine
        res = ScoutEngine(min_score=0).scan(ticker=ticker, data={"metrics": metrics})
        return res.details

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

    # -- positions / portfolio / ledger --
    def _load_positions(self) -> list[dict]:
        pos_dir = self.journal / "paper" / "positions"
        if not pos_dir.exists():
            return []
        out = []
        for f in sorted(pos_dir.glob("*.yml")):
            data = _load_yaml(f)
            if not isinstance(data, dict):
                continue
            ticker = data.get("ticker") or f.stem
            entry = data.get("entry_price") or 0
            qty = data.get("quantity") or 0
            mkt = self._market_price(ticker)
            price = self.price_for(ticker)
            cp = mkt["price"] or price["price"]
            price_date = mkt["date"] or price["date"]
            current_value = None
            if cp and qty:
                current_value = round(cp * qty, 2)
            else:
                current_value = data.get("current_value")
            pl_pct = pl_usd = None
            if cp and entry and entry > 0:
                pl_pct = round((cp - entry) / entry * 100, 2)
                pl_usd = round((cp - entry) * qty, 2)
            stop = data.get("stop_loss")
            target = data.get("target_price")
            out.append({
                "ticker": ticker,
                "opp_id": data.get("opp_id"),
                "quantity": qty,
                "entry_price": entry,
                "entry_date": data.get("entry_date"),
                "total_invested": data.get("total_invested"),
                "current_value": current_value,
                "current_price": cp,
                "price_date": price_date,
                "stop_loss": stop,
                "target_price": target,
                "conviction_at_entry": data.get("conviction_at_entry"),
                "pl_pct": pl_pct,
                "pl_usd": pl_usd,
                "dist_to_stop_pct": round((cp - stop) / stop * 100, 1) if (cp and stop) else None,
                "dist_to_target_pct": round((target - cp) / cp * 100, 1) if (cp and target) else None,
            })
        return out

    def _load_ledger(self) -> list[dict]:
        ledger_dir = self.journal / "paper" / "ledger"
        out = []
        for f in sorted(ledger_dir.glob("*.yml")):
            data = _load_yaml(f)
            if isinstance(data, list):
                out.extend(d for d in data if isinstance(d, dict))
        return sorted(out, key=lambda t: t.get("date") or "", reverse=True)

    def _compute_portfolio(self, positions: list[dict]) -> dict:
        total_value = sum(p.get("current_value") or p.get("total_invested") or 0 for p in positions)
        total_invested = sum(p.get("total_invested") or 0 for p in positions)
        pl_total = total_value - total_invested
        sector_map: dict[str, float] = {}
        for p in positions:
            comp = self.companies.get(p["ticker"]) or {}
            sector = comp.get("sector") or "Otros"
            sector_map[sector] = sector_map.get(sector, 0) + (p.get("current_value") or 0)
        sector_top = None
        if sector_map:
            sector_top = max(sector_map.items(), key=lambda x: x[1])
            sector_top = {"sector": sector_top[0], "value": round(sector_top[1], 2),
                          "pct": round(sector_top[1] / total_value * 100, 1) if total_value else None}
        return {
            "total_value": round(total_value, 2),
            "total_invested": round(total_invested, 2),
            "total_pl_usd": round(pl_total, 2),
            "total_pl_pct": round(pl_total / total_invested * 100, 2) if total_invested else None,
            "positions_count": len(positions),
            "sector_top": sector_top,
            "sectors": sector_map,
        }

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

    # -- learning (post-mortems) --
    def _load_learning(self) -> list[dict]:
        companies_dir = self.journal / "companies"
        if not companies_dir.exists():
            return []
        out = []
        for ticker_dir in sorted(companies_dir.iterdir()):
            if not ticker_dir.is_dir() or not _is_valid_ticker(ticker_dir.name):
                continue
            opps_dir = ticker_dir / "case_file" / "opportunities"
            if not opps_dir.exists():
                continue
            for opp_dir in sorted(opps_dir.iterdir()):
                if not opp_dir.is_dir():
                    continue
                pm_dir = opp_dir / "post_mortem"
                if not pm_dir.exists():
                    continue
                for pm in sorted(pm_dir.glob("*.yml")):
                    data = _load_yaml(pm)
                    if not isinstance(data, dict):
                        continue
                    analysis = data.get("analysis") or {}
                    if isinstance(analysis, str):
                        try:
                            analysis = json.loads(analysis)
                        except Exception:
                            analysis = {"exit_analysis": analysis}
                    out.append({
                        "ticker": ticker_dir.name,
                        "opp_id": data.get("opp_id"),
                        "exit_reason": data.get("exit_reason"),
                        "generated_at": data.get("generated_at"),
                        "analysis": analysis if isinstance(analysis, dict) else {"raw": str(analysis)},
                    })
        return sorted(out, key=lambda l: l.get("generated_at") or "", reverse=True)

    # -- dashboard --
    def _build_dashboard(self, opps: list[dict], positions: list[dict],
                         buylist: list[dict], learning: list[dict]) -> dict:
        funnel: dict[str, int] = {}
        for o in opps:
            funnel[o["status"]] = funnel.get(o["status"], 0) + 1

        stale = [o for o in opps if o.get("is_stale")]
        alerts = [
            {"severity": "warn", "ticker": o["ticker"], "message": f"Research stale ({o.get('stale_days')}d sin actualizar)"}
            for o in stale
        ]
        for p in positions:
            if p.get("dist_to_stop_pct") is not None and p["dist_to_stop_pct"] <= 5:
                alerts.append({"severity": "high", "ticker": p["ticker"],
                               "message": f"Precio a {abs(p['dist_to_stop_pct']):.1f}% del stop loss"})
        for o in opps:
            if o.get("trend") == "DETERIORATING":
                alerts.append({"severity": "warn", "ticker": o["ticker"],
                               "message": "Convicción deteriorándose"})
        # suggested actions
        actions = []
        for o in opps:
            if o["status"] == "APPROVED":
                wy = o.get("wyckoff") or {}
                in_zone = bool(o.get("current_price") and o.get("intrinsic_value")
                               and o["current_price"] <= o["intrinsic_value"])
                actions.append({
                    "action": "BUY", "ticker": o["ticker"], "opp_id": o["opp_id"],
                    "conviction": o.get("conviction_overall"),
                    "detail": "Approved + en/por debajo de valor intrínseco" if in_zone else "Approved (valoración a vigilar)",
                    "wyckoff_phase": wy.get("phase"), "wyckoff_score": wy.get("score"),
                    "triggered_entry": wy.get("triggered_entry", False),
                })
        for p in positions:
            if p.get("dist_to_stop_pct") is not None and p["dist_to_stop_pct"] <= 5:
                actions.append({"action": "EXIT_WATCH", "ticker": p["ticker"],
                                "detail": f"Próximo a stop ({p['dist_to_stop_pct']:.1f}%)"})
        for l in learning:
            analysis = l.get("analysis") or {}
            if not analysis.get("would_invest_again", True):
                actions.append({"action": "LEARNING", "ticker": l["ticker"],
                                "detail": "Post-mortem: no re-invertir"})

        return {
            "funnel": funnel,
            "alerts": alerts,
            "actions": actions,
            "stats": {
                "active": len([o for o in opps if o["status"] in STATUS_ACTIVE]),
                "closed": len([o for o in opps if o["status"] in STATUS_CLOSED]),
                "positions": len(positions),
                "buylist": len(buylist),
                "learning": len(learning),
            },
        }

    # -- main build --
    def build(self) -> SiteData:
        ui_cfg = _load_yaml(self.config / "ui.yml")
        if isinstance(ui_cfg, dict):
            self.stale_days = int(ui_cfg.get("stale_days", self.stale_days))

        self.companies = self._load_companies()
        opps = self._load_opportunities()
        opps = self._attach_wyckoff(opps)
        buylist = self._load_buylist()
        watchlist = self._load_watchlist()
        positions = self._load_positions()
        ledger = self._load_ledger()
        wiki = self._load_wiki_index()
        learning = self._load_learning()
        portfolio = self._compute_portfolio(positions)
        dashboard = self._build_dashboard(opps, positions, buylist, learning)

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


def render_learning_page() -> str:
    body = ['<div class="wrap"><a class="back" href="index.html">&larr; Dashboard</a>',
            "<h1>Learning — Post-mortems</h1>",
            '<div id="learning-root"></div></div>',
            '<script src="assets/app.js"></script>',
            '<script>renderLearningPage();</script>']
    return PAGE_TPL.format(title="Learning", body="\n".join(body))


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
.back{color:var(--muted);font-size:13px}
.yaml{white-space:pre-wrap}
@media(max-width:720px){.wrap{padding:12px}.tabs{flex-direction:column}}
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
function wyPhase(p){ if(!p) return '—'; return `<span style="color:${colors[p]||'var(--muted)'}">${esc(p)}</span>`; }

function renderShell(){
  document.getElementById('tabs').innerHTML = [
    ['dashboard','Dashboard'],['screening','Discovery'],['opp','Research'],['buylist','Buy List'],['portfolio','Portfolio'],
    ['learning','Learning']
  ].map(([id,l])=>`<button class="tab" data-view="${id}">${l}</button>`).join('');
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{ document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); b.classList.add('active'); renderView(b.dataset.view); });
}

function renderAll(){ renderView('dashboard'); }

function renderView(id){
  id = id || 'dashboard';
  if(id==='dashboard') return renderDashboard();
  if(id==='opp') return renderOpp();
  if(id==='buylist') return renderBuylist();
  if(id==='portfolio') return renderPortfolio();
  if(id==='screening') return renderScreening();
  if(id==='learning') return renderLearning();
  renderDashboard();
}

// ---------- Dashboard ----------
function renderDashboard(){
  const d = DATA.dashboard;
  let html = '<div class="grid">';
  const cards = [['Activas', d.stats.active],['Cerradas', d.stats.closed],['Posiciones', d.stats.positions],['Buy List', d.stats.buylist],['Post-mortems', d.stats.learning]];
  cards.forEach(([k,v])=>html+=`<div class="card"><div class="muted">${k}</div><div style="font-size:26px;font-weight:700">${v}</div></div>`);
  html += '</div>';
  html += '<h2>Funnel de oportunidades</h2><table><thead><tr><th>Estado</th><th>Cantidad</th></tr></thead><tbody>';
  Object.entries(d.funnel).sort((a,b)=>b[1]-a[1]).forEach(([k,v])=>html+=`<tr><td>${badge(k)}</td><td>${v}</td></tr>`);
  html += '</tbody></table>';
  html += '<h2>Acciones sugeridas</h2>';
  if(!d.actions.length) html += '<p class="muted">Sin acciones pendientes.</p>';
  d.actions.forEach(a=>{
    const c = a.action==='BUY'?'pos':a.action==='LEARNING'?'':'neg';
    html += `<div class="alert ${a.action==='EXIT_WATCH'?'high':''}"><b class="${c}">${esc(a.action)}</b> <b>${esc(a.ticker)}</b> — ${esc(a.detail)}`+
      (a.wyckoff_phase?` <span class="muted">· wyckoff ${wyPhase(a.wyckoff_phase)} (${esc(a.wyckoff_score)})</span>`:'')+
      (a.triggered_entry?` <span class="badge" style="background:#102a1d;color:#4ade80">condiciones de entrada cumplidas</span>`:'')+
      `</div>`;
  });
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
  const rows = DATA.opportunities.filter(o=>o.status==='UNDER_DEEP_DD')
    .sort((a,b)=>(b.conviction_overall??-1)-(a.conviction_overall??-1));
  let html = `<h2>Research (${rows.length})</h2>`;
  html += `<p class="muted">Oportunidades en <b>Research / UNDER_DEEP_DD</b>: casos que superaron el umbral de Discovery (<b>≥ ${DISC_MIN_SCORE}</b>) y fueron promovidos automáticamente. Aquí se ejecuta la due diligence en profundidad (DDD, assessments, valuation y risk). Hacé clic en un ticker para ver el detalle completo del activo. Ordenadas por convicción, de mayor a menor.</p>`;
  html += `<p class="muted">Estados siguientes (automatizados): el worker de Decision Board evalúa el caso y lo pasa a <b>APPROVED</b> (aprobado para entrada) o a <b>WATCHLIST</b> (rechazado) según las reglas de entrada. La transición es automática; no hay umbral numérico fijo.</p>`;
  html += detailsEntryRules();
  html += `<input id="opp-search" placeholder="Buscar ticker..." style="margin:8px 0">`;
  html += `<table><thead><tr><th>Ticker</th><th>Conv.</th><th>Business</th><th>Valuation</th><th>Risk</th><th>Recovery</th><th>Precio</th><th>Intrínseco</th><th>Upside</th><th>Rules failed</th><th>Última inv.</th></tr></thead><tbody>`;
  rows.forEach(o=>{
    html += `<tr style="cursor:pointer" onclick="showCase('${o.opp_id}')">
      <td><b>${esc(o.ticker)}</b></td>
      <td>${o.conviction_overall??'—'}</td>
      <td>${o.scores?.BusinessAssessmentEngine??'—'}</td><td>${o.scores?.ValuationAssessmentEngine??'—'}</td>
      <td>${o.scores?.RiskAssessmentEngine??'—'}</td><td>${o.scores?.RecoveryAssessmentEngine??'—'}</td>
      <td>${money(o.current_price)}</td><td>${money(o.intrinsic_value)}</td>
      <td class="${o.upside_pct>=0?'pos':'neg'}">${pct(o.upside_pct,true)}</td>
      <td>${rulesBadge(o.proposal?.rules_failed)}</td>
      <td>${dt(o.last_research)} ${staleBadge(o)}</td></tr>`;
  });
  html += '</tbody></table>';
  setView('opp', html);
  document.getElementById('opp-search').oninput = e=>{
    const q=e.target.value.toLowerCase();
    document.querySelectorAll('#opp tbody tr').forEach(tr=>tr.style.display=tr.textContent.toLowerCase().includes(q)?'':'none');
  };
}

// ---------- Buy List ----------
function renderBuylist(){
  const rows = DATA.buylist.slice().sort((a,b)=>((b.wyckoff?.score)??-1)-((a.wyckoff?.score)??-1));
  let html = `<h2>Buy List (${rows.length})</h2>`;
  html += `<p class="muted">Activos <b>APPROVED</b> listos para entrada (siguiente paso: <b>ENTRY_PENDING</b>). Ordenadas por score Wyckoff descendente.</p>`;
  html += detailsEntryThresholds();
  if(!rows.length) html += `<div class="card"><p class="muted">La Buy List está vacía.</p></div>`;
  html += `<table><thead><tr><th>Ticker</th><th>Industria</th><th>Conv.</th><th>Último precio</th><th>Zona compra (top)</th><th>Target</th><th>Margen a target</th><th>Wyckoff</th><th>Cond. fallida</th><th>Últ. análisis</th></tr></thead><tbody>`;
  rows.forEach(r=>{
    const margin = (r.current_price&&r.target_price&&r.target_price>0)? (r.target_price-r.current_price)/r.current_price*100 : null;
    const wy = r.wyckoff;
    const fails = buylistEntryFails(r);
    html += `<tr style="cursor:pointer" onclick="showOppFromBuylist('${r.opp_id||''}','${r.ticker}')">
      <td><b>${esc(r.ticker)}</b></td><td class="muted">${esc(r.industry||'—')}</td><td>${r.conviction_score??'—'}</td>
      <td>${money(r.current_price)}</td><td>${money(r.buy_zone_top)}</td><td>${money(r.target_price)}</td>
      <td class="${margin>=0?'pos':'neg'}">${pct(margin,true)}</td>
      <td>${wyPhase(wy?.phase)} ${wy?.score??''}</td><td>${fails.length?fails.map(f=>`<span class="badge" style="background:#2a1516;color:#f87171">${f}</span>`).join(' '):'<span class="pos">Listo</span>'}</td>
      <td>${dt(wy?.analyzed_at)}</td></tr>`;
  });
  html += '</tbody></table>';
  setView('buylist', html);
}

// ---------- Portfolio ----------
function renderPortfolio(){
  const pf = DATA.portfolio;
  let html = '<div class="grid">';
  html += `<div class="card"><div class="muted">Valor total</div><div style="font-size:24px;font-weight:700">${money(pf.total_value)}</div></div>`;
  html += `<div class="card"><div class="muted">P/L portfolio</div><div style="font-size:24px;font-weight:700" class="${pf.total_pl_usd>=0?'pos':'neg'}">${money(pf.total_pl_usd)} (${pct(pf.total_pl_pct,true)})</div></div>`;
  html += `<div class="card"><div class="muted">Posiciones</div><div style="font-size:24px;font-weight:700">${pf.positions_count}</div></div>`;
  html += `<div class="card"><div class="muted">Sector top</div><div style="font-size:18px;font-weight:700">${esc(pf.sector_top?.sector||'—')} ${pf.sector_top?('('+fmt(pf.sector_top.pct,1)+'%)'):''}</div></div>`;
  html += '</div>';
  html += `<h2>Activos</h2><table><thead><tr><th>Ticker</th><th>Peso</th><th>Cant</th><th>Entry</th><th>Último</th><th>P/L %</th><th>P/L $</th><th>Stop (dist)</th><th>Target</th></tr></thead><tbody>`;
  const total = pf.total_value||0;
  DATA.positions.forEach(p=>{
    const weight = total? (p.current_value||0)/total*100 : null;
    html += `<tr style="cursor:pointer" onclick="showCaseFromPos('${p.opp_id||''}','${p.ticker}')">
      <td><b>${esc(p.ticker)}</b></td><td>${weight!==null?fmt(weight,1)+'%':'—'}</td>
      <td>${p.quantity??'—'}</td><td>${money(p.entry_price)}</td><td>${money(p.current_price)}</td>
      <td class="${p.pl_pct>=0?'pos':'neg'}">${pct(p.pl_pct,true)}</td><td class="${p.pl_usd>=0?'pos':'neg'}">${money(p.pl_usd)}</td>
      <td>${money(p.stop_loss)} ${p.dist_to_stop_pct!==null?`(${fmt(p.dist_to_stop_pct,1)}%)`:''}</td>
      <td>${money(p.target_price)} ${p.dist_to_target_pct!==null?`(${fmt(p.dist_to_target_pct,1)}%)`:''}</td></tr>`;
  });
  html += '</tbody></table>';
  html += '<h2>Sectores</h2><table><thead><tr><th>Sector</th><th>Valor</th></tr></thead><tbody>';
  Object.entries(pf.sectors||{}).forEach(([k,v])=>html+=`<tr><td>${esc(k)}</td><td>${money(v)}</td></tr>`);
  html += '</tbody></table>';
  setView('portfolio', html);
}

// ---------- Screening Watchlist ----------
// ---------- Discovery ----------
function renderScreening(){
  const rows = DATA.watchlist;
  let html = `<h2>Discovery (${rows.length})</h2>`;
  html += `<p class="muted">Candidatos del Discovery Domain (Scout), primer estado del funnel. La promoción es automática por el pipeline mensual: si el score de screening es <b>≥ ${DISC_MIN_SCORE}</b> (umbral <code>scoring.min_opportunity_score</code>), el caso pasa solo a <b>Research / UNDER_DEEP_DD</b>, sin aprobación manual. El score global es el promedio de las 5 métricas del Scout.</p>`;
  html += `<table><thead><tr><th>Ticker</th><th>Score</th>${mcolHeaders()}<th>Agregado</th></tr></thead><tbody>`;
  rows.forEach(r=>html+=`<tr><td><b>${esc(r.ticker)}</b></td><td><b class="${r.score>=70?'pos':''}">${r.score??'—'}</b></td>${mcolCells(r.metrics)}<td>${dt(r.added_at)}</td></tr>`);
  html += '</tbody></table>';
  setView('screening', html);
}
function mcolHeaders(){ return `<th>Size</th><th>Liquidez</th><th>Momentum</th><th>Valor</th><th>Calidad</th>`; }
function mcolCells(met){ const k=['size_score','liquidity_score','momentum_score','value_score','quality_score']; return k.map(m=>{ const v=met?met[m]:null; return `<td class="${v>=70?'pos':''}">${v??'—'}</td>`; }).join(''); }

// ---------- Wiki ----------
// ---------- Learning ----------
function renderLearning(){
  const rows = DATA.learning;
  let html = `<h2>Learning — Post-mortems (${rows.length})</h2>`;
  if(!rows.length) html += `<div class="card"><p class="muted">Aún no hay post-mortems. Cuando una oportunidad se cierre (EXITED → POST_MORTEM) aparecerá aquí el análisis, lecciones y ajustes.</p></div>`;
  rows.forEach(l=>{
    const a = l.analysis||{};
    html += `<details class="details"><summary><b>${esc(l.ticker)}</b> · ${esc(l.opp_id)} · <span class="muted">${esc(l.exit_reason)}</span> · ${dt(l.generated_at)}</summary>`;
    html += `<p><b>¿La tesis fue correcta?</b> ${a.thesis_was_correct===true?'Sí':a.thesis_was_correct===false?'No':'—'}</p>`;
    if(a.exit_analysis) html += `<p><b>Análisis:</b> ${esc(a.exit_analysis)}</p>`;
    if(a.lessons_learned?.length) html += `<p><b>Lecciones:</b></p><ul>${a.lessons_learned.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
    if(a.what_went_wrong?.length) html += `<p><b>Qué salió mal:</b></p><ul>${a.what_went_wrong.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
    if(a.what_went_right?.length) html += `<p><b>Qué salió bien:</b></p><ul>${a.what_went_right.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
    if(a.biases_detected?.length) html += `<p><b>Sesgos:</b> ${a.biases_detected.map(esc).join(', ')}</p>`;
    if(a.methodological_errors?.length) html += `<p><b>Errores metodológicos:</b></p><ul>${a.methodological_errors.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
    html += `<p><b>Re-invertiría:</b> ${a.would_invest_again===true?'Sí':a.would_invest_again===false?'No':'—'}</p>`;
    if(a.wyckoff_accuracy) html += `<p><b>Precisión Wyckoff:</b> ${esc(a.wyckoff_accuracy)}</p>`;
    html += `<pre class="yaml">${esc(JSON.stringify(a,null,2))}</pre>`;
    html += `</details>`;
  });
  setView('learning', html);
}

// ---------- Case View ----------
function findOpp(oppId){ return DATA.opportunities.find(o=>o.opp_id===oppId) || {opp_id:oppId,ticker:'?',status:'?',scores:{}}; }
function showCase(oppId){
  const o = findOpp(oppId);
  let html = `<button class="tab" onclick="renderAll()">← Volver</button>`;
  html += `<h1>${esc(o.ticker)} <span class="tick">${esc(o.opp_id)}</span> ${badge(o.status)}</h1>`;
  html += `<div class="grid">`;
  html += `<div class="card"><div class="muted">Convicción</div><div style="font-size:22px;font-weight:700">${o.conviction_overall??'—'}</div><div class="muted">${esc(o.confidence||'')} · ${esc(o.trend||'')}</div></div>`;
  html += `<div class="card"><div class="muted">Precio / Intrínseco</div><div style="font-size:18px">${money(o.current_price)} / ${money(o.intrinsic_value)}</div><div class="${o.upside_pct>=0?'pos':'neg'}">${pct(o.upside_pct,true)}</div></div>`;
  html += `<div class="card"><div class="muted">Última investigación</div><div style="font-size:16px">${dt(o.last_research)}</div>${staleBadge(o)}</div>`;
  html += `<div class="card"><div class="muted">Decisión</div><div style="font-size:18px">${esc(o.decision?.decision_type||'—')}</div><div class="muted">${esc(o.decision?.author||'')} ${dt(o.decision?.resolved_at)}</div></div>`;
  html += '</div>';
  html += `<h2>Assessment scores</h2><table><thead><tr><th>Engine</th><th>Score</th><th>Findings</th></tr></thead><tbody>`;
  Object.entries(o.scores||{}).forEach(([k,v])=>html+=`<tr><td>${esc(k)}</td><td class="score">${v??'—'}</td><td>${(o.findings?.[k]||[]).map(esc).join(' · ')||'—'}</td></tr>`);
  html += '</tbody></table>';
  if(o.decision?.justification) html += `<p class="muted">Justificación: ${esc(o.decision.justification)}</p>`;
  if((o.proposal?.rules_passed||[]).length) html += `<p>Reglas superadas: ${o.proposal.rules_passed.map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</p>`;
  if((o.proposal?.rules_failed||[]).length) html += `<p class="neg">Reglas falladas: ${o.proposal.rules_failed.map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</p>`;
  if(o.ddd?.categoria) html += `<p>Categoría DDD: <span class="pill">${esc(o.ddd.categoria)}</span></p>`;
  if(Object.keys(o.ddd?.ratings||{}).length) html += `<p>Ratings: ${Object.entries(o.ddd.ratings).map(([k,v])=>`<span class="pill">${esc(k)}: ${esc(v)}</span>`).join('')}</p>`;
  if(o.ddd?.riesgos?.length){ html += `<h2>Riesgos (DDD)</h2><ul>`; o.ddd.riesgos.forEach(r=>html+=`<li>${esc(r.riesgo)} <span class="muted">(${esc(r.probabilidad)} · ${esc(r.impacto)})</span></li>`); html += '</ul>'; }
  if(o.wyckoff){
    html += `<h2>Wyckoff (último análisis)</h2><table><thead><tr><th>Fase</th><th>Score</th><th>Confianza</th><th>Precio</th><th>Entry point</th><th>Target</th><th>Triggered</th></tr></thead><tbody>`;
    html += `<tr><td>${wyPhase(o.wyckoff.phase)}</td><td>${esc(o.wyckoff.score)}</td><td>${esc(o.wyckoff.confidence)}</td><td>${money(o.wyckoff.current_price)}</td><td>${esc(o.wyckoff.entry_point)}</td><td>${money(o.wyckoff.price_target)}</td><td>${o.wyckoff.triggered_entry?'<span class="pos">sí</span>':'no'}</td></tr></tbody></table>`;
    html += `<p class="muted">Analizado: ${dt(o.wyckoff.analyzed_at)}</p>`;
  }
  html += `<p><a href="wiki/${esc(o.ticker)}.html">Abrir wiki de ${esc(o.ticker)}</a></p>`;
  setView('case', html);
}
function showOppFromBuylist(oppId, ticker){ if(oppId){ showCase(oppId); } else { showCase(ticker); } }
function showCaseFromPos(oppId, ticker){ if(oppId){ showCase(oppId); } else { showCase(ticker); } }

function setView(id, html){ document.getElementById('view').innerHTML = `<div id="${id}">${html}</div>`; }

// learning standalone page (opcional)
function renderLearningPage(){ renderLearning(); }

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
<p class="muted">Generado <span id="gen-at" data-v="GENV"></span> · <a href="learning.html">Learning</a></p>
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
    (out / "learning").mkdir(parents=True, exist_ok=True)

    (out / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (out / "assets" / "app.js").write_text(
        f"const DISC_MIN_SCORE = {builder.disc_min_score};\n"
        f"const ENTRY_RULES = {json.dumps(builder.entry_rules, ensure_ascii=False)};\n"
        f"const ENTRY_CFG = {json.dumps(builder.entry_cfg, ensure_ascii=False)};\n"
        + APP_JS, encoding="utf-8"
    )
    (out / "data.json").write_text(
        json.dumps(_to_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8"
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

    (out / "learning.html").write_text(render_learning_page(), encoding="utf-8")

    # copy index.html to root of out (already done) — also write a .nojekyll
    (out / ".nojekyll").write_text("", encoding="utf-8")

    return out


def _to_jsonable(data: SiteData) -> dict:
    d = data.__dict__
    for k in ("companies",):
        d[k] = {tk: c for tk, c in data.companies.items()}
    return d


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    stale = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_STALE_DAYS
    out = write_site(base, stale_days=stale)
    print(f"[site] Built {out} ({len(_to_jsonable(SiteBuilder(base).build()).get('opportunities', []))} opps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
