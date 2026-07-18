import json as json_lib
import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime, UTC
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

app = typer.Typer(name="idos", help="Investment Decision Operating System")
console = Console()
state_machine = OpportunityStateMachine()


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
    opp_id = f"OPP-{datetime.now(datetime.UTC).strftime('%Y%m%d')}-{len(sqlite.list_opportunities()) + 1:03d}"
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
def opp_list(status: str = ""):
    ctx = _get_context()
    sqlite, _, _ = _get_stores(ctx)
    opps = sqlite.list_opportunities(status.upper() if status else None)
    if not opps:
        console.print("[yellow]No opportunities found[/yellow]")
        return
    table = Table(title="Opportunities")
    table.add_column("ID", style="cyan")
    table.add_column("Ticker")
    table.add_column("Status")
    table.add_column("Conviction")
    table.add_column("Updated")
    for opp in opps:
        conv = opp.get("conviction", {}).get("overall", "N/A")
        table.add_row(opp["id"], opp["ticker"], opp["status"], str(conv), opp["updated_at"][:10])
    console.print(table)


@app.command()
def opp_transition(opp_id: str, target: str):
    ctx = _get_context()
    sqlite, _, _ = _get_stores(ctx)
    opp_data = sqlite.get_opportunity(opp_id)
    if not opp_data:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return
    current = OpportunityStatus(opp_data["status"])
    target_status = OpportunityStatus(target.upper())
    try:
        transition = state_machine.transition(current, target_status, cause="cli command")
        sqlite.save_opportunity({**opp_data, "status": target_status.value})
        sqlite.record_transition(opp_id, current.value, target_status.value, cause="cli command")
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
    entries = journal.load_watchlist()
    if not entries:
        console.print("[yellow]Watchlist is empty[/yellow]")
        return
    table = Table(title="Watchlist")
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
    positions = engine.get_positions()
    watchlist = engine.get_watchlist()
    total_weight = engine.total_weight()
    active_opps = [o for o in opps if o["status"] not in ("ARCHIVED", "EXITED")]

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
def event_log():
    ctx = _get_context()
    sqlite, _, _ = _get_stores(ctx)
    bus = get_event_bus()
    history = bus.get_history()
    if not history:
        console.print("[yellow]No events[/yellow]")
        return
    table = Table(title="Recent Events")
    table.add_column("Type")
    table.add_column("Source")
    table.add_column("Timestamp")
    for e in history[-20:]:
        table.add_row(e.type, e.source, e.timestamp.isoformat()[:19])
    console.print(table)


# ──────────────────────────────────────────────
# MANUAL INTERVENTION COMMANDS (no UI required)
# ──────────────────────────────────────────────

