# Dev Second Brain — SKETCH

## Pitch
A coding assistant that indexes your codebase locally, answers questions, and
writes patches — using YOUR API key (BYOK) at cost, or a local model. You own
the index and the history; no telemetry, no $20/mo markup.

## Problem
GitHub Copilot / Cursor charge $10-20/mo reselling model tokens, keep your
code in their cloud, and send telemetry. The open-source building blocks
(Aider, Continue, Tabby) already prove a BYOK/self-hosted assistant is viable.

## Target user
Indie devs, contractors under NDA, and privacy/security-conscious engineers
who can't or won't ship their code to a cloud assistant.

## Incumbent & wedge
- Incumbent: Copilot, Cursor, JetBrains AI, Windsurf.
- Wedge: BYOK at cost + local-first index + no telemetry + your tool, your data.
  (This is the strongest fit for the Hermes agent skills you already have.)

## MVP
1. Point at a local repo (or workspace folder).
2. Build a local index: file tree + code embeddings (or a repo-map like Aider).
3. Ask questions ("where is auth handled?", "summarize this module").
4. Suggest a patch; apply it to files (write-only, user confirms).
5. Backend: BYOK (DeepSeek-V4-Flash/Pro, gpt-4o-mini, Claude Haiku) or local llama.cpp.

Explicitly OUT of MVP: full IDE plugin, multi-repo, autonomous agents, cloud sync.

## Stack
- Index: embeddings via a small code model + sqlite-vec, or Aider-style repo-map.
- LLM: BYOK hosted (see _shared/MODELS.md) or local (Qwen2.5-Coder / DeepSeek-Coder GGUF).
- CLI first (fastest to validate), then an editor plugin / Android app later.
- Study: Aider-AI/aider (edit + repo-map), continuedev/continue (BYOK UX),
  TabbyML/tabby (self-host + no-telemetry stance).

## Pricing model
- Free: local model, basic Q&A.
- One-time or BYOK: your key at cost, no subscription. (You are the pricing
  wedge — "pay the model, not the middleman.")

## Risks
- Retrieval quality (right file for the question) is the hard 80%; a naive
  "embed everything" is mediocre — repo-map + lexical search beats it.
- Editing code safely (patch vs whole-file) — follow Aider's diff/apply approach.
- BYOK means we must handle keys carefully (Android Keystore / OS keychain).

## Roadmap
- Phase 1: CLI that answers questions over a local repo (index + LLM).
- Phase 2: patch proposal + apply with confirm.
- Phase 3: BYOK polish, history, cost tracking per query.
- Phase 4: editor plugin and/or Android app; local model default.

## First milestone
"Where is authentication handled?" answered correctly over a real mid-size
repo, with citations to files/lines. Retrieval + grounded answer = the whole bet.
