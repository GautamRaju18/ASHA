"""
Pluggable LLM interface with multi-provider FAILOVER.

`complete_json` tries each provider in a chain (configured primary first,
default Gemini, then local Ollama as a last resort) and fails over to the next
on ANY error — timeout, rate limit (429), or unparseable output. No artificial
rate-limiting/backoff: a provider that 429s or times out is abandoned
immediately for the next one.

JSON is parsed robustly (models occasionally wrap it in prose). If every
provider fails, callers apply the conservative (refer) default.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from app.config import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    OPENAI_COMPAT,
    GEMINI_PROVIDERS,
    OPENROUTER_PROVIDERS,
    LLM_TIMEOUT_S,
)


class LLMError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Provider availability + failover chain
# --------------------------------------------------------------------------- #
def _available(provider: str) -> bool:
    if provider in OPENAI_COMPAT:
        return bool(OPENAI_COMPAT[provider][1])  # has api key
    if provider == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    if provider == "ollama":
        return True
    return False


def provider_chain() -> list[str]:
    """Ordered providers to try: configured primary first, then the others
    that have credentials, with local Ollama as the last-resort fallback."""
    chain: list[str] = []

    def add(p: str) -> None:
        if p and p not in chain and _available(p):
            chain.append(p)

    add(LLM_PROVIDER)
    for p in GEMINI_PROVIDERS:  # Gemini models first (3.5 Flash, then 3 Pro)
        add(p)
    for p in OPENROUTER_PROVIDERS:  # free OpenRouter models as fallback
        add(p)
    add("anthropic")
    # Local Ollama is always the last-resort fallback: if every cloud provider is
    # rate-limited or down, the app still works (degraded) instead of failing.
    add("ollama")
    return chain or ["ollama"]


# --------------------------------------------------------------------------- #
# JSON extraction helpers
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> Optional[Any]:
    text = text.strip()
    # strip ```json fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # find first balanced {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
    return None


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
def _ollama_chat(system: str, user: str, temperature: float) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
    }
    try:
        r = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=LLM_TIMEOUT_S)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama request failed: {e}") from e
    return r.json().get("message", {}).get("content", "")


def _anthropic_chat(system: str, user: str, temperature: float) -> str:
    if not ANTHROPIC_API_KEY:
        raise LLMError("ASHA_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1500,
        "temperature": temperature,
        "system": system + "\n\nReturn ONLY valid JSON, no prose.",
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", json=payload,
                       headers=headers, timeout=LLM_TIMEOUT_S)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"Anthropic request failed: {e}") from e
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _openai_compatible_chat(provider: str, system: str, user: str, temperature: float) -> str:
    """Gemini / Kimi (Moonshot) — both speak the OpenAI chat-completions dialect."""
    base_url, api_key, model = OPENAI_COMPAT[provider]
    if not api_key:
        raise LLMError(f"ASHA_LLM_PROVIDER={provider} but its API key is not set")
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    # No backoff/throttle: on rate limit (429), timeout, or any error we raise
    # immediately so the caller fails over to the other provider.
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT_S)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise LLMError(f"{provider} request failed: {e.response.status_code} "
                       f"{e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise LLMError(f"{provider} request failed: {e}") from e
    choices = r.json().get("choices", [])
    if not choices:
        raise LLMError(f"{provider} returned no choices")
    return choices[0].get("message", {}).get("content", "")


def _raw_complete(provider: str, system: str, user: str, temperature: float) -> str:
    if provider == "anthropic":
        return _anthropic_chat(system, user, temperature)
    if provider in OPENAI_COMPAT:
        return _openai_compatible_chat(provider, system, user, temperature)
    return _ollama_chat(system, user, temperature)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
_NUDGE = ("\n\nYour previous reply was not valid JSON. "
          "Reply again with ONLY a single valid JSON object.")


def complete_json(system: str, user: str, temperature: float = 0.0,
                  retries: int = 1) -> Optional[Any]:
    """Try each provider in the failover chain. For each provider, attempt the
    call and parse JSON; on a transport error fail over IMMEDIATELY to the next
    provider (the chain has several fast models, so retrying a throttled one
    just adds latency); on unparseable output, nudge the same provider once.
    Returns parsed JSON or None if every provider fails."""
    errors: list[str] = []
    for provider in provider_chain():
        attempt_user = user
        for _ in range(retries + 1):
            try:
                text = _raw_complete(provider, system, attempt_user, temperature)
            except LLMError as e:
                errors.append(str(e))
                break  # provider down/throttled -> next provider, no waiting
            parsed = _extract_json(text)
            if parsed is not None:
                return parsed
            attempt_user = user + _NUDGE  # bad JSON: nudge same provider once
    if errors:
        print(f"[llm] all providers failed: {' | '.join(errors[-3:])}")
    return None


def health() -> dict:
    chain = provider_chain()
    primary = chain[0] if chain else LLM_PROVIDER
    info = {"provider": primary, "chain": chain, "ok": bool(chain)}

    def model_of(p: str) -> str:
        if p in OPENAI_COMPAT:
            return OPENAI_COMPAT[p][2]
        if p == "anthropic":
            return ANTHROPIC_MODEL
        return OLLAMA_MODEL

    info["model"] = model_of(primary)
    info["models"] = {p: model_of(p) for p in chain}
    info["detail"] = "failover: " + " -> ".join(chain) if len(chain) > 1 else f"single provider: {primary}"
    return info
