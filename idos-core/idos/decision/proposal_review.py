"""Versioned manager review for deterministic Decision proposals."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def decision_proposal_fingerprint(proposal: dict[str, Any]) -> str:
    """Fingerprint an Assessment snapshot, ignoring only its review metadata."""
    canonical = {key: value for key, value in proposal.items() if key not in {"status", "manager_review"}}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
