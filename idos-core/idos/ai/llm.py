import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests


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
    def __init__(
        self,
        provider: str = "",
        api_key: str = "",
        model: str = "",
        fallback_model: str = "",
    ):
        self.provider = provider or os.getenv("IDOS_LLM_PROVIDER", "openrouter")
        self.api_key = api_key or self._resolve_api_key(self.provider)
        self.model = model or os.getenv("IDOS_LLM_MODEL", "openai/gpt-4o")
        self.fallback_model = fallback_model or os.getenv("IDOS_LLM_FALLBACK_MODEL", "gemini-2.0-flash")
        self.timeout = int(os.getenv("IDOS_LLM_TIMEOUT", "60"))

    @staticmethod
    def _resolve_api_key(provider: str) -> str:
        key_map = {
            "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
            "gemini": os.getenv("GEMINI_API_KEY", ""),
            "openai": os.getenv("OPENAI_API_KEY", ""),
        }
        return key_map.get(provider, os.getenv("OPENROUTER_API_KEY", ""))

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        label: str = "",
    ) -> LLMResponse:
        label = label or f"{self.provider}/{self.model}"
        _trunc = lambda s, n=200: (s[:n] + "...") if len(s) > n else s
        print(f"\n{'='*60}")
        print(f"[LLM] {label}")
        print(f"[LLM] SYSTEM: {_trunc(system_prompt)}")
        print(f"[LLM] PROMPT: {_trunc(prompt)}")
        start = time.time()
        try:
            if self.provider == "openai":
                resp = self._call_openai(prompt, system_prompt, temperature, max_tokens)
            elif self.provider == "openrouter":
                resp = self._call_openrouter(prompt, system_prompt, temperature, max_tokens)
            elif self.provider == "gemini":
                resp = self._call_gemini(prompt, system_prompt, temperature, max_tokens)
            else:
                resp = self._call_generic(prompt, system_prompt, temperature, max_tokens)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and self.fallback_model and self.provider == "gemini":
                orig_model = self.model
                self.model = self.fallback_model
                print(f"[LLM] 429 en {orig_model}, fallback a {self.fallback_model}...")
                try:
                    resp = self._call_gemini(prompt, system_prompt, temperature, max_tokens)
                except Exception as e2:
                    resp = LLMResponse(
                        content="", model=self.model, success=False, error=str(e2),
                        latency_ms=int((time.time() - start) * 1000),
                    )
                finally:
                    self.model = orig_model
            else:
                resp = LLMResponse(
                    content="", model=self.model, success=False, error=str(e),
                    latency_ms=int((time.time() - start) * 1000),
                )
        except Exception as e:
            resp = LLMResponse(
                content="",
                model=self.model,
                success=False,
                error=str(e),
                latency_ms=int((time.time() - start) * 1000),
            )
        if resp.success:
            print(f"[LLM] RESPONSE ({resp.latency_ms}ms, {resp.tokens_in}→{resp.tokens_out} tok): {_trunc(resp.content, 500)}")
        else:
            print(f"[LLM] ERROR ({resp.latency_ms}ms): {resp.error}")
        print(f"{'='*60}\n")
        return resp

    def generate_structured(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        structured_prompt = (
            f"{prompt}\n\nIMPORTANTE: Responde ÚNICAMENTE con JSON válido. "
            "No incluyas markdown, ni ```json, ni explicaciones adicionales. "
            "Solo el objeto JSON."
        )
        resp = self.generate(structured_prompt, system_prompt, temperature, max_tokens)
        if not resp.success:
            return {"error": resp.error, "_raw": resp.content}

        return self._parse_json(resp.content)

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        max_retries = 3
        for attempt in range(max_retries):
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"[LLM] Rate limited (429), retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        return resp

    def _call_openai(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        start = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=data["model"],
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
        )

    def _call_openrouter(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        start = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/alebertolli/idos",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.model),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
        )

    def _call_gemini(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        start = time.time()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt + "\n\n" + prompt}]})
        else:
            contents.append({"role": "user", "parts": [{"text": prompt}]})

        resp = self._request_with_retry("POST", url,
            json={
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=self.timeout,
        )
        data = resp.json()
        candidate = data["candidates"][0]
        text = candidate["content"]["parts"][0]["text"]

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            content=text,
            model=self.model,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
        )

    def _call_generic(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        start = time.time()
        base_url = os.getenv("IDOS_LLM_BASE_URL", "https://api.openai.com/v1")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        data = resp.json()
        choice = data["choices"][0]

        return LLMResponse(
            content=choice["message"]["content"],
            model=data["model"],
            latency_ms=int((time.time() - start) * 1000),
            success=True,
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        from idos.resilience.self_healing import SelfHealer
        healer = SelfHealer()
        result = healer.parse_with_healing(content)
        if result is not None:
            return result

        cleaned = content.strip()
        if cleaned.startswith("```"):
            for line in cleaned.split("\n"):
                if line.strip().startswith("{"):
                    cleaned = line.strip()
                    break
            else:
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"error": "Failed to parse JSON", "_raw": content}
