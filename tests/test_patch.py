"""Tests for diff extraction and whole-file rewrite parsing (sbrain.patch)."""

from sbrain import patch


def test_extract_diff_strips_prose_and_fences():
    reply = (
        "Here is the change you asked for:\n\n"
        "```\n"
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old line\n"
        "+new line\n"
        " context\n"
        "```\n"
        "Hope that helps!"
    )
    diff = patch.extract_diff(reply)
    assert diff is not None
    assert diff.startswith("diff --git a/foo.py b/foo.py")
    assert "+new line" in diff
    assert "Hope that helps" not in diff


def test_extract_diff_returns_none_without_hunk():
    assert patch.extract_diff("no diff here at all") is None


def test_summarize_diff_lists_files():
    diff = "diff --git a/src/app.py b/src/app.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert patch.summarize_diff(diff) == ["src/app.py"]


def test_parse_whole_reply_extracts_file_blocks():
    reply = "=== FILE: foo.py ===\ndef add(a, b):\n    return a + b\n=== END ===\n"
    out = patch.parse_whole_reply(reply, allowed_paths={"foo.py"})
    assert "foo.py" in out
    assert out["foo.py"] == "def add(a, b):\n    return a + b\n"


def test_parse_whole_reply_ignores_disallowed_paths():
    reply = "=== FILE: /etc/passwd ===\nmalicious\n=== END ===\n"
    out = patch.parse_whole_reply(reply, allowed_paths={"foo.py"})
    assert out == {}


def test_parse_whole_reply_handles_no_change():
    assert patch.parse_whole_reply("NO_CHANGE", allowed_paths={"foo.py"}) == {}


def test_compute_unified_diff_detects_change():
    diff = patch.compute_unified_diff("a\nb\n", "a\nc\n", "x.py")
    assert "diff --git a/x.py b/x.py" in diff
    assert "-b" in diff
    assert "+c" in diff


def test_compute_unified_diff_empty_when_identical():
    assert patch.compute_unified_diff("a\n", "a\n", "x.py") == ""


def test_apply_whole_file_writes_and_backs_up(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("original\n")
    ok, msg = patch.apply_whole_file(tmp_path, "code.py", "updated\n")
    assert ok is True
    assert target.read_text() == "updated\n"
    backup = tmp_path / "code.py.sbrain.bak"
    assert backup.exists()
    assert backup.read_text() == "original\n"


def test_apply_whole_file_noop_when_unchanged(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("same\n")
    ok, msg = patch.apply_whole_file(tmp_path, "code.py", "same\n")
    assert ok is True
    assert "no change" in msg
    assert not (tmp_path / "code.py.sbrain.bak").exists()
