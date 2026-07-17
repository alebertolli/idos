from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


@dataclass
class PromptTemplate:
    name: str
    system_prompt: str = ""
    user_prompt: str = ""
    category: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class PromptRegistry:
    def __init__(self, prompts_dir: str | Path | None = None):
        self._templates: dict[str, PromptTemplate] = {}
        self._prompts_dir = Path(prompts_dir) if prompts_dir else None
        if self._prompts_dir and self._prompts_dir.exists():
            self._load_all()

    def _load_all(self):
        for yml_file in self._prompts_dir.rglob("*.yml"):
            name = yml_file.stem
            category = yml_file.parent.name
            try:
                with open(yml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._templates[name] = PromptTemplate(
                    name=name,
                    system_prompt=data.get("system_prompt", ""),
                    user_prompt=data.get("user_prompt", ""),
                    category=category,
                    metadata={k: v for k, v in data.items() if k not in ("system_prompt", "user_prompt")},
                )
            except Exception:
                pass

    def load(self, name: str, category: str = "") -> PromptTemplate | None:
        if category:
            return self._templates.get(f"{category}_{name}") or self._templates.get(name)
        return self._templates.get(name)

    def get(self, name: str, category: str = "", **kwargs: Any) -> str | None:
        template = self.load(name, category)
        if not template:
            return None
        try:
            return template.user_prompt.format(**kwargs)
        except KeyError:
            return template.user_prompt

    def get_system(self, name: str, category: str = "") -> str | None:
        template = self.load(name, category)
        return template.system_prompt if template else None

    def register(self, name: str, system_prompt: str = "", user_prompt: str = "",
                 category: str = "", metadata: dict[str, Any] | None = None):
        self._templates[name] = PromptTemplate(
            name=name, system_prompt=system_prompt, user_prompt=user_prompt,
            category=category, metadata=metadata or {},
        )

    def list_by_category(self, category: str) -> list[PromptTemplate]:
        return [t for t in self._templates.values() if t.category == category]

    def all(self) -> list[PromptTemplate]:
        return list(self._templates.values())

    def count(self) -> int:
        return len(self._templates)
