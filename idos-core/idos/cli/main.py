import json as json_lib
import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime
from typing import Optional

from idos.core.context import IDOSContext
from idos.data.sqlite import SQLiteStore
from idos.data.knowledge import KnowledgeRepository
from idos.data.journal import JournalRepository
from idos.state.machine import OpportunityStateMachine
from idos.models.enums import OpportunityStatus
from idos.models.knowledge import Company
from idos.models.journal import Opportunity, CaseFile
from idos.events.bus import get_event_bus
from idos.events.types import Event
from idos.telemetry.trace import get_tracer
from idos.discovery.operability import OperabilityFilter
from idos.discovery.screening import FinvizScreener
from idos.timezone import AR_TZ

app = typer.Typer(name="idos", help="Investment Decision Operating System")
console = Console()
state_machine = OpportunityStateMachine()

def _load_assessment_scores(ticker: str, opp_id: str, ctx) -> dict[str, int]:
    import yaml
    dp = ctx.journal_path / "companies" / ticker.upper() / "case_file" / "opportunities" / opp_id / "decision_proposal.yml"
    if not dp.exists():
        return {}
    try:
        data = yaml.safe_load(dp.read_text(encoding="utf-8"))
        return data.get("assessments", {}) if data else {}
    except Exception:
        return {}

def _get_context() -> IDOSContext:
    base = Path.cwd()
    return IDOSContext.create(base)

def _get_stores(ctx: IDOSContext) -> tuple[SQLiteStore, KnowledgeRepository, JournalRepository]:
    sqlite = SQLiteStore(ctx.sqlite_path)
    knowledge = KnowledgeRepository(ctx.knowledge_path)
    journal = JournalRepository(ctx.journal_path)
    return sqlite, knowledge, journal

@app.command()
def init():
    base = Path.cwd()
    for d in ["idos-knowledge/companies", "idos-journal/companies",
              "idos-journal/portfolio/positions", "idos-journal/learnings/post_mortems",
              "idos-config/prompts/scout", "idos-config/prompts/research",
              "idos-config/prompts/portfolio", "idos-config/rules"]:
        (base / d).mkdir(parents=True, exist_ok=True)
    console.print("[green]IDOS initialized successfully[/green]")

@app.command()
def company_add(ticker: str, name: str = "", sector: str = ""):
    ctx = _get_context()
    _, knowledge, _ = _get_stores(ctx)
    company = Company(ticker=ticker.upper(), name=name or ticker.upper(), sector=sector)
    knowledge.save_company(ticker.upper(), company.model_dump())
    bus = get_event_bus()
    bus.publish_sync("company:created", {"ticker": ticker.upper()})
    console.print(f"[green]Company {ticker.upper()} added[/green]")

@app.command()
def company_show(ticker: str):
    ctx = _get_context()
    _, knowledge, _ = _get_stores(ctx)
    data = knowledge.load_company(ticker.upper())
    if not data:
        console.print(f"[red]Company {ticker.upper()} not found[/red]")
        return
    table = Table(title=f"Company: {ticker.upper()}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for k, v in data.items():
        table.add_row(k, str(v))
    console.print(table)

@app.command()
def opp_create(ticker: str):
    ctx = _get_context()
    sqlite, knowledge, journal = _get_stores(ctx)
    opp_id = f"OPP-{datetime.now(AR_TZ).strftime('%Y%m%d')}-{len(sqlite.list_opportunities()) + 1:03d}"
    opp = Opportunity(
        id=opp_id,
        ticker=ticker.upper(),
        status=OpportunityStatus.DISCOVERED,
    )
    sqlite.save_opportunity(opp.model_dump())
    journal.save_opportunity(ticker.upper(), opp.model_dump())
    bus = get_event_bus()
    bus.publish_sync("opportunity:created", {"opp_id": opp_id, "ticker": ticker.upper()})
    console.print(f"[green]Opportunity {opp_id} created for {ticker.upper()}[/green]")

@app.command()
def opp_list(status: str = "", verbose: bool = False):
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)
    opps = sqlite.list_opportunities(status.upper() if status else None)
    seen = {o["id"] for o in opps}
    journal_opps = journal.list_all_opportunities(status.upper() if status else None)
    for jo in journal_opps:
        if jo["id"] not in seen:
            opps.append(jo)
    if not opps:
        console.print("[yellow]No opportunities found[/yellow]")
        return
    table = Table(title=f"Opportunities ({len(opps)})")
    table.add_column("ID", style="cyan")
    table.add_column("Ticker")
    table.add_column("Status")
    table.add_column("Conviction")
    table.add_column("Updated")
    if verbose:
        table.add_column("Business")
        table.add_column("Valuation")
        table.add_column("Risk")
        table.add_column("Recovery")
        table.add_column("Portfolio")
    for opp in opps:
        conv = opp.get("conviction", {}).get("overall", "N/A")
        row = [opp["id"], opp["ticker"], opp["status"], str(conv), opp.get("updated_at", "?")[:10]]
        if verbose:
            scores = _load_assessment_scores(opp["ticker"], opp["id"], ctx)
            row.extend([
                str(scores.get("BusinessAssessmentEngine", "?")),
                str(scores.get("ValuationAssessmentEngine", "?")),
                str(scores.get("RiskAssessmentEngine", "?")),
                str(scores.get("RecoveryAssessmentEngine", "?")),
                str(scores.get("PortfolioAssessmentEngine", "?")),
            ])
        table.add_row(*row)
    console.print(table)

