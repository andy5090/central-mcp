# Workspaces — Design Spec

Phase 3 of the central-mcp roadmap. Two independent sub-features that can ship in order.

---

## Sub-feature 1 — Project grouping (tags inside one registry)

### Problem

Users with 10+ projects want to dispatch to a logical slice (e.g. "all frontend projects") without naming each one. Today, fan-out requires N separate `dispatch` calls from the orchestrator.

### Data model

Add an optional top-level key to `registry.yaml`:

```yaml
workspaces:
  frontend: [my-app, api-server]
  infra:    [rink-service, rinkdns-agents]

projects:
  - name: my-app
    ...
```

Projects not listed under any workspace stay individually addressable as today. A project may appear in multiple workspaces.

### MCP surface changes

| Tool | Change |
|---|---|
| `dispatch(target, prompt)` | `target` resolves to a workspace name → fan out to each member project; returns a list of `dispatch_id`s |
| `list_projects` | gains optional `workspace` filter |
| `orchestration_history` | gains optional `workspace` filter; fan-out runs share a `group_id` |
| `add_project` | gains optional `--workspace` flag |

### CLI surface changes

```
central-mcp up --workspace frontend      # tmux/zellij: only this workspace's panes
central-mcp list --workspace infra
```

### Dispatch fan-out

- Each member project is dispatched independently (non-blocking, parallel).
- `dispatch` with a workspace target returns `{workspace: "frontend", dispatches: [{project: "my-app", dispatch_id: "…"}, …]}`.
- `orchestration_history` groups these under a shared `group_id` so the orchestrator can poll all at once.

### Resolution order

When `target` matches both a project name and a workspace name:
- Default: project wins (explicit beats group).
- Prefix `@frontend` to force workspace resolution.

### Open questions

- Should fan-out respect per-project `permission_mode` or override from the workspace?
- Concurrent dispatch cap per workspace (avoid saturating API rate limits)?

---

## Sub-feature 2 — Registry profiles (switchable workspaces)

### Problem

Users juggle multiple unrelated project sets (work laptop / personal / client engagement) and today must manually swap `registry.yaml` or maintain parallel installs.

### Directory layout

```
~/.central-mcp/
  registry.yaml          ← default (backward compatible)
  config.toml
  workspaces/
    client-x/
      registry.yaml
      config.toml        ← optional workspace-local overrides
      logs/
    personal/
      registry.yaml
      logs/
```

### Selection cascade

1. `CENTRAL_MCP_WORKSPACE=<name>` env var
2. `central-mcp --workspace <name>` CLI flag
3. `config.toml` → `[workspace] default = "client-x"`
4. Root `~/.central-mcp/registry.yaml` (current behavior)

### `config.toml` additions

```toml
[workspace]
default = "work"          # optional; falls back to root registry if unset
```

### CLI additions

```
central-mcp workspace list
central-mcp workspace new <name>
central-mcp workspace use <name>     # sets default in config.toml
central-mcp workspace current        # prints active workspace name
```

### `paths.py` impact

`resolve_home()` in `paths.py` gains workspace awareness. All downstream paths (`registry.yaml`, `logs/`, `workers/`) derive from the resolved root — no other module needs changes.

### Backward compatibility

- Root `~/.central-mcp/registry.yaml` remains valid forever; no migration required.
- The new `workspaces/` subtree is opt-in.

---

## Sub-feature 3 — Shared context (deferred)

Apply a shared prompt prefix or `CLAUDE.md` template to every dispatch inside a workspace. Deferred until Sub-features 1 and 2 are stable and real usage reveals what "shared context" actually needs to contain.

---

## Implementation order

1. **Sub-feature 1** first — purely additive to `registry.yaml` + `server.py`. No path changes.
2. **Sub-feature 2** second — touches `paths.py` and `registry.py`; higher blast radius.
3. **Sub-feature 3** last — depends on both.

Sub-feature 1 can ship as a minor version bump. Sub-feature 2 warrants a minor bump with a migration note.
