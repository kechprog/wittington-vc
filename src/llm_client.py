"""Small OpenRouter client for fit judgment.

OpenRouter uses an OpenAI-compatible chat completions API. We keep this module
stdlib-only to preserve the repo's minimal dependency footprint.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from pydantic import ValidationError

from models import FitJudgment, WittingtonCategory

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
_JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_FIT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "score_adjustment": {"type": "integer", "minimum": -20, "maximum": 20},
        "category": {"type": "string", "enum": [category.value for category in WittingtonCategory]},
        "rationale": {"type": "string"},
    },
    "required": ["score_adjustment", "category", "rationale"],
    "additionalProperties": False,
}


def judge_fit(prompt: str, *, model: str = DEFAULT_MODEL) -> FitJudgment | None:
    """Return a structured fit judgment, or None if the LLM call fails."""
    api_key = os.environ.get("OPENROUTER_API")
    if not api_key:
        return None

    base_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You score venture prospects for Wittington Ventures. "
                    "Return only JSON with score_adjustment, category, rationale. "
                    "Be concise, conservative, and do not invent facts."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 180,
    }
    payloads = [
        {
            **base_payload,
            "provider": {"require_parameters": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "fit_judgment",
                    "strict": True,
                    "schema": _FIT_JUDGMENT_SCHEMA,
                },
            },
        },
        {**base_payload, "response_format": {"type": "json_object"}},
        base_payload,
    ]

    for body_payload in payloads:
        content = _chat_completion(api_key, body_payload)
        if content is None:
            continue

        match = _JSON_BLOCK_PATTERN.search(content or "")
        if not match:
            continue
        try:
            return FitJudgment.model_validate_json(match.group(0))
        except ValidationError:
            continue
    return None


def _chat_completion(api_key: str, payload: dict) -> str | None:
    request = urllib.request.Request(
        _OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "Wittington VC Prospect Ranker",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.load(response)
        return body["choices"][0]["message"]["content"]
    except (
        KeyError,
        IndexError,
        TypeError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        return None
