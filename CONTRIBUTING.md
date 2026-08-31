# Contributing to Dev Second Brain

Thanks for your interest in improving `sbrain`! This project aims to stay small,
dependency-free, and easy to understand. Contributions that keep it that way are
very welcome.

## Getting set up

You need Python 3.9+ and [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`)
on your PATH.

```bash
git clone https://github.com/savagedamage/dev-second-brain.git
cd dev-second-brain
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # installs sbrain + pytest + ruff
```

## Running the checks

Before opening a pull request, please run:

```bash
pytest            # run the test suite
ruff check .      # lint
ruff format --check .   # formatting check (run `ruff format .` to fix)
```

CI runs these same checks on every push and pull request, so running them
locally first saves a round trip.

## Guidelines

- **Keep it dependency-free.** The core (`sbrain/`) uses only the Python
  standard library plus the external `rg` binary. Please don't add Python
  runtime dependencies without discussing it first in an issue.
- **Add a test for behaviour you change.** The retrieval and diff-parsing logic
  is the make-or-break part of the tool; regressions there are the most
  damaging, so cover them.
- **Prefer boring, readable code** over clever abstractions.
- **Small, focused commits** with clear messages (e.g. `fix: ...`, `test: ...`,
  `docs: ...`) are easier to review than one large change.

## Reporting bugs

Open an issue describing what you ran, what you expected, and what happened.
Include your OS, Python version, and whether you were using a local model or a
BYOK backend.
