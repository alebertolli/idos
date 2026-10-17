"""Tests for LLMClient — stub mode (no real API calls)."""

import os

import pytest

from idos.ai.llm import LLMClient


def test_llm_client_defaults():
    client = LLMClient(provider="test", api_key="key", model="test-model")
    assert client.provider == "test"
    assert client.api_key == "key"
    assert client.model == "test-model"


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


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"candidates": []}, "Gemini returned no candidates"),
        ({"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}, "finish reason: SAFETY"),
    ],
)
def test_gemini_empty_response_has_actionable_error(monkeypatch, payload, message):
    class FakeResponse:
        def json(self):
            return payload

    client = LLMClient(provider="gemini", api_key="test-key", model="test-model")
    monkeypatch.setattr(client, "_request_with_retry", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(ValueError, match=message):
        client._call_gemini("prompt", "system", 0.1, 100)


def test_gemini_sends_api_key_in_header_not_url(monkeypatch):
    class FakeResponse:
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    client = LLMClient(provider="gemini", api_key="test-secret-key-123", model="test-model")
    captured = {}

    def capture_request(_method, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        return FakeResponse()

    monkeypatch.setattr(client, "_request_with_retry", capture_request)

    response = client._call_gemini("prompt", "system", 0.1, 100)

    assert response.success
    assert "test-secret-key-123" not in captured["url"]
    assert "key=" not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "test-secret-key-123"


def test_provider_http_errors_redact_api_keys_from_logs_and_result(monkeypatch, capsys):
    import requests

    secret = "test-secret-key-123"
    client = LLMClient(provider="gemini", api_key=secret, model="test-model")
    response = requests.Response()
    response.status_code = 401

    def fail_request(*_args, **_kwargs):
        raise requests.HTTPError(
            f"401 Unauthorized: https://example.test/path?key={secret}", response=response
        )

    monkeypatch.setattr(client, "_call_gemini", fail_request)

    result = client.generate("prompt")

    assert not result.success
    assert secret not in result.error
    assert "[REDACTED]" in result.error
    assert secret not in capsys.readouterr().out


def test_rate_limited_provider_does_not_call_same_provider_fallback(monkeypatch):
    import requests
    from idos.ai.llm import LLMClient as LC, LLMResponse

    client = LC.__new__(LC)
    client.provider = "openrouter"
    client.api_key = "router-key"
    client.model = "primary"
    client.fallback_model = "free-fallback"
    client.fallback_providers = [{"provider": "groq", "model": "groq-model", "api_key": "groq-key"}]
    client.timeout = 5
    called_models = []
    rate_limit = requests.Response()
    rate_limit.status_code = 429

    def router_call(_prompt, _system, _temperature, _max_tokens, _api_key, model):
        called_models.append(model)
        raise requests.HTTPError("429 Too Many Requests", response=rate_limit)

    monkeypatch.setattr(client, "_call_openrouter", router_call)
    monkeypatch.setattr(
        client,
        "_call_groq",
        lambda *_args: LLMResponse(content="ok", success=True, model="groq-model"),
    )

    result = client.generate("prompt")

    assert result.success
    assert called_models == ["primary"]
