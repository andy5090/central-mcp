"""Command implementations + shared helpers for the central-mcp CLI."""

from __future__ import annotations

import argparse
import hashlib
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
from central_mcp import config as user_config
from central_mcp.config import current_workspace, set_current_workspace
from central_mcp.registry import (
    add_project as registry_add,
    add_to_workspace,
    add_workspace,
    load_registry,
    load_workspaces,
    projects_in_workspace,
    remove_from_workspace,
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
# Canonical source is `central_mcp.agents.AGENTS[*].can_orchestrate` —
# this re-export keeps legacy imports working.
from central_mcp.agents import ORCHESTRATORS   # noqa: E402

# Per-(agent, mode) argv suffix for the orchestrator launcher.
# `auto` is claude-only (Team/Enterprise/API + Sonnet/Opus 4.6). Agents
# without an entry for a given mode fall back to no flags (= restricted).
PERMISSION_MODE_FLAGS: dict[str, dict[str, list[str]]] = {
    "claude": {
        "bypass":     ["--dangerously-skip-permissions"],
        "auto":       ["--enable-auto-mode", "--permission-mode", "auto"],
        "restricted": [],
    },
    "codex": {
        "bypass":     ["--dangerously-bypass-approvals-and-sandbox"],
        "restricted": [],
    },
    "gemini": {
        "bypass":     ["--yolo"],
        "restricted": [],
    },
}

DEFAULT_PERMISSION_MODE = "bypass"


def _flags_for(agent: str, mode: str) -> list[str] | None:
    """Return the flag list for (agent, mode) or None if unsupported.

    None means "this agent does not implement this mode at all" (e.g.
    codex has no `auto`). The caller decides whether to error or skip.
    """
    modes = PERMISSION_MODE_FLAGS.get(agent)
    if modes is None:
        return None
    return modes.get(mode)


# ---------- server / listing ----------

def cmd_serve(args: argparse.Namespace) -> int:
    user_config.ensure_initialized()
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

def _resolve_max_panes(args: argparse.Namespace) -> int:
    """Resolve the effective max-panes-per-window for `up` / `tmux` /
    `zellij`. Falls back to `grid.pick_panes_per_window()` — which
    reads the current terminal size — when `--max-panes` is absent.
    """
    explicit = getattr(args, "max_panes", None)
    if explicit:
        return explicit
    from central_mcp.grid import pick_panes_per_window
    return pick_panes_per_window()


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

    mode = args.permission_mode
    flags = _flags_for(key, mode)
    if flags is None:
        print(
            f"warning: --permission-mode {mode!r}: {key!r} has no flags defined; "
            "launching without permission flags.",
            file=sys.stderr,
        )
        flags = []
    command = " ".join([binary, *flags]) if flags else binary

    return layout.OrchestratorPane(command=command, cwd=str(launch_dir), label=label)


MULTIPLEXERS: list[tuple[str, str]] = [
    ("tmux", "tmux"),
    ("zellij", "zellij"),
]

def _detect_multiplexers() -> list[tuple[str, str]]:
    """Return (name, binary) pairs for every installed multiplexer."""
    return [(name, binary) for name, binary in MULTIPLEXERS if shutil.which(binary)]


def _color_enabled() -> bool:
    """Whether to emit ANSI color escapes.

    Off when stdout is not a TTY (piped output, CI logs) or when the
    user has set NO_COLOR (the de-facto opt-out, see no-color.org).
    """
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


# Module-level so callers (and tests) can read the same palette helpers
# without re-deriving the truthy/empty strings every call.
class _Palette:
    __slots__ = ("bold", "dim", "cyan", "reset")

    def __init__(self, enabled: bool) -> None:
        self.bold  = "\x1b[1m"  if enabled else ""
        self.dim   = "\x1b[2m"  if enabled else ""
        self.cyan  = "\x1b[36m" if enabled else ""
        self.reset = "\x1b[0m"  if enabled else ""


def _arrow_select(
    prompt: str,
    labels: list[str],
    default: int = 0,
    *,
    description: str | None = None,
) -> int:
    """Interactive arrow-key picker. Returns the chosen index.

    Uses termios cbreak on POSIX TTYs so the user can navigate with
    ↑/↓ (or k/j), commit with Enter, and cancel with Esc/q (returns
    `default`). Falls back to the legacy numbered-input flow when
    stdin/stdout aren't interactive or termios isn't available
    (Windows native, piped input).

    `description` (optional): a sub-line printed under the prompt in
    dim style — use it for non-actionable hints like "set X in
    config.toml to silence this".

    Renders with ANSI color when stdout is a TTY and NO_COLOR isn't
    set: prompt is bold, description and key hint are dim, the
    selected option is bold-cyan. Codes are silently dropped on
    non-color terminals.
    """
    # Fallback path: non-TTY environments or platforms without termios.
    try:
        import termios  # noqa: F401  (POSIX only — ImportError on Windows)
        import tty
        tty_ok = sys.stdin.isatty() and sys.stdout.isatty()
    except ImportError:
        tty_ok = False

    pal = _Palette(_color_enabled())

    if not tty_ok:
        print(f"{pal.bold}{prompt}{pal.reset}")
        if description:
            print(f"{pal.dim}{description}{pal.reset}")
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        while True:
            raw = input(
                f"Pick one [1-{len(labels)}] (default {default + 1}): "
            ).strip()
            if not raw:
                return default
            try:
                idx = int(raw) - 1
            except ValueError:
                print("enter a number")
                continue
            if 0 <= idx < len(labels):
                return idx
            print("out of range")

    # Interactive cbreak path.
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    print(f"{pal.bold}{prompt}{pal.reset}")
    if description:
        print(f"{pal.dim}{description}{pal.reset}")
    print(f"{pal.dim}(↑/↓ to move, Enter to select, Esc/q to cancel){pal.reset}")
    selected = default
    first = True
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[?25l")   # hide cursor
        while True:
            if not first:
                # Move cursor up N lines to repaint the list. Header lines
                # (prompt / description / hint) are printed once and stay
                # above the redraw window.
                sys.stdout.write(f"\x1b[{len(labels)}A")
            first = False
            for i, label in enumerate(labels):
                marker = "›" if i == selected else " "
                line = f" {marker} {label}"
                # \x1b[K clears the rest of the line in case the
                # previous frame had a longer label at this index.
                if i == selected:
                    sys.stdout.write(
                        f"\r\x1b[K{pal.bold}{pal.cyan}{line}{pal.reset}\n"
                    )
                else:
                    sys.stdout.write(f"\r\x1b[K{line}\n")
            sys.stdout.flush()

            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Could be ESC alone or the start of an arrow sequence.
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A" and selected > 0:
                        selected -= 1
                    elif ch3 == "B" and selected < len(labels) - 1:
                        selected += 1
                else:
                    return default
            elif ch in ("\r", "\n"):
                return selected
            elif ch in ("k",) and selected > 0:
                selected -= 1
            elif ch in ("j",) and selected < len(labels) - 1:
                selected += 1
            elif ch in ("q", "Q", "\x03"):   # Ctrl-C also lands here
                return default
    except KeyboardInterrupt:
        return default
    finally:
        sys.stdout.write("\x1b[?25h")   # show cursor
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _pick_multiplexer_interactive(installed: list[tuple[str, str]]) -> str:
    idx = _arrow_select(
        "Multiple multiplexers detected — which should `central-mcp up` use?",
        [name for name, _bin in installed],
    )
    return installed[idx][0]


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


def cmd_monitor(_args: argparse.Namespace) -> int:
    from central_mcp.monitor import run as _monitor_run
    return _monitor_run()


def cmd_upgrade(args: argparse.Namespace) -> int:
    from central_mcp import upgrade
    # Always tear down any live observation session before replacing
    # the binary — otherwise its orchestrator + `central-mcp watch`
    # children hold the old version and the upgrade "doesn't take"
    # from the user's POV. --check is read-only so we skip the
    # teardown there.
    if not args.check:
        _teardown_observation_session()
    return upgrade.run(check_only=args.check)


def _teardown_observation_session(session_name: str | None = None) -> bool:
    """Kill tmux + zellij observation sessions and clear the version stamp.

    If `session_name` is given, kills only that specific tmux session.
    If None, kills all `cmcp-*` + legacy `central` tmux sessions.
    Always kills the matching zellij session (or all cmcp-* if no name given).
    Returns True if anything was actually torn down.
    """
    from central_mcp import session_info

    any_killed, _ = layout.kill_all(session_name)
    if shutil.which("zellij"):
        from central_mcp import zellij as zj
        if session_name is not None:
            if zj.has_session(session_name):
                r = zj._run(["delete-session", session_name, "--force"])
                if r.ok:
                    any_killed = True
        else:
            # Kill all cmcp-* zellij sessions + legacy
            for zs in _zellij_cmcp_sessions():
                r = zj._run(["delete-session", zs, "--force"])
                if r.ok:
                    any_killed = True
    session_info.clear()
    return any_killed


def _zellij_cmcp_sessions() -> list[str]:
    """Return all zellij session names starting with 'cmcp-' plus legacy 'central'."""
    from central_mcp import zellij as zj
    from central_mcp.layout import SESSION_PREFIX, LEGACY_SESSION
    try:
        r = zj._run(["list-sessions", "--no-formatting"])
        names = [line.strip() for line in r.stdout.splitlines() if line.strip()]
        cmcp = [n for n in names if n.startswith(SESSION_PREFIX)]
        if LEGACY_SESSION in names:
            cmcp.append(LEGACY_SESSION)
        return cmcp
    except Exception:
        return []


def cmd_down(args: argparse.Namespace) -> int:
    """Tear down the observation session for both backends.

    Users don't have to remember which multiplexer currently holds
    `central` — `cmcp down` kills whichever has a matching session.
    Reports each backend's outcome so a partially-live state is
    visible.
    """
    from central_mcp import session_info

    any_killed = False
    any_error = False

    killed_tmux, msg_tmux = layout.kill_all()
    print(f"tmux: {msg_tmux}")
    if killed_tmux:
        any_killed = True
    elif "no session" not in msg_tmux:
        any_error = True

    # zellij is optional — only try if the binary is on PATH.
    if shutil.which("zellij"):
        zj_sessions = _zellij_cmcp_sessions()
        if zj_sessions:
            from central_mcp import zellij as zj
            for zs in zj_sessions:
                r = zj._run(["delete-session", zs, "--force"])
                if r.ok:
                    print(f"zellij: deleted session '{zs}'")
                    any_killed = True
                else:
                    detail = (r.stderr or r.stdout or "").strip()
                    print(f"zellij: delete-session '{zs}' failed{': ' + detail if detail else ''}")
                    any_error = True
        else:
            print("zellij: no observation sessions found")

    # Always clear the stamp so a later `cmcp up` isn't held back by
    # an orphan file pointing at a version/multiplexer that's gone.
    session_info.clear()

    if any_error:
        return 1
    return 0 if any_killed else 0


def _resolve_workspace_for_tmux(args: argparse.Namespace) -> str:
    """Return the target workspace name for tmux/zellij commands."""
    ws_override = getattr(args, "workspace", None)
    return ws_override if ws_override else current_workspace()


def cmd_tmux(args: argparse.Namespace) -> int:
    """Attach to the observation tmux session via the CLI."""
    from central_mcp import session_info

    # Handle `cmcp tmux switch <name>`
    if getattr(args, "tmux_sub", None) == "switch":
        return _cmd_tmux_switch(args)

    if not shutil.which("tmux"):
        print("error: tmux is not installed or not on PATH", file=sys.stderr)
        return 1

    use_all = getattr(args, "all", False)
    orchestrator = _orchestrator_pane_for_up(args)
    panes_per_window = _resolve_max_panes(args)
    if panes_per_window < 1:
        print(f"error: --max-panes must be >= 1 (got {panes_per_window})", file=sys.stderr)
        return 1

    if use_all:
        ws_map = load_workspaces() or {"default": []}
        workspaces = list(ws_map.keys())
        attach_ws = current_workspace()
        for ws in workspaces:
            sname = layout.session_name_for_workspace(ws)
            projs = projects_in_workspace(ws)
            if tmux.has_session(sname):
                _teardown_observation_session(sname)
            created, messages = layout.ensure_session(
                orchestrator=orchestrator if ws == attach_ws else None,
                panes_per_window=panes_per_window,
                session_name=sname,
                projects=projs,
            )
            for m in messages:
                print(f"[{ws}] {m}")
        session_info.write(multiplexer="tmux")
        attach_sname = layout.session_name_for_workspace(attach_ws)
        os.execvp("tmux", ["tmux", "attach", "-t", attach_sname])
    else:
        ws = _resolve_workspace_for_tmux(args)
        sname = layout.session_name_for_workspace(ws)
        projs = projects_in_workspace(ws)
        if tmux.has_session(sname):
            _teardown_observation_session(sname)
        created, messages = layout.ensure_session(
            orchestrator=orchestrator,
            panes_per_window=panes_per_window,
            session_name=sname,
            projects=projs,
        )
        for m in messages:
            print(m)
        if not created:
            return 1
        session_info.write(multiplexer="tmux")
        os.execvp("tmux", ["tmux", "attach", "-t", sname])


def _cmd_tmux_switch(args: argparse.Namespace) -> int:
    """Attach to cmcp-<name> tmux session, creating it if missing."""
    ws = args.ws_name
    sname = layout.session_name_for_workspace(ws)
    if not tmux.has_session(sname):
        orchestrator = _orchestrator_pane_for_up(args)
        panes_per_window = _resolve_max_panes(args)
        projs = projects_in_workspace(ws)
        created, messages = layout.ensure_session(
            orchestrator=orchestrator,
            panes_per_window=panes_per_window,
            session_name=sname,
            projects=projs,
        )
        for m in messages:
            print(m)
        if not created and not tmux.has_session(sname):
            return 1
    os.execvp("tmux", ["tmux", "attach", "-t", sname])


def cmd_zellij(args: argparse.Namespace) -> int:
    """Attach to the observation session via Zellij."""
    from central_mcp import zellij, session_info

    # Handle `cmcp zellij switch <name>`
    if getattr(args, "zellij_sub", None) == "switch":
        return _cmd_zellij_switch(args)

    if not shutil.which("zellij"):
        print("error: zellij is not installed or not on PATH", file=sys.stderr)
        return 1

    use_all = getattr(args, "all", False)
    orchestrator = _orchestrator_pane_for_up(args)
    panes_per_window = _resolve_max_panes(args)
    if panes_per_window < 1:
        print(f"error: --max-panes must be >= 1 (got {panes_per_window})", file=sys.stderr)
        return 1

    if use_all:
        ws_map = load_workspaces() or {"default": []}
        workspaces = list(ws_map.keys())
        attach_ws = current_workspace()
        for ws in workspaces:
            sname = layout.session_name_for_workspace(ws)
            projs = projects_in_workspace(ws)
            if zellij.has_session(sname):
                _teardown_observation_session(sname)
            layout_path = paths.central_mcp_home() / f"zellij-layout-{sname}.kdl"
            zellij.write_layout(layout_path, orchestrator=orchestrator if ws == attach_ws else None,
                                panes_per_window=panes_per_window, projects=projs)
            print(f"[{ws}] wrote layout: {layout_path}")
        session_info.write(multiplexer="zellij")
        attach_sname = layout.session_name_for_workspace(attach_ws)
        attach_layout = paths.central_mcp_home() / f"zellij-layout-{attach_sname}.kdl"
        os.execvp("zellij", ["zellij", "--session", attach_sname,
                              "--new-session-with-layout", str(attach_layout)])
    else:
        ws = _resolve_workspace_for_tmux(args)
        sname = layout.session_name_for_workspace(ws)
        projs = projects_in_workspace(ws)
        if zellij.has_session(sname):
            _teardown_observation_session(sname)
        layout_path = paths.central_mcp_home() / f"zellij-layout-{sname}.kdl"
        zellij.write_layout(layout_path, orchestrator=orchestrator,
                            panes_per_window=panes_per_window, projects=projs)
        print(f"wrote layout: {layout_path}")
        session_info.write(multiplexer="zellij")
        os.execvp("zellij", ["zellij", "--session", sname,
                              "--new-session-with-layout", str(layout_path)])


def _cmd_zellij_switch(args: argparse.Namespace) -> int:
    """Attach to cmcp-<name> zellij session, creating it if missing."""
    from central_mcp import zellij, session_info
    ws = args.ws_name
    sname = layout.session_name_for_workspace(ws)
    if not zellij.has_session(sname):
        orchestrator = _orchestrator_pane_for_up(args)
        panes_per_window = _resolve_max_panes(args)
        projs = projects_in_workspace(ws)
        layout_path = paths.central_mcp_home() / f"zellij-layout-{sname}.kdl"
        zellij.write_layout(layout_path, orchestrator=orchestrator,
                            panes_per_window=panes_per_window, projects=projs)
        print(f"wrote layout: {layout_path}")
        session_info.write(multiplexer="zellij")
    os.execvp("zellij", ["zellij", "--session", sname,
                          "--new-session-with-layout",
                          str(paths.central_mcp_home() / f"zellij-layout-{sname}.kdl")])


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


def cmd_reorder(args: argparse.Namespace) -> int:
    from central_mcp import registry as _registry
    try:
        reordered = _registry.reorder(
            list(args.order), strict=bool(args.strict),
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("new order:")
    for p in reordered:
        print(f"  {p.name:20}  agent={p.agent:8}  {p.path}")
    print(
        "(rerun `cmcp tmux` or `cmcp zellij` to rebuild the observation "
        "session with this pane order)",
        file=sys.stderr,
    )
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

    # Seed config.toml with system timezone + default workspace so the file
    # reflects resolved values (not fallbacks) the user can inspect and edit.
    user_config.ensure_initialized()

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

def _maybe_prompt_upgrade() -> None:
    """Startup-time version probe — runs on every interactive launch.

    Probes PyPI on every `central-mcp run`. The check is bounded by a
    short timeout (2s) and silent on every failure path (network down,
    non-TTY shell, not yet installed from source) so startup is never
    blocked. The picker is only shown when a newer release is actually
    available. Controlled by `[user].upgrade_check_enabled` in
    config.toml — set to false to disable entirely.
    """
    if not user_config.upgrade_check_enabled():
        return
    # Only prompt in interactive shells — scripted runs should not
    # block on a picker.
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return

    from central_mcp import upgrade
    result = upgrade.check_available_silent(timeout=2.0)
    if result is None:
        return                    # up to date, or offline, or pre-install
    cur, latest = result

    print(file=sys.stderr)        # spacer above the picker
    try:
        choice = _arrow_select(
            prompt=f"central-mcp {latest} is available (you have {cur}).",
            description=(
                "Set `[user].upgrade_check_enabled = false` in config.toml "
                "to silence this prompt."
            ),
            labels=["Upgrade now", "Skip"],
            default=0,
        )
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return
    if choice != 0:
        return                    # declined — skip
    # Hand off to the existing upgrade flow. It spawns `uv tool install`
    # (or pip) synchronously; on success the user should re-run
    # `cmcp run` on the new binary, so we exit after.
    rc = upgrade.run(check_only=False)
    if rc == 0:
        print(
            "\nupgrade complete — please re-run your command on the new version.",
            file=sys.stderr,
        )
        raise SystemExit(0)


def _detect_installed() -> list[tuple[str, str, str]]:
    return [(k, b, label) for k, b, label in ORCHESTRATORS if shutil.which(b)]


def _orchestrator_over_quota(agent: str) -> bool:
    """True if the orchestrator's provider-reported quota is at/above
    the configured fallback threshold. Agents without a quota API
    (`has_quota_api=False`) always return False — we have nothing to
    base a skip decision on.
    """
    from central_mcp import agents as _agents
    cap = _agents.get(agent)
    if cap is None or not cap.has_quota_api:
        return False

    th = user_config.quota_threshold()
    try:
        if agent == "claude":
            from central_mcp.quota import claude as _claude
            q = _claude.fetch()
            if q.get("mode") != "pro":
                return False   # API key users have no subscription quota
            raw = q.get("raw") or {}
            fh_pct = (raw.get("five_hour") or {}).get("utilization", 0) * 100
            wd_pct = (raw.get("seven_day") or {}).get("utilization", 0) * 100
            return fh_pct >= th["five_hour"] or wd_pct >= th["seven_day"]

        if agent == "codex":
            from central_mcp.quota import codex as _codex
            q = _codex.fetch()
            if q is None or q.get("mode") != "chatgpt":
                return False
            raw = q.get("raw") or {}
            rl = raw.get("rate_limit") or {}
            pw_pct = (rl.get("primary_window") or {}).get("used_percent", 0)
            sw_pct = (rl.get("secondary_window") or {}).get("used_percent", 0)
            return pw_pct >= th["five_hour"] or sw_pct >= th["seven_day"]
    except Exception:
        return False
    return False


def _resolve_orchestrator_chain(
    preferred: str | None,
) -> list[tuple[tuple[str, str, str], str]]:
    """Return an ordered list of (entry, skip_reason_or_empty) for every
    orchestrator candidate, honoring this priority:

      1. `preferred` (user preference or explicit default)
      2. `config.toml [orchestrator].fallback` list, in order
      3. remaining installed orchestrator-capable agents

    Uninstalled agents are dropped silently. Over-quota agents stay in
    the list with a skip_reason so the caller can surface "tried X,
    skipped due to Y" context.
    """
    from central_mcp import agents as _agents
    seen: set[str] = set()
    order: list[str] = []
    candidates = [preferred] if preferred else []
    candidates += user_config.orchestrator_fallback()
    candidates += [a.name for a in _agents.installed(lambda a: a.can_orchestrate)]
    for name in candidates:
        if not name or name in seen:
            continue
        cap = _agents.get(name)
        if cap is None or not cap.can_orchestrate:
            continue
        if not shutil.which(cap.binary):
            continue
        order.append(name)
        seen.add(name)

    result: list[tuple[tuple[str, str, str], str]] = []
    for name in order:
        cap = _agents.AGENTS[name]
        entry = (cap.name, cap.binary, cap.label)
        skip = ""
        if _orchestrator_over_quota(name):
            th = user_config.quota_threshold()
            skip = f"quota ≥ {th['five_hour']}%/{th['seven_day']}%"
        result.append((entry, skip))
    return result


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
    for fname in ("CLAUDE.md", "AGENTS.md"):
        dest = target / fname
        content = _read_packaged(fname)
        if not dest.exists() or dest.read_text() != content:
            dest.write_text(content)
    # user.md is no longer scaffolded. The MCP server reads it only
    # when the user has actually written something via
    # `update_user_preferences`, so prior installs that still hold the
    # 0.10.11- template-with-examples are migrated away here:
    # if the file exists but is essentially template-only (header +
    # section markers + HTML comment blocks, no real user content),
    # delete it so the new "user-authored only" model takes effect.
    user_md = target / "user.md"
    if user_md.exists():
        try:
            if _is_pristine_user_md(user_md.read_text(encoding="utf-8")):
                user_md.unlink()
        except Exception:
            pass
    settings_dir = target / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text(_SETTINGS_JSON)


# SHA256 of the user.md template shipped through 0.10.11. Used only by
# `_is_pristine_user_md` to detect installs that still hold the unedited
# template so we can clean it up. Once 0.10.12 has been out for several
# releases, drop this constant and the migration in `_ensure_launch_dir`.
_USER_MD_0_10_11_SHA256 = (
    "e9b14b568cdf63c74d49342b47463eaf57efa31843cf3b4d155a3732b7a9b265"
)


def _is_pristine_user_md(text: str) -> bool:
    """Return True if user.md is empty, whitespace-only, or byte-equal
    to the unedited 0.10.11 template. Used by `_ensure_launch_dir` to
    migrate legacy installs to the new "user-authored only" model. Any
    user-edited file (even a single keystroke) fails the byte match and
    is preserved.
    """
    if not text.strip():
        return True
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest == _USER_MD_0_10_11_SHA256


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
    idx = _arrow_select(
        "Multiple coding agents detected — which should central-mcp launch?",
        [f"{label} ({binary})" for _key, binary, label in installed],
    )
    return installed[idx]


def cmd_run(args: argparse.Namespace) -> int:
    _ensure_default_registry()
    user_config.ensure_initialized()
    _maybe_prompt_upgrade()
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
            # Fallback-aware resolution: walk the chain (preferred →
            # user-configured fallback → remaining installed
            # orchestrators), skipping any entry whose provider quota
            # is at/above the configured threshold.
            fallback_on = user_config.orchestrator_fallback_enabled()
            chain = _resolve_orchestrator_chain(pref)
            chain_names = [e[0][0] for e in chain]
            if fallback_on:
                for entry, skip_reason in chain:
                    if skip_reason:
                        print(
                            f"ℹ  skipping {entry[0]} ({skip_reason})",
                            file=sys.stderr,
                        )
                        continue
                    choice = entry
                    if entry[0] != pref:
                        source = f"fallback (primary {pref!r} unavailable)"
                    else:
                        source = "saved preference"
                    break
                if choice is None:
                    print(
                        f"warning: all orchestrators in chain are over quota — "
                        f"falling back to raw preference {pref!r}",
                        file=sys.stderr,
                    )
                    for entry in installed:
                        if entry[0] == pref:
                            choice = entry
                            source = "saved preference (quota ignored)"
                            break
            else:
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
    mode = args.permission_mode
    flags = _flags_for(key, mode)
    if flags is None:
        print(
            f"warning: --permission-mode {mode!r}: {key!r} has no flags "
            "defined; launching without permission flags.",
            file=sys.stderr,
        )
    elif flags:
        argv.extend(flags)

    from central_mcp import upgrade
    installed_ver = upgrade.installed_version() or "source"
    source_suffix = f"  [{source}]" if source else ""
    print(f"central-mcp  : {installed_ver}")
    print(f"orchestrator : {label} ({binary}){source_suffix}")
    print(f"launch cwd   : {launch_dir}")
    if len(argv) > 1:
        print(f"extra args   : {' '.join(argv[1:])}")

    if args.dry_run:
        print("(dry-run: not executing)")
        return 0

    # Expose the launching terminal's dimensions to the orchestrator
    # as env vars. Rationale: agent CLIs (claude, codex, gemini, ...)
    # spawn their Bash tool subprocesses without a controlling TTY,
    # so `tput cols` / `stty size` from inside those tools falls back
    # to the terminfo default of 80x24. `cmcp` itself IS running in
    # a real TTY, so `shutil.get_terminal_size()` here reflects the
    # actual cmux pane / tmux pane / plain terminal size. The cmux
    # bootstrap recipe in data/AGENTS.md reads CMCP_OBS_W / CMCP_OBS_H
    # to decide grid density without needing to probe from inside the
    # agent's Bash tool.
    try:
        _term_size = shutil.get_terminal_size((200, 50))
        os.environ["CMCP_OBS_W"] = str(_term_size.columns)
        os.environ["CMCP_OBS_H"] = str(_term_size.lines)
    except OSError:
        # get_terminal_size has defaults; no reason to reach here, but
        # bail silently if somehow it does.
        pass

    os.chdir(launch_dir)
    try:
        os.execvp(binary, argv)
    except FileNotFoundError:
        print(f"error: {binary!r} vanished from PATH between detection and exec", file=sys.stderr)
        return 1


# ---------- workspace ----------

def cmd_workspace(args: argparse.Namespace) -> int:
    sub = getattr(args, "workspace_sub", None)
    if sub == "list":
        return _ws_list()
    if sub == "current":
        return _ws_current()
    if sub == "new":
        return _ws_new(args.ws_name)
    if sub == "use":
        return _ws_use(args.ws_name)
    if sub == "add":
        return _ws_add_project(args.project, args.workspace)
    if sub == "remove":
        return _ws_remove_project(args.project, args.workspace)
    print("usage: cmcp workspace <list|current|new|use|add|remove>", file=sys.stderr)
    return 1


def _ws_list() -> int:
    ws_map = load_workspaces()
    active = current_workspace()
    if not ws_map:
        ws_map = {"default": []}
    for name, members in ws_map.items():
        count = len(projects_in_workspace(name))
        marker = "*" if name == active else " "
        print(f"  {marker} {name:<20} ({count} project{'s' if count != 1 else ''})")
    return 0


def _ws_current() -> int:
    print(current_workspace())
    return 0


def _ws_new(name: str) -> int:
    try:
        add_workspace(name)
        print(f"workspace created: {name}")
        return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _ws_use(name: str) -> int:
    try:
        set_current_workspace(name)
        print(f"switched to workspace: {name}")
        return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _ws_add_project(project: str, workspace: str) -> int:
    try:
        add_to_workspace(project, workspace)
        print(f"added {project!r} to workspace {workspace!r}")
        return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _ws_remove_project(project: str, workspace: str) -> int:
    removed = remove_from_workspace(project, workspace)
    if removed:
        print(f"removed {project!r} from workspace {workspace!r}")
        return 0
    print(f"error: {project!r} is not a member of workspace {workspace!r}", file=sys.stderr)
    return 1
