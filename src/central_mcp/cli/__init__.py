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
    cmd_run,
    cmd_serve,
    cmd_unalias,
    cmd_up,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="central-mcp",
        description="Orchestrator-agnostic MCP hub for coding agents.",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="run the MCP server on stdio")
    p_serve.set_defaults(func=cmd_serve)

    p_up = sub.add_parser(
        "up",
        help="create the optional tmux observation session (one pane per project)",
    )
    p_up.set_defaults(func=cmd_up)

    p_down = sub.add_parser("down", help="kill the observation tmux session")
    p_down.set_defaults(func=cmd_down)

    p_list = sub.add_parser("list", help="print the registry")
    p_list.set_defaults(func=cmd_list)

    p_brief = sub.add_parser("brief", help="print the orchestrator brief")
    p_brief.set_defaults(func=cmd_brief)

    p_add = sub.add_parser("add", help="register a new project")
    p_add.add_argument("name", help="short project identifier")
    p_add.add_argument("path", help="absolute project path")
    p_add.add_argument(
        "--agent",
        default="claude",
        help="adapter name (claude|codex|gemini|droid|opencode)",
    )
    p_add.add_argument("--description", default="")
    p_add.add_argument("--tag", action="append")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="unregister a project")
    p_remove.add_argument("name")
    p_remove.set_defaults(func=cmd_remove)

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

    p_install = sub.add_parser("install", help="register central-mcp with an MCP client")
    p_install.add_argument("client", choices=["claude", "codex", "gemini", "opencode"])
    p_install.add_argument("--dry-run", action="store_true")
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

    p_run = sub.add_parser(
        "run",
        help="launch a coding-agent CLI as orchestrator (picks one on first run)",
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
        "--bypass",
        action="store_true",
        help=(
            "launch the agent in its permission-bypass / yolo mode when supported "
            "(claude: --dangerously-skip-permissions, codex: "
            "--dangerously-bypass-approvals-and-sandbox, gemini: --yolo)"
        ),
    )
    p_run.add_argument("--dry-run", action="store_true", help="print the plan without executing")
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    # No args, or first arg is a flag (not a subcommand) → inject "run".
    # Handles: `central-mcp`, `central-mcp --bypass`, `central-mcp --agent X`.
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
