#!/usr/bin/env python3
"""DDD Research Worker — decides which opportunities need (re)research.

Selection rules:
  NORMAL mode (monthly cron):
    - SCREENED: process -> UNDER_RESEARCH
    - UNDER_RESEARCH with stale > 30d: process with force_reprocess=True
    - All others: skip
  FORCE mode (30-day re-research, manual, earnings):
    - UNDER_RESEARCH: re-research (no status change)
    - All others: skip
  Tickers in BUY_LIST or PORTFOLIO: skip by default. A manual, single-ticker
  REVIEW_BUYLIST run may re-research the exact Buy List opportunity; portfolio
  positions remain excluded.

Run with --preview to list candidates without processing.
"""

import json
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

from idos.research.events import canonical_event_type, load_event_evidence
from idos.research.hourly_ramp import (
    initial_state as initial_hourly_ramp_state,
    batch_limit as hourly_ramp_batch_limit,
    load_state as load_hourly_ramp_state,
    record_outcome as record_hourly_ramp_outcome,
    resume_state as resume_hourly_ramp_state,
    save_state as save_hourly_ramp_state,
)

STALE_DAYS = 30
MAX_RESEARCH_CANDIDATES_PER_RUN = 5
RESUME_QUEUE_PATH = Path("cache/ddd_research_resume.json")
HOURLY_RAMP_STATE_PATH = Path("cache/ddd_research_capacity.json")
SKIP_TICKERS = set()

def _save_resume_queue(items: list[dict]) -> None:
    """Persist deferred monthly Research work atomically for the next scheduled run."""
    RESUME_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = RESUME_QUEUE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"schema_version": 1, "pending": items}, indent=2), encoding="utf-8")
    temporary.replace(RESUME_QUEUE_PATH)


def _load_resume_queue() -> list[dict]:
    try:
        payload = json.loads(RESUME_QUEUE_PATH.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("pending"), list):
            return []
        return [item for item in payload["pending"] if isinstance(item, dict) and item.get("ticker") and item.get("opp_id")]
    except (OSError, ValueError, AttributeError):
        return []


EVENT_RESEARCHABLE_STATUSES = {
    "SCREENED",
    "UNDER_RESEARCH",
    "UNDER_DEEP_DD",
    "APPROVED",
    "ENTRY_PENDING",
}


def _parse_dt(s):
    if not s:
        return None
    try:
        if isinstance(s, datetime):
            return s
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _load_skip_tickers():
    skip = set()
    bl = Path("idos-journal/portfolio/buylist.yml")
    if bl.exists():
        try:
            d = yaml.safe_load(bl.read_text(encoding="utf-8")) or {}
            for e in d.get("entries", []):
                if e.get("ticker"):
                    skip.add(e["ticker"].upper())
        except Exception:
            pass
    pos_dir = Path("idos-journal/paper/positions")
    if pos_dir.exists():
        for f in pos_dir.glob("*.yml"):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8"))
                if isinstance(d, dict) and d.get("ticker"):
                    skip.add(d["ticker"].upper())
            except Exception:
                pass
    return skip


def _load_buylist_opportunities():
    """Return exact Buy List (ticker, opportunity) pairs for explicit re-review."""
    path = Path("idos-journal/portfolio/buylist.yml")
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("entries", []) if isinstance(data, dict) else []
        return {
            (str(entry.get("ticker", "")).upper(), str(entry.get("opp_id", "")))
            for entry in entries
            if isinstance(entry, dict) and entry.get("ticker") and entry.get("opp_id")
        }
    except (OSError, yaml.YAMLError, AttributeError):
        return set()