@app.command()
def opp_transition(opp_id: str, target: str):
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)
    opp_data = sqlite.get_opportunity(opp_id)
    if not opp_data:
        console.print(f"[yellow]Opportunity {opp_id} not in SQLite, trying journal...[/yellow]")
        for ticker_dir in (ctx.journal_path / "companies").iterdir():
            if ticker_dir.is_dir():
                opp = journal.load_opportunity(ticker_dir.name, opp_id)
                if opp:
                    opp_data = opp
                    opp_data["ticker"] = ticker_dir.name
                    break
    if not opp_data:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return
    current = OpportunityStatus(opp_data["status"])
    target_status = OpportunityStatus(target.upper())
    try:
        transition = state_machine.transition(current, target_status, cause="cli command")
        sqlite.save_opportunity({**opp_data, "status": target_status.value})
        sqlite.record_transition(opp_id, current.value, target_status.value, cause="cli command")
        journal.log_event("opportunity:transitioned", {
            "opp_id": opp_id,
            "ticker": opp_data.get("ticker", ""),
            "from": current.value,
            "to": target_status.value,
        }, source="cli")
        bus = get_event_bus()
        bus.publish_sync("opportunity:transitioned", {
            "opp_id": opp_id,
            "from": current.value,
            "to": target_status.value,
        })
        console.print(f"[green]{opp_id}: {current.value} -> {target_status.value}[/green]")
    except Exception as e:
        console.print(f"[red]Transition failed: {e}[/red]")

@app.command()
def watchlist():
    ctx = _get_context()
    _, _, journal = _get_stores(ctx)
    filepath = ctx.journal_path / "portfolio" / "watchlist.yml"
    console.print(f"[dim]Reading: {filepath}[/dim]")
    if not filepath.exists():
        console.print(f"[yellow]File not found: {filepath}[/yellow]")
        return
    import yaml
    raw = yaml.safe_load(filepath.read_text(encoding="utf-8"))
    console.print(f"[dim]YAML entries: {len(raw.get('entries', [])) if raw else 0}[/dim]")
    entries = journal.load_watchlist()
    if not entries:
        console.print("[yellow]Watchlist is empty[/yellow]")
        return
    table = Table(title=f"Watchlist ({len(entries)} entries)")
    table.add_column("Ticker")
    table.add_column("Score")
    table.add_column("Added")
    for e in entries:
        table.add_row(e.get("ticker", ""), str(e.get("score", "")), e.get("added_at", ""))
    console.print(table)

@app.command()
def position_list():
    ctx = _get_context()
    _, _, journal = _get_stores(ctx)
    from idos.portfolio.engine import PortfolioEngine
    engine = PortfolioEngine(journal)
    positions = engine.get_positions()
    if not positions:
        console.print("[yellow]No positions[/yellow]")
        return
    table = Table(title="Portfolio Positions")
    table.add_column("Ticker")
    table.add_column("Shares")
    table.add_column("Avg Price")
    table.add_column("Weight %")
    table.add_column("Status")
    for p in positions:
        table.add_row(p.get("ticker", ""), str(p.get("shares", 0)),
                      f"${p.get('avg_entry_price', 0):.2f}", f"{p.get('weight_pct', 0):.1f}%",
                      p.get("status", ""))
    console.print(table)

@app.command()
def dashboard():
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)
    from idos.portfolio.engine import PortfolioEngine
    engine = PortfolioEngine(journal)
    opps = sqlite.list_opportunities()
    if not opps:
        opps = journal.list_all_opportunities()
    else:
        journal_opps = journal.list_all_opportunities()
        existing_ids = {o["id"] for o in opps}
        for jo in journal_opps:
            if jo["id"] not in existing_ids:
                opps.append(jo)
    positions = engine.get_positions()
    watchlist = engine.get_watchlist()
    total_weight = engine.total_weight()
    active_opps = [o for o in opps if o.get("status", "") not in ("ARCHIVED", "EXITED")]

    info = Panel.fit(
        f"[bold]IDOS Dashboard[/bold]\n\n"
        f"Active Opportunities: {len(active_opps)}\n"
        f"Portfolio Positions: {len(positions)}\n"
        f"Total Weight: {total_weight:.1f}%\n"
        f"Watchlist: {len(watchlist)}",
        title="Portfolio Overview",
    )
    console.print(info)

@app.command()
def event_log(limit: int = 20, ticker: str = ""):
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)
    bus = get_event_bus()
    history = bus.get_history()
    if not history:
        events = journal.list_events(limit=limit)
    else:
        events = [{"timestamp": e.timestamp.isoformat()[:19], "event_type": e.type, "source": e.source, "data": {}} for e in history[-limit:]]
    if ticker:
        events = [e for e in events if ticker.upper() in str(e.get("data", {}))]
    if not events:
        console.print("[yellow]No events[/yellow]")
        return
    table = Table(title=f"Recent Events ({'journal' if not bus.get_history() else 'bus'})")
    table.add_column("Type")
    table.add_column("Source")
    table.add_column("Timestamp")
    for e in events[:limit]:
        ts = e.get("timestamp", "")[:19]
        table.add_row(e.get("event_type", "?"), e.get("source", "?"), ts)
    console.print(table)

# ──────────────────────────────────────────────
# MANUAL INTERVENTION COMMANDS (no UI required)
# ──────────────────────────────────────────────

