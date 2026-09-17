---
name: graphify
description: Query a local AST knowledge graph (calls, imports, paths) before grepping the whole tree. Use when the user asks how X relates to Y, who calls a symbol, or how to navigate architecture — and graphify-out/graph.json exists. Fail-safe to Grep/Read if the graph or CLI is missing. Do not rebuild the full graph unless the user explicitly asks.
---

# Graphify (query-first)

Local tree-sitter graph. Complements MCP `user-codebase-memory-mcp` (history/semantics). Graphify is for structural edges.

CLI: `graphify` (PyPI package `graphifyy`, isolated `uv tool`). On Windows put `%USERPROFILE%\.local\bin` on PATH. PowerShell: `graphify query "..."`, never `/graphify .` as a path.

## Fail-safe

If `graphify` is missing or `graphify-out/graph.json` is missing: Grep/Read as usual. Do **not** block. Do **not** run a full extract of Silent-Project (four git folders) unless the user explicitly asked to build the graph.

## When the graph exists

```
graphify query "<question>"
graphify path "SymbolA" "SymbolB"
graphify explain "Symbol"
```

Then Read only the files the query pointed at.

## Do not

- Rebuild on every turn (`graphify .` / `/graphify .`).
- Index secrets (`.env`, `.env.deploy`, keys). Respect `.graphifyignore`.
- Commit `graphify-out/`.
- Treat graphify as a replacement for Memory Bank or the memory MCP.
