from datetime import datetime
from pathlib import Path
from typing import Any
import yaml

from idos.timezone import AR_TZ
from idos.portfolio.ledger import Trade, TradeLedger


class PaperTrader:
    def __init__(self, config: dict[str, Any], journal):
        self.bankroll = config.get("bankroll", 100000)
        self.max_position_pct = config.get("max_position_pct", 3.0)
        self.fee_pct = config.get("fee_pct", 0.1)
        self.asymmetry_divisor = config.get("stop_loss_asymmetry_divisor", 3)
        self.ledger = TradeLedger(journal)
        self.journal = journal

    def calculate_stop_loss(self, entry_price: float, intrinsic_value: float) -> float:
        upside_pct = ((intrinsic_value - entry_price) / entry_price) * 100
        if upside_pct <= 0:
            return round(entry_price * 0.8, 2)
        risk_pct = upside_pct / self.asymmetry_divisor
        stop_price = entry_price * (1 - risk_pct / 100)
        return round(stop_price, 2)

    def calculate_quantity(self, price: float) -> int:
        if price <= 0:
            return 0
        max_value = self.bankroll * (self.max_position_pct / 100)
        fee = max_value * (self.fee_pct / 100)
        investable = max_value - fee
        qty = int(investable / price)
        return max(qty, 0)

    def buy(self, ticker: str, price: float, conviction: int, opp_id: str, intrinsic_value: float) -> dict[str, Any]:
        existing_qty = self.ledger.net_position(ticker)
        if existing_qty > 0:
            return {"status": "skipped", "reason": f"{ticker} already held ({existing_qty} shares)"}

        qty = self.calculate_quantity(price)
        if qty <= 0:
            return {"status": "error", "reason": f"Quantity <= 0 at price {price}"}

        value = round(qty * price, 2)
        fee = round(value * (self.fee_pct / 100), 2)
        stop_loss = self.calculate_stop_loss(price, intrinsic_value)

        trade = Trade(
            ticker=ticker.upper(),
            type="BUY",
            price=price,
            quantity=qty,
            value=value,
            fee=fee,
            reason="entry_monitor",
            opp_id=opp_id,
        )
        self.ledger.record(trade)
        self._save_position(ticker, opp_id, price, qty, value, stop_loss, intrinsic_value, conviction)

        position_pct = round(value / self.bankroll * 100, 2)
        print(f"[PAPER] BUY {ticker}: {qty} shares @ ${price:.2f} = ${value:.2f} ({position_pct}% of portfolio, SL=${stop_loss:.2f})")
        return {
            "status": "executed",
            "ticker": ticker,
            "type": "BUY",
            "price": price,
            "quantity": qty,
            "value": value,
            "fee": fee,
            "stop_loss": stop_loss,
            "position_pct": position_pct,
        }

    def sell(self, ticker: str, price: float, reason: str) -> dict[str, Any]:
        pos = self._load_position(ticker)
        if not pos:
            return {"status": "skipped", "reason": f"No position for {ticker}"}

        qty = pos["quantity"]
        value = round(qty * price, 2)
        fee = round(value * (self.fee_pct / 100), 2)
        cost_basis = pos["total_invested"]
        pnl = round(value - cost_basis - fee, 2)
        pnl_pct = round((pnl / cost_basis) * 100, 2) if cost_basis else 0

        trade = Trade(
            ticker=ticker.upper(),
            type="SELL",
            price=price,
            quantity=qty,
            value=value,
            fee=fee,
            reason=reason,
            opp_id=pos.get("opp_id", ""),
            pnl=pnl,
        )
        self.ledger.record(trade)
        self._remove_position(ticker)

        print(f"[PAPER] SELL {ticker}: {qty} shares @ ${price:.2f} = ${value:.2f} (P&L=${pnl:.2f}/{pnl_pct:+.2f}%)")
        return {
            "status": "executed",
            "ticker": ticker,
            "type": "SELL",
            "price": price,
            "quantity": qty,
            "value": value,
            "fee": fee,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }

    def check_stops(self, current_prices: dict[str, float]) -> list[dict[str, Any]]:
        exits = []
        for pos in self.current_positions():
            ticker = pos["ticker"]
            price = current_prices.get(ticker)
            if not price:
                continue
            stop = pos.get("stop_loss", 0)
            if stop > 0 and price <= stop:
                result = self.sell(ticker, price, "stop_loss")
                exits.append(result)
        return exits

    def current_positions(self) -> list[dict[str, Any]]:
        positions = []
        pos_dir = self.journal.base / "paper" / "positions"
        if pos_dir.exists():
            for f in sorted(pos_dir.iterdir()):
                if f.suffix == ".yml":
                    p = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    if p:
                        positions.append(p)
        return positions

    def _position_path(self, ticker: str) -> Path:
        p = self.journal.base / "paper" / "positions"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{ticker.upper()}.yml"

    def _save_position(self, ticker, opp_id, price, qty, value, stop_loss, target, conviction):
        path = self._position_path(ticker)
        pos = {
            "ticker": ticker.upper(),
            "opp_id": opp_id,
            "entry_price": price,
            "quantity": qty,
            "total_invested": value,
            "current_value": value,
            "stop_loss": stop_loss,
            "target_price": target,
            "entry_date": datetime.now(AR_TZ).isoformat(),
            "conviction_at_entry": conviction,
        }
        path.write_text(
            yaml.dump(pos, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _load_position(self, ticker: str) -> dict[str, Any] | None:
        path = self._position_path(ticker)
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or None
        return None

    def _remove_position(self, ticker: str):
        path = self._position_path(ticker)
        if path.exists():
            path.unlink()
