"""Command implementations + shared helpers for the central-mcp CLI."""

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
from central_mcp.registry import (
    add_project as registry_add,
    load_registry,
    remove_project as registry_remove,
)


# Inline default for the SessionStart hook.
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
    return files("central_mcp").joinpath("data", name).read_text(encoding="utf-8")


# Supported orchestrators for `central-mcp run`, in picker order.
ORCHESTRATORS: list[tuple[str, str, str]] = [
    ("claude", "claude", "Claude Code"),
    ("codex", "codex", "Codex CLI"),
    ("gemini", "gemini", "Gemini CLI"),
]

# Known permission-bypass flags for `central-mcp run --bypass`.
BYPASS_FLAGS: dict[str, list[str]] = {
    "claude": ["--dangerously-skip-permissions"],
    "codex": ["--dangerously-bypass-approvals-and-sandbox"],
    "gemini": ["--yolo"],
}


# ---------- server / listing ----------

def cmd_serve(args: argparse.Namespace) -> int:
    from central_mcp.server import main as server_main
    server_main()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    projects = load_registry()
    if not projects:
        print("(registry is empty)")
        return 0
    for p in projects:
        print(f"{p.name:20}  agent={p.agent:8}  {p.path}")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    print(brief_mod.render())
    return 0


# ---------- observation layer (optional tmux) ----------

def _orchestrator_pane_for_up(args: argparse.Namespace) -> layout.OrchestratorPane | None:
    """Pick an orchestrator for pane 0 or return None to skip.

    Non-interactive resolution: saved preference → first installed.
    No picker, no prompting — `up` is meant to be scriptable.
    """
    if args.no_orchestrator:
        return None

    installed = _detect_installed()
    if not installed:
        print(
            "warning: no orchestrator CLI on PATH — skipping orchestrator pane",
            file=sys.stderr,
        )
        return None

    choice: tuple[str, str, str] | None = None
    pref = _load_preference()
    if pref:
        for entry in installed:
            if entry[0] == pref:
                choice = entry
                break
    if choice is None:
        choice = installed[0]

    key, binary, label = choice
    launch_dir = paths.central_mcp_home()
    _ensure_launch_dir(launch_dir)

    command = binary
    if args.bypass:
        flags = BYPASS_FLAGS.get(key)
        if flags:
            command = " ".join([binary, *flags])

    return layout.OrchestratorPane(command=command, cwd=str(launch_dir), label=label)


MULTIPLEXERS: list[tuple[str, str]] = [
    ("tmux", "tmux"),
    ("zellij", "zellij"),
]


def _detect_multiplexers() -> list[tuple[str, str]]:
    """Return (name, binary) pairs for every installed multiplexer."""
    return [(name, binary) for name, binary in MULTIPLEXERS if shutil.which(binary)]


def _pick_multiplexer_interactive(installed: list[tuple[str, str]]) -> str:
    print("Multiple multiplexers detected — which should `central-mcp up` use?")
    for i, (name, _bin) in enumerate(installed, 1):
        print(f"  {i}. {name}")
    while True:
        raw = input(f"Pick one [1-{len(installed)}] (default 1): ").strip()
        if not raw:
            return installed[0][0]
        try:
            idx = int(raw) - 1
        except ValueError:
            print("enter a number")
            continue
        if 0 <= idx < len(installed):
            return installed[idx][0]
        print("out of range")


def _resolve_multiplexer_for_up() -> str | None:
    """Decide which multiplexer backend `central-mcp up` should use.

    No persistent preference — `up` always prompts when both backends
    are available so users can pick per launch. If only one is
    installed, uses it without prompting. For a permanent choice, use
    `central-mcp tmux` or `central-mcp zellij` directly.
    """
    installed = _detect_multiplexers()
    if not installed:
        return None
    if len(installed) == 1:
        return installed[0][0]
    if not sys.stdin.isatty():
        print(
            "error: multiple multiplexers detected and this is not a TTY.\n"
            "       run `central-mcp up` interactively, or call\n"
            "       `central-mcp tmux` / `central-mcp zellij` directly.",
            file=sys.stderr,
        )
        return None
    return _pick_multiplexer_interactive(installed)


