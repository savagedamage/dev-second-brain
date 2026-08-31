# Dev Second Brain — RESEARCH

## Competitors
- GitHub Copilot — $10/mo, cloud, telemetry.
- Cursor / Windsurf — $20/mo, cloud, proprietary.
- JetBrains AI — subscription.
- (These all resell model tokens at a markup; that's our pricing wedge.)

## Open-source building blocks (verified)
- Aider-AI/aider (~49k*) — terminal pair-programmer; study repo-map + diff/apply.
- continuedev/continue (~36k*) — OSS in-editor assistant; study BYOK UX.
- TabbyML/tabby (~34k*) — self-hosted coding assistant; study self-host + no-telemetry.
- ggml-org/llama.cpp (~126k*) — local model runtime.
- asg017/sqlite-vec (~8k*) — local code-embedding search.

## Models
- Local: Qwen2.5-Coder / DeepSeek-Coder (GGUF) — VERIFY best current small coding model.
- BYOK: DeepSeek-V4-Flash-0731 (cheap), DeepSeek-V4-Pro-0813 (stronger),
  gpt-4o-mini, Claude Haiku. See _shared/MODELS.md.

## Key technical questions
1. Retrieval strategy: repo-map (Aider) + lexical vs embedding search — which
   gives grounded, cited answers? (This is the make-or-break.)
2. Patch safety: unified-diff apply with user confirm (Aider's approach).
3. Cost per query with BYOK — expose it, so the "pay the model, not the
   middleman" story is literal.
4. Key handling: OS keychain / Android Keystore; never log keys.

## Notes
- This is the project most aligned with your existing Hermes agent skills —
  it's essentially "your own local coding agent" and could even reuse
  Hermes-style tool orchestration.
- Strongest "me-first" project: build it for your own use, dogfood daily,
  then productize.

## Links to keep
- Aider: https://github.com/Aider-AI/aider
- Continue: https://github.com/continuedev/continue
- Tabby: https://github.com/TabbyML/tabby
