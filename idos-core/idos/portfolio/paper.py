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
        self._capture_entry_snapshot(ticker, opp_id, price, qty, value, stop_loss,
                                     intrinsic_value, conviction)

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

    def sell(self, ticker: str, price: float, reason: str, exit_pct: float = 1.0) -> dict[str, Any]:
        pos = self._load_position(ticker)
        if not pos:
            return {"status": "skipped", "reason": f"No position for {ticker}"}

        exit_pct = max(0.0, min(float(exit_pct), 1.0))
        if exit_pct <= 0:
            return {"status": "skipped", "reason": "exit_pct must be > 0"}

        total_qty = pos["quantity"]
        sell_qty = int(round(total_qty * exit_pct))
        if sell_qty <= 0:
            return {"status": "skipped", "reason": f"exit_pct {exit_pct:.2f} too small for {total_qty} shares"}

        value = round(sell_qty * price, 2)
        fee = round(value * (self.fee_pct / 100), 2)
        cost_basis_total = pos["total_invested"]
        cost_basis_sold = round(cost_basis_total * (sell_qty / total_qty), 2)
        pnl = round(value - cost_basis_sold - fee, 2)
        pnl_pct = round((pnl / cost_basis_sold) * 100, 2) if cost_basis_sold else 0

        trade = Trade(
            ticker=ticker.upper(),
            type="SELL",
            price=price,
            quantity=sell_qty,
            value=value,
            fee=fee,
            reason=reason,
            opp_id=pos.get("opp_id", ""),
            pnl=pnl,
        )
        self.ledger.record(trade)

        closed = sell_qty >= total_qty
        if closed:
            self._remove_position(ticker)
            remaining_qty = 0
        else:
            remaining_qty = total_qty - sell_qty
            pos["quantity"] = remaining_qty
            pos["total_invested"] = round(cost_basis_total * (remaining_qty / total_qty), 2)
            pos["current_value"] = round(pos["quantity"] * price, 2)
            pos["updated_at"] = datetime.now(AR_TZ).isoformat()
            self._write_position(pos)

        print(f"[PAPER] SELL {ticker}: {sell_qty} shares @ ${price:.2f} = ${value:.2f} (P&L=${pnl:.2f}/{pnl_pct:+.2f}%, exit_pct={exit_pct*100:.0f}%)")
        return {
            "status": "executed",
            "ticker": ticker,
            "type": "SELL",
            "price": price,
            "quantity": sell_qty,
            "value": value,
            "fee": fee,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_pct": exit_pct,
            "closed": closed,
            "remaining_quantity": remaining_qty,
        }

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
        self._write_position(pos)

    def _capture_entry_snapshot(self, ticker: str, opp_id: str, price: float, qty: int,
                                value: float, stop_loss: float, target: float,
                                conviction: int):
        """Fija el snapshot analitico del momento exacto de la entrada."""
        try:
            from idos.portfolio.entry_snapshot import build_entry_snapshot, save_entry_snapshot
            snapshot = build_entry_snapshot(self.journal, ticker, opp_id, {
                "entry_price": price,
                "quantity": qty,
                "total_invested": value,
                "stop_loss": stop_loss,
                "target_price": target,
                "intrinsic_value": target,
                "conviction": conviction,
                "current_price": price,
                "entry_date": datetime.now(AR_TZ).isoformat(),
            })
            save_entry_snapshot(self.journal, ticker, opp_id, snapshot)
            print(f"[PAPER] entry snapshot for {ticker} saved")
        except Exception as e:
            print(f"[PAPER] error capturando entry snapshot {ticker}: {e}")

    def _write_position(self, pos: dict[str, Any]):
        path = self._position_path(pos["ticker"])
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
