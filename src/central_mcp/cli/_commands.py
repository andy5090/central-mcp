"""Command implementations + shared helpers for the central-mcp CLI.

Every `_cmd_*` function is a leaf handler invoked by the parser wired up
in `central_mcp.cli.__init__`. Helper functions that are only used by
the commands live here too so that the parser module stays small and
contains only argparse wiring.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path

import tomlkit

from central_mcp import brief as brief_mod
from central_mcp import install as install_mod
from central_mcp import layout
from central_mcp import paths
from central_mcp import tmux


# Inline default for the SessionStart hook — small enough that package-data
# lookup would be overkill. Writing `central-mcp brief` means the hook
# resolves through PATH, which works regardless of how the package was
# installed.
_SETTINGS_JSON = """\
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "central-mcp brief"
          }
        ]
      }
    ]
  }
}
"""


def _read_packaged(name: str) -> str:
    """Load a file from `central_mcp/data/` as shipped in the wheel."""
    return files("central_mcp").joinpath("data", name).read_text(encoding="utf-8")
from central_mcp.registry import (
    add_project as registry_add,
    load_registry,
    projects_by_session,
    remove_project as registry_remove,
)


# Supported orchestrator agents, in the order they're offered in the picker.
# (key used in config, binary name on PATH, human-readable label).
ORCHESTRATORS: list[tuple[str, str, str]] = [
    ("claude", "claude", "Claude Code"),
    ("codex", "codex", "Codex CLI"),
    ("cursor", "cursor-agent", "Cursor Agent"),
    ("gemini", "gemini", "Gemini CLI"),
]

# Known "skip all permission prompts" / yolo flags per orchestrator.
# Unset entries mean the agent has no documented bypass mode (as far as
# central-mcp knows) — `--bypass` will warn and launch without any extra flag.
BYPASS_FLAGS: dict[str, list[str]] = {
    "claude": ["--dangerously-skip-permissions"],
    "codex": ["--dangerously-bypass-approvals-and-sandbox"],
    "gemini": ["--yolo"],
    # cursor-agent: not wired up — add when a stable flag exists.
}


# ---------- thin command wrappers ----------

def cmd_serve(args: argparse.Namespace) -> int:
    from central_mcp.server import main as server_main
    server_main()
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    created, messages = layout.ensure_session()
    for m in messages:
        print(m)
    if created:
        print()
        print("Attach with: tmux attach -t central")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
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


def cmd_list(args: argparse.Namespace) -> int:
    projects = load_registry()
    if not projects:
        print("(registry is empty)")
        return 0
    for p in projects:
        print(f"{p.name:20}  {p.tmux.target:25}  agent={p.agent:8}  {p.path}")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    print(brief_mod.render())
    return 0


# ---------- registry mutation ----------

def cmd_add(args: argparse.Namespace) -> int:
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


def cmd_remove(args: argparse.Namespace) -> int:
    ok = registry_remove(args.name)
    if not ok:
        print(f"error: no project named {args.name!r}", file=sys.stderr)
        return 1
    print(f"removed: {args.name}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Create an empty registry.yaml.

    Default target is $HOME/.central-mcp/registry.yaml — the same location
    the cascade falls back to when no env var or ./registry.yaml is set.
    Pass a directory to scaffold ./registry.yaml inside it, or a .yaml file
    path to be explicit.
    """
    if args.path is None:
        reg = paths.central_mcp_home() / "registry.yaml"
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

    # Opportunistically install the `cmcp` short-name alias. Silent skip on
    # any conflict — the user can always run `central-mcp alias` later or
    # pick a different name. This is why we do NOT declare a second
    # console_script entry point in pyproject.toml.
    if not args.no_alias:
        _try_auto_alias("cmcp")

    print()
    print("Next steps:")
    print("  1. central-mcp install claude     # or codex, cursor")
    print("  2. Start that client and add projects in natural language, e.g.:")
    print('     "Add ~/Projects/my-app to the hub and run Claude on it."')
    print("     (The orchestrator will call add_project; shell fallback is")
    print("      `central-mcp add NAME PATH --agent claude`.)")
    return 0


# ---------- install ----------

def cmd_install(args: argparse.Namespace) -> int:
    return install_mod.install(args.client, dry_run=args.dry_run)


# ---------- alias ----------

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


def _try_auto_alias(name: str) -> None:
    """Best-effort: create a short-name alias, swallow conflicts quietly.

    Used by `init` so first-time setup ends with the short name available
    whenever it's safe. Prints a single info line so the user knows what
    did (or did not) happen.
    """
    bin_dir, target = _alias_bin_dir_and_target()
    if bin_dir is None:
        return

    target_resolved = target.resolve()
    link = bin_dir / name
    existing = shutil.which(name)

    if existing:
        existing_resolved = Path(existing).resolve()
        if existing_resolved == target_resolved:
            print(f"alias: {name!r} already points here — skipped")
            return
        print(
            f"alias: skipped {name!r} — conflicts with {existing}. "
            f"Use `central-mcp alias OTHER_NAME` if you want a short name."
        )
        return

    if link.exists() or link.is_symlink():
        print(f"alias: skipped {name!r} — {link} already exists")
        return

    try:
        link.symlink_to(target)
    except OSError as e:
        print(f"alias: could not create {link} ({e})")
        return
    print(f"alias: created {link} -> {target} (run `central-mcp unalias` to remove)")


