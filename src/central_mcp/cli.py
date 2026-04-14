"""central-mcp command-line interface.

Subcommands:
  serve      run the MCP server on stdio (default when no subcommand given)
  up         bring up the tmux layout from registry.yaml
  down       kill all sessions referenced by registry.yaml
  list       print the registry in a compact form
  brief      print the orchestrator brief (same as SessionStart hook output)
  add        register a new project in registry.yaml
  remove     unregister a project
  init       scaffold registry.yaml + .claude/settings.json in cwd
  install    register this server with an MCP client (claude | codex | cursor)

Running `central-mcp` with no subcommand starts the MCP server — this is
what MCP clients invoke over stdio. All other subcommands are for humans.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from central_mcp import brief as brief_mod
from central_mcp import install as install_mod
from central_mcp import layout
from central_mcp import tmux
from central_mcp.registry import (
    DEFAULT_REGISTRY_PATH,
    add_project as registry_add,
    load_registry,
    projects_by_session,
    remove_project as registry_remove,
)


def _cmd_serve(args: argparse.Namespace) -> int:
    from central_mcp.server import main as server_main
    server_main()
    return 0


def _cmd_up(args: argparse.Namespace) -> int:
    root = Path(DEFAULT_REGISTRY_PATH).resolve().parent
    created, messages = layout.ensure_session(root)
    for m in messages:
        print(m)
    if created:
        print()
        print("Attach with: tmux attach -t central")
    return 0


def _cmd_down(args: argparse.Namespace) -> int:
    sessions = set(projects_by_session().keys())
    sessions.add(layout.HUB_SESSION)
    killed = 0
    for s in sessions:
        if tmux.has_session(s):
            tmux._run(["kill-session", "-t", s])
            print(f"killed session: {s}")
            killed += 1
    if not killed:
        print("no sessions to kill")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    projects = load_registry()
    if not projects:
        print("(registry is empty)")
        return 0
    for p in projects:
        print(f"{p.name:20}  {p.tmux.target:25}  agent={p.agent:8}  {p.path}")
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    print(brief_mod.render())
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    try:
        proj = registry_add(
            name=args.name,
            path_=str(Path(args.path).expanduser().resolve()),
            agent=args.agent,
            session=args.session,
            window=args.window,
            pane=args.pane,
            description=args.description or "",
            tags=args.tag or None,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"added: {proj.name} -> {proj.tmux.target} (agent={proj.agent})")

    if getattr(args, "no_start", False):
        return 0
    from central_mcp.server import _ensure_pane_up

    err = _ensure_pane_up(proj)
    if err:
        print(f"warning: auto-start skipped: {err.get('error')}", file=sys.stderr)
        return 0
    print(f"started: {proj.tmux.target} (agent={proj.agent})")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    ok = registry_remove(args.name)
    if not ok:
        print(f"error: no project named {args.name!r}", file=sys.stderr)
        return 1
    print(f"removed: {args.name}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    reg = target / "registry.yaml"
    if reg.exists() and not args.force:
        print(f"error: {reg} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    reg.write_text(
        "# central-mcp project registry — edit to describe your projects.\n"
        "# See `central-mcp add --help` for the CLI equivalent.\n\n"
        "projects: []\n"
    )
    print(f"wrote {reg}")

    settings_dir = target / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(
            '{\n'
            '  "hooks": {\n'
            '    "SessionStart": [\n'
            '      {\n'
            '        "hooks": [\n'
            '          {\n'
            '            "type": "command",\n'
            f'            "command": "central-mcp brief"\n'
            '          }\n'
            '        ]\n'
            '      }\n'
            '    ]\n'
            '  }\n'
            '}\n'
        )
        print(f"wrote {settings_file}")

    print()
    print("Next steps:")
    print("  1. central-mcp install claude    # or codex, cursor")
    print("  2. central-mcp add <name> <path> --agent claude")
    print("     (tmux pane + agent CLI auto-starts on add)")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    return install_mod.install(args.client, dry_run=args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="central-mcp",
        description="Orchestrator-agnostic MCP hub for coding agents.",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="run the MCP server on stdio")
    p_serve.set_defaults(func=_cmd_serve)

    p_up = sub.add_parser("up", help="bring up the tmux layout")
    p_up.set_defaults(func=_cmd_up)

    p_down = sub.add_parser("down", help="kill every session referenced by the registry")
    p_down.set_defaults(func=_cmd_down)

    p_list = sub.add_parser("list", help="print the registry")
    p_list.set_defaults(func=_cmd_list)

    p_brief = sub.add_parser("brief", help="print the orchestrator brief")
    p_brief.set_defaults(func=_cmd_brief)

    p_add = sub.add_parser("add", help="register a new project")
    p_add.add_argument("name", help="short project identifier")
    p_add.add_argument("path", help="absolute project path")
    p_add.add_argument("--agent", default="shell", help="adapter name (claude|codex|gemini|cursor|shell)")
    p_add.add_argument("--session", default="central")
    p_add.add_argument("--window", default="projects")
    p_add.add_argument("--pane", type=int, default=None)
    p_add.add_argument("--description", default="")
    p_add.add_argument("--tag", action="append")
    p_add.add_argument(
        "--no-start",
        action="store_true",
        help="only update registry.yaml; skip auto-booting the pane + agent",
    )
    p_add.set_defaults(func=_cmd_add)

    p_remove = sub.add_parser("remove", help="unregister a project")
    p_remove.add_argument("name")
    p_remove.set_defaults(func=_cmd_remove)

    p_init = sub.add_parser("init", help="scaffold registry.yaml in a directory")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    p_install = sub.add_parser("install", help="register central-mcp with an MCP client")
    p_install.add_argument("client", choices=["claude", "codex", "cursor"])
    p_install.add_argument("--dry-run", action="store_true")
    p_install.set_defaults(func=_cmd_install)

    return parser


def main() -> None:
    # No args → run MCP server (this is what MCP clients invoke over stdio).
    if len(sys.argv) == 1:
        from central_mcp.server import main as server_main
        server_main()
        return

    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    rc = args.func(args)
    raise SystemExit(rc or 0)


if __name__ == "__main__":
    main()
