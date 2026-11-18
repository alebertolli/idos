"""Exercise configuration -> router -> HTTP contract without real credentials."""
import json
from pathlib import Path

import pytest
import requests
import yaml

from idos.ai.llm import LLMClient
from idos.ai.service import LLMService


ROOT = Path(__file__).resolve().parents[3]


def response(payload, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


def completion(finish="stop", content='{"ok": true}', refusal=None):
    return {
        "model": "gpt-4o-mini",
        "choices": [{"finish_reason": finish, "message": {"content": content, "refusal": refusal}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    }


def test_configured_chain_reaches_openai_last_and_persists_json(tmp_path, monkeypatch, capsys):
    config = yaml.safe_load((ROOT / "idos-config/models.yml").read_text(encoding="utf-8"))
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(key, "synthetic-key-" + key)
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        if url == "https://api.openai.com/v1/chat/completions":
            assert method == "POST"
            assert kwargs["headers"]["Authorization"] == "Bearer synthetic-key-OPENAI_API_KEY"
            payload = kwargs["json"]
            assert payload["model"] == "gpt-4o-mini"
            assert payload["max_completion_tokens"] == 64
            assert payload["response_format"] == {"type": "json_object"}
            assert payload["messages"][0] == {"role": "system", "content": "Synthetic integration test"}
            return response(completion())
        return response({"error": "capacity unavailable"}, 429)

    monkeypatch.setattr(requests, "request", request)
    service = LLMService.from_config(config)
    assert service._rank_providers("analysis") == ["gemini", "groq", "openrouter", "openai"]
    assert service._rank_providers("research") == ["gemini", "groq", "openai"]
    result = service.generate_structured("Return JSON with ok=true", "Synthetic integration test", max_tokens=64)
    assert result == {"ok": True}
    output = tmp_path / "result.json"
    output.write_text(json.dumps(result), encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert len(calls) == 4
    assert calls[-1] == "https://api.openai.com/v1/chat/completions"
    assert service.router.get_provider("openai") is None
    assert service._rank_providers("analysis")[-1] == "openai"
    assert "synthetic-key-" not in capsys.readouterr().out


@pytest.mark.parametrize("finish, content, refusal", [
    ("length", '{"partial":', None),
    ("content_filter", "", None),
    ("stop", None, "refused"),
    ("stop", "   ", None),
])
def test_openai_rejects_incomplete_or_refused_response(monkeypatch, finish, content, refusal):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: response(completion(finish, content, refusal)))
    client = LLMClient(provider="openai", api_key="synthetic-key", model="gpt-4o-mini", fallback_model="")
    result = client.generate("Synthetic test")
    assert not result.success
    assert "incomplete or refused" in result.error


def test_no_cross_provider_model_is_invented(monkeypatch):
    monkeypatch.setenv("IDOS_LLM_FALLBACK_MODEL", "gemini-foreign-model")
    service = LLMService.from_config({"providers": {"openai": {"model": "gpt-4o-mini"}}})
    assert service.clients["openai"].fallback_model == ""


def test_missing_openai_key_never_reuses_primary_provider_credential(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = LLMClient(provider="gemini", api_key="synthetic-gemini-secret", model="gemini-test",
                       fallback_providers=[{"provider": "openai", "model": "gpt-4o-mini"}])

    def unavailable(*args, **kwargs):
        raise requests.HTTPError("capacity unavailable", response=response({}, 429))

    monkeypatch.setattr(client, "_call_gemini", unavailable)
    monkeypatch.setattr(requests, "request", lambda *a, **kw: pytest.fail("Must not send a foreign credential"))
    assert not client.generate("Synthetic test").success


def test_model_without_configured_default_is_safe():
    service = LLMService.from_config({"providers": {}})
    assert service.model() == ""


def test_llm_worker_accepts_default_config_and_serializes_service_model(monkeypatch):
    from idos.workers.ai.llm_worker import LLMWorker

    assert isinstance(LLMWorker().client, LLMClient)
    service = LLMService.from_config({"default_provider": "openai", "providers": {"openai": {"model": "gpt-4o-mini"}}})
    monkeypatch.setattr(service, "generate_structured", lambda **kw: {"ok": True})
    worker = LLMWorker({"llm_service": service})
    monkeypatch.setattr(worker.registry, "get", lambda name: {"user_prompt": "Synthetic JSON test"})
    result = worker.run({"prompt_name": "synthetic", "structured": True})
    assert result["model"] == "gpt-4o-mini"
    assert json.loads(json.dumps(result))["structured"] == {"ok": True}


def test_workflows_supply_the_verified_secret_name():
    for name in ("board-review", "daily-refresh", "ddd-pipeline", "friday-digest", "monthly-rebalance"):
        workflow = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8"))
        env = workflow.get("env", {})
        if "OPENAI_API_KEY" not in env:
            env = next(job["env"] for job in workflow["jobs"].values() if "OPENAI_API_KEY" in job.get("env", {}))
        assert env["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
