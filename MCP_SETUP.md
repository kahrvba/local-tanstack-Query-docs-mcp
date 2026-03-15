# Local Docs MCP Setup

This repo now includes a local MCP server at:

- `mcp_docs_server.py`

It exposes the `docs/` folder to Codex via:

- `list_docs` tool (list files with pagination and optional glob pattern)
- `search_docs` tool (path + content search with pagination)
- `read_doc` tool (chunked reads with offset/length)
- `resources/list` and `resources/read`

## 1) Add to Codex `config.toml`

Add this block to your Codex MCP config file (usually `~/.codex/config.toml`):

```toml
[mcp_servers.tanstack]
command = "python3"
args = ["/Users/ahmed/query/mcp_docs_server.py"]
```

If your Codex config uses `servers` instead of `mcp_servers`, use this equivalent shape:

```toml
[servers.tanstack]
command = "python3"
args = ["/Users/ahmed/query/mcp_docs_server.py"]
```

## 2) Restart Codex

Restart your Codex chat/session so it reloads MCP servers.

## 3) Use it effectively in chat

Use prompts that force pagination/chunking so Codex can traverse the full docs corpus:

- "Use `tanstack.list_docs` with pattern `docs/framework/react/**/*.md` and page through all results."
- "Use `tanstack.search_docs` for `suspense` and keep paginating with `nextOffset` until `hasMore` is false."
- "Use `tanstack.read_doc` on `docs/framework/react/guides/suspense.md` and continue reading chunks using `nextOffset` until full file is read."

## Practical limits (important)

- There is no server-side truncation anymore in `read_doc`; it supports chunked full reads.
- LLM context windows still exist, so Codex cannot hold all docs in one prompt at once.
- The best strategy is iterative retrieval: search -> shortlist -> chunked reads -> synthesis.

## Security behavior

- The server is read-only.
- It only serves files inside `/Users/ahmed/query/docs`.
