"""Tests for query tokenization, expansion, and file scoring (sbrain.retrieve)."""

from sbrain import retrieve


def test_tokenize_lowercases_and_splits():
    assert retrieve.tokenize("Where is Auth handled?") == ["where", "is", "auth", "handled"]


def test_filtered_terms_drop_stopwords_and_short_tokens():
    terms = retrieve._filtered_terms(retrieve.tokenize("where is the api key check"))
    assert "the" not in terms
    assert "is" not in terms
    assert "api" in terms
    assert "key" in terms


def test_expand_terms_joins_adjacent_identifiers():
    out = retrieve.expand_terms(["api", "key"])
    assert "api_key" in out
    assert "apikey" in out
    assert "api-key" in out


def test_expand_terms_applies_synonyms():
    out = retrieve.expand_terms(["authentication"])
    assert "auth" in out


def test_expand_terms_light_stemming():
    out = retrieve.expand_terms(["permissions"])
    # synonym map maps permissions -> permission
    assert "permission" in out


def test_expand_terms_deduplicates():
    out = retrieve.expand_terms(["auth", "auth"])
    assert out.count("auth") == 1


def test_merge_windows_merges_overlapping():
    # radius 2 around lines 10 and 11 should merge into one window.
    windows = retrieve._merge_windows([10, 11], radius=2, max_lines=100)
    assert windows == [(8, 13)]


def test_merge_windows_respects_budget():
    windows = retrieve._merge_windows([5, 50, 500], radius=2, max_lines=6)
    total = sum(e - s + 1 for s, e in windows)
    assert total <= 6


def test_score_files_ranks_rare_terms_higher():
    # "auth" appears in 1 file, "server" appears in everything -> auth wins.
    n_files = 10
    idx_files = {f"f{i}.py": {"path": f"f{i}.py", "syms": []} for i in range(n_files)}
    term_dfs = {
        "auth": {"f0.py"},
        "server": {f"f{i}.py" for i in range(n_files)},
    }
    hits = {}
    ranked = retrieve.score_files(term_dfs, hits, idx_files, ["auth", "server"], n_files)
    top_path = ranked[0][1]
    assert top_path == "f0.py"


def test_repo_map_overview_lists_symbols():
    idx = {"files": [{"path": "a.py", "syms": [{"name": "foo", "line": 1}]}]}
    out = retrieve.repo_map_overview(idx, ["a.py"])
    assert "a.py" in out
    assert "foo" in out
