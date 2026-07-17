from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    success: bool = True
    error: str = ""


class LLMClient:
    def __init__(self, provider: str = "openai", api_key: str = "", model: str = ""):
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> LLMResponse:
        return LLMResponse(
            content="[LLM stub] Replace with actual API call",
            model=self.model or f"{self.provider}/stub",
        )

    def generate_structured(self, prompt: str, schema: type, system_prompt: str = "", **kwargs) -> Any:
        resp = self.generate(prompt, system_prompt, **kwargs)
        return resp
