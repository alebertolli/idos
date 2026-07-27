from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict[str, Any] | None:
    import yaml
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