def cmd_up(args: argparse.Namespace) -> int:
    """Launch the observation session, picking the backend interactively.

    Detects tmux / zellij on PATH. If both are installed, prompts every
    time (no saved preference — users pick per launch). If only one is
    installed, uses it silently. Delegates to the backend-specific
    handler (`cmd_tmux` / `cmd_zellij`), which in turn creates the
    session if missing and attaches.
    """
    backend = _resolve_multiplexer_for_up()
    if backend is None:
        print(
            "error: no supported multiplexer installed (tmux or zellij)",
            file=sys.stderr,
        )
        return 1
    print(f"(using {backend})")
    if backend == "tmux":
        return cmd_tmux(args)
    if backend == "zellij":
        return cmd_zellij(args)
    print(f"error: unsupported multiplexer {backend!r}", file=sys.stderr)
    return 1


def cmd_watch(args: argparse.Namespace) -> int:
    from central_mcp import watch
    return watch.run(args.name, from_start=args.from_start)


def cmd_upgrade(args: argparse.Namespace) -> int:
    from central_mcp import upgrade
    return upgrade.run(check_only=args.check)


def cmd_down(args: argparse.Namespace) -> int:
    killed, message = layout.kill_all()
    print(message)
    return 0 if killed or "no session" in message else 1


def cmd_tmux(args: argparse.Namespace) -> int:
    """Attach to the observation tmux session via the CLI.

    Named after the backend (tmux) so users learn a consistent
    convention: `central-mcp tmux` attaches via tmux, `central-mcp
    zellij` attaches via zellij. If the session doesn't exist yet,
    creates it first (equivalent of `central-mcp up && tmux attach`)
    so a single command brings the whole layout up and drops the user
    in.
    """
    if not shutil.which("tmux"):
        print("error: tmux is not installed or not on PATH", file=sys.stderr)
        return 1

    if not tmux.has_session(layout.SESSION):
        orchestrator = _orchestrator_pane_for_up(args)
        panes_per_window = args.panes_per_window or layout.DEFAULT_PANES_PER_WINDOW
        if panes_per_window < 1:
            print(
                f"error: --panes-per-window must be >= 1 (got {panes_per_window})",
                file=sys.stderr,
            )
            return 1
        created, messages = layout.ensure_session(
            orchestrator=orchestrator,
            panes_per_window=panes_per_window,
        )
        for m in messages:
            print(m)
        if not created:
            return 1

    os.execvp("tmux", ["tmux", "attach", "-t", layout.SESSION])


def cmd_zellij(args: argparse.Namespace) -> int:
    """Attach to the observation session via Zellij.

    Mirrors `cmd_tmux` but uses Zellij's KDL layout: builds the file
    from the current registry, then launches (or attaches to) a session
    named `central`. Panes run exactly the same commands as tmux mode
    (`central-mcp watch <project>` per project, the orchestrator on
    the left half of the hub tab).
    """
    from central_mcp import zellij

    if not shutil.which("zellij"):
        print("error: zellij is not installed or not on PATH", file=sys.stderr)
        return 1

    orchestrator = _orchestrator_pane_for_up(args)
    panes_per_window = args.panes_per_window or layout.DEFAULT_PANES_PER_WINDOW
    if panes_per_window < 1:
        print(
            f"error: --panes-per-window must be >= 1 (got {panes_per_window})",
            file=sys.stderr,
        )
        return 1

    if zellij.has_session(zellij.SESSION):
        print(f"(session '{zellij.SESSION}' already running — attaching)")
        os.execvp("zellij", ["zellij", "attach", zellij.SESSION])

    layout_path = paths.central_mcp_home() / "zellij-layout.kdl"
    zellij.write_layout(
        layout_path,
        orchestrator=orchestrator,
        panes_per_window=panes_per_window,
    )
    print(f"wrote layout: {layout_path}")
    os.execvp(
        "zellij",
        ["zellij", "--session", zellij.SESSION, "--layout", str(layout_path)],
    )