@app.command()
def opp_research(ticker: str, opp_id: str = ""):
    """Ejecuta DDD + AOIF + Hypothesis sobre una oportunidad (WATCHLIST → UNDER_DEEP_DD)."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities("WATCHLIST")
        matching = [o for o in opps if o["ticker"] == ticker.upper()]
        if not matching:
            console.print(f"[red]No WATCHLIST opportunities found for {ticker.upper()}[/red]")
            return
        opp_id = matching[0]["id"]

    opp = sqlite.get_opportunity(opp_id)
    if not opp:
        console.print(f"[red]Opportunity {opp_id} not found[/red]")
        return

    console.print(f"[cyan]Researching {ticker} ({opp_id})...[/cyan]")
    from idos.workers.ai.research_worker import ResearchWorker
    worker = ResearchWorker({})
    result = worker.execute({
        "ticker": ticker,
        "opp_id": opp_id,
        "base_path": str(ctx.config_path.parent),
    })
    if result.status == "failed":
        console.print(f"[red]Research failed: {result.error}[/red]")
        return
    output = result.output
    table = Table(title=f"Research Results: {ticker}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Status", output.get("status", "N/A"))
    table.add_row("Score", str(output.get("score", "N/A")))
    table.add_row("Classification", output.get("classification", "N/A"))
    table.add_row("Market Error", output.get("market_error_conclusion", "N/A"))
    table.add_row("Hypotheses", str(output.get("hypotheses_count", 0)))
    console.print(table)


@app.command()
def opp_approve(ticker: str, opp_id: str = ""):
    """Evalúa DDD vs reglas de entrada (UNDER_DEEP_DD → APPROVED o WATCHLIST)."""
    ctx = _get_context()
    sqlite, _, _ = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities("UNDER_DEEP_DD")
        matching = [o for o in opps if o["ticker"] == ticker.upper()]
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
        matching = [o for o in opps if o["ticker"] == ticker.upper() and o["status"] in ("UNDER_DEEP_DD",)]
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
    opp["updated_at"] = datetime.now(UTC).isoformat()
    sqlite.save_opportunity(opp)
    sqlite.record_transition(opp_id, old_status, "WATCHLIST", cause=reason, worker="cli")
    console.print(f"[yellow]{ticker} ({opp_id}): {old_status} → WATCHLIST (reason: {reason})[/yellow]")


@app.command()
def entry_evaluate(ticker: str, opp_id: str = ""):
    """Evalúa condiciones de entrada para oportunidad APPROVED/ENTRY_PENDING."""
    ctx = _get_context()
    sqlite, _, _ = _get_stores(ctx)

    if not opp_id:
        opps = sqlite.list_opportunities()
        matching = [o for o in opps if o["ticker"] == ticker.upper()
                    and o["status"] in ("APPROVED", "ENTRY_PENDING")]
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
        matching = [o for o in opps if o["ticker"] == ticker.upper()
                    and o["status"] in ("MONITORING", "FULL_POSITION", "ACCUMULATING")]
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
        "stop_loss": "Stop loss activado",
        "portfolio_rebalance": "Reemplazo por mejor oportunidad",
        "risk_trigger": "Riesgo permanente detectado",
        "manual": "Decisión manual del inversor",
    }
    if reason not in valid_reasons:
        console.print(f"[red]Invalid reason. Options: {', '.join(valid_reasons.keys())}[/red]")
        return

    old_status = opp["status"]
    opp["status"] = "EXITED"
    opp["updated_at"] = datetime.now(UTC).isoformat()
    sqlite.save_opportunity(opp)
    sqlite.record_transition(opp_id, old_status, "EXITED", cause=reason, worker="cli")
    console.print(f"[yellow]{ticker}: {old_status} → EXITED ({valid_reasons[reason]})[/yellow]")

    position = journal.load_position(ticker.upper())
    if position:
        position["status"] = "CLOSED"
        position["exit_reason"] = reason
        position["exited_at"] = datetime.now(UTC).isoformat()
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
def opp_show(ticker: str, opp_id: str = ""):
    """Muestra estado completo de una oportunidad."""
    ctx = _get_context()
    sqlite, _, journal = _get_stores(ctx)

    if opp_id:
        opps = [sqlite.get_opportunity(opp_id)] if sqlite.get_opportunity(opp_id) else []
    else:
        opps = sqlite.list_opportunities()
        opps = [o for o in opps if o["ticker"] == ticker.upper()]

    if not opps:
        console.print(f"[red]No opportunities found for {ticker.upper()}[/red]")
        return

    for opp in opps:
        info = Panel.fit(
            f"[bold]Opportunity: {opp['id']}[/bold]\n\n"
            f"Ticker: {opp['ticker']}\n"
            f"Status: {opp['status']}\n"
            f"Conviction: {opp.get('conviction', {}).get('overall', 'N/A')}\n"
            f"Created: {opp.get('created_at', 'N/A')[:10]}\n"
            f"Updated: {opp.get('updated_at', 'N/A')[:10]}",
            title="Opportunity Detail",
        )
        console.print(info)

        # Show transitions
        rows = sqlite.conn.execute(
            "SELECT from_status, to_status, cause, timestamp FROM state_transitions "
            "WHERE opportunity_id = ? ORDER BY timestamp DESC LIMIT 10",
            (opp["id"],),
        )
        transitions = list(rows.fetchall())
        if transitions:
            t_table = Table(title="Recent Transitions")
            t_table.add_column("From")
            t_table.add_column("To")
            t_table.add_column("Cause")
            t_table.add_column("When")
            for t in transitions:
                t_table.add_row(t["from_status"], t["to_status"],
                                t["cause"], t["timestamp"][:19])
            console.print(t_table)


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


if __name__ == "__main__":
    app()
