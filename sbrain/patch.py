"""Phase 2: patch proposal + apply (unified diff, user confirm).

Flow:
  1. retrieve relevant context
  2. ask the model for a minimal unified diff
  3. extract + summarize the diff
  4. (optional) user confirmation
  5. apply with `patch -p1` (backups via -b)
"""

from __future__ import annotations

import difflib
import re
import subprocess
import tempfile
from pathlib import Path

PATCH_SYSTEM = (
    "You are a precise code-editing assistant. Given code context and an "
    "instruction, produce a MINIMAL unified diff that implements exactly the "
    "requested change and nothing else. Output ONLY the diff, using standard "
    "'diff --git a/<path> b/<path>' headers, correct 'index' and '--- / +++' "
    "lines, and accurate '@@ -l,c +l,c @@' hunk headers. Each removed line is "
    "prefixed '-', each added line '+', each unchanged context line ' '. Do "
    "NOT wrap the diff in markdown fences and do NOT add any explanation "
    "before or after it. If you cannot make the change, output 'NO_CHANGE'."
)


def build_prompt(instruction: str, context: str) -> str:
    return f"CODE CONTEXT:\n{context}\n\nINSTRUCTION: {instruction}\n\nProduce the unified diff now:"


_DIFF_START = re.compile(r"^(?:diff --git |--- |\+\+\+ |@@ )", re.M)
_VALID_PREFIXES = (
    "diff --git", "index ", "--- ", "+++ ", "@@ ",
    "new file mode", "deleted file mode", "similarity index", "rename from", "rename to",
)


def extract_diff(text: str) -> str | None:
    """Pull the unified diff out of a model reply, dropping prose/fences."""
    text = text.strip()
    text = text.strip("`")  # strip markdown fences
    lines = text.splitlines()

    start = None
    for i, l in enumerate(lines):
        if l.startswith("diff --git "):
            start = i
            break
        if l.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            start = i
            break
    if start is None:
        return None

    keep: list[str] = []
    saw_hunk = False
    for l in lines[start:]:
        if l.startswith(_VALID_PREFIXES):
            keep.append(l)
            if l.startswith("@@"):
                saw_hunk = True
            continue
        if saw_hunk and (l[:1] in ("+", "-", " ", "\\")):
            keep.append(l)
            continue
        if l.strip() == "":
            keep.append(l)
            continue
        break  # first non-diff line after the diff ends the extraction

    out = "\n".join(keep).rstrip()
    return out if saw_hunk else None


def summarize_diff(diff_text: str) -> list[str]:
    """List the files touched by a diff."""
    files = []
    for l in diff_text.splitlines():
        if l.startswith("diff --git "):
            # diff --git a/foo b/foo  (or "a/foo" "b/foo")
            parts = l.split()
            if len(parts) >= 4:
                files.append(parts[3].removeprefix("b/"))
            elif len(parts) == 3:
                files.append(parts[2].removeprefix("b/"))
    return files


def apply_diff(repo_root: Path, diff_text: str) -> tuple[bool, str]:
    """Apply a unified diff with `patch -p1`; returns (ok, output)."""
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
        fh.write(diff_text)
        tmp = fh.name
    try:
        proc = subprocess.run(
            ["patch", "-p1", "-f", "-b", "--no-backup-if-mismatch", "-i", tmp],
            cwd=repo_root, capture_output=True, text=True,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()
    except FileNotFoundError:
        return False, "patch(1) not found on PATH"
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# whole-file rewrite mode (more reliable for weak/small local models)
# ---------------------------------------------------------------------------

WHOLE_SYSTEM = (
    "You are a precise code-editing assistant. You are given the CURRENT "
    "content of one or more files and an instruction. Rewrite the COMPLETE new "
    "content of EVERY file that must change to satisfy the instruction. Keep "
    "all unchanged code byte-for-byte identical. Output ONLY the changed files, "
    "each exactly in this format:\n\n"
    "=== FILE: <path> ===\n<complete new file content>\n=== END ===\n\n"
    "Do not add explanation, markdown fences, or any text outside these blocks. "
    "If no change is needed, output exactly: NO_CHANGE"
)

def build_whole_prompt(instruction: str, files: dict[str, str]) -> str:
    parts = []
    for path, content in files.items():
        parts.append(f"=== FILE: {path} ===\n{content}=== END ===")
    return (
        "CURRENT FILES:\n" + "\n".join(parts)
        + f"\n\nINSTRUCTION: {instruction}\n\nNow output the changed files:"
    )


def parse_whole_reply(reply: str, allowed_paths: set[str]) -> dict[str, str]:
    """Extract {path: new_content} from a whole-file reply, preserving newlines."""
    stripped = reply.strip()
    if stripped.upper() == "NO_CHANGE" or (len(stripped) < 40 and "NO_CHANGE" in stripped.upper()):
        return {}

    def clean_path(s: str) -> str:
        return s.strip().removeprefix("a/").removeprefix("b/").removeprefix("./")

    out: dict[str, str] = {}
    cur_path: str | None = None
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_path, cur_lines
        if cur_path is not None and cur_path in allowed_paths and cur_lines:
            out[cur_path] = "".join(cur_lines)
        cur_path = None
        cur_lines = []

    for ln in reply.splitlines(keepends=True):
        s = ln.rstrip("\n").strip()
        if s.startswith("=== FILE: "):
            flush()
            header = s[len("=== FILE: "):]
            if header.endswith("==="):
                header = header[:-3]
            cur_path = clean_path(header)
            continue
        if s in ("=== END ===", "=== END"):
            flush()
            continue
        if cur_path is not None:
            cur_lines.append(ln)
    flush()
    return out


def compute_unified_diff(old: str, new: str, path: str, context: int = 3) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}", n=context,
    )
    body = "".join(diff)
    if not body:
        return ""
    return f"diff --git a/{path} b/{path}\n{body}"


def apply_whole_file(repo_root: Path, path: str, new_content: str) -> tuple[bool, str]:
    """Backup the original then write new content. Returns (ok, message)."""
    target = repo_root / path
    try:
        original = target.read_text()
    except OSError as e:
        return False, f"cannot read {path}: {e}"
    if original == new_content:
        return True, f"{path}: no change"
    try:
        (repo_root / (path + ".sbrain.bak")).write_text(original)
        target.write_text(new_content)
    except OSError as e:
        return False, f"cannot write {path}: {e}"
    return True, f"{path}: updated (backup at {path}.sbrain.bak)"