@app.command()
def opp_research(ticker: str, opp_id: str = "", force: bool = False):
    """Ejecuta DDD + AOIF + Hypothesis sobre una oportunidad.
    Por defecto busca WATCHLIST → UNDER_DEEP_DD. Con --force reprocesa cualquier estado sin cambiar status."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        filter_status = None if force else "WATCHLIST"
        opps = sqlite.list_opportunities(filter_status)
        matching = [o for o in opps if o.get("ticker", "") == ticker.upper()]
        if not matching:
            opps = journal.list_all_opportunities(filter_status)
            matching = [o for o in opps if o.get("ticker", "") == ticker.upper()]
        if not matching:
            label = "WATCHLIST" if not force else "any"
            console.print(f"[red]No {label} opportunities found for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    opp = sqlite.get_opportunity(opp_id)
    if not opp:
        opp_yaml = journal.load_opportunity(ticker.upper(), opp_id)
        if opp_yaml:
            opp_yaml.setdefault("conviction", {"overall": 50})
            sqlite.save_opportunity(opp_yaml)
            opp = opp_yaml
    if not opp:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return

    mode = "FORCE" if force else "NORMAL"
    console.print(f"[cyan]{mode} Researching {ticker} ({opp_id})...[/cyan]")
    from idos.workers.ai.research_worker import ResearchWorker
    worker = ResearchWorker({})
    ctx_worker = {
        "ticker": ticker,
        "opp_id": opp_id,
        "base_path": str(ctx.config_path.parent),
    }
    if force:
        ctx_worker["force_reprocess"] = True
        ctx_worker["event_type"] = "manual"
    result = worker.execute(ctx_worker)
    if result.status == "failed":
        console.print(f"[red]Research failed: {result.error}[/red]")
        return
    output = result.output
    if output.get("status") == "skipped":
        console.print(f"[yellow]Skipped: {output.get('reason', '')}[/yellow]")
        return
    table = Table(title=f"Research Results: {ticker} ({mode})")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Status", output.get("status", "N/A"))
    table.add_row("Score", str(output.get("score", "N/A")))
    table.add_row("Classification", output.get("classification", "N/A"))
    table.add_row("Market Error", output.get("market_error_conclusion", "N/A"))
    table.add_row("Hypotheses", str(output.get("hypotheses_count", 0)))
    ddd_empty = output.get("ddd_empty", False)
    if ddd_empty:
        table.add_row("[red]DDD Quality[/red]", "[red]VACIO (LLM sin datos)[/red]")
    console.print(table)
    if ddd_empty:
        console.print("[red]⚠ DDD report vacío — el LLM no generó análisis real (falta API key o datos)[/red]")

@app.command()
def opp_approve(ticker: str, opp_id: str = ""):
    """Evalúa DDD vs reglas de entrada (UNDER_DEEP_DD → APPROVED o WATCHLIST)."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities("UNDER_DEEP_DD")
        matching = [o for o in opps if o.get("ticker", "") == ticker.upper()]
        if not matching:
            opps = journal.list_all_opportunities("UNDER_DEEP_DD")
            matching = [o for o in opps if o.get("ticker", "") == ticker.upper()]
        if not matching:
            console.print(f"[red]No UNDER_DEEP_DD opportunities found for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    console.print(f"[cyan]Evaluating {ticker} ({opp_id}) via Decision Board...[/cyan]")
    from idos.workers.ai.decision_board_worker import DecisionBoardWorker
    worker = DecisionBoardWorker({})
    result = worker.execute({
        "ticker": ticker,
        "opp_id": opp_id,
        "base_path": str(ctx.config_path.parent),
    })
    if result.status == "failed":
        console.print(f"[red]Decision Board failed: {result.error}[/red]")
        return
    output = result.output
    decision = output.get("decision", "UNKNOWN")
    color = "green" if decision == "APPROVED" else "yellow" if decision == "WATCHLIST" else "red"
    console.print(f"[{color}]Decision: {decision}[/{color}]")
    console.print(f"Rules pass: {output.get('all_rules_pass')}")
    console.print(f"Decision ID: {output.get('decision_id')}")

@app.command()
def opp_reject(ticker: str, opp_id: str = "", reason: str = "insufficient_evidence"):
    """Rechaza oportunidad y la devuelve a WATCHLIST."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities()
        matching = [o for o in opps if o.get("ticker", "") == ticker.upper() and o.get("status") in ("UNDER_DEEP_DD",)]
        if not matching:
            opps = journal.list_all_opportunities()
            matching = [o for o in opps if o.get("ticker", "") == ticker.upper() and o.get("status") in ("UNDER_DEEP_DD",)]
        if not matching:
            console.print(f"[red]No research-stage opportunities found for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    opp = sqlite.get_opportunity(opp_id)
    if not opp:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return

    old_status = opp["status"]
    opp["status"] = "WATCHLIST"
    opp["updated_at"] = datetime.now(AR_TZ).isoformat()
    sqlite.save_opportunity(opp)
    sqlite.record_transition(opp_id, old_status, "WATCHLIST", cause=reason, worker="cli")
    journal.save_opportunity(ticker.upper(), opp)
    journal.log_event("opportunity:rejected", {
        "opp_id": opp_id, "ticker": ticker.upper(),
        "from": old_status, "to": "WATCHLIST", "reason": reason,
    }, source="cli")
    console.print(f"[yellow]{ticker} ({opp_id}): {old_status} → WATCHLIST (reason: {reason})[/yellow]")

@app.command()
def entry_evaluate(ticker: str, opp_id: str = ""):
    """Evalúa condiciones de entrada para oportunidad APPROVED/ENTRY_PENDING."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities()
        matching = [o for o in opps if o.get("ticker", "") == ticker.upper()
                    and o.get("status") in ("APPROVED", "ENTRY_PENDING")]
        if not matching:
            opps = journal.list_all_opportunities()
            matching = [o for o in opps if o.get("ticker", "") == ticker.upper()
                        and o.get("status") in ("APPROVED", "ENTRY_PENDING")]
        if not matching:
            console.print(f"[red]No APPROVED/ENTRY_PENDING opportunities for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    console.print(f"[cyan]Checking entry conditions for {ticker} ({opp_id})...[/cyan]")
    from idos.workers.portfolio.entry_monitor_worker import EntryMonitorWorker
    worker = EntryMonitorWorker({})
    result = worker.execute({
        "ticker": ticker,
        "opp_id": opp_id,
        "base_path": str(ctx.config_path.parent),
    })
    if result.status == "failed":
        console.print(f"[red]Entry evaluation failed: {result.error}[/red]")
        return
    output = result.output
    table = Table(title=f"Entry Signal: {ticker}")
    table.add_column("Condition", style="cyan")
    table.add_column("Status")
    for key in ("all_conditions_met", "price_in_zone", "wyckoff_confirmed", "thesis_active", "portfolio_fit"):
        val = output.get(key, False)
        color = "green" if val else "red"
        table.add_row(key.replace("_", " ").title(), f"[{color}]{val}[/{color}]")
    table.add_row("Current Price", f"${output.get('current_price', 0):.2f}")
    table.add_row("Target Price", f"${output.get('target_price', 0):.2f}")
    table.add_row("Margin of Safety", f"{output.get('margin_of_safety_pct', 0):.1f}%")
    table.add_row("Wyckoff Phase", output.get("wyckoff_phase", "N/A"))
    console.print(table)
    if output.get("entry_executed"):
        console.print("[green]✓ Entry conditions met — position should be accumulating[/green]")

@app.command()
def position_exit(ticker: str, reason: str = "thesis_broken",
                  opp_id: str = ""):
    """Cierra posición y genera post-mortem (MONITORING → EXITED → ARCHIVED)."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities()
        matching = [o for o in opps if o.get("ticker", "") == ticker.upper()
                    and o.get("status") in ("MONITORING", "FULL_POSITION", "ACCUMULATING")]
        if not matching:
            opps = journal.list_all_opportunities()
            matching = [o for o in opps if o.get("ticker", "") == ticker.upper()
                        and o.get("status") in ("MONITORING", "FULL_POSITION", "ACCUMULATING")]
        if not matching:
            console.print(f"[red]No active positions found for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    opp = sqlite.get_opportunity(opp_id)
    if not opp:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return

    valid_reasons = {
        "thesis_broken": "Tesis invalidada",
        "valuation_target": "Valoración objetivo alcanzada",
        "portfolio_rebalance": "Reemplazo por mejor oportunidad",
        "risk_trigger": "Tesis cambiada tras re-assessment de riesgo",
        "manual": "Decisión manual del inversor",
    }
    if reason not in valid_reasons:
        console.print(f"[red]Invalid reason. Options: {', '.join(valid_reasons.keys())}[/red]")
        return

    old_status = opp["status"]
    opp["status"] = "EXITED"
    opp["exit_reason"] = reason
    opp["updated_at"] = datetime.now(AR_TZ).isoformat()
    sqlite.save_opportunity(opp)
    sqlite.record_transition(opp_id, old_status, "EXITED", cause=reason, worker="cli")
    journal.save_opportunity(ticker.upper(), opp)
    journal.log_event("position:exited", {
        "opp_id": opp_id, "ticker": ticker.upper(),
        "from": old_status, "to": "EXITED", "reason": reason,
    }, source="cli")
    console.print(f"[yellow]{ticker}: {old_status} → EXITED ({valid_reasons[reason]})[/yellow]")

    position = journal.load_position(ticker.upper())
    if position:
        position["status"] = "CLOSED"
        position["exit_reason"] = reason
        position["exited_at"] = datetime.now(AR_TZ).isoformat()
        journal.save_position(ticker.upper(), position)
        console.print(f"[yellow]Position closed in journal[/yellow]")

    console.print(f"[cyan]Generating post-mortem...[/cyan]")
    from idos.workers.learning.post_mortem_worker import PostMortemWorker
    worker = PostMortemWorker({})
    pm_result = worker.execute({
        "ticker": ticker,
        "opp_id": opp_id,
        "exit_reason": reason,
        "base_path": str(ctx.config_path.parent),
    })
    if pm_result.status == "failed":
        console.print(f"[red]Post-mortem generation failed: {pm_result.error}[/red]")
        return
    pm_output = pm_result.output
    console.print(f"[green]Post-mortem completed. Archived: {pm_output.get('archived')}[/green]")
    for lesson in pm_output.get("lessons", []):
        console.print(f"  • {lesson}")

@app.command()
def thesis_invalidate(ticker: str, opp_id: str = "",
                      reason: str = "falsacion manual de la tesis"):
    """Marca la tesis de una posición como invalidada (Thesis Exit).

    El ExitMonitorWorker vende el 100% de la posición en el siguiente run diario.
    """
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities()
        matching = [o for o in opps if o.get("ticker", "") == ticker.upper()
                    and o.get("status") in ("MONITORING", "FULL_POSITION", "ACCUMULATING", "REDUCING")]
        if not matching:
            console.print(f"[red]No active positions found for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    opp = sqlite.get_opportunity(opp_id)
    if not opp:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return

    opp["thesis_active"] = False
    opp["thesis_invalidated_reason"] = reason
    opp["updated_at"] = datetime.now(AR_TZ).isoformat()
    sqlite.save_opportunity(opp)
    yaml_opp = journal.load_opportunity(ticker.upper(), opp_id)
    if yaml_opp:
        yaml_opp["thesis_active"] = False
        yaml_opp["thesis_invalidated_reason"] = reason
        yaml_opp["updated_at"] = opp["updated_at"]
        journal.save_opportunity(ticker.upper(), yaml_opp)
    journal.log_event("thesis:invalidated", {
        "opp_id": opp_id, "ticker": ticker.upper(), "reason": reason,
    }, source="cli")
    console.print(f"[red]Tesis invalidada para {ticker} ({opp_id}). El motor de salida liquidara la posicion.[/red]")

@app.command()
def opp_show(ticker: str, opp_id: str = ""):
    """Muestra estado completo de una oportunidad incluyendo DDD report y assessments."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)
    opp_ticker = ticker.upper()

    if opp_id:
        opp = sqlite.get_opportunity(opp_id)
        if not opp:
            opp = journal.load_opportunity(opp_ticker, opp_id)
        opps = [opp] if opp else []
    else:
        opps = sqlite.list_opportunities()
        opps = [o for o in opps if o.get("ticker", "").upper() == opp_ticker]
        if not opps:
            opps = journal.list_all_opportunities()
            opps = [o for o in opps if o.get("ticker", "").upper() == opp_ticker]

    if not opps:
        console.print(f"[red]No opportunities found for {opp_ticker}[/red]")
        return

    import yaml

    for opp in opps:
        opp_id = opp["id"] if "id" in opp else opp.get("id", "?")
        conv = opp.get("conviction", {}).get("overall", "N/A")

        # ── Basic info + metrics ──
        basic_lines = [
            f"[bold]Opportunity: {opp_id}[/bold]",
            f"Ticker: {opp.get('ticker', opp_ticker)}",
            f"Status: {opp['status']}",
            f"Conviction: {conv}",
            f"Created: {opp.get('created_at', '?')[:10]}",
            f"Updated: {opp.get('updated_at', '?')[:10]}",
        ]
        ddd_file = ctx.journal_path / "companies" / opp_ticker / "case_file" / "opportunities" / opp_id / "ddd_report.yml"
        if ddd_file.exists():
            try:
                ddd = yaml.safe_load(ddd_file.read_text(encoding="utf-8"))
                pi = ddd.get("prompt_inputs", {})
                if pi:
                    basic_lines.append("")
                    basic_lines.append("[bold]Métricas del prompt:[/bold]")
                    basic_lines.append(f"  Revenue: ${pi.get('revenue', 0):,.0f}M")
                    basic_lines.append(f"  Rev Growth: {pi.get('revenue_growth', 0):+.1f}%")
                    basic_lines.append(f"  Op Margin: {pi.get('operating_margin', 0):.1f}%")
                    basic_lines.append(f"  ROIC: {pi.get('roic', 0):.1f}%")
                    basic_lines.append(f"  FCF: ${pi.get('fcf_adjusted', 0):,.0f}M")
                    basic_lines.append(f"  D/E: {pi.get('debt_to_equity', 0):.1f}x")
                    basic_lines.append(f"  P/E: {pi.get('pe_ratio', 0):.1f}x")
                    basic_lines.append(f"  CEO tenure: {pi.get('ceo_tenure', 0)}y")
                    basic_lines.append(f"  Insider ownership: {pi.get('insider_ownership', 0):.1f}%")
            except Exception:
                pass
        console.print(Panel.fit("\n".join(basic_lines), title="Opportunity Detail"))

        base = ctx.journal_path / "companies" / opp_ticker / "case_file" / "opportunities" / opp_id

        # ── DDD Report ──
        ddd_file = base / "ddd_report.yml"
        if ddd_file.exists():
            try:
                ddd = yaml.safe_load(ddd_file.read_text(encoding="utf-8"))
                cls = ddd.get("clasificacion_oportunidad", {})
                err = ddd.get("error_mercado", {})
                thesis = ddd.get("tesis_inversion", "")
                risks = ddd.get("dominio_riesgos", [])
                catalysts = ddd.get("dominio_catalizadores", [])
                bq = ddd.get("dominio_business_quality", {})
                fh = ddd.get("dominio_financial_health", {})
                mgmt = ddd.get("dominio_management", {})
                gr = ddd.get("dominio_growth", {})
                val = ddd.get("opinion_valoracion", "")
                evidencias = ddd.get("calidad_evidencia", {})
                ejecutivo = ddd.get("resumen_ejecutivo", "")

                lines = ["[bold]DDD Report[/bold]"]
                if ejecutivo:
                    lines.append(f"  Resumen: {ejecutivo[:300]}")
                lines.append(f"  Categoría: {cls.get('categoria', 'N/A')}")
                lines.append(f"  Justificación: {cls.get('justificacion', 'N/A')[:200]}")
                lines.append(f"  Score general: {ddd.get('score_general', 'N/A')}/100")
                lines.append(f"  Error de mercado: {err.get('conclusion_error_valoracion', 'N/A')}")
                lines.append(f"  Hipótesis contraria: {err.get('hipotesis_contraria', 'N/A')[:200]}")
                if err.get("catalizador_cambio"):
                    cc = err["catalizador_cambio"]
                    lines.append(f"  Catalizador: {cc.get('descripcion', '')[:200]} (prob: {cc.get('probabilidad_pct', '?')}%, impacto: {cc.get('impacto', '?')})")
                if val:
                    lines.append(f"  Valuación: {val}")
                if thesis:
                    lines.append(f"  Tesis: {thesis[:400]}")
                if bq:
                    lines.append(f"  Business Quality: {bq.get('rating', 'N/A')} — {bq.get('analisis', '')[:200]}")
                if fh:
                    lines.append(f"  Financial Health: {fh.get('rating', 'N/A')} — {fh.get('analisis', '')[:200]}")
                if mgmt:
                    lines.append(f"  Management: {mgmt.get('rating', 'N/A')} — {mgmt.get('analisis', '')[:200]}")
                if gr:
                    lines.append(f"  Growth: {gr.get('rating', 'N/A')} — {gr.get('analisis', '')[:200]}")
                if risks:
                    lines.append(f"  Riesgos ({len(risks)}):")
                    for r in risks[:3]:
                        lines.append(f"    • {r.get('riesgo', '')[:150]} (prob: {r.get('probabilidad', '?')}, impacto: {r.get('impacto', '?')})")
                if catalysts:
                    lines.append(f"  Catalizadores ({len(catalysts)}):")
                    for c in catalysts[:3]:
                        lines.append(f"    • {c.get('descripcion', '')[:150]} (prob: {c.get('probabilidad_pct', '?')}%)")
                if evidencias:
                    h = evidencias.get("hechos_verificados", [])
                    i = evidencias.get("inferencias_llm", [])
                    p = evidencias.get("preguntas_abiertas", [])
                    lines.append(f"  Evidencia: {len(h)} hechos, {len(i)} inferencias, {len(p)} preguntas abiertas")
                console.print(Panel.fit("\n".join(lines), title="DDD Report"))
            except Exception as e:
                console.print(f"[dim]DDD report read error: {e}[/dim]")

        # ── Assessments ──
        ass_dir = base / "assessments"
        if ass_dir.exists():
            ass_files = sorted(ass_dir.glob("*.yml"))
            if ass_files:
                ass_lines = []
                for af in ass_files:
                    try:
                        ad = yaml.safe_load(af.read_text(encoding="utf-8"))
                        if ad:
                            ass_lines.append(f"  {ad.get('engine', '?')}: score={ad.get('score', '?')} "
                                             f"conf={ad.get('confidence', '?')}")
                            for f_ in ad.get("findings", [])[:3]:
                                ass_lines.append(f"    • {f_[:200]}")
                    except Exception:
                        pass
                if ass_lines:
                    console.print(Panel.fit("\n".join(ass_lines), title="Assessments"))

        # ── Decision Proposal ──
        dp_file = base / "decision_proposal.yml"
        if dp_file.exists():
            try:
                dp = yaml.safe_load(dp_file.read_text(encoding="utf-8"))
                dp_lines = [f"  Recommendation: {dp.get('recommendation', '?')}"]
                dp_lines.append(f"  Conviction score: {dp.get('conviction_score', '?')}")
                dp_lines.append(f"  Rules passed: {len(dp.get('rules_passed', []))}")
                dp_lines.append(f"  Rules failed: {len(dp.get('rules_failed', []))}")
                for k, v in dp.get("assessments", {}).items():
                    dp_lines.append(f"  {k.replace('AssessmentEngine', '')}: {v}")
                console.print(Panel.fit("\n".join(dp_lines), title="Decision Proposal"))
            except Exception:
                pass

        # ── Board Resolution ──
        br_file = base / "board_resolution.yml"
        if br_file.exists():
            try:
                br = yaml.safe_load(br_file.read_text(encoding="utf-8"))
                color = "green" if br.get("approved") else "yellow"
                br_lines = [f"  Approved: [{color}]{br.get('approved')}[/{color}]"]
                br_lines.append(f"  Decision type: {br.get('decision_type', '?')}")
                br_lines.append(f"  Justification: {br.get('justification', 'N/A')[:300]}")
                console.print(Panel.fit("\n".join(br_lines), title="Board Resolution"))
            except Exception:
                pass

@app.command()
def schedule_status():
    """Muestra estado de los workers schedule."""
    ctx = _get_context()
    from idos.workers.scheduler.service import SchedulerService
    scheduler = SchedulerService()
    status = scheduler.job_status()
    if not status:
        console.print("[yellow]No scheduled jobs[/yellow]")
        return
    table = Table(title="Scheduled Jobs")
    table.add_column("Job")
    table.add_column("Runs")
    table.add_column("Failures")
    table.add_column("Last Run")
    for name, info in status.items():
        table.add_row(name, str(info["runs"]), str(info["failures"]),
                      str(info["last_run"]) if info["last_run"] else "N/A")
    console.print(table)

@app.command()
def scout(tickers: str = "", force_refresh: bool = False):
    """Ejecuta screening sobre watchlist.md o lista de tickers."""
    ctx = _get_context()
    config = {
        "universe_path": str(ctx.config_path.parent / "idos-config/universe/watchlist.md"),
        "journal_path": str(ctx.journal_path),
    }
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        config["tickers"] = ticker_list

    from idos.workers.data.scout_worker import ScoutWorker
    worker = ScoutWorker(config)
    result = worker.execute({
        "force_refresh": force_refresh,
        "tickers": ticker_list if tickers else None,
    })

    if result.status == "failed":
        console.print(f"[red]Scout failed: {result.error}[/red]")
        return

    output = result.output
    passed = [r for r in output.get("results", []) if r.get("passed")]
    table = Table(title=f"Scout Results ({output.get('tickers_screened', 0)} screened, {output.get('passed_count', 0)} passed)")
    table.add_column("Ticker", style="cyan")
    table.add_column("Score")
    table.add_column("Rank")
    table.add_column("Reason")
    for r in sorted(passed, key=lambda x: x.get("rank", 99)):
        table.add_row(r["ticker"], str(r.get("scout_score", "")), str(r.get("rank", "")), r.get("reason", ""))
    console.print(table)

@app.command()
def telegram_bot(daemon: bool = False):
    """Inicia el bot de Telegram para responder comandos interactivos."""
    from idos.workers.notifications.telegram_bot import TelegramBot
    base = Path.cwd()
    bot = TelegramBot({"base_path": base})
    if daemon:
        console.print("[green]Telegram bot iniciado (polling cada 30s). Ctrl+C para detener.[/green]")
        try:
            while True:
                bot.execute({"single_run": False})
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("[yellow]Bot detenido.[/yellow]")
    else:
        result = bot.execute({"single_run": True})
        console.print(f"Procesados {result.output.get('processed', 0)} comandos.")

if __name__ == "__main__":
    app()

# ──────────────────────────────────────────────
# OPERABLE ASSETS MANAGEMENT
# ──────────────────────────────────────────────

def _get_operable_filter() -> OperabilityFilter:
    ctx = _get_context()
    path = str(ctx.config_path.parent / "idos-config/universe/operable.yml")
    return OperabilityFilter(path)

@app.command()
def operable_add(ticker: str, name: str = "", type: str = "us_equity",
                 source: str = "manual", ratio: str = "",
                 byma_symbol: str = "", notes: str = ""):
    """Agrega un activo a la lista de operables."""
    op = _get_operable_filter()
    if op.is_operable(ticker):
        console.print(f"[yellow]{ticker.upper()} ya esta en la lista[/yellow]")
        return
    entry = op.add(ticker, name=name, type=type, source=source,
                   ratio=ratio, byma_symbol=byma_symbol, notes=notes)
    console.print(f"[green]{ticker.upper()} agregado a la lista de operables[/green]")
    console.print(f"  Tipo: {entry['type']} | Fuente: {entry['source']}")

@app.command()
def operable_remove(ticker: str):
    """Elimina un activo de la lista de operables."""
    op = _get_operable_filter()
    if op.remove(ticker):
        console.print(f"[green]{ticker.upper()} eliminado de la lista de operables[/green]")
    else:
        console.print(f"[red]{ticker.upper()} no encontrado en la lista[/red]")

@app.command()
def operable_list(type: str = "", source: str = ""):
    """Lista activos operables, opcionalmente filtrados por tipo o fuente."""
    op = _get_operable_filter()
    entries = op.list(type=type, source=source)
    if not entries:
        console.print("[yellow]No hay activos operables registrados[/yellow]")
        return
    table = Table(title=f"Activos Operables ({len(entries)})")
    table.add_column("Ticker", style="cyan")
    table.add_column("Nombre")
    table.add_column("Tipo")
    table.add_column("Fuente")
    table.add_column("Ratio")
    table.add_column("Byma")
    table.add_column("Actualizado")
    for e in entries:
        table.add_row(
            e["ticker"],
            e.get("name", ""),
            e.get("type", ""),
            e.get("source", ""),
            e.get("ratio", "N/A"),
            e.get("byma_symbol", "N/A"),
            e.get("updated_at", ""),
        )
    console.print(table)

@app.command()
def operable_check(ticker: str):
    """Verifica si un ticker esta en la lista de operables."""
    op = _get_operable_filter()
    entry = op.check(ticker)
    if entry:
        console.print(f"[green]{ticker.upper()} ES operable[/green]")
        console.print(f"  Nombre: {entry.get('name', 'N/A')}")
        console.print(f"  Tipo: {entry.get('type', 'N/A')}")
        console.print(f"  Fuente: {entry.get('source', 'N/A')}")
        console.print(f"  Ratio: {entry.get('ratio', 'N/A')}")
        console.print(f"  Byma: {entry.get('byma_symbol', 'N/A')}")
    else:
        console.print(f"[red]{ticker.upper()} NO esta en la lista de operables[/red]")

@app.command()
def operable_import(file: str):
    """Importa activos desde un archivo CSV (columna 'ticker' requerida)."""
    op = _get_operable_filter()
    try:
        added, skipped = op.import_csv(file)
        console.print(f"[green]Importacion completada: {added} agregados, {skipped} omitidos[/green]")
    except FileNotFoundError:
        console.print(f"[red]Archivo no encontrado: {file}[/red]")
    except Exception as e:
        console.print(f"[red]Error en importacion: {e}[/red]")

@app.command()
def operable_stats():
    """Muestra estadisticas de la lista de operables."""
    op = _get_operable_filter()
    s = op.stats()
    if s["total"] == 0:
        console.print("[yellow]No hay activos operables registrados[/yellow]")
        return
    info = Panel.fit(
        f"[bold]Activos Operables: {s['total']}[/bold]\n\n"
        + "Por tipo:\n"
        + "\n".join(f"  {k}: {v}" for k, v in s["by_type"].items())
        + "\n\nPor fuente:\n"
        + "\n".join(f"  {k}: {v}" for k, v in s["by_source"].items())
        + f"\n\nUltima actualizacion: {s['last_updated'] or 'N/A'}",
        title="Operability Stats",
    )
    console.print(info)

# ──────────────────────────────────────────────
# SCREENER COMMANDS
# ──────────────────────────────────────────────

def _get_screener() -> FinvizScreener:
    ctx = _get_context()
    path = str(ctx.config_path.parent / "idos-config/screeners")
    return FinvizScreener(path)

@app.command()
def screener_list():
    """Lista los screeners disponibles (Value, Growth, Momentum, Quality, Deep Value)."""
    s = _get_screener()
    screeners = s.list_screeners()
    if not screeners:
        console.print("[yellow]No hay screeners configurados en idos-config/screeners/[/yellow]")
        return
    table = Table(title="Screeners Disponibles")
    table.add_column("Nombre", style="cyan")
    table.add_column("Descripcion")
    table.add_column("Reglas")
    table.add_column("Pass Rate Est.")
    for scr in screeners:
        table.add_row(
            scr["name"],
            scr["description"],
            str(scr["rule_count"]),
            f"{scr['expected_pass_rate']*100:.0f}%",
        )
    console.print(table)

@app.command()
def screener_run(ticker: str, name: str = ""):
    """Evalua un ticker contra uno o todos los screeners."""
    ctx = _get_context()
    from idos.workers.data.refresh_worker import DataRefreshWorker
    worker = DataRefreshWorker({"journal_path": str(ctx.journal_path)})
    result = worker.execute({"tickers": [ticker], "max_tickers": 1})
    if result.status == "failed":
        console.print(f"[red]Error obteniendo datos: {result.error}[/red]")
        return
    data = result.output.get("data", {}).get(ticker, {}).get("merged_data", {})
    if not data:
        console.print(f"[yellow]No hay datos financieros para {ticker.upper()}[/yellow]")
        return

    s = _get_screener()
    if name:
        passed = s.run(data, name)
        console.print(f"[bold]Screener: {name}[/bold]")
        color = "green" if passed else "red"
        console.print(f"  Resultado: [{color}]{'PASA' if passed else 'NO PASA'}[/{color}]")
        return

    results = s.run_all(data)
    table = Table(title=f"Screeners: {ticker.upper()}")
    table.add_column("Screener", style="cyan")
    table.add_column("Resultado")
    for screener_name, passed in results.items():
        color = "green" if passed else "red"
        table.add_row(screener_name, f"[{color}]{'PASA' if passed else 'NO PASA'}[/{color}]")
    console.print(table)

# ──────────────────────────────────────────────
# UNIVERSE PIPELINE COMMANDS
# ──────────────────────────────────────────────

@app.command()
def universe_build():
    """Ejecuta el pipeline completo: Finviz → Filter → Fetch → Scout."""
    ctx = _get_context()
    config = {
        "config_path": str(ctx.config_path.parent / "idos-config"),
        "journal_path": str(ctx.journal_path),
        "cache_path": str(ctx.config_path.parent / "cache"),
    }
    from idos.workers.data.universe_pipeline import UniversePipeline
    worker = UniversePipeline(config)
    result = worker.execute({})
    if result.status == "failed":
        console.print(f"[red]Pipeline failed: {result.error}[/red]")
        return
    output = result.output
    console.print(f"\n[green]Pipeline completed in {output.get('duration_seconds', 0):.0f}s[/green]")
    console.print(f"  Finviz: {output.get('finviz_count', 0)} tickers")
    console.print(f"  Operable: {output.get('operable_count', 0)} tickers")
    console.print(f"  Fetched: {output.get('fetch_new', 0)} new, {output.get('fetch_cached', 0)} cached")
    console.print(f"  Scout: {output.get('scout_passed', 0)} passed, {output.get('scout_rejected', 0)} rejected")

@app.command()
def universe_fetch():
    """Fetch datos financieros para tickers operables sin cache."""
    ctx = _get_context()
    from idos.discovery.operability import OperabilityFilter
    from idos.workers.data.refresh_worker import DataRefreshWorker
    operable_path = str(ctx.config_path.parent / "idos-config/universe/operable.yml")
    operable = OperabilityFilter(operable_path)
    tickers = sorted(operable.tickers)
    if not tickers:
        console.print("[yellow]No operable tickers found[/yellow]")
        return
    console.print(f"[cyan]Fetching data for {len(tickers)} operable tickers...[/cyan]")
    config = {
        "journal_path": str(ctx.journal_path),
        "cache_path": str(ctx.config_path.parent / "cache"),
    }
    refresher = DataRefreshWorker(config)
    result = refresher.execute({"tickers": tickers})
    if result.status == "failed":
        console.print(f"[red]Fetch failed: {result.error}[/red]")
        return
    data = result.output.get("data", {})
    console.print(f"[green]Fetched data for {len(data)} tickers[/green]")

@app.command()
def universe_status():
    """Muestra estadisticas del universo y cache."""
    ctx = _get_context()
    from idos.discovery.operability import OperabilityFilter
    operable_path = str(ctx.config_path.parent / "idos-config/universe/operable.yml")
    operable = OperabilityFilter(operable_path)
    op_stats = operable.stats()

    cache_path = Path(ctx.config_path.parent / "cache")
    cached_files = list(cache_path.glob("*.json")) if cache_path.exists() else []
    cached_tickers = [f.stem for f in cached_files if f.stem != "finviz_screener_cache"]

    info = Panel.fit(
        f"[bold]Universe Status[/bold]\n\n"
        f"Operable tickers: {op_stats['total']}\n"
        f"Cached tickers: {len(cached_tickers)}\n"
        f"Cache directory: {cache_path}",
        title="Pipeline Status",
    )
    console.print(info)


# ── Auto-Fix Agent CLI ──────────────────────────────────────────────────

@app.command()
def auto_fix_list():
    """Lista Issues con auto-fix-pendientes."""
    import requests, os
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        console.print("[red]GH_TOKEN or GITHUB_TOKEN required[/red]")
        return
    repo = "alebertolli/idos"
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/issues?labels=auto-fix-proposed,auto-fix-analyzed&state=open",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        console.print(f"[red]API error: {resp.status_code}[/red]")
        return
    issues = resp.json()
    if not issues:
        console.print("[yellow]No open auto-fix issues found[/yellow]")
        return
    table = Table(title="Auto-Fix Issues")
    table.add_column("#", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Labels", style="green")
    for issue in issues:
        labels_str = ", ".join(l["name"] for l in issue.get("labels", []))
        table.add_row(str(issue["number"]), issue["title"], labels_str)
    console.print(table)


@app.command()
def auto_fix_show(issue_number: int = typer.Argument(..., help="Issue number")):
    """Muestra detalle de una Issue + plan de fix."""
    import requests, os
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        console.print("[red]GH_TOKEN or GITHUB_TOKEN required[/red]")
        return
    repo = "alebertolli/idos"
    issue = requests.get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    comments = requests.get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    panel = Panel.fit(
        f"[bold]Issue #{issue_number}[/bold]\n\n"
        f"Title: {issue.get('title', '?')}\n"
        f"State: {issue.get('state', '?')}\n"
        f"Labels: {', '.join(l['name'] for l in issue.get('labels', []))}\n"
        f"URL: {issue.get('html_url', '?')}",
        title="Issue Details",
    )
    console.print(panel)

    for comment in comments:
        if "## 🔧 Auto-Fix Plan" in comment.get("body", ""):
            console.print(Panel(comment["body"][:2000], title="Auto-Fix Plan"))
            break
    else:
        console.print("[yellow]No fix plan found yet. Run: idos auto-fix analyze <number>[/yellow]")


@app.command()
def auto_fix_analyze(issue_number: int = typer.Argument(..., help="Issue number")):
    """Analiza error y genera plan de fix via LLM."""
    from idos.workers.automation.auto_fix_agent import AutoFixAgent
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    agent = AutoFixAgent({"token": token})
    with console.status(f"[bold green]Analyzing issue #{issue_number}..."):
        result = agent.execute({"action": "analyze", "issue_number": issue_number})
    r = result.output if hasattr(result, "output") else result
    console.print(f"[green]Analyzed issue #{issue_number}[/green]")
    if "fix_plan" in r:
        console.print(Panel(json_lib.dumps(r["fix_plan"], indent=2), title="Fix Plan"))
    console.print("[bold]Run [cyan]idos auto-fix apply <number>[/cyan] to apply[/bold]")


@app.command()
def auto_fix_apply(issue_number: int = typer.Argument(..., help="Issue number")):
    """Aplica el plan de fix y crea un Pull Request."""
    from idos.workers.automation.auto_fix_agent import AutoFixAgent
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    agent = AutoFixAgent({"token": token})
    with console.status(f"[bold green]Applying fix for issue #{issue_number}..."):
        result = agent.execute({"action": "apply", "issue_number": issue_number})
    r = result.output if hasattr(result, "output") else result
    if r.get("status") == "pr_created":
        console.print(f"[green]PR created: {r['pr_url']}[/green]")
    else:
        console.print(f"[red]Apply failed: {r}[/red]")


@app.command()
def site_build(
    output: str = typer.Option("site", help="Directorio de salida de la UI estática"),
    stale_days: int = typer.Option(30, help="Días sin investigación para marcar stale"),
):
    """Genera la UI estática (HTML+JSON) publicable en GitHub Pages."""
    from idos.site.builder import write_site
    ctx = _get_context()
    with console.status("[bold green]Generando sitio estático..."):
        out = write_site(ctx.journal_path.parent, Path(output), stale_days=stale_days)
    console.print(f"[green]Sitio generado en {out}[/green]")
