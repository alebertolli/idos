"""Tests for LLMClient — stub mode (no real API calls)."""

from pathlib import Path

import yaml

from idos.ai.llm import LLMClient


def test_llm_client_defaults():
    client = LLMClient(provider="test", api_key="key", model="test-model")
    assert client.provider == "test"
    assert client.api_key == "key"
    assert client.model == "test-model"


def test_provider_model_config_uses_pinned_models_and_no_random_router():
    repo_root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((repo_root / "idos-config" / "models.yml").read_text(encoding="utf-8"))
    providers = config["llm"]["providers"]

    assert providers["gemini"]["model"] == "gemini-3.8-flash"
    assert providers["gemini"]["fallback"] == "gemini-3.7-flash"
    assert providers["groq"]["model"] == "openai/gpt-oss-120b"
    assert providers["groq"]["fallback"] == "openai/gpt-oss-20b"
    assert providers["openrouter"]["model"] == "google/gemma-4-31b-it:free"
    assert "fallback" not in providers["openrouter"]
    assert all(
        entry.get("fallback_model") != "openrouter/free"
        for entry in config["llm"]["fallback_order"]
    )


def test_generate_fallback_on_no_api_key():
    client = LLMClient(provider="openai", api_key="", model="gpt-4o")
    resp = client.generate("Hello")
    assert not resp.success
    assert resp.error != ""


def test_generate_structured_parse_json():
    client = LLMClient(provider="openai", api_key="", model="gpt-4o")
    result = client.generate_structured("Test")
    assert "error" in result
    assert result["error"] != ""


def test_generate_falls_back_on_empty_content(monkeypatch):
    from idos.ai.llm import LLMClient as LC, LLMResponse

    client = LC.__new__(LC)
    client.provider = "openai"
    client.api_key = "k"
    client.model = "m1"
    client.fallback_model = ""
    client.fallback_providers = [{"provider": "openai", "model": "m2", "api_key": "k"}]
    client.timeout = 5

    def fake_call(prompt, system_prompt, temperature, max_tokens, api_key, model):
        if model == "m1":
            return LLMResponse(content=None, success=True, model="m1")
        return LLMResponse(content="real response", success=True, model="m2")

    monkeypatch.setattr(client, "_call_openai", fake_call)

    resp = client.generate("hi")
    assert resp.success
    assert resp.content == "real response"


def test_generate_fails_when_all_providers_empty(monkeypatch):
    from idos.ai.llm import LLMClient as LC, LLMResponse

    client = LC.__new__(LC)
    client.provider = "openai"
    client.api_key = "k"
    client.model = "m1"
    client.fallback_model = ""
    client.fallback_providers = []
    client.timeout = 5

    def fake_call(prompt, system_prompt, temperature, max_tokens, api_key, model):
        return LLMResponse(content=None, success=True, model="m1")

    monkeypatch.setattr(client, "_call_openai", fake_call)

    resp = client.generate("hi")
    assert not resp.success
    assert resp.content == ""


def test_generate_structured_parse_embedded_json():
    from idos.ai.llm import LLMClient as LC

    client = LC.__new__(LC)
    client._parse_json = LC._parse_json.__get__(client)

    result = client._parse_json('{"key": "value"}')
    assert result["key"] == "value"


def test_parse_json_with_markdown_fence():
    from idos.ai.llm import LLMClient as LC

    client = LC.__new__(LC)
    client._parse_json = LC._parse_json.__get__(client)

    result = client._parse_json("```json\n{\"key\": \"value\"}\n```")
    assert result["key"] == "value"


def test_parse_json_invalid():
    from idos.ai.llm import LLMClient as LC

    client = LC.__new__(LC)
    client._parse_json = LC._parse_json.__get__(client)

    result = client._parse_json("not json at all")
    assert "error" in result


def test_parse_json_with_text_prefix():
    from idos.ai.llm import LLMClient as LC

    client = LC.__new__(LC)
    client._parse_json = LC._parse_json.__get__(client)

    result = client._parse_json('Here is the JSON: {"score": 85}')
    assert result["score"] == 85
