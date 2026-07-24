import os
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from idos.ai.llm import LLMClient, LLMResponse
from idos.resilience.adaptive import AdaptiveRouter
from idos.resilience.circuit import CircuitBreaker
from idos.resilience.ratelimit import RateLimiter


class LLMService:
    """Centralized LLM access point with automatic provider selection,
    rate limiting, circuit breaking, and adaptive routing.

    All workers should use this via config.get("llm_service") instead of
    creating LLMClient instances directly.
    """

    def __init__(self, config_path: str | Path | None = None):
        cfg = self._load_config(config_path or self._default_config_path())
        llm_cfg = cfg.get("llm", cfg)
        self._init_from_config(llm_cfg)

    @classmethod
    def from_config(cls, cfg: dict) -> "LLMService":
        svc = cls.__new__(cls)
        llm_cfg = cfg.get("llm", cfg)
        svc._init_from_config(llm_cfg)
        return svc

    @staticmethod
    def _default_config_path() -> Path:
        return Path("idos-config") / "models.yml"

    @staticmethod
    def _load_config(path: str | Path) -> dict:
        path = Path(path)
        if not path.exists():
            print(f"[LLM] Config {path} not found, using defaults")
            return {"llm": {"default_provider": "gemini", "providers": {}}}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _init_from_config(self, llm_cfg: dict):
        self.default_provider = llm_cfg.get("default_provider", "gemini")
        providers_cfg = llm_cfg.get("providers", {})

        self.clients: dict[str, LLMClient] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.rate_limiters: dict[str, RateLimiter] = {}
        self.provider_limits: dict[str, dict] = {}

        cb_cfg = llm_cfg.get("circuit_breaker", {})
        cb_threshold = cb_cfg.get("failure_threshold", 3)
        cb_timeout = cb_cfg.get("recovery_timeout", 60)

        for name, pcfg in providers_cfg.items():
            self.clients[name] = LLMClient(
                provider=name,
                model=pcfg["model"],
                fallback_model=pcfg.get("fallback", ""),
                fallback_providers=[],
            )
            self.circuit_breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=cb_threshold,
                recovery_timeout=cb_timeout,
            )
            self.rate_limiters[f"{name}:rpm"] = RateLimiter(
                max_calls=pcfg.get("rpm", 30), window_seconds=60
            )
            self.rate_limiters[f"{name}:rpd"] = RateLimiter(
                max_calls=pcfg.get("rpd", 1000), window_seconds=86400
            )
            self.provider_limits[name] = {
                "rpm": pcfg.get("rpm", 30),
                "rpd": pcfg.get("rpd", 1000),
                "task_types": pcfg.get("task_types", []),
            }

        self.fallback_order = llm_cfg.get("fallback_order", [])
        self.router = AdaptiveRouter()

        for name, pcfg in providers_cfg.items():
            self.router.register(name, pcfg.get("task_types", []))

    def _rank_providers(self, task_type: str = "analysis",
                        provider_hint: str | None = None) -> list[str]:
        ordered = []
        if provider_hint and provider_hint in self.clients:
            ordered.append(provider_hint)
        best = self.router.select(task_type)
        if best and best not in ordered:
            ordered.append(best)
        for entry in self.fallback_order:
            p = entry.get("provider")
            if p in self.clients and p not in ordered:
                ordered.append(p)
        for p in self.clients:
            if p not in ordered:
                ordered.append(p)
        return ordered

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        task_type: str = "analysis",
        provider_hint: str | None = None,
    ) -> LLMResponse:
        providers = self._rank_providers(task_type, provider_hint)
        first_error = ""
        start = time.time()

        print(f"\n{'='*60}")
        print(f"[LLM] Task: {task_type} | Providers: {', '.join(providers)}")
        print(f"[LLM] SYSTEM: {(system_prompt[:200] + '...') if len(system_prompt) > 200 else system_prompt}")
        print(f"[LLM] PROMPT: {(prompt[:200] + '...') if len(prompt) > 200 else prompt}")

        for provider in providers:
            cb = self.circuit_breakers.get(provider)
            if cb and not cb.is_available:
                print(f"[LLM] {provider}: circuit OPEN, skipping")
                continue

            rl_rpm = self.rate_limiters.get(f"{provider}:rpm")
            rl_rpd = self.rate_limiters.get(f"{provider}:rpd")
            if rl_rpm and not rl_rpm.allow(provider):
                remaining = rl_rpm.remaining(provider)
                print(f"[LLM] {provider}: RPM limit reached ({remaining} remaining this min), skipping")
                continue
            if rl_rpd and not rl_rpd.allow(provider):
                remaining = rl_rpd.remaining(provider)
                print(f"[LLM] {provider}: RPD limit reached ({remaining} remaining today), skipping")
                continue

            client = self.clients[provider]
            if rl_rpm:
                rl_rpm.record(provider)
            if rl_rpd:
                rl_rpd.record(provider)

            print(f"\n{'─'*50}")
            print(f"[LLM] Trying {provider}/{client.model}...")

            resp = client.generate(prompt, system_prompt, temperature, max_tokens)

            if resp.success:
                self.router.record_outcome(provider, True, resp.latency_ms)
                if cb:
                    cb.record_success()
                remaining_rpm = rl_rpm.remaining(provider) if rl_rpm else "?"
                remaining_rpd = rl_rpd.remaining(provider) if rl_rpd else "?"
                print(f"[LLM] {provider}: OK ({resp.latency_ms}ms, {resp.tokens_in}→{resp.tokens_out} tok, "
                      f"RPM left={remaining_rpm}, RPD left={remaining_rpd})")
                print(f"{'='*60}\n")
                return resp
            else:
                self.router.record_outcome(provider, False, resp.latency_ms)
                if cb:
                    cb.record_failure()
                if not first_error:
                    first_error = resp.error
                print(f"[LLM] {provider}: FAILED - {resp.error[:150]}")
                time.sleep(2)
                continue

        print(f"{'='*60}\n")
        return LLMResponse(
            content="", success=False, error=first_error or "All providers failed",
            latency_ms=int((time.time() - start) * 1000),
        )

    def generate_structured(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        task_type: str = "analysis",
        provider_hint: str | None = None,
    ) -> dict[str, Any]:
        from idos.resilience.self_healing import SelfHealer
        import json
        import re

        structured_prompt = (
            f"{prompt}\n\nIMPORTANTE: Responde ÚNICAMENTE con JSON válido. "
            "No incluyas markdown, ni ```json, ni explicaciones adicionales. "
            "Solo el objeto JSON."
        )
        resp = self.generate(
            structured_prompt, system_prompt, temperature, max_tokens,
            task_type=task_type, provider_hint=provider_hint,
        )
        if not resp.success:
            return {"error": resp.error, "_raw": resp.content}

        cleaned = resp.content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        cleaned = re.sub(r"(?<!\\)\\(?![/\"\\bftnru])", "\\\\", cleaned)
        cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        collapsed = re.sub(r"\s+", " ", cleaned)
        try:
            return json.loads(collapsed)
        except json.JSONDecodeError:
            pass

        healer = SelfHealer()
        result = healer.parse_with_healing(cleaned)
        if result is not None:
            return result

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        print(f"[LLM] Failed to parse JSON, raw preview: {resp.content[:300]}")
        return {"error": "Failed to parse JSON", "_raw": resp.content}

    def health(self) -> dict[str, Any]:
        status = {}
        for name in self.clients:
            cb = self.circuit_breakers.get(name)
            limits = self.provider_limits.get(name, {})
            rl_rpm = self.rate_limiters.get(f"{name}:rpm")
            rl_rpd = self.rate_limiters.get(f"{name}:rpd")
            status[name] = {
                "model": self.clients[name].model,
                "circuit": cb.state if cb else "unknown",
                "rpm_remaining": rl_rpm.remaining(name) if rl_rpm else "?",
                "rpd_remaining": rl_rpd.remaining(name) if rl_rpd else "?",
                "limits": limits,
            }
        return status

    def model(self) -> str:
        return self.clients.get(self.default_provider, {}).model if hasattr(self, "clients") else ""
