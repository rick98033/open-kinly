"""One-call client for an OpenAI-compatible structured-output endpoint."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelError(RuntimeError):
    pass


def author_once(
    *,
    base_url: str,
    model: str,
    system_prompt: str,
    utterance: str,
    schema: dict[str, Any],
    api_key: str | None = None,
    max_tokens: int = 512,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": utterance},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "assistant_request_v4",
                "strict": True,
                "schema": schema,
            },
        },
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = base_url.rstrip("/") + "/chat/completions"
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ModelError(f"model request failed: {error}") from error
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    choices = raw.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ModelError("model response must contain exactly one choice")
    choice = choices[0]
    content = choice.get("message", {}).get("content")
    if not isinstance(content, str) or not content:
        raise ModelError("model response has no output text")
    return {
        "content": content,
        "latency_ms": latency_ms,
        "usage": raw.get("usage", {}),
        "finish_reason": choice.get("finish_reason"),
    }