def cmd_alias(args: argparse.Namespace) -> int:
    """Create a symlink alias for `central-mcp`, conflict-checked."""
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

    existing = shutil.which(name)
    if existing:
        existing_resolved = Path(existing).resolve()
        if existing_resolved == target_resolved:
            print(f"alias {name!r} already resolves to central-mcp ({existing}) — no change")
            return 0
        if link.is_symlink() and link.resolve() == target_resolved:
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

    if link.exists() or link.is_symlink():
        print(f"error: {link} already exists — refusing to overwrite", file=sys.stderr)
        return 1
    link.symlink_to(target)
    print(f"created alias: {link} -> {target}")
    return 0


def cmd_unalias(args: argparse.Namespace) -> int:
    """Remove an alias previously created by `central-mcp alias`."""
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


# ---------- run / orchestrator picker ----------

def _detect_installed() -> list[tuple[str, str, str]]:
    """Return every orchestrator whose binary is on PATH, in ORCHESTRATORS order."""
    return [(k, b, label) for k, b, label in ORCHESTRATORS if shutil.which(b)]


def _load_preference() -> str | None:
    if not paths.config_file().exists():
        return None
    try:
        data = tomlkit.parse(paths.config_file().read_text())
    except Exception:
        return None
    return (data.get("orchestrator") or {}).get("default")


def _save_preference(key: str) -> None:
    paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
    if paths.config_file().exists():
        data = tomlkit.parse(paths.config_file().read_text())
    else:
        data = tomlkit.document()
    orch = data.get("orchestrator")
    if orch is None:
        orch = tomlkit.table()
        data["orchestrator"] = orch
    orch["default"] = key
    paths.config_file().write_text(tomlkit.dumps(data))


def _ensure_launch_dir(target: Path) -> None:
    """Scaffold preamble + SessionStart hook in the launch directory.

    CLAUDE.md / AGENTS.md content is shipped as package data under
    `central_mcp/data/` so editable and non-editable installs both
    resolve to the same canonical text. Existing files are never
    overwritten so users can customize.
    """
    target.mkdir(parents=True, exist_ok=True)
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(_read_packaged("CLAUDE.md"))
    agents_md = target / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(_read_packaged("AGENTS.md"))
    settings_dir = target / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(_SETTINGS_JSON)


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


def cmd_run(args: argparse.Namespace) -> int:
    installed = _detect_installed()
    if not installed:
        print(
            "error: no supported coding-agent CLI detected on PATH.\n"
            "       install one of: claude, codex, cursor-agent, gemini",
            file=sys.stderr,
        )
        return 1

    choice: tuple[str, str, str] | None = None
    source = ""

    if args.agent and args.pick:
        print("error: --agent and --pick are mutually exclusive", file=sys.stderr)
        return 1

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
        source = "--agent (one-off, not saved)"
    elif args.pick:
        if not sys.stdin.isatty():
            print("error: --pick requires an interactive terminal", file=sys.stderr)
            return 1
        choice = _prompt_choice(installed)
        _save_preference(choice[0])
        print(f"saved default orchestrator: {choice[0]} → {paths.config_file()}")
        source = "--pick (saved)"
    else:
        pref = _load_preference()
        if pref:
            for entry in installed:
                if entry[0] == pref:
                    choice = entry
                    source = "saved preference"
                    break
            if choice is None:
                print(
                    f"warning: saved preference {pref!r} no longer on PATH — re-picking",
                    file=sys.stderr,
                )
        if choice is None:
            if len(installed) == 1:
                choice = installed[0]
                print(f"Only {choice[2]} detected — launching it.")
                _save_preference(choice[0])
                source = "only detected (saved)"
            elif sys.stdin.isatty():
                choice = _prompt_choice(installed)
                _save_preference(choice[0])
                print(f"saved default orchestrator: {choice[0]} → {paths.config_file()}")
                source = "first-run picker (saved)"
            else:
                print(
                    "error: multiple agents detected and no --agent specified "
                    "in a non-interactive shell.\n       "
                    f"detected: {', '.join(e[0] for e in installed)}\n"
                    "       use --agent NAME or run interactively with --pick",
                    file=sys.stderr,
                )
                return 1

    assert choice is not None
    key, binary, label = choice

    launch_dir = Path(args.cwd).expanduser().resolve() if args.cwd else paths.central_mcp_home()
    _ensure_launch_dir(launch_dir)

    argv: list[str] = [binary]
    if args.bypass:
        bypass = BYPASS_FLAGS.get(key)
        if bypass:
            argv.extend(bypass)
        else:
            print(
                f"warning: --bypass: {key!r} has no known permission-bypass flag in "
                "central-mcp; launching without it. Add one to BYPASS_FLAGS.",
                file=sys.stderr,
            )

    source_suffix = f"  [{source}]" if source else ""
    print(f"orchestrator : {label} ({binary}){source_suffix}")
    print(f"launch cwd   : {launch_dir}")
    if len(argv) > 1:
        print(f"extra args   : {' '.join(argv[1:])}")

    if args.dry_run:
        print("(dry-run: not executing)")
        return 0

    os.chdir(launch_dir)
    try:
        os.execvp(binary, argv)
    except FileNotFoundError:
        print(f"error: {binary!r} vanished from PATH between detection and exec", file=sys.stderr)
        return 1
