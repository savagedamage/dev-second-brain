"""sbrain CLI: index a repo, ask grounded questions with citations."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import index as index_mod
from . import history as history_mod
from . import llm as llm_mod
from . import patch as patch_mod
from . import retrieve as retrieve_mod

MODEL_PATH = "/data/data/com.termux/files/home/projects/local-meeting-notes/spike/qwen2.5-3b-instruct-q4_k_m.gguf"
SERVER_BIN = "/data/data/com.termux/files/home/projects/local-meeting-notes/spike/llama.cpp/build/bin/llama-server"


def _resolve_repo(arg: str | None) -> Path:
    return Path(arg or os.environ.get("SBRAIN_REPO", ".")).resolve()


def _load_or_build_index(repo: Path, quiet: bool = False) -> dict:
    cache = index_mod.cache_path_for(repo)
    idx = index_mod.load_index(cache)
    if idx is None:
        if not quiet:
            print(f"[sbrain] no index yet for {repo}; indexing ...", file=sys.stderr)
        idx = index_mod.index_repo(repo)
        if not quiet:
            print(f"[sbrain] indexed {idx['n_files']} files", file=sys.stderr)
    return idx


def _context_budget() -> tuple[int, int, int, int]:
    """(top_k, radius, max_lines_per_file, max_total_lines) tuned per backend."""
    if llm_mod.resolve_backend()["kind"] == "byok":
        return 4, 4, 60, 300
    return 3, 3, 35, 130


def cmd_index(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.path)
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 1
    t0 = time.time()
    idx = index_mod.index_repo(repo)
    print(f"indexed {idx['n_files']} files from {idx['root']} in {time.time() - t0:.1f}s")
    if args.verbose:
        for f in idx["files"]:
            print(f"  {f['path']} ({f['lines']} lines, {len(f['syms'])} syms)")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.path)
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 1
    idx = _load_or_build_index(repo)
    if idx["n_files"] == 0:
        print("error: index is empty; nothing to search", file=sys.stderr)
        return 1

    terms = retrieve_mod.tokenize(args.question)
    if not terms:
        print("error: empty query", file=sys.stderr)
        return 1

    top_k, radius, per_file, total = _context_budget()
    if args.top_k:
        top_k = args.top_k

    t0 = time.time()
    context, cited = retrieve_mod.build_context(
        repo, idx, terms, top_k=top_k, radius=radius,
        max_lines_per_file=per_file, max_total_lines=total,
    )
    if not context:
        print("no matches found in the indexed files", file=sys.stderr)
        return 1
    t_ret = time.time() - t0

    overview = retrieve_mod.repo_map_overview(idx, [c["path"] for c in cited])
    full_context = (
        f"RELEVANT FILES (repo map):\n{overview}\n\n"
        f"CODE CONTEXT (line-numbered):\n{context}"
    )

    print(f"[sbrain] retrieved {len(cited)} files in {t_ret*1000:.0f} ms "
          f"({sum(c['hits'] for c in cited)} hits); asking model ...", file=sys.stderr)

    max_tokens = args.max_tokens or llm_mod.default_max_tokens()
    try:
        result = llm_mod.chat(args.question, full_context, max_tokens=max_tokens)
    except llm_mod.LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print("\n" + result["answer"].strip() + "\n")
    print("---")
    print(f"backend: {result['backend']} ({result['model']})")
    if result["total_tokens"]:
        print(f"tokens: {result['total_tokens']} total "
              f"({result['prompt_tokens']} prompt / {result['completion_tokens']} completion)")
    if result.get("cost_usd") is not None:
        print(f"cost:   ${result['cost_usd']:.5f}")
    print("sources:")
    for c in cited:
        print(f"  {c['path']}  (score {c['score']}, {c['hits']} hits)")
    eid = history_mod.add("ask", args.question, result["answer"], cited, result, str(repo))
    print(f"history: {eid}")
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.path)
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 1
    idx = _load_or_build_index(repo)
    if idx["n_files"] == 0:
        print("error: index is empty; nothing to search", file=sys.stderr)
        return 1

    terms = retrieve_mod.tokenize(args.instruction)
    top_k, radius, per_file, total = _context_budget()
    if args.top_k:
        top_k = args.top_k
    _, cited = retrieve_mod.build_context(
        repo, idx, terms, top_k=top_k, radius=radius,
        max_lines_per_file=per_file, max_total_lines=total,
    )
    if not cited:
        print("no matching files found for that change", file=sys.stderr)
        return 1

    # read full content of candidate files (whole-file mode needs complete text)
    files: dict[str, str] = {}
    allowed: set[str] = set()
    for c in cited:
        p = repo / c["path"]
        try:
            text = p.read_text()
        except OSError:
            continue
        if len(text) > 30_000 or text.count("\n") > 600:
            print(f"[sbrain] note: {c['path']} too large for whole-file mode; skipped", file=sys.stderr)
            continue
        files[c["path"]] = text
        allowed.add(c["path"])
    if not files:
        print("no editable candidate files (all too large)", file=sys.stderr)
        return 1

    print(f"[sbrain] proposing change over {len(files)} file(s) "
          f"({', '.join(files)}) ...", file=sys.stderr)

    try:
        result = llm_mod.complete(
            patch_mod.WHOLE_SYSTEM,
            patch_mod.build_whole_prompt(args.instruction, files),
            max_tokens=args.max_tokens or llm_mod.default_max_tokens(),
            temperature=0.1,
        )
    except llm_mod.LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    changes = patch_mod.parse_whole_reply(result["answer"], allowed)
    if not changes:
        print("model reported no change (NO_CHANGE) or returned no valid file blocks.", file=sys.stderr)
        print("raw reply:\n" + result["answer"])
        return 1

    # show diffs
    diffs = []
    for path, new_content in changes.items():
        d = patch_mod.compute_unified_diff(files[path], new_content, path)
        if d:
            diffs.append(d)
    if not diffs:
        print("no content differences detected (model may have echoed input unchanged).", file=sys.stderr)
        return 1

    print("\n" + "\n".join(diffs) + "\n")
    print(f"would modify: {', '.join(changes)}")

    if args.dry_run:
        print("[dry-run] no changes applied")
        return 0

    if not args.yes:
        ans = input("Apply these changes? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("aborted")
            return 1

    ok_all = True
    for path, new_content in changes.items():
        ok, msg = patch_mod.apply_whole_file(repo, path, new_content)
        print(msg)
        ok_all = ok_all and ok
    if ok_all:
        eid = history_mod.add("fix", args.instruction, "\n".join(diffs), cited, result, str(repo))
        print(f"history: {eid}")
    return 0 if ok_all else 1


def cmd_status(args: argparse.Namespace) -> int:
    repo = _resolve_repo(args.path)
    backend = llm_mod.resolve_backend()
    print(f"repo:        {repo}")
    cache = index_mod.cache_path_for(repo)
    idx = index_mod.load_index(cache)
    if idx:
        age = time.time() - (idx.get("created") or 0)
        print(f"index:       {idx['n_files']} files, {age/60:.0f} min old ({cache.name})")
    else:
        print("index:       none (run 'sbrain index')")
    print(f"backend:     {backend['kind']} -> {backend['base']} (model: {backend['model']})")
    if backend["kind"] == "byok" and not backend["key"]:
        print("warning:     SBRAIN_API_KEY not set", file=sys.stderr)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    if args.show:
        e = history_mod.get_entry(args.show)
        if not e:
            print(f"no entry with id {args.show}", file=sys.stderr)
            return 1
        _print_entry(e)
        return 0
    entries = history_mod.list_entries(args.last)
    if not entries:
        print("no history yet (run 'sbrain ask ...')")
        return 0
    for e in entries:
        q = e["question"].replace("\n", " ")[:70]
        ts = time.strftime("%m-%d %H:%M", time.localtime(e["ts"]))
        cost = f"  ${e['cost_usd']:.5f}" if e.get("cost_usd") is not None else ""
        print(f"{e['id']}  {ts}  [{e['kind']}] {e['backend']}/{e['model']}{cost}")
        print(f"    {q}")
    return 0


def _print_entry(e: dict) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["ts"]))
    print(f"id:       {e['id']}")
    print(f"time:     {ts}")
    print(f"kind:     {e['kind']}")
    print(f"backend:  {e['backend']} ({e['model']})")
    print(f"repo:     {e['repo']}")
    print(f"question: {e['question']}")
    t = e.get("tokens") or {}
    if t.get("total_tokens"):
        print(f"tokens:   {t.get('total_tokens')} total ({t.get('prompt_tokens')} p / {t.get('completion_tokens')} c)")
    if e.get("cost_usd") is not None:
        print(f"cost:     ${e['cost_usd']:.5f}")
    if e.get("sources"):
        print("sources:  " + ", ".join(e["sources"]))
    print("\n" + (e["answer"] or "").strip())


def cmd_server(args: argparse.Namespace) -> int:
    print("# start the local model server (background):")
    print(f"  {SERVER_BIN} -m {MODEL_PATH} --port 8080 -c {args.ctx} "
          f"--threads {args.threads} --parallel 1 &")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="sbrain",
        description="Dev Second Brain: grounded Q&A over a local codebase.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="build/refresh the index for a repo")
    p_index.add_argument("path", nargs="?", default=None, help="repo root (default: cwd or SBRAIN_REPO)")
    p_index.add_argument("-v", "--verbose", action="store_true")
    p_index.set_defaults(func=cmd_index)

    p_ask = sub.add_parser("ask", help="ask a question about the repo")
    p_ask.add_argument("question", help="natural-language question")
    p_ask.add_argument("path", nargs="?", default=None, help="repo root (default: cwd or SBRAIN_REPO)")
    p_ask.add_argument("--top-k", type=int, default=None, help="files to include in context (default: 4 BYOK / 3 local)")
    p_ask.add_argument("--max-tokens", type=int, default=None)
    p_ask.set_defaults(func=cmd_ask)

    p_fix = sub.add_parser("fix", help="propose and apply a code change (unified diff)")
    p_fix.add_argument("instruction", help="natural-language change instruction")
    p_fix.add_argument("path", nargs="?", default=None, help="repo root (default: cwd or SBRAIN_REPO)")
    p_fix.add_argument("--top-k", type=int, default=None, help="files to include in context (default: 4 BYOK / 3 local)")
    p_fix.add_argument("--max-tokens", type=int, default=None)
    p_fix.add_argument("--yes", action="store_true", help="apply without prompting")
    p_fix.add_argument("--dry-run", action="store_true", help="show the diff but do not apply")
    p_fix.set_defaults(func=cmd_fix)

    p_status = sub.add_parser("status", help="show repo/backend status")
    p_status.add_argument("path", nargs="?", default=None)
    p_status.set_defaults(func=cmd_status)

    p_hist = sub.add_parser("history", help="browse past queries")
    p_hist.add_argument("--last", type=int, default=20, help="entries to list (default 20)")
    p_hist.add_argument("show", nargs="?", default=None, help="entry id to show in full")
    p_hist.set_defaults(func=cmd_history)

    p_server = sub.add_parser("server", help="print the local llama-server command")
    p_server.add_argument("--ctx", type=int, default=8192)
    p_server.add_argument("--threads", type=int, default=8)
    p_server.set_defaults(func=cmd_server)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
