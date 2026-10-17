from idos.ai.llm import LLMResponse
from idos.ai.service import LLMService


def test_service_fails_over_after_empty_primary_response(monkeypatch):
    service = LLMService.from_config({
        "llm": {
            "default_provider": "gemini",
            "providers": {
                "gemini": {"model": "gemini-primary", "task_types": ["analysis"]},
                "groq": {"model": "groq-fallback", "task_types": ["analysis"]},
            },
            "fallback_order": [{"provider": "groq"}],
        }
    })
    calls = []

    def empty_response(*_args, **_kwargs):
        calls.append("gemini")
        return LLMResponse(content="", success=False, error="Gemini returned no text content")

    def usable_response(*_args, **_kwargs):
        calls.append("groq")
        return LLMResponse(content='{"thesis": "evidence-backed"}', model="groq-fallback")

    monkeypatch.setattr(service.clients["gemini"], "generate", empty_response)
    monkeypatch.setattr(service.clients["groq"], "generate", usable_response)
    monkeypatch.setattr("idos.ai.service.time.sleep", lambda *_args: None)

    result = service.generate("research", task_type="analysis")

    assert result.success
    assert result.content == '{"thesis": "evidence-backed"}'
    assert calls == ["gemini", "groq"]


def test_service_logs_request_metadata_without_prompt_or_response(monkeypatch, capsys):
    service = LLMService.from_config({
        "llm": {
            "default_provider": "gemini",
            "providers": {"gemini": {"model": "gemini-test", "task_types": ["analysis"]}},
        }
    })
    prompt = "private-portfolio-context-marker"
    response_body = '{"private": "response-marker"}'
    monkeypatch.setattr(
        service.clients["gemini"],
        "generate",
        lambda *_args, **_kwargs: LLMResponse(
            content=response_body, success=True, latency_ms=5
        ),
    )

    result = service.generate(prompt, system_prompt="private-system-marker")

    logs = capsys.readouterr().out
    assert result.success
    assert "prompt_chars=" in logs
    assert prompt not in logs
    assert "private-system-marker" not in logs
    assert response_body not in logs
