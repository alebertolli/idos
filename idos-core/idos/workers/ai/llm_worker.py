from typing import Any

from idos.ai.llm import LLMClient
from idos.ai.prompts import PromptRegistry
from idos.workers.base import BaseWorker, WorkerResult, WorkerStatus


class LLMWorker(BaseWorker):
    name = "llm_worker"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.client = config.get("llm_service") or LLMClient(
            provider=config.get("provider", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            fallback_model=config.get("fallback_model", ""),
            fallback_providers=config.get("fallback_providers", []),
        )
        prompts_path = config.get("prompts_path", "")
        self.registry = PromptRegistry(prompts_path) if prompts_path else PromptRegistry()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt_name = context.get("prompt_name", "")
        if not prompt_name:
            msg = "No prompt_name provided in context"
            raise ValueError(msg)

        template = self.registry.get(prompt_name)
        if not template:
            msg = f"Prompt '{prompt_name}' not found in registry"
            raise ValueError(msg)

        prompt_kwargs = {k: v for k, v in context.items() if k != "prompt_name"}
        formatted = template["user_prompt"].format(**prompt_kwargs)
        system = template.get("system_prompt", "")

        structured = context.get("structured", False)
        temperature = context.get("temperature", 0.3 if not structured else 0.1)

        if structured:
            result = self.client.generate_structured(
                prompt=formatted,
                system_prompt=system,
                temperature=temperature,
            )
            return {
                "prompt_name": prompt_name,
                "structured": result,
                "model": self.client.model,
            }

        result = self.client.generate(
            prompt=formatted,
            system_prompt=system,
            temperature=temperature,
        )
        return {
            "prompt_name": prompt_name,
            "content": result.content,
            "model": result.model,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "latency_ms": result.latency_ms,
        }
