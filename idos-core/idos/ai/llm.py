import json
import os
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import requests


_SECRET_QUERY_PARAMETER = re.compile(
    r"([?&](?:key|api_key|access_token|token)=)[^&#\s]+", re.IGNORECASE
)
_AUTHORIZATION_CREDENTIAL = re.compile(
    r"(authorization['\"]?\s*[:=]\s*['\"]?(?:bearer|basic)\s+)"
    r"[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
_API_KEY_HEADER = re.compile(
    r"((?:x-goog-api-key|x-api-key|api-key)['\"]?\s*[:=]\s*['\"]?)"
    r"[^,'\"\s}]+",
    re.IGNORECASE,
)


def redact_sensitive_text(
    message: Any, secrets: list[str] | tuple[str, ...] = ()
) -> str:
    """Remove API credentials from provider errors before logging or returning them."""
    safe_message = str(message)
    known_secrets = (
        value for value in secrets
        if isinstance(value, str) and len(value) >= 8
    )
    for secret in sorted(known_secrets, key=len, reverse=True):
        safe_message = safe_message.replace(secret, "[REDACTED]")
    safe_message = _SECRET_QUERY_PARAMETER.sub(r"\1[REDACTED]", safe_message)
    safe_message = _AUTHORIZATION_CREDENTIAL.sub(r"\1[REDACTED]", safe_message)
    return _API_KEY_HEADER.sub(r"\1[REDACTED]", safe_message)


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    success: bool = True
    error: str = ""
    provider: str = ""
    status_code: int | None = None
    retry_after_seconds: float | None = None
    rate_limit_remaining_tokens: int | None = None
    rate_limit_reset_seconds: float | None = None


def _parse_retry_delay(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        reset_at = parsedate_to_datetime(value)
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=timezone.utc)
        return max(0.0, (reset_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        pass

    # Groq reset headers use values such as "2m59.56s".
    matches = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value.strip().lower())
    if not matches:
        return None
    scales = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(amount) * scales[unit] for amount, unit in matches)


def _rate_limit_metadata(response: requests.Response) -> dict[str, Any]:
    headers = getattr(response, "headers", {}) or {}
    retry_after = _parse_retry_delay(headers.get("Retry-After"))
    reset_delay = (
        _parse_retry_delay(headers.get("x-ratelimit-reset-tokens"))
        or _parse_retry_delay(headers.get("x-ratelimit-reset-requests"))
    )
    remaining = headers.get("x-ratelimit-remaining-tokens")
    try:
        remaining_tokens = int(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining_tokens = None
    return {
        "retry_after_seconds": retry_after if retry_after is not None else reset_delay,
        "rate_limit_remaining_tokens": remaining_tokens,
        "rate_limit_reset_seconds": reset_delay,
    }


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
        response_format: str | None = None,
        task_type: str = "analysis",
    ) -> LLMResponse:
        _call_chain = [{"provider": self.provider, "model": self.model, "api_key": self.api_key, "fallback_model": self.fallback_model}]
        _call_chain += self.fallback_providers
        _trunc = lambda s, n=200: (s[:n] + "...") if len(s) > n else s
        first_error = ""
        last_failure: dict[str, Any] = {}
        blocked_providers: set[str] = set()
        start = time.time()
        for idx, entry in enumerate(_call_chain):
            prov = entry["provider"]
            if prov in blocked_providers:
                continue
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
                    resp = self._call_gemini(
                        prompt, system_prompt, temperature, max_tokens, akey, modl,
                        response_format=response_format,
                    )
                elif prov == "groq":
                    resp = self._call_groq(prompt, system_prompt, temperature, max_tokens, akey, modl)
                else:
                    resp = self._call_generic(prompt, system_prompt, temperature, max_tokens, akey, modl)
            except requests.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None
                if status_code in (402, 429):
                    metadata = _rate_limit_metadata(e.response)
                    last_failure = {
                        "provider": prov,
                        "status_code": status_code,
                        **metadata,
                    }
                    blocked_providers.add(prov)
                    safe_error = redact_sensitive_text(e, [akey])
                    print(f"[LLM] {status_code} en {prov}; se suspende el proveedor para esta solicitud")
                    if not first_error:
                        first_error = safe_error
                    continue
                fbk = entry.get("fallback_model", "")
                if fbk and e.response is not None and status_code in (404, 408, 500, 502, 503, 504):
                    print(f"[LLM] {e.response.status_code} en {modl}, fallback a {fbk}...")
                    try:
                        if prov == "gemini":
                            resp = self._call_gemini(
                                prompt, system_prompt, temperature, max_tokens, akey, fbk,
                                response_format=response_format,
                            )
                        elif prov == "groq":
                            resp = self._call_groq(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        elif prov == "openrouter":
                            resp = self._call_openrouter(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        elif prov == "openai":
                            resp = self._call_openai(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                        else:
                            resp = self._call_generic(prompt, system_prompt, temperature, max_tokens, akey, fbk)
                    except Exception as e2:
                        response = getattr(e2, "response", None)
                        status_code = response.status_code if response is not None else None
                        if status_code in (402, 429):
                            last_failure = {
                                "provider": prov,
                                "status_code": status_code,
                                **_rate_limit_metadata(response),
                            }
                            blocked_providers.add(prov)
                        safe_error = redact_sensitive_text(e2, [akey])
                        print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {safe_error}")
                        if not first_error: first_error = safe_error
                        continue
                else:
                    safe_error = redact_sensitive_text(e, [akey])
                    print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {safe_error}")
                    if not first_error: first_error = safe_error
                    continue
            except Exception as e:
                safe_error = redact_sensitive_text(e, [akey])
                print(f"[LLM] ERROR ({int((time.time()-start)*1000)}ms): {safe_error}")
                if not first_error: first_error = safe_error
                continue
            if resp.success and resp.content:
                resp.provider = prov
                print(f"[LLM] RESPONSE ({resp.latency_ms}ms, {resp.tokens_in}→{resp.tokens_out} tok): {_trunc(resp.content, 500)}")
                print(f"{'='*60}\n")
                return resp
            msg = resp.error or "respuesta vacía del proveedor"
            msg = redact_sensitive_text(msg, [akey])
            if not first_error:
                first_error = msg
            print(f"[LLM] {lbl}: respuesta sin contenido util ({msg}), intentando siguiente fallback")
            print(f"{'='*60}\n")
            continue
        print(f"{'='*60}\n")
        return LLMResponse(
            content="", success=False, error=first_error,
            latency_ms=int((time.time() - start) * 1000), **last_failure,
        )

    def generate_structured(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        task_type: str = "analysis",
    ) -> dict[str, Any]:
        structured_prompt = (
            f"{prompt}\n\nIMPORTANTE: Responde ÚNICAMENTE con JSON válido. "
            "No incluyas markdown, ni ```json, ni explicaciones adicionales. "
            "Solo el objeto JSON."
        )
        resp = self.generate(
            structured_prompt, system_prompt, temperature, max_tokens,
            response_format="json", task_type=task_type,
        )
        if not resp.success:
            return {"error": resp.error, "_raw": resp.content}

        return self._parse_json(resp.content)

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        max_retries = 3
        for attempt in range(max_retries):
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 429:
                # Let the provider router try another configured provider. Long waits
                # would hold the Research worker and consume retries without progress.
                resp.raise_for_status()
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
            **_rate_limit_metadata(resp),
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
            **_rate_limit_metadata(resp),
        )

    def _call_gemini(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        api_key: str = "",
        model: str = "",
        response_format: str | None = None,
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

        generation_config = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if response_format == "json":
            generation_config["responseMimeType"] = "application/json"

        resp = self._request_with_retry("POST", url,
            headers={"x-goog-api-key": _key},
            json={"contents": contents, "generationConfig": generation_config},
            timeout=self.timeout,
        )
        data = resp.json()
        candidate = data["candidates"][0]
        finish_reason = candidate.get("finishReason")
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))

        if finish_reason and finish_reason != "STOP":
            return LLMResponse(
                content=text,
                model=_mod,
                latency_ms=int((time.time() - start) * 1000),
                success=False,
                error=f"Gemini terminó con finishReason={finish_reason}; respuesta incompleta",
            )

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            content=text,
            model=_mod,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
            **_rate_limit_metadata(resp),
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
            **_rate_limit_metadata(resp),
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
