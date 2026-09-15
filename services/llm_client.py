from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .logger import get_logger
from .paths import ROOT, load_json


log = get_logger("llm")


def _load_env() -> None:
    load_dotenv(ROOT / ".env")


def mock_mode() -> bool:
    _load_env()
    return os.getenv("MOCK_GENERATION", "false").strip().lower() in ("1", "true", "yes")


def model_name() -> str:
    _load_env()
    return os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    pricing = load_json(ROOT / "config" / "model_pricing.json")
    rates = pricing.get("models", {}).get(model)
    if not rates:
        return None
    return (prompt_tokens / 1_000_000.0) * rates["input_per_million"] + (
        completion_tokens / 1_000_000.0
    ) * rates["output_per_million"]


def chat_json(system: str, user: str, usage_acc: dict | None = None) -> dict:
    """Compact JSON chat completion. Never logs the API key."""
    _load_env()
    if mock_mode():
        log.info("LLM skipped (MOCK_GENERATION=true)")
        return {"_mock": True, "items": []}

    from openai import OpenAI

    model = model_name()
    log.info("LLM call start model=%s user_chars=%s", model, len(user))
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    text = resp.choices[0].message.content or "{}"
    usage = resp.usage
    ptok = int(getattr(usage, "prompt_tokens", 0) or 0)
    ctok = int(getattr(usage, "completion_tokens", 0) or 0)
    cost = estimate_cost_usd(model, ptok, ctok)
    log.info(
        "LLM call end model=%s prompt_tokens=%s completion_tokens=%s estimated_cost_usd=%s",
        model,
        ptok,
        ctok,
        f"{cost:.6f}" if cost is not None else "cost_not_configured",
    )
    if usage_acc is not None:
        usage_acc["model"] = model
        usage_acc["prompt_tokens"] = usage_acc.get("prompt_tokens", 0) + ptok
        usage_acc["completion_tokens"] = usage_acc.get("completion_tokens", 0) + ctok
        if cost is not None:
            usage_acc["estimated_cost_usd"] = round(usage_acc.get("estimated_cost_usd", 0.0) + cost, 6)
        else:
            usage_acc.setdefault("estimated_cost_usd", None)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error("LLM returned non-JSON; wrapping as empty items.")
        data = {"items": [], "raw": text[:500]}
    return data
