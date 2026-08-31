"""LLM backend: OpenAI-compatible chat completions over urllib.

Resolution order:
  1. SBRAIN_BASE_URL set  -> BYOK endpoint (e.g. https://api.deepseek.com/v1),
     requires SBRAIN_API_KEY, model from SBRAIN_MODEL.
  2. otherwise            -> local llama-server on SBRAIN_LOCAL_URL
     (default http://127.0.0.1:8080/v1).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_LOCAL_URL = "http://127.0.0.1:8080/v1"
DEFAULT_LOCAL_MODEL = "local"

SYSTEM_PROMPT = (
    "You are a precise code assistant. Answer the user's question about the "
    "codebase using ONLY the provided context snippets. Every factual claim "
    "must be grounded in the context. Cite sources inline as path:line "
    "(e.g. src/auth.c:120). If the context does not contain the answer, say "
    "so directly - do not guess or use outside knowledge. Be concise."
)


class LLMError(Exception):
    pass


def _cost_usd(prompt_tokens, completion_tokens) -> float | None:
    """Cost from SBRAIN_PRICE_INPUT / SBRAIN_PRICE_OUTPUT (USD per 1M tokens)."""
    pi = os.environ.get("SBRAIN_PRICE_INPUT")
    po = os.environ.get("SBRAIN_PRICE_OUTPUT")
    if pi is None or po is None:
        return None
    try:
        return ((prompt_tokens or 0) / 1e6) * float(pi) + ((completion_tokens or 0) / 1e6) * float(po)
    except ValueError:
        return None


def resolve_backend() -> dict:
    base = os.environ.get("SBRAIN_BASE_URL", "").strip().rstrip("/")
    if base:
        return {
            "kind": "byok",
            "base": base,
            "key": os.environ.get("SBRAIN_API_KEY", "").strip(),
            "model": os.environ.get("SBRAIN_MODEL", "").strip() or "deepseek-v4-flash",
        }
    return {
        "kind": "local",
        "base": os.environ.get("SBRAIN_LOCAL_URL", DEFAULT_LOCAL_URL).rstrip("/"),
        "key": "",
        "model": os.environ.get("SBRAIN_MODEL", "").strip() or DEFAULT_LOCAL_MODEL,
    }


def complete(system: str, user: str, max_tokens: int = 900, temperature: float = 0.2) -> dict:
    """Raw chat-completions call with explicit messages. Returns result dict."""
    backend = resolve_backend()
    payload = {
        "model": backend["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{backend['base']}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {backend['key']}"} if backend["key"] else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(os.environ.get("SBRAIN_TIMEOUT", "600"))) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        raise LLMError(f"HTTP {e.code} from {backend['kind']} backend: {body}") from e
    except urllib.error.URLError as e:
        hint = ""
        if backend["kind"] == "local":
            hint = (". Is llama-server running? Start it with 'sbrain server' "
                    "(or set SBRAIN_BASE_URL/SBRAIN_API_KEY for BYOK)")
        raise LLMError(f"cannot reach {backend['kind']} backend at {backend['base']}: {e.reason}{hint}") from e
    except (json.JSONDecodeError, KeyError) as e:
        raise LLMError(f"bad response from {backend['kind']} backend: {e}") from e

    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected response shape from {backend['kind']} backend: {e}") from e
    usage = data.get("usage", {})
    return {
        "answer": answer,
        "backend": backend["kind"],
        "model": backend["model"],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost_usd": _cost_usd(usage.get("prompt_tokens"), usage.get("completion_tokens")),
    }


def chat(question: str, context: str, max_tokens: int = 900, temperature: float = 0.2,
         system: str | None = None) -> dict:
    user = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
    return complete(system or SYSTEM_PROMPT, user, max_tokens=max_tokens, temperature=temperature)


def default_max_tokens() -> int:
    """BYOK reasoning models spend tokens on chain-of-thought and need headroom."""
    return 2000 if resolve_backend()["kind"] == "byok" else 320
