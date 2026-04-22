# Workspaces — Design Spec

**Date:** 2026-04-22  
**Status:** Approved  
**Target versions:** 0.9.0 (data + CLI), 0.9.1 (observation mode), 0.9.2 (MCP fan-out)

---

## Goal

Let users group projects into named workspaces so:
- Observation mode (tmux / zellij / cmux) defaults to the currently active workspace
- `dispatch` can fan out to all projects in a workspace with one call
- `list_projects` defaults to the current workspace context
- Users can switch workspace context without editing `registry.yaml`

---

## Section 1 — Data Model

### registry.yaml

Top-level `workspaces` map added alongside the existing `projects` list:

```yaml
workspaces:
  default: [rink-service, central-mcp, andineering]
  personal: [gluecut-dawg, programming-history]

projects:
  - name: rink-service
    path: /Users/andy/Projects/rink-service
    agent: codex
    ...
```

- A project may belong to multiple workspaces.
- Projects not listed under any workspace are treated as members of `default`.
- The `projects` list structure is unchanged (backward compatible).

### config.toml

```toml
[workspace]
current = "default"    # changed by `cmcp workspace use <name>`
```

### Migration

| Situation | Behavior |
|---|---|
| Fresh install (`init`) | Creates `workspaces: {default: [all projects]}` + `config.toml current = "default"` |
| Upgrade (no `workspaces:` key in registry.yaml) | `registry.py` detects missing key on load → auto-inserts `default` workspace containing all existing projects → saves silently |
| Already has `workspaces:` | No change |

Migration is transparent — existing users see no behavior change because their entire project list becomes `default`.

### registry.py additions

```python
@dataclass
class Registry:
    projects: list[Project]
    workspaces: dict[str, list[str]]  # NEW: {workspace_name: [project_name, ...]}

    def projects_in_workspace(self, name: str) -> list[Project]: ...
    def workspace_names(self) -> list[str]: ...
```

---

## Section 2 — CLI Interface

### `cmcp workspace` subcommand

```bash
cmcp workspace list                              # list all workspaces + project counts + active marker
cmcp workspace new <name>                        # add empty workspace to registry.yaml
cmcp workspace use <name>                        # update config.toml current (no observation side effects)
cmcp workspace current                           # print active workspace name
cmcp workspace add <project> --workspace <name>  # add project to a workspace
cmcp workspace remove <project> --workspace <name>  # remove project from a workspace
```

`workspace list` output example:
```
  default   (5 projects)
* work      (3 projects)   ← currently active
  personal  (4 projects)
```

### Observation mode flags (tmux / zellij / cmux)

All observation backends gain `--workspace` and `--all` flags:

```bash
cmcp tmux                          # current workspace projects only
cmcp tmux --workspace personal     # specific workspace override
cmcp tmux --all                    # all projects (old behavior)

cmcp zellij                        # same semantics
cmcp zellij --workspace work
cmcp zellij --all

# cmux: agent-driven, same flag surface passed through AGENTS.md recipe
```

### Session naming with `--all`

When `--all` is used, each workspace gets its own named session:

```
tmux sessions:    cmcp-default, cmcp-work, cmcp-personal
zellij sessions:  cmcp-default, cmcp-work, cmcp-personal
cmux workspaces:  cmcp-hub, cmcp-work-watch-1, cmcp-personal-watch-1, cmcp-default-watch-1
```

Default (no `--all`): session named `cmcp-<current-workspace>`. For users on `default`, this is `cmcp-default`. **Breaking change note:** existing tmux/zellij sessions named `central` are not auto-renamed; users should run `cmcp tmux` once after upgrading to create the new `cmcp-default` session (old `central` session can be killed manually).

### tmux / zellij session switch

```bash
cmcp tmux switch <name>     # attach to cmcp-<name> tmux session (create if missing)
cmcp zellij switch <name>   # attach to cmcp-<name> zellij session (create if missing)
```

`workspace use` is intentionally separate — it updates the logical context (config.toml) without touching any running terminal session.

---

## Section 3 — MCP Tool Changes

### `dispatch` — workspace fan-out

```python
# Single project (unchanged)
dispatch("rink-service", "update dependencies")
# → {ok: True, dispatch_id: "abc123", project: "rink-service", ...}

# Workspace fan-out (new)
dispatch("work", "run linter")
# → {
#     ok: True,
#     workspace: "work",
#     dispatches: [
#       {project: "rink-service", dispatch_id: "abc123"},
#       {project: "central-mcp",  dispatch_id: "def456"},
#     ],
#     group_id: "grp-789"
#   }
```

**Resolution order:** if `target` matches both a project name and a workspace name, project wins. Use `@work` prefix to force workspace resolution. The `@` prefix is only valid in the `dispatch` MCP tool `target` parameter — not in CLI flags or other tools.

Each member project is dispatched independently and non-blocking (parallel). Conflict mitigation prefaces apply per-project as normal.

### `list_projects` — workspace-aware default

```python
list_projects()                      # current workspace only (NEW default)
list_projects(workspace="__all__")   # all projects (old behavior)
list_projects(workspace="personal")  # specific workspace
```

### `orchestration_history` — full view default, optional filter

```python
orchestration_history()                    # all workspaces (unchanged default — orchestrator needs full picture)
orchestration_history(workspace="work")    # filter to specific workspace
```

Fan-out dispatches are grouped under `group_id` in history output.

### `add_project` / `update_project` — workspace param

```python
add_project("new-api", path="/...", workspace="work")
update_project("rink-service", workspace="personal")  # move to workspace
```

---

## Section 4 — cmux Multi-Workspace Observation

### Default (current workspace)

```
cmux sidebar:
  cmcp-hub              ← orchestrator pane (unchanged)
  cmcp-watch-1          ← current workspace projects (existing naming preserved)
```

### `--all` mode

Each workspace becomes its own cmux workspace tab:

```
cmux sidebar:
  cmcp-hub
  cmcp-work-watch-1
  cmcp-personal-watch-1
  cmcp-default-watch-1
```

`AGENTS.md` / `CLAUDE.md` (shipped runtime guidelines) will be updated with a recipe for building multi-workspace cmux layouts, including the naming convention above.

---

## Section 5 — Implementation Order (Layered)

| Phase | Scope | Version |
|---|---|---|
| 1 | `registry.py` workspace parsing + auto-migration; `config.toml` current workspace; `paths.py` config load | 0.9.0 |
| 2 | `cmcp workspace` CLI (list / new / use / current / add / remove) | 0.9.0 |
| 3 | tmux / zellij `--workspace` / `--all` flags + `switch` subcommand + session naming | 0.9.1 |
| 4 | cmux `--all` multi-workspace recipe in `AGENTS.md` / `CLAUDE.md` | 0.9.1 |
| 5 | MCP: `dispatch` fan-out + `list_projects` workspace default + `orchestration_history` filter + `add_project` workspace param | 0.9.2 |

Each phase ships as a standalone patch or minor bump. Phase 1+2 together = 0.9.0 minor bump (new CLI surface). Phase 3+4 = 0.9.1 patch. Phase 5 = 0.9.2 minor bump (MCP surface change).

---

## Open Questions (resolved)

- **Resolution order (project vs workspace name clash):** project wins; `@name` forces workspace
- **Fan-out concurrency cap:** not enforced in MVP; existing per-project conflict mitigation applies
- **Shared context per workspace (CLAUDE.md templates):** deferred to post-0.9.x
- **Multiple registry files:** out of scope; one registry.yaml forever
