"""Tests for the gitignore-aware file indexer (sbrain.index)."""

from pathlib import Path

from sbrain import index


def test_gitignore_basename_matches_at_any_depth():
    rules = [("ignore", "*.log")]
    assert index.is_ignored(rules, "a/b/debug.log", False) is True
    assert index.is_ignored(rules, "debug.log", False) is True
    assert index.is_ignored(rules, "a/b/debug.txt", False) is False


def test_anchored_pattern_does_not_match_nested():
    # "/server" must NOT match "tools/server/..." - this is the documented fix.
    rules = [("ignore", "/server")]
    assert index.is_ignored(rules, "server", True) is True
    assert index.is_ignored(rules, "tools/server", True) is False


def test_negation_reincludes_file():
    rules = [("ignore", "*.log"), ("negate", "keep.log")]
    assert index.is_ignored(rules, "keep.log", False) is False
    assert index.is_ignored(rules, "other.log", False) is True


def test_dir_only_pattern_ignores_dirs_not_files():
    rules = [("ignore", "build/")]
    assert index.is_ignored(rules, "build", True) is True
    assert index.is_ignored(rules, "build", False) is False


def test_symbols_extracted_for_python():
    lines = ["def foo():", "    pass", "class Bar:", "    def method(self):"]
    syms = index._symbols_for(Path("x.py"), lines)
    names = {s["name"] for s in syms}
    assert "foo" in names
    assert "Bar" in names
    assert "method" in names


def test_binary_detection_by_extension_and_null_byte():
    assert index._is_binary(Path("a.png"), b"whatever") is True
    assert index._is_binary(Path("a.txt"), b"hello\x00world") is True
    assert index._is_binary(Path("a.txt"), b"hello world") is False


def test_build_index_walks_a_temp_repo(tmp_path):
    (tmp_path / "keep.py").write_text("def hello():\n    return 1\n")
    (tmp_path / "skip.log").write_text("noise\n")
    (tmp_path / ".gitignore").write_text("*.log\n")
    (tmp_path / "empty.py").write_text("")  # zero-byte files are skipped

    idx = index.build_index(tmp_path)
    paths = {f["path"] for f in idx["files"]}
    assert "keep.py" in paths
    assert "skip.log" not in paths  # ignored
    assert "empty.py" not in paths  # zero-byte
    assert idx["n_files"] == len(idx["files"])


def test_cache_path_is_stable_and_hashed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    p1 = index.cache_path_for(tmp_path)
    p2 = index.cache_path_for(tmp_path)
    assert p1 == p2
    assert p1.suffix == ".json"


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache = index.cache_path_for(tmp_path)
    idx = {"root": str(tmp_path), "created": None, "n_files": 0, "files": []}
    index.save_index(idx, cache)
    loaded = index.load_index(cache)
    assert loaded is not None
    assert loaded["n_files"] == 0
    assert loaded["created"] is not None  # stamped on save


def test_load_index_missing_returns_none(tmp_path):
    assert index.load_index(tmp_path / "does-not-exist.json") is None
