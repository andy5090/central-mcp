"""central-mcp command-line interface — parser wiring + entry point.

Command implementations live in `central_mcp.cli._commands`; this module
is deliberately small and contains only argparse plumbing plus the
`main()` entry point that `python -m central_mcp` and the `central-mcp`
console script resolve to. Running with no arguments launches the
orchestrator (same as `central-mcp run`). Use `central-mcp serve` to
start the MCP server on stdio explicitly (what MCP clients invoke).
"""

from __future__ import annotations

import argparse
import sys

from central_mcp import paths
from central_mcp.cli._commands import (
    ORCHESTRATORS,
    cmd_add,
    cmd_alias,
    cmd_brief,
    cmd_down,
    cmd_init,
    cmd_install,
    cmd_list,
    cmd_remove,
    cmd_reorder,
    cmd_run,
    cmd_serve,
    cmd_tmux,
    cmd_unalias,
    cmd_up,
    cmd_upgrade,
    cmd_monitor,
    cmd_watch,
    cmd_workspace,
    cmd_zellij,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="central-mcp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Orchestrator-agnostic MCP hub for coding agents.\n"
            "\n"
            "Two entry points — same binary, different roles:\n"
            "  central-mcp run     launch a coding-agent CLI as the orchestrator\n"
            "                      (claude / codex / gemini / opencode) with the\n"
            "                      central-mcp MCP tools auto-loaded. Bare\n"
            "                      `central-mcp` (no args) is shorthand for this.\n"
            "  central-mcp serve   run the MCP server on stdio. This is what an\n"
            "                      MCP client (claude, codex, gemini, opencode)\n"
            "                      invokes after `central-mcp install <client>`.\n"
            "\n"
            "`cmcp` is the default short alias (created by `central-mcp init` or\n"
            "`central-mcp alias`). All subcommands work under either name."
        ),
        epilog=(
            "Quick-start:\n"
            "  central-mcp init              # one-time: scaffold registry + alias\n"
            "  central-mcp install all       # register with every detected MCP client\n"
            "  cmcp add my-app /path/to/app --agent claude\n"
            "  cmcp                          # launch orchestrator (= `cmcp run`)\n"
            "\n"
            "Observation panes (optional):\n"
            "  cmcp tmux                     # tmux session: orchestrator + per-project watch\n"
            "  cmcp zellij                   # same, on zellij\n"
            "  cmcp watch <project>          # standalone log tail\n"
            "\n"
            "Run `central-mcp <subcommand> --help` for subcommand-specific options."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser(
        "serve",
        help="run the MCP server on stdio (called by MCP clients, not by hand)",
        description=(
            "Run central-mcp as an MCP server on stdio. This is the entry "
            "point that registered MCP clients (claude / codex / gemini / "
            "opencode) invoke after `central-mcp install <client>`. You "
            "don't normally run this by hand — use `central-mcp run` to "
            "launch an orchestrator session that auto-loads the MCP tools."
        ),
    )
    p_serve.add_argument(
        "--workspace",
        metavar="NAME",
        default=None,
        help=(
            "scope this MCP server to a workspace (sets CMCP_WORKSPACE in "
            "this process). Defaults to the env var if set, else the saved "
            "config.toml [user].last_workspace. Use this to run multiple "
            "MCP servers concurrently in different clients."
        ),
    )
    p_serve.set_defaults(func=cmd_serve)

    p_up = sub.add_parser(
        "up",
        help="create the tmux observation session (orchestrator + one pane per project)",
        description=(
            "Create the tmux observation session for the current workspace "
            "(`cmcp-<workspace>`). Pane 0 launches the saved orchestrator "
            "(unless --no-orchestrator); the remaining panes each tail a "
            "project's dispatch.jsonl via `central-mcp watch <project>`. "
            "Non-interactive — uses the saved orchestrator preference, no "
            "picker. For zellij, use `central-mcp zellij` instead. To "
            "attach interactively (creating the session if needed) use "
            "`central-mcp tmux`."
        ),
    )
    p_up.add_argument(
        "--no-orchestrator",
        action="store_true",
        help="skip the orchestrator pane at index 0 (project panes only)",
    )
    p_up.add_argument(
        "--permission-mode",
        dest="permission_mode",
        choices=["bypass", "auto", "restricted"],
        default="bypass",
        help=(
            "orchestrator pane's permission mode (default: bypass). "
            "auto is claude-only (Team/Enterprise/API + Sonnet/Opus 4.6). "
            "restricted emits no permission flags."
        ),
    )
    p_up.add_argument(
        "--max-panes",
        type=int,
        default=None,
        metavar="N",
        help=(
            "max panes per window (default: auto — derived from the "
            "current terminal size to keep each pane above a coding-"
            "agent-readable floor). Overflow spills to cmcp-2, cmcp-3, …"
        ),
    )
    p_up.set_defaults(func=cmd_up)

    p_watch = sub.add_parser(
        "watch",
        help="tail a project's dispatch event log (jsonl)",
        description=(
            "Stream events from "
            "`~/.central-mcp/logs/<project>/dispatch.jsonl` as a "
            "human-readable summary. Used by observation panes "
            "(tmux / zellij / cmux), but also useful standalone — "
            "open a terminal and run it directly to watch a project's "
            "dispatch activity."
        ),
    )
    p_watch.add_argument("name", help="project name (must exist in registry)")
    p_watch.add_argument(
        "--from-start",
        action="store_true",
        help="replay the whole log from the beginning instead of following from end",
    )
    p_watch.set_defaults(func=cmd_watch)

    p_monitor = sub.add_parser(
        "monitor",
        help="portfolio dashboard: per-agent subscription quota + today's dispatch stats",
        description=(
            "Single-screen overview across all registered projects:\n"
            "  - per-agent subscription quota where central-mcp can\n"
            "    introspect it (claude only at this time)\n"
            "  - today's dispatch counts per project\n"
            "    (success / failure / cancelled)\n"
            "  - registry summary (orchestrator, project count)\n"
            "\n"
            "Read-only snapshot — does not start observation panes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_monitor.set_defaults(func=cmd_monitor)

    p_upgrade = sub.add_parser(
        "upgrade",
        help="check PyPI for a newer central-mcp and upgrade via uv (or pip fallback)",
        description=(
            "Manual upgrade entry point. `central-mcp run` already probes "
            "PyPI on every launch and offers a picker when a newer release "
            "is available; use this subcommand when you want to check or "
            "upgrade out-of-band, or when you've silenced the auto-probe. "
            "Uses `uv tool install` when available, falling back to `pip "
            "install --upgrade`."
        ),
    )
    p_upgrade.add_argument(
        "--check",
        action="store_true",
        help="only check for a newer version; do not install",
    )
    p_upgrade.set_defaults(func=cmd_upgrade)

    p_down = sub.add_parser(
        "down",
        help="tear down the observation session(s) (tmux + zellij)",
        description=(
            "Tear down all `cmcp-*` observation sessions on both tmux "
            "and zellij and clear the active-session stamp. Reports each "
            "backend's outcome so a partially-live state is visible."
        ),
    )
    p_down.set_defaults(func=cmd_down)

    p_tmux = sub.add_parser(
        "tmux",
        help="attach to the observation session via tmux (creates it first if needed)",
    )
    tmux_sub = p_tmux.add_subparsers(dest="tmux_sub")
    p_tmux_switch = tmux_sub.add_parser("switch", help="attach to cmcp-<name> tmux session (create if missing)")
    p_tmux_switch.add_argument("ws_name", metavar="NAME")
    p_tmux_switch.add_argument("--no-orchestrator", action="store_true")
    p_tmux_switch.add_argument("--permission-mode", dest="permission_mode",
                               choices=["bypass", "auto", "restricted"], default="bypass")
    p_tmux_switch.add_argument("--max-panes", type=int, default=None, metavar="N")
    p_tmux.add_argument("--no-orchestrator", action="store_true")
    p_tmux.add_argument(
        "--permission-mode",
        dest="permission_mode",
        choices=["bypass", "auto", "restricted"],
        default="bypass",
        help=(
            "orchestrator pane's permission mode (default: bypass). "
            "auto is claude-only (Team/Enterprise/API + Sonnet/Opus 4.6)."
        ),
    )
    p_tmux.add_argument(
        "--max-panes", type=int, default=None, metavar="N",
        help="max panes per tmux window (default: auto — terminal-size derived)",
    )
    p_tmux.add_argument("--workspace", metavar="NAME", default=None,
                        help="show only projects in this workspace (default: current workspace)")
    p_tmux.add_argument("--all", action="store_true",
                        help="create sessions for all workspaces")
    p_tmux.set_defaults(func=cmd_tmux)

    p_zellij = sub.add_parser(
        "zellij",
        help="attach to the observation session via zellij (creates it first if needed)",
    )
    zellij_sub = p_zellij.add_subparsers(dest="zellij_sub")
    p_zellij_switch = zellij_sub.add_parser("switch", help="attach to cmcp-<name> zellij session (create if missing)")
    p_zellij_switch.add_argument("ws_name", metavar="NAME")
    p_zellij_switch.add_argument("--no-orchestrator", action="store_true")
    p_zellij_switch.add_argument("--permission-mode", dest="permission_mode",
                                 choices=["bypass", "auto", "restricted"], default="bypass")
    p_zellij_switch.add_argument("--max-panes", type=int, default=None, metavar="N")
    p_zellij.add_argument("--no-orchestrator", action="store_true")
    p_zellij.add_argument(
        "--permission-mode",
        dest="permission_mode",
        choices=["bypass", "auto", "restricted"],
        default="bypass",
        help=(
            "orchestrator pane's permission mode (default: bypass). "
            "auto is claude-only (Team/Enterprise/API + Sonnet/Opus 4.6)."
        ),
    )
    p_zellij.add_argument(
        "--max-panes", type=int, default=None, metavar="N",
        help="max panes per zellij tab (default: auto — terminal-size derived)",
    )
    p_zellij.add_argument("--workspace", metavar="NAME", default=None,
                          help="show only projects in this workspace (default: current workspace)")
    p_zellij.add_argument("--all", action="store_true",
                          help="create sessions for all workspaces")
    p_zellij.set_defaults(func=cmd_zellij)

    p_list = sub.add_parser(
        "list",
        help="print the registry (project name → agent → path)",
        description=(
            "Print every registered project as `name  agent=<adapter>  "
            "<path>`, in the order the orchestrator sees them. To change "
            "the order, use `central-mcp reorder`."
        ),
    )
    p_list.set_defaults(func=cmd_list)

    p_brief = sub.add_parser(
        "brief",
        help="print the orchestrator brief (markdown summary the orchestrator sees)",
        description=(
            "Print the markdown-formatted project brief that the "
            "orchestrator session opens with — same content as the "
            "SessionStart hook in `~/.central-mcp/CLAUDE.md` / "
            "`AGENTS.md`. Useful for previewing what context the "
            "orchestrator will receive without launching it."
        ),
    )
    p_brief.set_defaults(func=cmd_brief)

    p_add = sub.add_parser(
        "add",
        help="register a new project in the registry",
        description=(
            "Add a project to `~/.central-mcp/registry.yaml` so it shows "
            "up in `list_projects`, observation panes, and dispatches. "
            "The agent flag picks the coding-agent CLI used when "
            "central-mcp dispatches work into this project."
        ),
    )
    p_add.add_argument("name", help="short project identifier (used by all MCP tools)")
    p_add.add_argument("path", help="absolute project path (must exist)")
    p_add.add_argument(
        "--agent",
        default="claude",
        help="adapter name: claude | codex | gemini | droid | opencode (default: claude)",
    )
    p_add.add_argument(
        "--description",
        default="",
        help="optional one-line description shown in `list_projects`",
    )
    p_add.add_argument(
        "--tag",
        action="append",
        help="optional tag (repeatable) — surfaced in registry queries",
    )
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="unregister a project")
    p_remove.add_argument("name")
    p_remove.set_defaults(func=cmd_remove)

    p_reorder = sub.add_parser(
        "reorder",
        help=(
            "reorder the registry's projects — names move to the front "
            "in the given order; unmentioned projects keep their "
            "relative order after the reordered prefix."
        ),
    )
    p_reorder.add_argument(
        "order",
        nargs="+",
        metavar="NAME",
        help="project names in the desired order (at least one)",
    )
    p_reorder.add_argument(
        "--strict",
        action="store_true",
        help=(
            "require the `order` list to name every registered project "
            "(errors if any is missing or extra)"
        ),
    )
    p_reorder.set_defaults(func=cmd_reorder)

    p_init = sub.add_parser(
        "init",
        help="scaffold an empty registry.yaml (default: ~/.central-mcp/registry.yaml)",
    )
    p_init.add_argument(
        "path",
        nargs="?",
        default=None,
        help="directory or .yaml file (default: $HOME/.central-mcp/registry.yaml)",
    )
    p_init.add_argument("--force", action="store_true")
    p_init.add_argument(
        "--no-alias",
        action="store_true",
        help="skip the automatic `cmcp` alias creation (opt out if you manage PATH shims yourself)",
    )
    p_init.set_defaults(func=cmd_init)

    p_install = sub.add_parser(
        "install",
        help="register central-mcp with an MCP client (use `all` to detect + install everywhere)",
        description=(
            "Add `central-mcp serve` to the target MCP client's "
            "configuration so the client auto-spawns it on launch and "
            "can call its tools (dispatch, list_projects, …). Backs up "
            "the client config before writing. Use `all` to detect every "
            "supported client on PATH and install in each. Re-running "
            "for an already-installed client is a no-op."
        ),
    )
    p_install.add_argument(
        "client",
        choices=["claude", "codex", "gemini", "opencode", "all"],
        help="target client, or `all` to auto-detect every supported client on PATH",
    )
    p_install.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned config edits without writing them",
    )
    p_install.set_defaults(func=cmd_install)

    p_alias = sub.add_parser(
        "alias",
        help="create a short-name symlink to central-mcp (conflict-checked, default: cmcp)",
    )
    p_alias.add_argument("name", nargs="?", default="cmcp")
    p_alias.set_defaults(func=cmd_alias)

    p_unalias = sub.add_parser(
        "unalias",
        help="remove an alias previously created by `central-mcp alias`",
    )
    p_unalias.add_argument("name", nargs="?", default="cmcp")
    p_unalias.set_defaults(func=cmd_unalias)

    p_ws = sub.add_parser(
        "workspace",
        help="manage project workspaces (group projects under named scopes)",
        description=(
            "Workspaces are named project groups. The orchestrator\n"
            "sees only the active workspace's projects by default —\n"
            "switching workspace re-scopes `list_projects`, observation\n"
            "panes, and the brief. Each workspace gets its own\n"
            "`cmcp-<workspace>` tmux/zellij session.\n"
            "\n"
            "Subcommands:\n"
            "  list     show every workspace with project counts\n"
            "  current  print the active workspace name\n"
            "  new      create a new empty workspace\n"
            "  use      switch the active workspace\n"
            "  add      add a project to a workspace\n"
            "  remove   remove a project from a workspace"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ws_sub = p_ws.add_subparsers(dest="workspace_sub")

    ws_sub.add_parser("list", help="list workspaces with project counts and active marker")
    ws_sub.add_parser("current", help="print the active workspace name")

    p_ws_new = ws_sub.add_parser("new", help="create a new empty workspace")
    p_ws_new.add_argument("ws_name", metavar="NAME")

    p_ws_use = ws_sub.add_parser(
        "use",
        help="switch the active workspace (interactive picker if NAME omitted)",
    )
    p_ws_use.add_argument("ws_name", metavar="NAME", nargs="?", default=None)

    p_ws_add = ws_sub.add_parser("add", help="add a project to a workspace")
    p_ws_add.add_argument("project", metavar="PROJECT")
    p_ws_add.add_argument("--workspace", required=True, metavar="WORKSPACE")

    p_ws_rm = ws_sub.add_parser("remove", help="remove a project from a workspace")
    p_ws_rm.add_argument("project", metavar="PROJECT")
    p_ws_rm.add_argument("--workspace", required=True, metavar="WORKSPACE")

    p_ws.set_defaults(func=cmd_workspace)

    p_run = sub.add_parser(
        "run",
        help="launch a coding-agent CLI as orchestrator (picks one on first run)",
        description=(
            "Launch a coding-agent CLI (claude / codex / gemini / opencode) as "
            "the orchestrator. On startup, central-mcp prints its own version "
            "above the orchestrator summary and probes PyPI for a newer "
            "release on every launch (interactive picker, 2s timeout, silent "
            "on failure). Silence the probe with "
            "`[user].upgrade_check_enabled = false` in config.toml."
        ),
    )
    p_run.add_argument(
        "--agent",
        choices=[o[0] for o in ORCHESTRATORS],
        help="one-off agent override (does NOT update the saved preference)",
    )
    p_run.add_argument(
        "--pick",
        action="store_true",
        help="re-run the interactive picker and update the saved preference",
    )
    p_run.add_argument(
        "--cwd",
        help=f"launch directory (default: {paths.central_mcp_home()})",
    )
    p_run.add_argument(
        "--permission-mode",
        dest="permission_mode",
        choices=["bypass", "auto", "restricted"],
        default="bypass",
        help=(
            "orchestrator permission mode (default: bypass). "
            "bypass = permission-skip/yolo flags (claude: "
            "--dangerously-skip-permissions, codex: "
            "--dangerously-bypass-approvals-and-sandbox, gemini: --yolo). "
            "auto = claude-only classifier-reviewed mode "
            "(--enable-auto-mode --permission-mode auto), requires "
            "Team/Enterprise/API plan + Sonnet/Opus 4.6. "
            "restricted = no permission flags; the agent may halt on "
            "operations that would normally prompt."
        ),
    )
    p_run.add_argument(
        "--workspace",
        metavar="NAME",
        default=None,
        help=(
            "scope this orchestrator session to a workspace (sets "
            "CMCP_WORKSPACE for the orchestrator + its MCP server child). "
            "Lets you run multiple `cmcp run` instances in different "
            "terminals, each on a different workspace, without touching "
            "config.toml. Defaults to env CMCP_WORKSPACE, else the saved "
            "config.toml [user].last_workspace."
        ),
    )
    p_run.add_argument("--dry-run", action="store_true", help="print the plan without executing")
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    # Version check before any routing.
    if len(sys.argv) > 1 and sys.argv[1] in ("-v", "--version"):
        from importlib.metadata import version
        print(version("central-mcp"))
        return

    # No args, or first arg is a flag (not a subcommand) → inject "run".
    # Handles: `central-mcp`, `central-mcp --permission-mode X`, `central-mcp --agent X`.
    # MCP clients use `central-mcp serve` explicitly, so this is safe.
    if len(sys.argv) == 1 or sys.argv[1].startswith("-"):
        sys.argv.insert(1, "run")

    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    rc = args.func(args)
    raise SystemExit(rc or 0)


if __name__ == "__main__":
    main()
