"""Tests for local history storage and LLM backend resolution."""

from sbrain import history, llm


def test_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    result = {
        "backend": "local",
        "model": "test-model",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "cost_usd": None,
    }
    cited = [{"path": "a.py"}, {"path": "b.py"}]
    eid = history.add("ask", "what is this?", "an answer", cited, result, "/repo")
    assert len(eid) == 12

    entries = history.list_entries(10)
    assert len(entries) == 1
    assert entries[0]["question"] == "what is this?"
    assert entries[0]["sources"] == ["a.py", "b.py"]

    fetched = history.get_entry(eid)
    assert fetched is not None
    assert fetched["answer"] == "an answer"


def test_history_get_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert history.get_entry("deadbeef0000") is None


def test_resolve_backend_defaults_to_local(monkeypatch):
    monkeypatch.delenv("SBRAIN_BASE_URL", raising=False)
    backend = llm.resolve_backend()
    assert backend["kind"] == "local"
    assert backend["base"].startswith("http")


def test_resolve_backend_byok_when_base_url_set(monkeypatch):
    monkeypatch.setenv("SBRAIN_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("SBRAIN_API_KEY", "sk-test")
    monkeypatch.setenv("SBRAIN_MODEL", "some-model")
    backend = llm.resolve_backend()
    assert backend["kind"] == "byok"
    assert backend["base"] == "https://api.example.com/v1"
    assert backend["key"] == "sk-test"
    assert backend["model"] == "some-model"


def test_cost_usd_none_without_prices(monkeypatch):
    monkeypatch.delenv("SBRAIN_PRICE_INPUT", raising=False)
    monkeypatch.delenv("SBRAIN_PRICE_OUTPUT", raising=False)
    assert llm._cost_usd(100, 50) is None


def test_cost_usd_computes_with_prices(monkeypatch):
    monkeypatch.setenv("SBRAIN_PRICE_INPUT", "1.0")  # $1 per 1M input tokens
    monkeypatch.setenv("SBRAIN_PRICE_OUTPUT", "2.0")  # $2 per 1M output tokens
    cost = llm._cost_usd(1_000_000, 1_000_000)
    assert cost == 3.0


def test_default_max_tokens_higher_for_byok(monkeypatch):
    monkeypatch.setenv("SBRAIN_BASE_URL", "https://api.example.com/v1")
    assert llm.default_max_tokens() == 2000
    monkeypatch.delenv("SBRAIN_BASE_URL", raising=False)
    assert llm.default_max_tokens() == 320
