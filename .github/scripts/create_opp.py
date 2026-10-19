#!/usr/bin/env python3
"""Create a new DISCOVERED opportunity on the fly (used by DDD pipeline)."""

import json
import sys
from datetime import datetime
from pathlib import Path

from idos.data.sqlite import SQLiteStore
from idos.data.journal import JournalRepository
from idos.timezone import AR_TZ


def create_opp(ticker, journal_path="idos-journal", force=False):
    """Create a new DISCOVERED opportunity for the given ticker."""
    journal = Path(journal_path)
    existing_opps = SQLiteStore('idos.db').list_opportunities()
    seq = len(existing_opps) + 1
    new_opp_id = f'OPP-{datetime.now(AR_TZ).strftime("%Y%m%d")}-{seq:03d}'
    now = datetime.now(AR_TZ).isoformat()
    new_opp_text = json.dumps({
        'id': new_opp_id,
        'ticker': ticker.upper(),
        'status': 'DISCOVERED',
        'conviction': {'overall': 0},
        'created_at': now,
        'updated_at': now,
    })
    jr = JournalRepository(journal)
    jr.save_opportunity(ticker, new_opp_text)
    print(f'[DDD] Created new opportunity {new_opp_id} for {ticker}')


if __name__ == '__main__':
    ticker = sys.argv[1] if len(sys.argv) > 1 else ''
    journal_path = sys.argv[2] if len(sys.argv) > 2 else 'idos-journal'
    force_flag = sys.argv[3].lower() == 'true' if len(sys.argv) > 3 else False
    create_opp(ticker, journal_path, force_flag)