"""Check OpenAI API authentication without generating model output."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _safe_text(value: object, api_key: str) -> str:
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    return " ".join(text.split())[:300]


def check_auth(api_key: str) -> dict[str, object]:
    if not api_key:
        return {
            "ok": False,
            "http_status": None,
            "error_type": "missing_secret",
            "error_code": None,
            "error_message": "OPENAI_API_KEY is not set in this workflow.",
            "request_id": None,
            "gpt_6_luna_listed": None,
            "models_returned": None,
        }

    request = Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
            models = payload.get("data", []) if isinstance(payload, dict) else []
            model_ids = {
                item.get("id") for item in models if isinstance(item, dict)
            }
            return {
                "ok": True,
                "http_status": response.status,
                "error_type": None,
                "error_code": None,
                "error_message": None,
                "request_id": response.headers.get("x-request-id"),
                "gpt_6_luna_listed": "gpt-6-luna" in model_ids,
                "models_returned": len(model_ids),
            }
    except HTTPError as error:
        try:
            body = json.loads(error.read(65536))
        except (json.JSONDecodeError, OSError):
            body = {}
        detail = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(detail, dict):
            detail = {}
        return {
            "ok": False,
            "http_status": error.code,
            "error_type": _safe_text(detail.get("type"), api_key) or None,
            "error_code": _safe_text(detail.get("code"), api_key) or None,
            "error_message": _safe_text(detail.get("message"), api_key) or None,
            "request_id": error.headers.get("x-request-id"),
            "gpt_6_luna_listed": None,
            "models_returned": None,
        }
    except (URLError, TimeoutError, OSError) as error:
        return {
            "ok": False,
            "http_status": None,
            "error_type": type(error).__name__,
            "error_code": None,
            "error_message": _safe_text(error, api_key),
            "request_id": None,
            "gpt_6_luna_listed": None,
            "models_returned": None,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = check_auth(os.environ.get("OPENAI_API_KEY", ""))
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
