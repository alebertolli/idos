import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
        self.fallback_model = fallback_model or os.getenv("IDOS_LLM_FALLBACK_MODEL", "gemini-2.5-flash")
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
        _call_chain = [{"provider": self.provider, "model": self.model, "api_key": self.api_key, "fallback_model": self.fallback_model}]
        _call_chain += self.fallback_providers
        api_keys = [entry.get("api_key", "") for entry in _call_chain]
        first_error = ""
        start = time.time()
        for idx, entry in enumerate(_call_chain):
            prov = entry["provider"]
            modl = entry.get("model", self.model)
            akey = entry.get("api_key", self._resolve_api_key(prov))
            lbl = entry.get("label", f"{prov}/{modl}")
            if not akey:
                message = f"{prov}: API key not configured"
                if not first_error:
                    first_error = message
                print(f"[LLM] {message}; skipping provider")
                continue
            if idx > 0:
                print(f"\n{'='*60}")
                print(f"[LLM] Fallback {idx}: {lbl}")
            else:
                print(f"\n{'='*60}")
                print(f"[LLM] {lbl}")
            print(
                f"[LLM] Request metadata: system_chars={len(system_prompt)} "
                f"prompt_chars={len(prompt)}"
            )
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
                status_code = e.response.status_code if e.response is not None else None
                if fbk and status_code == 404:
                    print(f"[LLM] {e.response.status_code} en {modl}, fallback a {fbk}...")
                    try:
                        if prov == "gemini":
                            resp = self._call_gemini(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        elif prov == "groq":
                            resp = self._call_groq(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        elif prov == "openrouter":
                            resp = self._call_openrouter(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        elif prov == "openai":
                            resp = self._call_openai(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        else:
                            resp = self._call_generic(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                    except Exception as e2:
                        safe_error = self._redact_error(e2, api_keys)
                        print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {safe_error}")
                        if not first_error: first_error = safe_error
                        continue
                else:
                    safe_error = self._redact_error(e, api_keys)
                    print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {safe_error}")
                    if not first_error: first_error = safe_error
                    continue
            except Exception as e:
                safe_error = self._redact_error(e, api_keys)
                print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {safe_error}")
                if not first_error: first_error = safe_error
                continue
            if resp.success and resp.content:
                print(
                    f"[LLM] RESPONSE ({resp.latency_ms}ms, "
                    f"{resp.tokens_in}→{resp.tokens_out} tok)"
                )
                print(f"{'='*60}\n")
                return resp
            msg = self._redact_error(resp.error or "respuesta vacía del proveedor", api_keys)
            if not first_error:
                first_error = msg
            print(f"[LLM] {lbl}: respuesta sin contenido util ({msg}), intentando siguiente fallback")
            print(f"{'='*60}\n")
            continue
        print(f"{'='*60}\n")
        return LLMResponse(content="", success=False, error=first_error,
                           latency_ms=int((time.time() - start) * 1000))

    def _redact_error(self, error: Any, api_keys: list[str] | None = None) -> str:
        """Remove credentials from provider errors before logging or persisting them."""
        message = str(error)
        known_keys = [
            self.api_key,
            *(api_keys or []),
            os.getenv("GEMINI_API_KEY", ""),
            os.getenv("GOOGLE_API_KEY", ""),
            os.getenv("OPENROUTER_API_KEY", ""),
            os.getenv("GROQ_API_KEY", ""),
            os.getenv("OPENAI_API_KEY", ""),
        ]
        for secret in set(known_keys):
            if secret and len(secret) >= 8:
                message = message.replace(secret, "[REDACTED]")
        message = re.sub(
            r"(?i)([?&](?:key|api_key|access_token)=)[^&\s]+",
            r"\1[REDACTED]",
            message,
        )
        message = re.sub(
            r"(?i)(authorization\s*:\s*bearer\s+)[^\s,]+",
            r"\1[REDACTED]",
            message,
        )
        return message

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
            return {"error": self._redact_error(resp.error), "_raw": resp.content}

        return self._parse_json(resp.content)

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        max_attempts = 3
        transient_statuses = {408, 429, 500, 502, 503, 504}
        for attempt in range(max_attempts):
            resp = requests.request(method, url, **kwargs)
            if resp.status_code in transient_statuses and attempt < max_attempts - 1:
                wait = self._retry_delay_seconds(resp.headers.get("Retry-After"), attempt)
                if wait > 120:
                    print(f"[LLM] HTTP {resp.status_code}: retry delay exceeds 120s; trying next provider")
                    resp.raise_for_status()
                print(
                    f"[LLM] HTTP {resp.status_code}: retrying in {wait:.1f}s "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )
                resp.close()
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("LLM request exhausted its attempt budget")

    @staticmethod
    def _retry_delay_seconds(retry_after: str | None, attempt: int) -> float:
        """Honor Retry-After seconds/date; use bounded exponential backoff with jitter otherwise."""
        if retry_after:
            try:
                return max(0, int(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        return 2 ** (attempt + 2) + random.uniform(0, 1)

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
            f"{_mod}:generateContent"
        )
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt + "\n\n" + prompt}]})
        else:
            contents.append({"role": "user", "parts": [{"text": prompt}]})

        resp = self._request_with_retry("POST", url,
            headers={"x-goog-api-key": _key, "Content-Type": "application/json"},
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
        candidates = data.get("candidates") or []
        if not candidates:
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            reason = f" (block reason: {block_reason})" if block_reason else ""
            raise ValueError(f"Gemini returned no candidates{reason}")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            finish_reason = candidate.get("finishReason")
            reason = f" (finish reason: {finish_reason})" if finish_reason else ""
            raise ValueError(f"Gemini returned no text content{reason}")

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
