# cmux layout schema

> **Status (2026-04-21): reference only.** The shipped cmux CLI (0.63.2,
> build 79) rejects `cmux new-workspace --layout`:
> `Error: new-workspace: unknown flag '--layout'`. The flag is wired up
> in the cmux source tree (`CLI/cmux.swift:2175`) but has not landed in
> a release binary. Until it does, central-mcp uses an agent-driven
> bootstrap instead (see `Phase 2b` in `docs/ROADMAP.md`) — the
> `build_layout_json` builder that used to produce JSON for this schema
> has been removed. This doc is retained so that when a release does
> ship `--layout`, the wire format is already documented and the
> declarative path can be rewired cleanly.

Authoritative source: `manaflow-ai/cmux/Sources/CmuxConfig.swift` in
the cmux repo. When (re-)wiring the declarative path, cross-check the
Swift decoder first — the GUI validates the JSON server-side and will
reject anything that doesn't match.

## Wire path (from `cmcp cmux` → cmux.app)

1. `central_mcp.cmux.ensure_workspace()` emits
   `cmux new-workspace --name central --layout <JSON>`.
2. `CLI/cmux.swift:2170` (the `new-workspace` case) parses the CLI
   args, sets `params["title"] = --name`, `params["cwd"] = --cwd`,
   and assigns `params["layout"]` to the parsed JSON object — then
   calls `client.sendV2(method: "workspace.create", params:)`.
3. `Sources/TerminalController.swift:3461` (the `workspace.create`
   handler) decodes `params["layout"]` via
   `JSONDecoder().decode(CmuxLayoutNode.self, ...)`.

So `--layout` receives a bare `CmuxLayoutNode` subtree, not a
`CmuxWorkspaceDefinition` — title / cwd / color are NOT embedded in
the JSON; they go on separate CLI flags / `params` keys.

## Schema (from `CmuxConfig.swift`)

```
CmuxLayoutNode (tagged union):
  pane branch:
    {"pane": {"surfaces": [CmuxSurfaceDefinition, ...]}}      # ≥1 surface
  split branch:
    {"direction": "horizontal"|"vertical",
     "split": Double?,                                          # clamped 0.1-0.9
     "children": [CmuxLayoutNode, CmuxLayoutNode]}              # exactly 2

CmuxSurfaceDefinition:
  type: "terminal"|"browser"   (required)
  name, command, cwd, url: String?
  env: {String: String}?
  focus: Bool?
```

A node must have exactly one of `pane` / `direction` — both is an
error, neither is an error. Splits must have exactly two children.

## Field-name gotchas

- Split children live under `children: [...]`, not `first` / `second`.
- Pane leaves wrap surfaces under `pane`:
  `{"pane": {"surfaces": [...]}}`, not bare `{"surfaces": [...]}`.
- The CLI help at `cmux.swift:7305` shows the canonical form.
