"""dev-second-brain: index a local repo for grounded Q&A.

Phase 1: lightweight, dependency-free index.
  - gitignore-aware file walk
  - per-file line counts + regex symbol extraction (repo-map style)
  - stored as JSON in the user cache dir, keyed by repo root hash
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# gitignore handling (pragmatic subset: *, **, ?, !, trailing /, comments)
# ---------------------------------------------------------------------------

def _load_gitignore_rules(repo_root: Path) -> list[tuple[str, str]]:
    """Return list of (kind, pattern) where kind in {'ignore', 'negate'}."""
    rules: list[tuple[str, str]] = []
    gi = repo_root / ".gitignore"
    if not gi.is_file():
        return rules
    for raw in gi.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            rules.append(("negate", line[1:].strip()))
        else:
            rules.append(("ignore", line))
    return rules


def _matches(pattern: str, rel_path: str, is_dir: bool) -> bool:
    """Match a single gitignore pattern against a repo-relative path."""
    pat = pattern
    anchored = pat.startswith("/")
    pat = pat.lstrip("/")
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")

    if dir_only and not is_dir:
        return False

    def core(p: str, path: str) -> bool:
        if p == "**":
            return True
        # fnmatch's '*' also matches '/', which is over-broad but the safe
        # direction for an index (we may skip a few extra files, never miss
        # the anchored case).
        return fnmatch.fnmatch(path, p)

    if anchored or "/" in pat:
        # rooted pattern: relative to the repo root -> match the full path only.
        # This is the key fix: "/server" must NOT match "tools/server/...".
        return core(pat, rel_path)
    # no slash and not anchored: matches basename at any depth.
    return core(pat, Path(rel_path).name) or core(pat, rel_path)


def is_ignored(rules: list[tuple[str, str]], rel_path: str, is_dir: bool) -> bool:
    ignored = False
    for kind, pat in rules:
        if _matches(pat, rel_path, is_dir):
            ignored = kind == "ignore"
    return ignored


# ---------------------------------------------------------------------------
# binary / size filtering
# ---------------------------------------------------------------------------

_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".gz", ".bz2", ".xz", ".7z", ".tar", ".rar",
    ".so", ".a", ".o", ".dylib", ".dll", ".exe", ".bin", ".gguf", ".safetensors",
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".mov", ".mkv", ".webm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".pyc", ".pyo", ".class", ".jar", ".apk", ".aab", ".dex",
    ".db", ".sqlite", ".sqlite3", ".idx", ".pack",
}

_SKIP_DIRS = {".git", ".hg", ".svn", ".sbrain"}


def _is_binary(path: Path, sample: bytes) -> bool:
    if path.suffix.lower() in _BINARY_EXT:
        return True
    return b"\x00" in sample[:8192]


# ---------------------------------------------------------------------------
# symbol extraction (regex repo-map; not tree-sitter, good enough for phase 1)
# ---------------------------------------------------------------------------

_SYM_PATTERNS: dict[str, list[re.Pattern]] = {
    ".py": [
        re.compile(r"^\s*(?:async\s+)?def\s+(\w+)"),
        re.compile(r"^\s*class\s+(\w+)"),
    ],
    ".c": [
        re.compile(r"^\s*(?:static\s+|inline\s+|const\s+|LLAMA_API\w*\s+)*[\w\*]+\s+(\w+)\s*\("),
        re.compile(r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+(\w+)"),
    ],
    ".h": [
        re.compile(r"^\s*(?:LLAMA_API\w*\s+)?[\w\*]+\s+(\w+)\s*\("),
        re.compile(r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+(\w+)"),
    ],
    ".cpp": [
        re.compile(r"^\s*(?:static\s+|inline\s+|constexpr\s+|virtual\s+|explicit\s+|LLAMA_API\w*\s+)*[\w:<>,~*&]+\s+(\w+)\s*\("),
        re.compile(r"^\s*(?:class|struct|enum|namespace)\s+(\w+)"),
    ],
    ".cc": [
        re.compile(r"^\s*(?:static\s+|inline\s+|constexpr\s+|virtual\s+|explicit\s+)*[\w:<>,~*&]+\s+(\w+)\s*\("),
        re.compile(r"^\s*(?:class|struct|enum|namespace)\s+(\w+)"),
    ],
    ".hpp": [
        re.compile(r"^\s*(?:static\s+|inline\s+|constexpr\s+|virtual\s+|explicit\s+|LLAMA_API\w*\s+)*[\w:<>,~*&]+\s+(\w+)\s*\("),
        re.compile(r"^\s*(?:class|struct|enum|namespace)\s+(\w+)"),
    ],
    ".js": [
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\("),
    ],
    ".ts": [
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\("),
        re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)"),
    ],
    ".go": [re.compile(r"^\s*func\s+(?:\(\w+ \*\w+\)\s*)?(\w+)"), re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface)")],
    ".rs": [
        re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
        re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait|mod|impl)\s+(\w+)"),
    ],
    ".java": [
        re.compile(r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\w+)*\s*(\w+)\s*\("),
        re.compile(r"^\s*(?:public|private|protected|abstract|final)?\s*(?:class|interface|enum)\s+(\w+)"),
    ],
    ".kt": [
        re.compile(r"^\s*(?:public|private|internal|protected|override|suspend|fun)?\s*fun\s+(\w+)"),
        re.compile(r"^\s*(?:public|private|internal)?\s*(?:class|interface|object|data class)\s+(\w+)"),
    ],
    ".sh": [re.compile(r"^\s*([a-zA-Z_]\w*)\s*\(\)\s*\{"), re.compile(r"^\s*(?:function\s+)?([a-zA-Z_]\w*)\s*\(\)")],
}


def _symbols_for(path: Path, lines: list[str]) -> list[dict]:
    pats = _SYM_PATTERNS.get(path.suffix.lower())
    if not pats:
        return []
    out: list[dict] = []
    for i, line in enumerate(lines, start=1):
        for p in pats:
            m = p.search(line)
            if m:
                out.append({"name": m.group(1), "line": i})
                break
    return out


# ---------------------------------------------------------------------------
# index build
# ---------------------------------------------------------------------------

_MAX_FILE_BYTES = 1_000_000
_MAX_LINES = 60_000


def build_index(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    rules = _load_gitignore_rules(repo_root)
    files = []
    skipped = 0

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _SKIP_DIRS
            and not is_ignored(rules, os.path.relpath(os.path.join(dirpath, d), repo_root), True)
        )
        for fn in sorted(filenames):
            fp = Path(dirpath) / fn
            rel = os.path.relpath(fp, repo_root)
            if is_ignored(rules, rel, False):
                continue
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size > _MAX_FILE_BYTES or size == 0:
                skipped += 1
                continue
            try:
                with open(fp, "rb") as fh:
                    sample = fh.read(8192)
                if _is_binary(fp, sample):
                    skipped += 1
                    continue
                with open(fp, "r", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                skipped += 1
                continue
            lines = text.splitlines()
            if len(lines) > _MAX_LINES:
                skipped += 1
                continue
            files.append({
                "path": rel,
                "lines": len(lines),
                "size": size,
                "syms": _symbols_for(fp, lines),
            })

    index = {
        "root": str(repo_root),
        "created": None,
        "n_files": len(files),
        "files": files,
    }
    return index


def cache_path_for(repo_root: Path) -> Path:
    h = hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()[:16]
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sbrain"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"{h}.json"


def save_index(index: dict, path: Path) -> None:
    import time
    index["created"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, separators=(",", ":")))
    tmp.replace(path)


def load_index(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def index_repo(repo_root: Path) -> dict:
    idx = build_index(repo_root)
    save_index(idx, cache_path_for(repo_root))
    return idx


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    idx = index_repo(root)
    print(f"indexed {idx['n_files']} files from {idx['root']}")
    for f in idx["files"][:10]:
        print(f"  {f['path']} ({f['lines']} lines, {len(f['syms'])} syms)")
    if idx["n_files"] > 10:
        print(f"  ... and {idx['n_files'] - 10} more")
