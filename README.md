# Dev Second Brain

[![CI](https://github.com/savagedamage/dev-second-brain/actions/workflows/ci.yml/badge.svg)](https://github.com/savagedamage/dev-second-brain/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A coding assistant that indexes your codebase locally and answers questions
with grounded, file:line citations. Phase 1 = CLI (index + grounded Q&A).
BYOK at cost, or a local model via llama.cpp. No telemetry.

## Status

- [x] Phase 1: `sbrain index` + `sbrain ask` (retrieval + cited answers)
- [x] Phase 2: `sbrain fix` (whole-file rewrite -> local diff -> apply w/ confirm + backup)
- [x] Phase 3: BYOK (DeepSeek V4), per-query $ cost, local history
- [ ] Phase 4: editor plugin / Android app, local-model default

## Layout

    sbrain/
      index.py     gitignore-aware walk + regex symbol (repo-map) extraction
      retrieve.py  IDF-weighted lexical search (rg) -> line-numbered context
      llm.py       OpenAI-compatible backend (local llama-server or BYOK)
      cli.py       subcommands: index / ask / status / server
    bin/sbrain     launcher

## Requirements

- Python 3.9+
- [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) on your PATH — used for
  fast lexical search. Install with `apt install ripgrep`, `brew install ripgrep`,
  or `pkg install ripgrep` (Termux).
- A model backend: either a local [llama.cpp](https://github.com/ggerganov/llama.cpp)
  server, or a BYOK OpenAI-compatible API (see [BYOK](#byok) below).

## Install

```bash
pip install git+https://github.com/savagedamage/dev-second-brain.git
# or, from a clone:
git clone https://github.com/savagedamage/dev-second-brain.git
cd dev-second-brain
pip install -e .
```

This installs an `sbrain` command. (You can also run it without installing via
`python3 -m sbrain ...` or `bin/sbrain ...` from a clone.)

## Usage

    # 1. index a repo (once; cached in ~/.cache/sbrain/<hash>.json)
    sbrain index /path/to/repo

    # 2. start a local model server (llama.cpp)
    sbrain server            # prints the command; set SBRAIN_SERVER_BIN /
                             # SBRAIN_MODEL_PATH to point at your binary + model

    # 3. ask
    sbrain ask "where is auth handled?" /path/to/repo

    # 4. fix (propose + apply a code change, with confirmation + .sbrain.bak backup)
    sbrain fix "fix the add function to return a + b" /path/to/repo
    #   flags: --yes (skip prompt), --dry-run (show diff only), --top-k N

    # 5. history (browse past queries; JSONL in ~/.local/share/sbrain/history.jsonl)
    sbrain history --last 10
    sbrain history <id>

    # optional: per-query cost (USD per 1M tokens; set both to enable)
    export SBRAIN_PRICE_INPUT=0.27 SBRAIN_PRICE_OUTPUT=1.10

### BYOK

    export SBRAIN_BASE_URL=https://api.deepseek.com/v1
    export SBRAIN_API_KEY=sk-...
    export SBRAIN_MODEL=deepseek-v4-flash      # or deepseek-v4-pro / deepseek-v4-flash-vision-exp
    bin/sbrain ask "..." /path/to/repo

Tested 2026-08-31 with DeepSeek-V4-Flash: ~12s end-to-end, high-quality grounded
answers with accurate file:line citations. Note: DeepSeek V4 models are REASONING
models (chain-of-thought in `reasoning_content`), so sbrain auto-bumps max_tokens
and widens the context budget for BYOK (see llm.default_max_tokens).

## Retrieval notes (the make-or-break)

- English stopwords dropped; remaining query terms are IDF-weighted via
  per-term document frequency (rg -l), so common repo terms ("llama",
  "server") score low while discriminators ("api_key", "auth") score high.
- Adjacent terms are joined to identifier forms ("api key" -> api_key),
  plus light plural->singular stemming and a small synonym map
  (authenticate -> auth).
- Symbol bonus is once-per-term, never summed per symbol (avoids files with
  hundreds of "llama_*" symbols dominating).
- Context is line-numbered (L123| code) so the model can cite path:line.

## Known issues / next

- Local qwen2.5-3b on this phone is slow (prompt eval ~7.6 tok/s, gen ~0.6-2.5
  tok/s, drops under sustained load) and its grounding is imperfect (may cite a
  secondary file over the true source). BYOK vision/text models fix quality; a
  q4_0 or 1.5B model would help latency.
- `fix` uses whole-file rewrite (compute the diff locally with difflib) because
  the local 3b INSTRUCT model cannot emit valid unified diffs directly. A coder
  model (Qwen2.5-Coder) or BYOK would enable the diff-native path
  (patch.extract_diff / apply_diff are implemented but unused by default).
- Retrieval latency ~10s on a 3k-file repo (one rg -l per term). Could be cut
  by batching doc-freq into fewer rg invocations.

## Development

```bash
git clone https://github.com/savagedamage/dev-second-brain.git
cd dev-second-brain
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"    # sbrain + pytest + ruff

pytest                      # run the tests
ruff check .                # lint
ruff format .               # auto-format
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor guide. The core
package has no Python runtime dependencies (standard library + the external `rg`
binary), and we'd like to keep it that way.

## License

[MIT](LICENSE) © savagedamage

