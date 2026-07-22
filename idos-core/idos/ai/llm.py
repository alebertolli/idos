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
        fallback_providers: list[dict[str, str]] | None = None,
    ):
        self.provider = provider or os.getenv("IDOS_LLM_PROVIDER", "openrouter")
        self.api_key = api_key or self._resolve_api_key(self.provider)
        self.model = model or os.getenv("IDOS_LLM_MODEL", "openai/gpt-4o")
        self.fallback_model = fallback_model or os.getenv("IDOS_LLM_FALLBACK_MODEL", "gemini-2.0-flash")
        self.fallback_providers = fallback_providers or []
        self.timeout = int(os.getenv("IDOS_LLM_TIMEOUT", "60"))

    @staticmethod
    def _resolve_api_key(provider: str) -> str:
        key_map = {
            "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
            "gemini": os.getenv("GEMINI_API_KEY", ""),
            "openai": os.getenv("OPENAI_API_KEY", ""),
            "groq": os.getenv("GROQ_API_KEY", ""),
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
        _call_chain = [{"provider": self.provider, "model": self.model, "api_key": self.api_key}]
        _call_chain += self.fallback_providers
        _trunc = lambda s, n=200: (s[:n] + "...") if len(s) > n else s
        first_error = ""
        start = time.time()
        for idx, entry in enumerate(_call_chain):
            prov = entry["provider"]
            modl = entry.get("model", self.model)
            akey = entry.get("api_key", self._resolve_api_key(prov))
            lbl = entry.get("label", f"{prov}/{modl}")
            if idx > 0:
                print(f"\n{'='*60}")
                print(f"[LLM] Fallback {idx}: {lbl}")
            else:
                print(f"\n{'='*60}")
                print(f"[LLM] {lbl}")
            print(f"[LLM] SYSTEM: {_trunc(system_prompt)}")
            print(f"[LLM] PROMPT: {_trunc(prompt)}")
            try:
                if prov == "openai":
                    resp = self._call_openai(prompt, system_prompt, temperature, max_tokens, akey, modl)
                elif prov == "openrouter":
                    resp = self._call_openrouter(prompt, system_prompt, temperature, max_tokens, akey, modl)
                elif prov == "gemini":
                    resp = self._call_gemini(prompt, system_prompt, temperature, max_tokens, akey, modl)
                elif prov == "groq":
                    resp = self._call_groq(prompt, system_prompt, temperature, max_tokens, akey, modl)
                else:
                    resp = self._call_generic(prompt, system_prompt, temperature, max_tokens, akey, modl)
            except requests.HTTPError as e:
                fbk = entry.get("fallback_model", "")
                if e.response is not None and e.response.status_code == 429 and fbk and prov == "gemini":
                    print(f"[LLM] 429 en {modl}, fallback a {fbk}...")
                    try:
                        resp = self._call_gemini(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                    except Exception as e2:
                        print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {e2}")
                        if not first_error: first_error = str(e2)
                        continue
                else:
                    print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {e}")
                    if not first_error: first_error = str(e)
                    continue
            except Exception as e:
                print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {e}")
                if not first_error: first_error = str(e)
                continue
            if resp.success:
                print(f"[LLM] RESPONSE ({resp.latency_ms}ms, {resp.tokens_in}→{resp.tokens_out} tok): {_trunc(resp.content, 500)}")
            print(f"{'='*60}\n")
            return resp
        print(f"{'='*60}\n")
        return LLMResponse(content="", success=False, error=first_error,
                           latency_ms=int((time.time() - start) * 1000))

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
        api_key: str = "",
        model: str = "",
    ) -> LLMResponse:
        _key = api_key or self.api_key
        _mod = model or self.model
        start = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _mod,
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
        api_key: str = "",
        model: str = "",
    ) -> LLMResponse:
        _key = api_key or self.api_key
        _mod = model or self.model
        start = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/alebertolli/idos",
            },
            json={
                "model": _mod,
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
            model=data.get("model", _mod),
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
        api_key: str = "",
        model: str = "",
    ) -> LLMResponse:
        _key = api_key or self.api_key
        _mod = model or self.model
        start = time.time()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{_mod}:generateContent?key={_key}"
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
            model=_mod,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
        )

    def _call_groq(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        api_key: str = "",
        model: str = "",
    ) -> LLMResponse:
        _key = api_key or self.api_key
        _mod = model or self.model
        start = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _mod,
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
            model=data.get("model", _mod),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
        )

    def _call_generic(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        api_key: str = "",
        model: str = "",
    ) -> LLMResponse:
        _key = api_key or self.api_key
        _mod = model or self.model
        start = time.time()
        base_url = os.getenv("IDOS_LLM_BASE_URL", "https://api.openai.com/v1")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._request_with_retry("POST", f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _mod,
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

        import re
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"error": "Failed to parse JSON", "_raw": content}
