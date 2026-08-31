"""Local Q&A history (append-only JSONL)."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def history_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    d = Path(base) / "sbrain"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.jsonl"


def add(kind: str, question: str, answer: str, cited: list[dict], result: dict, repo: str) -> str:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "kind": kind,
        "question": question,
        "answer": answer,
        "repo": repo,
        "backend": result.get("backend"),
        "model": result.get("model"),
        "tokens": {
            k: result[k]
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            if result.get(k) is not None
        },
        "cost_usd": result.get("cost_usd"),
        "sources": [c["path"] for c in cited],
    }
    with open(history_path(), "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry["id"]


def list_entries(n: int = 20) -> list[dict]:
    p = history_path()
    if not p.exists():
        return []
    entries = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return entries[-n:][::-1]


def get_entry(entry_id: str) -> dict | None:
    p = history_path()
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("id") == entry_id:
            return e
    return None