def _load_portfolio_tickers():
    """Return paper-position tickers, which remain excluded from DDD re-review."""
    tickers = set()
    positions_dir = Path("idos-journal/paper/positions")
    if not positions_dir.exists():
        return tickers
    for path in positions_dir.glob("*.yml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("ticker"):
                tickers.add(str(data["ticker"]).upper())
        except (OSError, yaml.YAMLError):
            continue
    return tickers


def _selected_strategy_id(strategy_catalog) -> str | None:
    """Resolve an optional single-strategy selector for bounded DDD runs."""
    requested = os.environ.get("STRATEGY_ID", "").strip()
    if not requested:
        return None
    profile = strategy_catalog.require(requested)
    if not profile.enabled:
        raise ValueError(f"STRATEGY_ID must refer to an enabled strategy: {profile.strategy_id}")
    return profile.strategy_id


def _matches_strategy(opportunity: dict, selected_strategy_id: str | None) -> bool:
    if selected_strategy_id is None:
        return True
    strategy_id = str(opportunity.get("strategy_id") or "COMPOUNDER").strip().upper()
    return strategy_id == selected_strategy_id


def write_preview_output(has_candidates: bool, output_path: str | Path | None = None) -> None:
    """Expose the deterministic Research selector result to a caller workflow."""
    target = output_path or os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as output_file:
        output_file.write(f"has_research_candidates={'true' if has_candidates else 'false'}\n")


def _canonical_event_type(event_type: str) -> str | None:
    canonical = str(event_type or "").strip().lower().replace("-", "_")
    if canonical in {"", "manual", "monthly", "re_research_30d"}:
        return None
    return canonical_event_type(canonical)


def _event_evidence_for_ticker(event_type: str, ticker: str) -> tuple[dict | None, str | None]:
    canonical = _canonical_event_type(event_type)
    if canonical is None:
        return None, None
    try:
        return load_event_evidence(canonical, ticker), None
    except ValueError as exc:
        return None, str(exc)


def _configured_event_trigger(opp: dict, event_type: str, catalog) -> str | None:
    """Return a material event only when the opportunity's strategy enables it."""
    canonical = _canonical_event_type(event_type)
    if canonical is None:
        return None
    try:
        profile = catalog.get(opp.get("strategy_id") or "COMPOUNDER")
    except (ValueError, AttributeError):
        return None
    if not profile.enabled or profile.research_profile == "systematic":
        return None
    research_cfg = profile.parameters.get("research", {})
    configured = research_cfg.get("event_triggers", []) if isinstance(research_cfg, dict) else []
    allowed = {
        str(item).strip().lower().replace("-", "_")
        for item in configured if isinstance(item, str)
    } if isinstance(configured, list) else set()
    return canonical if canonical in allowed else None


def _is_stale(opp: dict) -> tuple[bool, int | None]:
    """Return (is_stale, days_since_last_research)."""
    last_at = _parse_dt(opp.get("last_research_at") or opp.get("updated_at"))
    if not last_at:
        return True, None
    now = datetime.now(timezone.utc)
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    days = (now - last_at).days
    return days > STALE_DAYS, days


def _needs_research(
    opp: dict,
    force: bool,
    *,
    allow_buylist_research: bool = False,
    event_trigger: str | None = None,
) -> tuple[bool, bool, str]:
    """Return (should_process, force_reprocess, reason)."""
    status = opp.get("status", "")
    ticker = opp.get("ticker", "").upper()
    score = (opp.get("conviction") or {}).get("overall", 0)

    if ticker in SKIP_TICKERS and not (allow_buylist_research or event_trigger):
        return False, False, "in BUY_LIST/PORTFOLIO"

    if event_trigger:
        if status in EVENT_RESEARCHABLE_STATUSES:
            return True, True, f"configured event trigger: {event_trigger} (status={status})"
        return False, False, f"event trigger {event_trigger} not applicable to status {status}"

    if opp.get("research_profile") == "systematic" and status in {"SCREENED", "UNDER_RESEARCH"}:
        from idos.strategy.catalog import StrategyCatalog
        from idos.strategy.signals import current_selection
        try:
            profile = StrategyCatalog("idos-config/strategies.yml").require(opp.get("strategy_id", ""))
            if not profile.enabled or profile.research_profile != "systematic":
                return False, False, "systematic strategy not enabled"
            evidence = current_selection(Path.cwd(), profile.strategy_id, ticker, profile.parameters)
        except (ValueError, OSError) as exc:
            return False, False, f"systematic evidence: {exc}"
        if status == "UNDER_RESEARCH" and evidence["signal"] != opp.get("signal"):
            return True, True, "systematic signal changed; re-research required"

    if force:
        if allow_buylist_research:
            return True, True, f"FORCE manager-requested Buy List re-review (status={status})"
        if status == "UNDER_RESEARCH":
            return True, True, f"FORCE re-research UNDER_RESEARCH (score={score})"
        return False, False, f"FORCE: status {status} not re-researchable"

    if status == "SCREENED":
        return True, False, f"new entry: SCREENED (score={score})"

    if status == "UNDER_RESEARCH":
        stale, days = _is_stale(opp)
        if stale:
            reason = f"stale UNDER_RESEARCH ({days}d > {STALE_DAYS}d)" if days is not None else f"stale UNDER_RESEARCH (no last_research_at)"
            return True, True, reason
        days_str = f"{days}d" if days is not None else "no last_research_at"
        return False, False, f"UNDER_RESEARCH fresh ({days_str} <= {STALE_DAYS}d)"

    return False, False, f"status {status} not processable in NORMAL mode"


def preview():
    """Lista las oportunidades candidatas sin procesarlas. Para el workflow de GitHub Actions."""
    from idos.data.journal import JournalRepository
    from idos.data.sqlite import SQLiteStore
    from pathlib import Path

    global SKIP_TICKERS
    SKIP_TICKERS = set()
    bl = Path("idos-journal/portfolio/buylist.yml")
    if bl.exists():
        try:
            d = yaml.safe_load(bl.read_text(encoding="utf-8")) or {}
            for e in d.get("entries", []):
                if e.get("ticker"):
                    SKIP_TICKERS.add(e["ticker"].upper())
        except Exception:
            pass
    pos_dir = Path("idos-journal/paper/positions")
    if pos_dir.exists():
        for f in pos_dir.glob("*.yml"):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8"))
                if isinstance(d, dict) and d.get("ticker"):
                    SKIP_TICKERS.add(d["ticker"].upper())
            except Exception:
                pass

    now = datetime.now(timezone.utc)
    companies_dir = Path("idos-journal/companies")
    screened = []
    stale = []
    fresh = []
    force_list = []
    excluded = []
    selected = []
    skipped = []
    force = os.environ.get("FORCE", "false").lower() == "true"
    event_type = os.environ.get("EVENT_TYPE", "monthly")
    event_requested = _canonical_event_type(event_type)
    from idos.strategy.catalog import StrategyCatalog
    strategy_catalog = StrategyCatalog(Path("idos-config/strategies.yml"))
    selected_strategy_id = _selected_strategy_id(strategy_catalog)
    requested = {t.strip().upper() for t in os.environ.get("TICKER", "").split(",") if t.strip()}
    review_buylist = os.environ.get("REVIEW_BUYLIST", "false").lower() == "true"
    if review_buylist and (not force or len(requested) != 1):
        raise ValueError("REVIEW_BUYLIST requires FORCE=true and exactly one selected TICKER")
    buylist_opportunities = _load_buylist_opportunities()
    portfolio_tickers = _load_portfolio_tickers()
    if review_buylist:
        selected_ticker = next(iter(requested))
        if selected_ticker in portfolio_tickers:
            raise ValueError("Portfolio positions cannot be selected for Buy List re-review")
        if not any(ticker == selected_ticker for ticker, _ in buylist_opportunities):
            raise ValueError("Selected ticker has no current Buy List opportunity to re-review")

    for d in sorted(companies_dir.iterdir()):
        if not d.is_dir():
            continue
        ticker = d.name.upper()
        if requested and ticker not in requested:
            continue
        if ticker in portfolio_tickers:
            excluded.append(ticker)
            continue
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
                if not data:
                    continue
                if not _matches_strategy(data, selected_strategy_id):
                    continue
                event_trigger = _configured_event_trigger(data, event_type, strategy_catalog)
                event_evidence, evidence_error = _event_evidence_for_ticker(event_type, ticker)
                is_selected_buylist_entry = (
                    review_buylist
                    and requested == {ticker}
                    and (ticker, str(data.get("id", ""))) in buylist_opportunities
                    and ticker not in portfolio_tickers
                )
                is_event_buylist_entry = (
                    event_trigger is not None
                    and (ticker, str(data.get("id", ""))) in buylist_opportunities
                    and ticker not in portfolio_tickers
                )
                if (review_buylist and not is_selected_buylist_entry) or (
                    ticker in SKIP_TICKERS and not (is_selected_buylist_entry or is_event_buylist_entry)
                ):
                    excluded.append(ticker)
                    continue
                status = data.get("status", "")
                score = (data.get("conviction") or {}).get("overall", 0)

                should, reprocess, reason = _needs_research(
                    data,
                    force,
                    allow_buylist_research=is_selected_buylist_entry,
                    event_trigger=event_trigger if event_evidence else None,
                )
                if event_requested and (event_trigger is None or event_evidence is None):
                    should, reprocess = False, False
                    reason = evidence_error or "event trigger is not enabled for this strategy"
                entry = {
                    "ticker": ticker,
                    "opp_id": data["id"],
                    "reason": reason,
                    "force_reprocess": reprocess,
                    "trigger_type": event_trigger,
                }
                if event_evidence:
                    entry["event_evidence"] = event_evidence
                (selected if should else skipped).append(entry)

                if status == "SCREENED":
                    screened.append((ticker, data["id"], score))
                elif status == "UNDER_RESEARCH":
                    stale_flag, days = _is_stale(data)
                    if stale_flag:
                        stale.append((ticker, data["id"], score, days))
                    else:
                        fresh.append((ticker, data["id"], score, days))
                elif status == "WATCHLIST":
                    excluded.append(ticker)
            except Exception:
                pass

    if review_buylist and not selected:
        raise ValueError("No matching Buy List opportunity was selected for re-review")

    print(f"[PREVIEW] Selected for this run after policy/data gates: {len(selected)}")
    print(f"[PREVIEW] SCREENED before policy/data gates: {len(screened)}")
    for t, oid, sc in screened[:5]:
        print(f"  - {t} {oid} score={sc}")
    if screened[5:]:
        print(f"  ... and {len(screened)-5} more")

    print(f"[PREVIEW] UNDER_RESEARCH stale>30d before policy/data gates: {len(stale)}")
    for t, oid, sc, days in stale[:5]:
        print(f"  - {t} {oid} score={sc} ({days}d)")
    if stale[5:]:
        print(f"  ... and {len(stale)-5} more")

    print(f"[PREVIEW] UNDER_RESEARCH fresh<=30d before FORCE/signal-change checks: {len(fresh)}")
    for t, oid, sc, days in fresh[:5]:
        print(f"  - {t} {oid} score={sc} ({days}d)")

    print(f"[PREVIEW] Excluded (BUY_LIST/PORTFOLIO/WATCHLIST): {len(excluded)}")

    Path("cache").mkdir(parents=True, exist_ok=True)
    Path("cache/ddd_preview.json").write_text(json.dumps({
        "selected": selected, "skipped": skipped,
        "screened": [{"ticker": t, "opp_id": oid, "score": sc} for t, oid, sc in screened],
        "stale": [{"ticker": t, "opp_id": oid, "score": sc, "days": days} for t, oid, sc, days in stale],
        "fresh": [{"ticker": t, "opp_id": oid, "score": sc, "days": days} for t, oid, sc, days in fresh],
        "excluded_count": len(excluded),
    }, indent=2), encoding="utf-8")
    write_preview_output(bool(selected))
    if selected_strategy_id and not selected:
        print(f"[DDD] No eligible opportunities for strategy {selected_strategy_id}")
        return 2
    if event_requested and not selected:
        print("[DDD] Material event preview has no candidate with valid evidence")
        return 2
    return 0


def main():
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    tickers_env = os.environ.get('TICKER', '')
    tickers = [t.strip().upper() for t in tickers_env.split(',') if t.strip()] if tickers_env else []
    event_type = os.environ.get('EVENT_TYPE', 'monthly')
    resume_pending = os.environ.get('RESUME_PENDING', 'false').lower() == 'true'
    hourly_ramp = os.environ.get('DDD_HOURLY_RAMP', 'false').lower() == 'true'
    hourly_ramp_state = load_hourly_ramp_state(HOURLY_RAMP_STATE_PATH)
    if hourly_ramp and os.environ.get('RESET_DDD_HOURLY_RAMP', 'false').lower() == 'true':
        hourly_ramp_state = resume_hourly_ramp_state(hourly_ramp_state)
        save_hourly_ramp_state(HOURLY_RAMP_STATE_PATH, hourly_ramp_state)
    if hourly_ramp and hourly_ramp_state.get('paused'):
        print('[DDD] Hourly Research ramp is paused after a provider or quality failure; no LLM calls will be made')
        print('[DDD] Last failure: {}'.format(hourly_ramp_state.get('pause_reason', 'unknown')))
    event_requested = _canonical_event_type(event_type)
    review_buylist = os.environ.get("REVIEW_BUYLIST", "false").lower() == "true"
    if review_buylist and (not force or len(tickers) != 1 or event_type != "manual"):
        print("[DDD] REVIEW_BUYLIST requires a manual run, FORCE=true, and exactly one TICKER")
        return 2

    journal = Path('idos-journal')
    os.chdir(os.environ.get('GITHUB_WORKSPACE', '.'))
    from idos.strategy.catalog import StrategyCatalog
    strategy_catalog = StrategyCatalog(Path("idos-config/strategies.yml"))
    selected_strategy_id = _selected_strategy_id(strategy_catalog)
    global SKIP_TICKERS
    SKIP_TICKERS = _load_skip_tickers()
    buylist_opportunities = _load_buylist_opportunities()
    portfolio_tickers = _load_portfolio_tickers()
    if review_buylist:
        selected_ticker = tickers[0]
        if selected_ticker in portfolio_tickers:
            print("[DDD] Portfolio positions cannot be selected for Buy List re-review")
            return 2
        if not any(ticker == selected_ticker for ticker, _ in buylist_opportunities):
            print("[DDD] Selected ticker has no current Buy List opportunity to re-review")
            return 2

    opportunities = []
    skipped_list = []
    companies_dir = journal / 'companies'

    if resume_pending:
        today = datetime.now(timezone.utc).date().isoformat()
        queue = _load_resume_queue()
        due = [item for item in queue if item.get('next_attempt_date', '') <= today]
        limit = hourly_ramp_batch_limit(hourly_ramp_state, len(due)) if hourly_ramp else MAX_RESEARCH_CANDIDATES_PER_RUN
        opportunities = due[:limit]
        print(f"[DDD] Resume mode: {len(opportunities)} due of {len(queue)} queued opportunities (batch limit={limit})")

    if not resume_pending and companies_dir.exists():
        for d in sorted(companies_dir.iterdir()):
            if not d.is_dir():
                continue
            ticker = d.name.upper()
            if tickers and ticker not in tickers:
                continue
            if ticker in portfolio_tickers:
                continue
            opp_dir = d / 'case_file' / 'opportunities'
            if not opp_dir.exists():
                continue
            for opp in sorted(opp_dir.iterdir()):
                if not opp.is_dir():
                    continue
                yf = opp / 'opportunity.yml'
                if not yf.exists():
                    continue
                try:
                    data = yaml.safe_load(yf.read_text(encoding='utf-8'))
                    if not data:
                        continue
                    if not _matches_strategy(data, selected_strategy_id):
                        continue
                    event_trigger = _configured_event_trigger(data, event_type, strategy_catalog)
                    event_evidence, evidence_error = _event_evidence_for_ticker(event_type, ticker)
                    is_selected_buylist_entry = (
                        review_buylist
                        and tickers == [ticker]
                        and (ticker, str(data.get("id", ""))) in buylist_opportunities
                        and ticker not in portfolio_tickers
                    )
                    is_event_buylist_entry = (
                        event_trigger is not None
                        and (ticker, str(data.get("id", ""))) in buylist_opportunities
                        and ticker not in portfolio_tickers
                    )
                    if (review_buylist and not is_selected_buylist_entry) or (
                        ticker in SKIP_TICKERS and not (is_selected_buylist_entry or is_event_buylist_entry)
                    ):
                        skipped_list.append({
                            'opp_id': data.get('id', ''), 'ticker': ticker,
                            'status': data.get('status', ''),
                            'reason': 'in BUY_LIST/PORTFOLIO; explicit re-review not selected',
                        })
                        continue
                    status = data.get('status', '')
                    score = data.get('conviction', {}).get('overall', 0)

                    should, opp_force, reason = _needs_research(
                        data,
                        force,
                        allow_buylist_research=is_selected_buylist_entry,
                        event_trigger=event_trigger if event_evidence else None,
                    )
                    if event_requested and (event_trigger is None or event_evidence is None):
                        should, opp_force = False, False
                        reason = evidence_error or "event trigger is not enabled for this strategy"
                    if should:
                        opportunities.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'score': score,
                            'current_status': status,
                            'reason': reason,
                            'force_reprocess': opp_force,
                            'trigger_type': event_trigger,
                            'event_evidence': event_evidence,
                        })
                    else:
                        skipped_list.append({
                            'opp_id': data['id'],
                            'ticker': ticker,
                            'status': status,
                            'reason': reason,
                        })
                except Exception as e:
                    print('[DDD] Error reading {}: {}'.format(yf, e))

    if not opportunities:
        print('[DDD] No eligible opportunities to process')
        if selected_strategy_id:
            print(f"[DDD] No eligible opportunities for strategy {selected_strategy_id}")
            return 2
        if review_buylist:
            print('[DDD] Requested Buy List re-review was not eligible; refusing a successful no-op')
            return 2
        if event_requested:
            print('[DDD] Material event has no eligible opportunity with valid evidence')
            return 2
        Path('cache').mkdir(parents=True, exist_ok=True)
        Path('cache/ddd_results.json').write_text(json.dumps({
            'processed': [], 'errors': [], 'total': 0,
            'status': 'none', 'event_type': event_type, 'force': force,
            'skipped': skipped_list,
        }, indent=2), encoding='utf-8')
        return 0

    queue = _load_resume_queue() if resume_pending else []
    if hourly_ramp and not resume_pending and not queue and opportunities and not hourly_ramp_state.get('paused'):
        hourly_ramp_state = initial_hourly_ramp_state()
    if not resume_pending and (hourly_ramp or event_type in {'monthly', 're-research-30d'}):
        known = {(item.get('ticker'), item.get('opp_id')) for item in queue}
        for item in opportunities:
            key = (item.get('ticker'), item.get('opp_id'))
            if key not in known:
                queue.append({**item, 'next_attempt_date': datetime.now(timezone.utc).date().isoformat()})
                known.add(key)
        _save_resume_queue(queue)
    elif not resume_pending:
        queue = []

    run_limit = (
        hourly_ramp_batch_limit(hourly_ramp_state, len(opportunities))
        if hourly_ramp else MAX_RESEARCH_CANDIDATES_PER_RUN
    )
    if len(opportunities) > run_limit:
        opportunities = opportunities[:run_limit]
    if hourly_ramp and hourly_ramp_state.get('paused'):
        if queue:
            _save_resume_queue(queue)
        Path('cache').mkdir(parents=True, exist_ok=True)
        Path('cache/ddd_results.json').write_text(json.dumps({
            'processed': [], 'errors': [], 'total': 0,
            'status': 'ramp_paused', 'event_type': event_type, 'force': force,
            'deferred_count': len(queue), 'skipped': skipped_list,
        }, indent=2), encoding='utf-8')
        print('[DDD] Preserved {} queued opportunities; no LLM calls made'.format(len(queue)))
        return 0
    print('[DDD] To process: {}'.format(len(opportunities)))
    for o in opportunities:
        print('  - {} {} ({}) reason={}'.format(
            o['ticker'], o['opp_id'], o['current_status'], o.get('reason', '')))
    if skipped_list:
        print('[DDD] Skipped: {}'.format(len(skipped_list)))
        for s in skipped_list[:5]:
            print('  skip: {} {} ({}) — {}'.format(s['ticker'], s['opp_id'], s['status'], s['reason']))

    # Execute ResearchWorker for each selected opportunity
    from idos.ai.service import LLMService
    from idos.workers.ai.research_worker import ResearchWorker
    from idos.data.sqlite import SQLiteStore
    from idos.data.journal import JournalRepository

    base_path = Path('idos-journal').parent
    sqlite = SQLiteStore(base_path / 'idos.db')
    journal = JournalRepository(base_path / 'idos-journal')

    models_path = Path("idos-config/models.yml")
    llm_service = LLMService(str(models_path)) if models_path.exists() else LLMService()
    rw = ResearchWorker({
        "llm_service": llm_service,
        "prompts_path": "idos-config/prompts",
    })
    rw_results = []
    rw_errors = []
    deferred_for_capacity = False
    for index, opp in enumerate(opportunities):
        ticker = opp['ticker']
        opp_id = opp['opp_id']
        opp_force = opp.get('force_reprocess', False)
        print('\n[STEP 2] ResearchWorker -> {} {} (force={}) ...'.format(ticker, opp_id, opp_force))
        try:
            ctx = {
                'ticker': ticker,
                'opp_id': opp_id,
                'base_path': str(base_path),
                'force_reprocess': opp_force,
                'event_type': opp.get('trigger_type') or event_type,
                'event_evidence': opp.get('event_evidence'),
            }
            r = rw.run(ctx)
            status = r.get('status', 'unknown')
            validation_errors = [str(error) for error in (r.get('errors') or []) if error]
            print('  -> status={} score={}'.format(
                status, r.get('conviction_score', r.get('score', '?'))))
            if validation_errors:
                print('  -> errors: {}'.format('; '.join(validation_errors)))
            rw_results.append({
                'opp_id': opp_id, 'ticker': ticker, 'status': status,
                'score': r.get('conviction_score', r.get('score')),
                'reason': opp.get('reason', ''),
                'errors': validation_errors,
            })
            if getattr(llm_service, 'capacity_exhausted', False):
                deferred_for_capacity = True
                rw_results[-1]['status'] = 'deferred_capacity'
                queue = [item for item in queue if (item.get('ticker'), item.get('opp_id')) != (ticker, opp_id)]
                queue.append({**opp, 'next_attempt_date': datetime.now(timezone.utc).date().isoformat()})
                queue.extend({**item, 'next_attempt_date': datetime.now(timezone.utc).date().isoformat()} for item in opportunities[index + 1:])
                unique = {}
                for item in queue:
                    unique[(item.get('ticker'), item.get('opp_id'))] = item
                queue = list(unique.values())
                _save_resume_queue(queue)
                break
            if status == 'completed':
                queue = [item for item in queue if (item.get('ticker'), item.get('opp_id')) != (ticker, opp_id)]
                if resume_pending or hourly_ramp or event_type in {'monthly', 're-research-30d'}:
                    _save_resume_queue(queue)
            if status != 'completed':
                rw_errors.append({
                    'ticker': ticker,
                    'opp_id': opp_id,
                    'status': status,
                    'error': r.get('error') or r.get('reason') or '; '.join(validation_errors) or f'Unexpected ResearchWorker status: {status}',
                    'errors': validation_errors,
                })
                if hourly_ramp:
                    print('[DDD] Hourly ramp stops at the first incomplete opportunity')
                    break
        except Exception as e:
            import traceback
            traceback.print_exc()
            print('  -> ERROR: {}'.format(e))
            rw_errors.append({'ticker': ticker, 'opp_id': opp_id, 'error': str(e)})
            if hourly_ramp:
                print('[DDD] Hourly ramp stops at the first ResearchWorker exception')
                break

    completed_keys = {(item.get('ticker'), item.get('opp_id')) for item in rw_results if item.get('status') == 'completed'}
    remaining = [item for item in queue if (item.get('ticker'), item.get('opp_id')) not in completed_keys]
    if queue and (resume_pending or hourly_ramp or event_type in {'monthly', 're-research-30d'}):
        _save_resume_queue(remaining)

    if hourly_ramp and opportunities:
        completed_count = len(completed_keys)
        if rw_errors:
            first_error = rw_errors[0]
            failure_reason = '{} {}: {}'.format(
                first_error.get('ticker', '?'),
                first_error.get('opp_id', '?'),
                first_error.get('error', 'Research failed'),
            )
        elif deferred_for_capacity:
            failure_reason = 'Provider capacity exhausted: {}'.format(
                getattr(llm_service, 'capacity_failure', None) or 'Research deferred'
            )
        elif completed_count != len(opportunities):
            failure_reason = f'Only {completed_count} of {len(opportunities)} opportunities completed'
        else:
            failure_reason = ''
        hourly_ramp_state = record_hourly_ramp_outcome(
            hourly_ramp_state,
            attempted=len(opportunities),
            completed=completed_count,
            failure_reason=failure_reason,
        )
        save_hourly_ramp_state(HOURLY_RAMP_STATE_PATH, hourly_ramp_state)
        print('[DDD] Hourly ramp next batch={} paused={} last_successful={}'.format(
            hourly_ramp_state['next_batch_size'],
            hourly_ramp_state['paused'],
            hourly_ramp_state['last_successful_batch_size'],
        ))

    results = {
        'total': len(opportunities),
        'processed': rw_results,
        'skipped': skipped_list,
        'assessments': [],
        'errors': rw_errors,
        'status': 'failed' if rw_errors and not deferred_for_capacity else ('partial_deferred' if remaining else 'research_completed'),
        'deferred_count': len(remaining),
        'capacity_failure': getattr(llm_service, 'capacity_failure', None),
        'event_type': event_type,
        'force': force,
        'stale_days_threshold': STALE_DAYS,
    }
    Path('cache').mkdir(parents=True, exist_ok=True)
    Path('cache/ddd_results.json').write_text(
        json.dumps(results, indent=2), encoding='utf-8'
    )
    print('\n[DDD] Research {} for {}, errors in {}'.format(
        'failed' if rw_errors else 'completed', len(rw_results), len(rw_errors)))
    if hourly_ramp and opportunities and hourly_ramp_state.get('paused'):
        return 1
    return 1 if rw_errors and not deferred_for_capacity else 0


if __name__ == '__main__':
    if '--preview' in sys.argv:
        sys.exit(preview() or 0)
    else:
        sys.exit(main())
