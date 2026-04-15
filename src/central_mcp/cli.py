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
import os
import shutil
import sys
from pathlib import Path

import tomlkit

from central_mcp import brief as brief_mod
from central_mcp import install as install_mod
from central_mcp import layout
from central_mcp import preamble
from central_mcp import tmux

CENTRAL_HOME = Path.home() / ".central-mcp"
CONFIG_FILE = CENTRAL_HOME / "config.toml"

# Supported orchestrator agents, in the order they're offered in the picker.
# (key used in config, binary name on PATH, human-readable label).
ORCHESTRATORS: list[tuple[str, str, str]] = [
    ("claude", "claude", "Claude Code"),
    ("codex", "codex", "Codex CLI"),
    ("cursor", "cursor-agent", "Cursor Agent"),
    ("gemini", "gemini", "Gemini CLI"),
]
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
    """Create an empty registry.yaml.

    Default target is $HOME/.central-mcp/registry.yaml — the same location
    the cascade falls back to when no env var or ./registry.yaml is set.
    Pass a directory to scaffold ./registry.yaml inside it, or a .yaml file
    path to be explicit.
    """
    if args.path is None:
        reg = Path.home() / ".central-mcp" / "registry.yaml"
    else:
        p = Path(args.path).expanduser().resolve()
        reg = p if p.suffix in {".yaml", ".yml"} else p / "registry.yaml"

    if reg.exists() and not args.force:
        print(f"error: {reg} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        "# central-mcp project registry — edit via `central-mcp add` or by hand.\n\n"
        "projects: []\n"
    )
    print(f"wrote {reg}")
    print()
    print("Next steps:")
    print("  1. central-mcp install claude     # or codex, cursor")
    print("  2. Start that client and add projects in natural language, e.g.:")
    print('     "Add ~/Projects/my-app to the hub and run Claude on it."')
    print("     (The orchestrator will call add_project; shell fallback is")
    print("      `central-mcp add NAME PATH --agent claude`.)")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    return install_mod.install(args.client, dry_run=args.dry_run)


def _detect_installed() -> list[tuple[str, str, str]]:
    """Return every orchestrator whose binary is on PATH, in ORCHESTRATORS order."""
    return [(k, b, label) for k, b, label in ORCHESTRATORS if shutil.which(b)]


def _load_preference() -> str | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        data = tomlkit.parse(CONFIG_FILE.read_text())
    except Exception:
        return None
    return (data.get("orchestrator") or {}).get("default")


def _save_preference(key: str) -> None:
    CENTRAL_HOME.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        data = tomlkit.parse(CONFIG_FILE.read_text())
    else:
        data = tomlkit.document()
    orch = data.get("orchestrator")
    if orch is None:
        orch = tomlkit.table()
        data["orchestrator"] = orch
    orch["default"] = key
    CONFIG_FILE.write_text(tomlkit.dumps(data))


def _ensure_launch_dir(target: Path) -> None:
    """Scaffold preamble + SessionStart hook in the launch directory.

    Idempotent: never overwrites existing files so users can customize.
    """
    target.mkdir(parents=True, exist_ok=True)
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(preamble.CLAUDE_MD)
    agents_md = target / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(preamble.AGENTS_MD)
    settings_dir = target / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(preamble.SETTINGS_JSON)


def _prompt_choice(installed: list[tuple[str, str, str]]) -> tuple[str, str, str]:
    """Interactive agent picker. Caller must verify stdin.isatty() first."""
    print("Multiple coding agents detected — which should central-mcp launch?")
    for i, (_key, binary, label) in enumerate(installed, 1):
        print(f"  {i}. {label} ({binary})")
    while True:
        raw = input(f"Pick one [1-{len(installed)}] (default 1): ").strip()
        if not raw:
            return installed[0]
        try:
            idx = int(raw) - 1
        except ValueError:
            print("enter a number")
            continue
        if 0 <= idx < len(installed):
            return installed[idx]
        print("out of range")


def _alias_bin_dir_and_target() -> tuple[Path | None, Path | None]:
    """Return (user-facing bin dir, the central-mcp binary path).

    We DO NOT resolve symlinks — managers like `uv tool` install their
    binaries via a PATH-facing shim that links into an internal venv.
    The alias belongs next to the shim, not inside the venv, so a
    subsequent `uv tool uninstall` sweeps everything cleanly.
    """
    target = shutil.which("central-mcp")
    if not target:
        return None, None
    target_path = Path(target)
    return target_path.parent, target_path


def _cmd_alias(args: argparse.Namespace) -> int:
    """Create a symlink alias for `central-mcp`, conflict-checked.

    Default name is `cmcp`. The link lives in the same directory as the
    installed central-mcp binary so it's automatically on PATH and tracked
    alongside the tool installation. If a file already exists at that name
    and is NOT our own symlink, we refuse.
    """
    bin_dir, target = _alias_bin_dir_and_target()
    if bin_dir is None:
        print(
            "error: `central-mcp` not on PATH — run `uv tool install --editable .` first",
            file=sys.stderr,
        )
        return 1

    target_resolved = target.resolve()
    name = args.name
    link = bin_dir / name

    # Anywhere-on-PATH conflict check (not just our bin_dir).
    existing = shutil.which(name)
    if existing:
        existing_resolved = Path(existing).resolve()
        if existing_resolved == target_resolved:
            print(f"alias {name!r} already resolves to central-mcp ({existing}) — no change")
            return 0
        if link.is_symlink() and link.resolve() == target_resolved:
            # Symlink points at us but something else shadows it on PATH.
            print(
                f"warning: {link} points to central-mcp, but a different {name!r} "
                f"on PATH wins: {existing}",
                file=sys.stderr,
            )
            return 0
        print(
            f"error: {name!r} conflicts with existing command: {existing}",
            file=sys.stderr,
        )
        print(
            f"       refusing to shadow it. pick a different name with "
            f"`central-mcp alias {{other-name}}`.",
            file=sys.stderr,
        )
        return 1

    # No conflict on PATH — create the symlink.
    if link.exists() or link.is_symlink():
        # Path shutil.which missed — e.g. dir not on PATH, or broken symlink.
        print(f"error: {link} already exists — refusing to overwrite", file=sys.stderr)
        return 1
    link.symlink_to(target)
    print(f"created alias: {link} -> {target}")
    return 0


