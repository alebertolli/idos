import pytest
import tempfile
from pathlib import Path
from idos.ai.prompts import PromptRegistry, PromptTemplate


class TestPromptRegistry:
    def test_register_and_load(self):
        pr = PromptRegistry()
        pr.register("ddd", system_prompt="You are a DDD analyst", user_prompt="Analyze {ticker}",
                     category="research")
        t = pr.load("ddd")
        assert t is not None
        assert t.system_prompt == "You are a DDD analyst"

    def test_get_formatted(self):
        pr = PromptRegistry()
        pr.register("scout", user_prompt="Screen {ticker} in {sector}")
        result = pr.get("scout", ticker="AAPL", sector="Tech")
        assert result == "Screen AAPL in Tech"

    def test_get_missing_key_returns_unformatted(self):
        pr = PromptRegistry()
        pr.register("test", user_prompt="Hello {name}")
        result = pr.get("test", wrong_key="World")
        assert result == "Hello {name}"

    def test_load_nonexistent(self):
        pr = PromptRegistry()
        assert pr.load("nonexistent") is None

    def test_list_by_category(self):
        pr = PromptRegistry()
        pr.register("a", category="scout")
        pr.register("b", category="scout")
        pr.register("c", category="research")
        assert len(pr.list_by_category("scout")) == 2
        assert len(pr.list_by_category("research")) == 1

    def test_load_from_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            scout_dir = Path(tmp) / "scout"
            scout_dir.mkdir()
            (scout_dir / "size.yml").write_text(
                "system_prompt: You are a size analyst\nuser_prompt: Analyze {ticker}\n"
            )
            pr = PromptRegistry(tmp)
            t = pr.load("size")
            assert t is not None
            assert "size analyst" in t.system_prompt
