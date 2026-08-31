"""Retrieval: lexical search (rg) with IDF weighting -> ranked context.

Design notes (phase 1):
  - English stopwords are dropped from the query.
  - Each surviving term is IDF-weighted via per-term document frequency
    (rg -l), so common repo terms like "llama"/"server" naturally score low.
  - Adjacent term pairs are also joined ("api key" -> "api_key", "apikey",
    "api-key") because code identifiers are frequently underscore/camel forms.
  - Line hits come from one combined rg -n call; files are ranked by the sum
    of matched-term IDF weights plus hit-density / filename / symbol bonuses.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
    "where", "which", "who", "whom", "what", "how", "why", "is", "are",
    "was", "were", "be", "been", "being", "am", "do", "does", "did",
    "have", "has", "had", "will", "would", "can", "could", "should",
    "shall", "may", "might", "must", "to", "of", "in", "on", "at", "by",
    "for", "with", "about", "into", "through", "during", "before", "after",
    "above", "below", "from", "up", "down", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "also", "this", "that", "these", "those", "it", "its", "i",
    "you", "your", "we", "our", "they", "them", "their", "he", "she",
    "his", "her", "us", "me", "my", "does", "happen", "happens", "require",
    "required", "missing", "wrong", "instead", "please", "explain",
    "show", "find", "tell", "give", "like", "using", "use", "used",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _filtered_terms(tokens: list[str]) -> list[str]:
    """Drop stopwords and near-duplicates; preserve order."""
    seen = set()
    out = []
    for t in tokens:
        if len(t) < 2 or t in _STOPWORDS or t.isdigit():
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


_SYNONYMS = {
    "authenticate": "auth",
    "authentication": "auth",
    "authenticated": "auth",
    "authorize": "auth",
    "authorization": "auth",
    "authorised": "auth",
    "permissions": "permission",
    "signin": "login",
    "sign-in": "login",
}


def expand_terms(tokens: list[str]) -> list[str]:
    """Add underscore/camel/hyphen joins, light stemming, and synonyms."""
    base = _filtered_terms(tokens)
    out = list(base)
    for a, b in zip(base, base[1:]):
        out.extend([f"{a}_{b}", f"{a}{b}", f"{a}-{b}"])
    for t in base:
        # light plural -> singular stemming
        if len(t) > 4 and t.endswith("es"):
            out.append(t[:-2])
        elif len(t) > 3 and t.endswith("s"):
            out.append(t[:-1])
        if t in _SYNONYMS:
            out.append(_SYNONYMS[t])
    seen = set()
    res = []
    for t in out:
        if t not in seen:
            seen.add(t)
            res.append(t)
    return res


def _norm(p: str) -> str:
    return p.removeprefix("./")


def _run_rg(args: list[str], repo_root: Path, timeout: int = 60) -> list[str]:
    try:
        proc = subprocess.run(
            ["rg", *args], cwd=repo_root, capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    return proc.stdout.splitlines()


def doc_freq(repo_root: Path, term: str) -> set[str]:
    """Files containing a term (for IDF)."""
    out = _run_rg(["-l", "-i", "-g", "!.git/**", "-e", term, "."], repo_root)
    return {_norm(p) for p in out if p}


def line_hits(repo_root: Path, terms: list[str]) -> dict[str, list[int]]:
    """Combined rg -n: {rel_path: [line numbers]}."""
    if not terms:
        return {}
    eargs = [x for t in terms for x in ("-e", t)]
    out = _run_rg(["-n", "-i", "--no-heading", "-m", "300", "-g", "!.git/**", *eargs, "."], repo_root)
    hits: dict[str, list[int]] = {}
    for line in out:
        parts = line.split(":", 2)
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        hits.setdefault(_norm(parts[0]), []).append(int(parts[1]))
    return hits


def score_files(
    term_dfs: dict[str, set[str]],
    hits: dict[str, list[int]],
    idx_files: dict[str, dict],
    terms: list[str],
    n_files: int,
) -> list[tuple[float, str]]:
    """Rank files by IDF-weighted term matches + density/name/symbol bonuses."""
    idf = {}
    for t in terms:
        df = len(term_dfs.get(t, ()))
        idf[t] = math.log((n_files + 1) / (df + 1)) + 1.0

    scores: dict[str, float] = {}
    hit_counts: dict[str, int] = {}
    for t in terms:
        w = idf[t]
        for path in term_dfs.get(t, ()):
            if path not in idx_files:
                continue
            scores[path] = scores.get(path, 0.0) + w

    # hit density: reward files with concentrated matches
    for path, lines in hits.items():
        if path not in idx_files:
            continue
        hit_counts[path] = len(lines)
        scores[path] = scores.get(path, 0.0) + min(len(lines), 15) * 0.3

    # filename + symbol bonuses (IDF-weighted; symbol bonus is once per term,
    # NOT summed over every symbol, so files with many same-prefix symbols
    # like "llama_*" don't get inflated)
    for path, base_score in list(scores.items()):
        fmeta = idx_files[path]
        name = Path(path).name.lower()
        for t in terms:
            if t in name:
                scores[path] += idf[t] * 1.2
        for t in terms:
            if len(t) >= 3 and any(t in s["name"].lower() for s in fmeta.get("syms", [])):
                scores[path] += idf[t] * 0.8

    ranked = sorted(((v, k) for k, v in scores.items()), key=lambda x: -x[0])
    return ranked[:12]


def _read_lines(repo_root: Path, rel_path: str) -> list[str]:
    try:
        return (repo_root / rel_path).read_text(errors="replace").splitlines()
    except OSError:
        return []


def _merge_windows(line_nos: list[int], radius: int, max_lines: int) -> list[tuple[int, int]]:
    if not line_nos:
        return []
    pts = sorted(set(line_nos))
    raw = [(max(1, ln - radius), ln + radius) for ln in pts]
    merged: list[tuple[int, int]] = []
    for s, e in raw:
        if merged and s <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    total = sum(e - s + 1 for s, e in merged)
    if total <= max_lines:
        return merged

    # over budget: keep the DENSEST hit clusters (not just the earliest),
    # so the actual answer location wins over sparse matches elsewhere.
    scored = sorted(
        ((sum(1 for ln in pts if s <= ln <= e), s, e) for s, e in merged),
        key=lambda x: (-(x[0] / max(1, x[2] - x[1] + 1)), -x[0]),
    )
    kept: list[tuple[int, int]] = []
    used = 0
    for h, s, e in scored:
        length = e - s + 1
        if used + length > max_lines:
            remain = max_lines - used
            if remain <= 0:
                break
            hits_in = [ln for ln in pts if s <= ln <= e]
            center = hits_in[len(hits_in) // 2] if hits_in else s
            ns = max(1, center - remain // 2)
            kept.append((ns, ns + remain - 1))
            used += remain
            continue
        kept.append((s, e))
        used += length
    kept.sort()
    return kept


def build_context(
    repo_root: Path,
    idx: dict,
    terms: list[str],
    top_k: int = 3,
    radius: int = 3,
    max_lines_per_file: int = 35,
    max_total_lines: int = 130,
) -> tuple[str, list[dict]]:
    idx_files = {f["path"]: f for f in idx["files"]}
    n_files = max(1, len(idx_files))

    terms = expand_terms(terms)
    if not terms:
        return "", []

    term_dfs = {t: doc_freq(repo_root, t) for t in terms}
    hits = line_hits(repo_root, terms)
    ranked = score_files(term_dfs, hits, idx_files, terms, n_files)[:top_k]

    # Window on RARE terms (low document frequency) so the context centers on
    # discriminating signal ("api_key", "auth") rather than generic words
    # ("server", "http", "request") that match everywhere.
    idf = {t: math.log((n_files + 1) / (len(term_dfs.get(t, ())) + 1)) + 1.0 for t in terms}
    df_thresh = max(20, n_files // 20)
    rare = sorted(
        (t for t in terms if 0 < len(term_dfs.get(t, ())) < df_thresh),
        key=lambda t: -idf[t],
    )
    top_idf = rare[:12]
    win_hits = line_hits(repo_root, top_idf) if top_idf else hits

    blocks: list[str] = []
    cited: list[dict] = []
    used_lines = 0
    for score, path in ranked:
        fmeta = idx_files[path]
        lines = _read_lines(repo_root, path)
        if not lines:
            continue
        windows = _merge_windows(win_hits.get(path, []) or hits.get(path, []), radius, max_lines_per_file)
        if not windows:
            continue
        sym_lines = ""
        if fmeta.get("syms"):
            syms = "; ".join(f"{s['name']}@{s['line']}" for s in fmeta["syms"][:14])
            sym_lines = f"  symbols: {syms}\n"
        header = f"### {path} ({len(lines)} lines)\n{sym_lines}"
        body = []
        for s, e in windows:
            for ln in range(s, min(e, len(lines)) + 1):
                body.append(f"L{ln}| {lines[ln - 1]}")
        budget = max_total_lines - used_lines
        if len(body) > budget:
            body = body[:budget]
        if not body:
            continue
        blocks.append(header + "\n".join(body))
        used_lines += len(body)
        cited.append({"path": path, "score": round(score, 1), "hits": len(hits.get(path, []))})
        if used_lines >= max_total_lines:
            break

    return "\n\n".join(blocks), cited


def repo_map_overview(idx: dict, top_paths: list[str], max_files: int = 25) -> str:
    idx_files = {f["path"]: f for f in idx["files"]}
    lines = []
    for path in top_paths[:max_files]:
        fmeta = idx_files.get(path)
        if fmeta is None:
            continue
        syms = fmeta.get("syms", [])[:8]
        suffix = f"  [{', '.join(s['name'] for s in syms)}]" if syms else ""
        lines.append(f"{path}{suffix}")
    return "\n".join(lines)
