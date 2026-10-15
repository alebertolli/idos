"""Convert Google Sheets Values API rows to a validated private snapshot.

This adapter is deliberately transport agnostic: credentials, Drive access and
the Sheets client belong to a private deployment boundary. It never writes data.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from idos.portfolio.audit import PortfolioAuditError


_HEADERS = {
    "Positions": ("position_id", "account_id", "instrument_id", "issuer",
                  "economic_cluster", "strategy_id", "sleeve", "sector",
                  "country", "argentina_risk_bucket", "currency",
                  "market_value", "source_ref"),
    "Cash": ("cash_id", "account_id", "currency", "balance", "source_ref"),
    "Obligations": ("obligation_id", "account_id", "due_date", "currency",
                    "amount", "status", "source_ref"),
    "FX": ("currency", "to_base", "as_of", "source_ref"),
}
_SNAPSHOT_KEYS = ("snapshot_id", "as_of", "base_currency", "source_version")


def _cell(row: Sequence[Any], index: int) -> Any:
    return row[index] if index < len(row) else ""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioAuditError(f"{label} is required")
    return value.strip()


def _date(value: Any, label: str) -> str:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        serial = _amount(value, label)
        if serial != serial.to_integral_value():
            raise PortfolioAuditError(f"{label} must be a calendar date")
        try:
            return (date(1899, 12, 30) + timedelta(days=int(serial))).isoformat()
        except (OverflowError, ValueError) as exc:
            raise PortfolioAuditError(f"{label} must be a valid date") from exc
    result = _text(value, label)
    try:
        date.fromisoformat(result)
    except ValueError as exc:
        raise PortfolioAuditError(f"{label} must be YYYY-MM-DD") from exc
    return result


def _amount(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise PortfolioAuditError(f"{label} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PortfolioAuditError(f"{label} must be a finite number") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise PortfolioAuditError(f"{label} must be a finite positive number")
    return result


def _table_rows(sheet: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(sheet, list) or not sheet:
        raise PortfolioAuditError(f"sheets.{name} must contain a header row")
    if not isinstance(sheet[0], (list, tuple)) or not all(isinstance(v, str) for v in sheet[0]):
        raise PortfolioAuditError(f"sheets.{name} headers must be text")
    header = tuple(v.strip() for v in sheet[0])
    expected = _HEADERS[name]
    if header != expected:
        raise PortfolioAuditError(f"sheets.{name} headers do not match schema v1.0")
    rows: list[dict[str, Any]] = []
    for index, cells in enumerate(sheet[1:], start=2):
        if not isinstance(cells, (list, tuple)):
            raise PortfolioAuditError(f"sheets.{name} row {index} must be a row")
        values = [_cell(cells, i) for i in range(len(expected))]
        if all(value is None or not str(value).strip() for value in values):
            continue
        if len(cells) > len(expected) and any(str(v).strip() for v in cells[len(expected):]):
            raise PortfolioAuditError(f"sheets.{name} row {index} has unexpected values")
        rows.append(dict(zip(expected, values)))
    return rows


def snapshot_from_sheets_values(sheets: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a complete, one-read Sheets export and return audit input.

    ``sheets`` maps tab names to Google Sheets Values API row arrays using
    UNFORMATTED_VALUE for amounts and dates. Date strings in ISO format and
    integral Google Sheets date serials are accepted. Snapshot is a key/value
    tab; the other four tabs include their exact headers as row one.
    """
    if not isinstance(sheets, Mapping):
        raise PortfolioAuditError("sheets must be an object")
    required_tabs = {"Snapshot", *_HEADERS}
    if not required_tabs.issubset(sheets):
        missing = sorted(required_tabs - set(sheets))
        raise PortfolioAuditError(f"missing sheets: {', '.join(missing)}")

    raw_meta = sheets["Snapshot"]
    if not isinstance(raw_meta, list):
        raise PortfolioAuditError("sheets.Snapshot must contain key/value rows")
    meta: dict[str, Any] = {}
    allowed_meta = set(_SNAPSHOT_KEYS)
    for index, cells in enumerate(raw_meta, start=1):
        if not isinstance(cells, (list, tuple)) or len(cells) < 2:
            continue
        key = str(cells[0]).strip()
        if key not in allowed_meta:
            continue
        if key in meta:
            raise PortfolioAuditError(f"duplicate Snapshot key: {key}")
        meta[key] = cells[1]
    if set(meta) != allowed_meta:
        raise PortfolioAuditError("Snapshot requires snapshot_id, as_of, base_currency and source_version")
    if _amount(meta["source_version"], "Snapshot.source_version", positive=True) != Decimal("1.0"):
        raise PortfolioAuditError("Snapshot.source_version must be 1.0")
    snapshot_id = _text(meta["snapshot_id"], "Snapshot.snapshot_id")
    as_of = _date(meta["as_of"], "Snapshot.as_of")
    base = _text(meta["base_currency"], "Snapshot.base_currency").upper()
    if len(base) != 3 or not base.isalpha():
        raise PortfolioAuditError("Snapshot.base_currency must be a three-letter code")

    positions = _table_rows(sheets["Positions"], "Positions")
    cash = _table_rows(sheets["Cash"], "Cash")
    obligations = _table_rows(sheets["Obligations"], "Obligations")
    fx_rows = _table_rows(sheets["FX"], "FX")
    if not positions:
        raise PortfolioAuditError("sheets.Positions must contain at least one position")

    fx: dict[str, str] = {}
    for index, row in enumerate(fx_rows):
        label = f"FX[{index}]"
        currency = _text(row["currency"], f"{label}.currency").upper()
        if len(currency) != 3 or not currency.isalpha():
            raise PortfolioAuditError(f"{label}.currency must be a three-letter code")
        if currency in fx:
            raise PortfolioAuditError(f"duplicate FX currency: {currency}")
        rate = _amount(row["to_base"], f"{label}.to_base", positive=True)
        fx_date = _date(row["as_of"], f"{label}.as_of")
        if fx_date > as_of:
            raise PortfolioAuditError(f"{label}.as_of is after snapshot.as_of")
        fx[currency] = str(rate)
        _text(row["source_ref"], f"{label}.source_ref")
    if base not in fx or _amount(fx[base], f"FX.{base}", positive=True) != 1:
        raise PortfolioAuditError("FX must include base currency at rate 1")

    def validate_rows(rows: list[dict[str, Any]], id_key: str, amount_key: str,
                      label: str, *, allow_zero_or_negative: bool = False) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result = []
        for index, row in enumerate(rows):
            prefix = f"{label}[{index}]"
            identifier = _text(row[id_key], f"{prefix}.{id_key}")
            if identifier in seen:
                raise PortfolioAuditError(f"duplicate {id_key}: {identifier}")
            seen.add(identifier)
            _text(row["account_id"], f"{prefix}.account_id")
            currency = _text(row["currency"], f"{prefix}.currency").upper()
            if currency not in fx:
                raise PortfolioAuditError(f"missing FX rate for {currency}")
            amount = _amount(row[amount_key], f"{prefix}.{amount_key}")
            if not allow_zero_or_negative and amount <= 0:
                raise PortfolioAuditError(f"{prefix}.{amount_key} must be a finite positive number")
            _text(row["source_ref"], f"{prefix}.source_ref")
            normalized = dict(row)
            normalized["currency"] = currency
            normalized[amount_key] = str(amount)
            result.append(normalized)
        return result

    positions = validate_rows(positions, "position_id", "market_value", "Positions")
    cash = validate_rows(cash, "cash_id", "balance", "Cash", allow_zero_or_negative=True)
    obligations = validate_rows(obligations, "obligation_id", "amount", "Obligations")
    for index, row in enumerate(obligations):
        due = _date(row["due_date"], f"Obligations[{index}].due_date")
        if _text(row["status"], f"Obligations[{index}].status").upper() != "PENDING":
            raise PortfolioAuditError(f"Obligations[{index}].status must be PENDING")
        row["due_date"] = due

    used_currencies = {row["currency"] for row in positions + cash + obligations}
    missing_fx = sorted(used_currencies - set(fx))
    if missing_fx:
        raise PortfolioAuditError(f"missing FX rate for {', '.join(missing_fx)}")
    return {
        "snapshot_id": snapshot_id,
        "source_version": "1.0",
        "as_of": as_of,
        "base_currency": base,
        "fx_to_base": fx,
        "positions": positions,
        "cash": cash,
        "obligations": obligations,
    }
