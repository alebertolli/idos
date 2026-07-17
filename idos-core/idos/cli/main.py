import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime

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
              "idos-config/prompts/scout", "idos-config/prompts/research", "idos-config/rules"]:
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


if __name__ == "__main__":
    app()
