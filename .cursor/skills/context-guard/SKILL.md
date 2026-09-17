---
name: context-guard
description: Local-first context hygiene for long chats, huge logs, and oversized files. Use when the conversation is long, a log/diff would flood the window, or the user asks to compact/handoff. Complements Memory Bank — do not skip MEMORY_BANK.md or TASKS.md. Progressive disclosure instead of whole-file dumps.
---

# Context-guard

Adapted from [ictechgy/context-guard](https://github.com/ictechgy/context-guard): keep tokens for the task, not for noise. Does **not** cancel the Memory Bank turn ritual.

## Progressive reads

1. Search (`Grep`) or a symbol/name first.
2. Read a line range or the matching hunk.
3. Full-file Read only when the file is small or the slice is not enough.
4. Never paste megabyte logs into the conversation. Head/tail, last N errors, or a short digest. Offer a path on disk if the user needs the rest.

## Memory Bank

Still read `.cursor/MEMORY_BANK.md` and `.cursor/TASKS.md` each user turn. Do **not** dump those files back into the reply. Quote only the section that matters.

## Output hygiene

- Trim test/build/diff output. Keep exit code, failing names, one representative snippet.
- After a command fails twice the same way, change strategy — do not refill context with the same log.
- Redact `.env`, `.env.deploy`, passwords, tokens, private keys. Do not echo them.

## Compact / handoff

When the chat is long or the user asks to compact: write a short handoff (goal, files touched, decisions, next step, open risks). Do not restart Memory Bank from scratch. Do not run upstream `context-guard setup` that rewrites AGENTS.md or installs MCP unless the user asked for that installer.

## Not in scope here

Claude-only plugin wizards (`/context-guard:setup|optimize|audit`), brief-mode rule injection, bash-reference receipts, cost-ledger HMAC, experimental proxies.
