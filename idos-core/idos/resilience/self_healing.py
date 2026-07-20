import json
import re
from typing import Any


class SelfHealer:
    def repair_json(self, text: str) -> str | None:
        text = text.strip()
        if not text:
            return None

        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        text = re.sub(r",\s*([\]}])", r"\1", text)

        text = re.sub(r"'", '"', text)

        text = re.sub(r"(?<!\\)\\(?![/\"\\bftnru])", "\\\\", text)

        text = re.sub(r",\s*$", "", text.strip())

        text = re.sub(r"(?<=[{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'"\1":', text)

        if not text.startswith("{"):
            idx = text.find("{")
            if idx >= 0:
                text = text[idx:]
        if not text.endswith("}"):
            idx = text.rfind("}")
            if idx >= 0:
                text = text[: idx + 1]

        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        try:
            text = text.replace("True", "true").replace("False", "false").replace("None", "null")
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        return None

    def repair_markdown_frontmatter(self, text: str) -> str | None:
        lines = text.split("\n")
        if not lines or lines[0].strip() != "---":
            return text

        end_idx = -1
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                end_idx = i
                break

        if end_idx < 0:
            return text

        frontmatter = lines[1:end_idx]
        repaired = []
        for line in frontmatter:
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if not value:
                    value = '""'
                elif value.lower() in ("true", "false", "yes", "no"):
                    value = value.lower()
                    if value in ("yes", "no"):
                        value = "true" if value == "yes" else "false"
                repaired.append(f"{key}: {value}")
            else:
                repaired.append(line)

        result = "---\n" + "\n".join(repaired) + "\n---\n" + "\n".join(lines[end_idx + 1 :])
        return result

    def parse_with_healing(self, text: str) -> dict[str, Any] | None:
        repaired = self.repair_json(text)
        if repaired:
            return json.loads(repaired)
        return None