# ---------- registry mutation ----------

def cmd_add(args: argparse.Namespace) -> int:
    from central_mcp.adapters.base import VALID_AGENTS
    if args.agent not in VALID_AGENTS:
        print(
            f"error: unknown agent {args.agent!r}. "
            f"Valid: {', '.join(sorted(VALID_AGENTS))}.",
            file=sys.stderr,
        )
        return 1
    try:
        proj = registry_add(
            name=args.name,
            path_=str(Path(args.path).expanduser().resolve()),
            agent=args.agent,
            description=args.description or "",
            tags=args.tag or None,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"added: {proj.name} -> {proj.path} (agent={proj.agent})")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    ok = registry_remove(args.name)
    if not ok:
        print(f"error: no project named {args.name!r}", file=sys.stderr)
        return 1
    print(f"removed: {args.name}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
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

    if not args.no_alias:
        _try_auto_alias("cmcp")

    print()
    print("Next steps:")
    print("  1. central-mcp install claude     # or codex, gemini")
    print("  2. Start that client and add projects in natural language, e.g.:")
    print('     "Add ~/Projects/my-app to the hub, agent=claude."')
    return 0


# ---------- install ----------

def cmd_install(args: argparse.Namespace) -> int:
    return install_mod.install(args.client, dry_run=args.dry_run)


# ---------- alias ----------

def _alias_bin_dir_and_target() -> tuple[Path | None, Path | None]:
    target = shutil.which("central-mcp")
    if not target:
        return None, None
    target_path = Path(target)
    return target_path.parent, target_path


def _try_auto_alias(name: str) -> None:
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
        print(f"error: {name!r} conflicts with existing command: {existing}", file=sys.stderr)
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


def _ensure_default_registry() -> bool:
    """Create `~/.central-mcp/registry.yaml` with `projects: []` if missing.

    Returns True when it just created the file (a cold-start signal the
    caller can use to trigger first-run bootstrap like auto-install).
    Returns False when the registry already existed.

    Only touches the default home registry; if the user has an explicit
    cwd registry or `$CENTRAL_MCP_REGISTRY` set, the cascade already
    picks that up and this helper is a no-op on the file that actually
    gets used.
    """
    reg = paths.central_mcp_home() / "registry.yaml"
    if reg.exists():
        return False
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        "# central-mcp project registry — edit via `central-mcp add` or by hand.\n\n"
        "projects: []\n"
    )
    return True


def _maybe_auto_install() -> None:
    """Run `install all` once on cold start, then never again.

    Gate file: `~/.central-mcp/.install_auto_done`. Present = previously
    ran auto-install (successful or skipped), so we leave the user's
    MCP client configs alone on every subsequent launch. `central-mcp
    install <client>` and `central-mcp install all` remain available
    for manual control at any time.
    """
    marker = paths.central_mcp_home() / ".install_auto_done"
    if marker.exists():
        return
    detected = install_mod.detect_installed_clients()
    if not detected:
        # No clients on PATH yet — leave the marker off so the next
        # cold start (after the user installs claude/codex/etc) picks
        # them up automatically.
        return
    print(
        "\nFirst-run bootstrap: registering central-mcp with detected MCP clients\n"
        "(rerun later with `central-mcp install <client>` or `central-mcp install all`)\n"
    )
    install_mod.install_all()
    try:
        marker.write_text("")
    except Exception:
        pass


def _prompt_choice(installed: list[tuple[str, str, str]]) -> tuple[str, str, str]:
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
    _ensure_default_registry()
    _maybe_auto_install()
    installed = _detect_installed()
    if not installed:
        supported = ", ".join(name for name, _bin, _label in ORCHESTRATORS)
        print(
            "error: no supported coding-agent CLI detected on PATH.\n"
            f"       install one of: {supported}",
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
                f"warning: --bypass: {key!r} has no known permission-bypass flag; "
                "launching without it.",
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