def _cmd_unalias(args: argparse.Namespace) -> int:
    """Remove an alias previously created by `central-mcp alias`.

    Only removes the link if it actually points to our central-mcp binary.
    """
    bin_dir, target = _alias_bin_dir_and_target()
    if bin_dir is None:
        print("error: `central-mcp` not on PATH", file=sys.stderr)
        return 1

    name = args.name
    link = bin_dir / name

    if not link.exists() and not link.is_symlink():
        print(f"no alias at {link}")
        return 0
    if not link.is_symlink():
        print(f"error: {link} is not a symlink — refusing to remove", file=sys.stderr)
        return 1
    try:
        resolved = link.resolve()
    except OSError as e:
        print(f"error: cannot resolve {link}: {e}", file=sys.stderr)
        return 1
    if resolved != target.resolve():
        print(
            f"error: {link} points to {resolved}, not central-mcp ({target.resolve()}) "
            "— refusing to remove",
            file=sys.stderr,
        )
        return 1
    link.unlink()
    print(f"removed alias: {link}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    installed = _detect_installed()
    if not installed:
        print(
            "error: no supported coding-agent CLI detected on PATH.\n"
            "       install one of: claude, codex, cursor-agent, gemini",
            file=sys.stderr,
        )
        return 1

    # 1. Which agent?
    choice: tuple[str, str, str] | None = None
    if args.agent:
        for entry in installed:
            if entry[0] == args.agent:
                choice = entry
                break
        if choice is None:
            print(
                f"error: {args.agent!r} is not installed (detected: "
                f"{', '.join(e[0] for e in installed)})",
                file=sys.stderr,
            )
            return 1
    else:
        pref = _load_preference()
        if pref:
            for entry in installed:
                if entry[0] == pref:
                    choice = entry
                    break
        if choice is None:
            if len(installed) == 1:
                choice = installed[0]
                print(f"Only {choice[2]} detected — launching it.")
                _save_preference(choice[0])
            elif sys.stdin.isatty():
                choice = _prompt_choice(installed)
                _save_preference(choice[0])
                print(f"saved default orchestrator: {choice[0]} → {CONFIG_FILE}")
            else:
                print(
                    "error: multiple agents detected and no --agent specified "
                    "in a non-interactive shell.\n       "
                    f"detected: {', '.join(e[0] for e in installed)}",
                    file=sys.stderr,
                )
                return 1

    assert choice is not None
    key, binary, label = choice

    # 2. Launch directory with orchestrator preamble
    launch_dir = Path(args.cwd).expanduser().resolve() if args.cwd else CENTRAL_HOME
    _ensure_launch_dir(launch_dir)

    # 3. Show what's going to happen
    print(f"orchestrator : {label} ({binary})")
    print(f"launch cwd   : {launch_dir}")

    if args.dry_run:
        print("(dry-run: not executing)")
        return 0

    # 4. Hand off the terminal
    os.chdir(launch_dir)
    try:
        os.execvp(binary, [binary])
    except FileNotFoundError:
        print(f"error: {binary!r} vanished from PATH between detection and exec", file=sys.stderr)
        return 1


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
    p_init.set_defaults(func=_cmd_init)

    p_install = sub.add_parser("install", help="register central-mcp with an MCP client")
    p_install.add_argument("client", choices=["claude", "codex", "cursor"])
    p_install.add_argument("--dry-run", action="store_true")
    p_install.set_defaults(func=_cmd_install)

    p_alias = sub.add_parser(
        "alias",
        help="create a short-name symlink to central-mcp (conflict-checked, default: cmcp)",
    )
    p_alias.add_argument("name", nargs="?", default="cmcp")
    p_alias.set_defaults(func=_cmd_alias)

    p_unalias = sub.add_parser(
        "unalias",
        help="remove an alias previously created by `central-mcp alias`",
    )
    p_unalias.add_argument("name", nargs="?", default="cmcp")
    p_unalias.set_defaults(func=_cmd_unalias)

    p_run = sub.add_parser(
        "run",
        help="launch a coding-agent CLI as orchestrator (picks one on first run)",
    )
    p_run.add_argument(
        "--agent",
        choices=[o[0] for o in ORCHESTRATORS],
        help="force a specific agent (otherwise: saved preference, auto-pick if one, interactive prompt if many)",
    )
    p_run.add_argument(
        "--cwd",
        help=f"launch directory (default: {CENTRAL_HOME})",
    )
    p_run.add_argument("--dry-run", action="store_true", help="print the plan without executing")
    p_run.set_defaults(func=_cmd_run)

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
