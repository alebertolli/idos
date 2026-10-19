from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IDOSContext:
    knowledge_path: Path
    journal_path: Path
    config_path: Path
    sqlite_path: Path = field(default_factory=lambda: Path.home() / ".idos" / "idos.db")

    @classmethod
    def create(cls, base_path: Path) -> "IDOSContext":
        return cls(
            knowledge_path=base_path / "idos-knowledge",
            journal_path=base_path / "idos-journal",
            config_path=base_path / "idos-config",
            sqlite_path=base_path / "idos.db",
        )

    @classmethod
    def defaults(cls) -> "IDOSContext":
        return cls(
            knowledge_path=Path("idos-knowledge"),
            journal_path=Path("idos-journal"),
            config_path=Path("idos-config"),
        )
