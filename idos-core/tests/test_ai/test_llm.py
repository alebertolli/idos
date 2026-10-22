"""Tests for LLMClient — stub mode (no real API calls)."""

from pathlib import Path

import yaml

from idos.ai.llm import LLMClient, redact_sensitive_text


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


def test_generate_falls_back_to_provider_model_on_503(monkeypatch):
    import requests
    from idos.ai.llm import LLMClient as LC, LLMResponse

    client = LC(
        provider="gemini", api_key="key", model="gemini-primary",
        fallback_model="gemini-fallback",
    )
    calls = []

    def fake_call(prompt, system_prompt, temperature, max_tokens, api_key, model, response_format=None):
        calls.append(model)
        if model == "gemini-primary":
            response = requests.Response()
            response.status_code = 503
            raise requests.HTTPError("temporary provider outage", response=response)
        return LLMResponse(content="valid response", model=model, success=True)

    monkeypatch.setattr(client, "_call_gemini", fake_call)

    result = client.generate("prompt")

    assert result.success
    assert result.content == "valid response"
    assert calls == ["gemini-primary", "gemini-fallback"]


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


def test_gemini_structured_request_uses_json_mime_type_and_joins_parts(monkeypatch):
    from idos.ai.llm import LLMClient as LC

    client = LC.__new__(LC)
    client.api_key = "key"
    client.model = "gemini-test"
    client.timeout = 5
    captured = {}

    class Response:
        def json(self):
            return {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"result":'}, {"text": '"ok"}'}]},
                }],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4},
            }

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(client, "_request_with_retry", fake_request)
    result = client._call_gemini("prompt", "system", 0.1, 100, response_format="json")

    assert captured["headers"]["x-goog-api-key"] == "key"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "key=" not in captured.get("url", "")
    assert result.success
    assert result.content == '{"result":"ok"}'


def test_redact_sensitive_text_removes_credentials_from_provider_errors():
    message = (
        "request failed at https://example.test/?key=abc123secret "
        "Authorization: Bearer bearer-secret-value"
    )

    safe_message = redact_sensitive_text(
        message, ["abc123secret", "bearer-secret-value"]
    )

    assert "abc123secret" not in safe_message
    assert "bearer-secret-value" not in safe_message
    assert "key=[REDACTED]" in safe_message
    assert "Bearer [REDACTED]" in safe_message
    assert "x-goog-api-key: [REDACTED]" in redact_sensitive_text(
        "request headers: x-goog-api-key: header-secret-value"
    )


def test_llm_service_redacts_provider_error_defensively(monkeypatch, capsys):
    from types import SimpleNamespace
    from idos.ai.llm import LLMResponse
    from idos.ai.service import LLMService

    service = LLMService.__new__(LLMService)
    service.clients = {
        "gemini": SimpleNamespace(
            model="gemini-test",
            generate=lambda *args, **kwargs: LLMResponse(
                content="", success=False,
                error="request failed with x-goog-api-key: header-secret-value",
            ),
        )
    }
    service.circuit_breakers = {}
    service.rate_limiters = {}
    service.provider_limits = {}
    service.router = SimpleNamespace(record_outcome=lambda *args: None)
    monkeypatch.setattr(service, "_rank_providers", lambda *args: ["gemini"])

    response = service.generate("prompt")
    captured = capsys.readouterr()

    assert "header-secret-value" not in response.error
    assert "header-secret-value" not in captured.out


def test_generate_redacts_credentials_from_logs_and_errors(monkeypatch, capsys):
    import requests
    from idos.ai.llm import LLMClient as LC

    secret = "sensitive-api-secret"
    client = LC(
        provider="openai", api_key=secret, model="test-model",
    )

    def fail_request(*args, **kwargs):
        raise requests.HTTPError(
            f"request failed: https://example.test/?key={secret}"
        )

    monkeypatch.setattr(client, "_call_openai", fail_request)
    response = client.generate("prompt")
    captured = capsys.readouterr()

    assert not response.success
    assert secret not in response.error
    assert secret not in captured.out
    assert "key=[REDACTED]" in response.error


def test_gemini_non_stop_finish_reason_marks_response_incomplete(monkeypatch):
    from idos.ai.llm import LLMClient as LC

    client = LC.__new__(LC)
    client.api_key = "key"
    client.model = "gemini-test"
    client.timeout = 5

    class Response:
        def json(self):
            return {
                "candidates": [{
                    "finishReason": "MAX_TOKENS",
                    "content": {"parts": [{"text": '{"partial":'}]},
                }],
            }

    monkeypatch.setattr(client, "_request_with_retry", lambda *args, **kwargs: Response())
    result = client._call_gemini("prompt", "system", 0.1, 100, response_format="json")

    assert not result.success
    assert "MAX_TOKENS" in result.error


def test_llm_service_requests_json_mode_for_structured_research(monkeypatch):
    from types import SimpleNamespace
    from idos.ai.llm import LLMResponse
    from idos.ai.service import LLMService

    service = LLMService.__new__(LLMService)
    captured = {}
    service.clients = {
        "gemini": SimpleNamespace(
            model="gemini-test",
            generate=lambda *args, **kwargs: (
                captured.update(kwargs) or LLMResponse(
                    content='{"ok": true}', model="gemini-test", success=True,
                )
            ),
        )
    }
    service.circuit_breakers = {}
    service.rate_limiters = {}
    service.provider_limits = {}
    service.router = SimpleNamespace(record_outcome=lambda *args: None)
    monkeypatch.setattr(service, "_rank_providers", lambda *args: ["gemini"])

    result = service.generate_structured("prompt", "system")

    assert result == {"ok": True}
    assert captured["response_format"] == "json"
