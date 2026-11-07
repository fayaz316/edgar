# ADR 0012 — One tool registry, exposed over MCP (Phase 2, first slice)
Status: Accepted · Date: 2026-11-07

## Context
Phase 2 needs an agent that calls tools, and the same tools available to external MCP clients
(Claude Desktop). Defining each tool twice - once for the agent, once for MCP - lets them drift:
different descriptions, different validation, different bugs.

## Options considered
- **One registry, thin front doors** — a tool is a name, a description, a pydantic argument model
  and a handler (`services/tools/`). The MCP server (`services/mcp/`) and, next, the agent both call
  `registry.call()`. **Won.**
- **Define tools directly as MCP functions and have the agent call them over MCP** — one definition
  too, but the agent would depend on a transport it doesn't need and be harder to test. Lost.
- **Generate MCP wrappers dynamically from the registry** — removes the small duplicated signatures,
  but the SDK builds schemas from typed function signatures, so dynamic wrappers hide the schema from
  type-checkers and readers. Lost for now; a drift test covers the duplication instead.
- **MCP SDK version:** the official `mcp` package. Its 2.x release renamed FastMCP to `MCPServer`; we
  use 2.x rather than pinning `<2`, since there is no 1.x code to keep. The standalone `fastmcp`
  package was not evaluated.

## Decision
Tools live in `services/tools/` (`registry.py`, `filings.py`): `search_filings` (hybrid search with
company and form-type filters, passages trimmed to 1,500 characters) and `list_filings`. Arguments are
validated by the registry, returning readable errors. `services/mcp/server.py` exposes them over stdio
(`make mcp`). A test asserts the MCP tool names and descriptions equal the registry's.

## Evidence
- Unit tests with fakes cover validation, filters, truncation and the MCP-vs-registry drift guard.
- A real stdio session (raw JSON-RPC) listed both tools, listed JPMorgan's filings, returned relevant
  passages for a JPMorgan mortgage question, and rejected `form_type="8-K"` with an error flag.
- NOT done: connecting Claude Desktop itself. That needs a line in its config (below), which is the
  user's file, so it has not been edited.

## Consequences
- **Good:** one place to change a tool; the agent will get identical behaviour for free.
- **Bad:** the MCP wrappers repeat each tool's argument list (guarded by a test, not removed). The
  server loads the embedding model at start-up (seconds) and holds a database pool, so it needs
  `DATABASE_URL` and the corpus to be embedded with the active model.
- **Not yet built (rest of Phase 2):** the LangGraph agent loop (plan, act, verify, step budget,
  retry/repair), the "contradiction hunter" sub-agent, and the trace view in the UI. The exit
  criterion (multi-step query with a visible trace; MCP demoable) is therefore NOT met.
- **No authentication on the MCP server:** acceptable for a local stdio process; it must not be
  exposed over a network as is (Phase 4).

## Trying it in Claude Desktop
Add to `claude_desktop_config.json` under `mcpServers` (adjust the path):
```json
"edgar-analyst": {
  "command": "uv",
  "args": ["run", "--directory", "/path/to/edgar-analyst",
           "--group", "local-embed", "python", "-m", "services.mcp.server"]
}
```
Postgres must be up (`make db-up`).
