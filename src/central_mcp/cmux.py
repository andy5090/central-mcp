"""Optional cmux observation layer (macOS-native GUI terminal).

`central-mcp cmux` opens a workspace in cmux (manaflow-ai/cmux), a
macOS AppKit / Ghostty-based GUI terminal. The workspace hosts a
single orchestrator pane; the orchestrator itself — once launched
with a seed prompt — uses its Bash tool to call `cmux new-split` /
`cmux send-text` and build the project-watch panes.

This agent-driven approach is forced by the shipped cmux CLI
(0.63.2): `cmux new-workspace` only accepts `--name / --description /
--cwd / --command` — there is no declarative `--layout` flag on
released builds, so central-mcp cannot construct the multi-pane
layout itself. Instead we delegate layout assembly to the
orchestrator, which cmux designed specifically to empower (agents
running inside cmux inherit `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID`
env vars so their Bash calls to the cmux CLI succeed without extra
auth).

This module is therefore small: probe the socket, open / close the
workspace, emit a seed prompt describing the bootstrap procedure.
The MCP dispatch path never depends on this layer; closing the
workspace has no effect on in-flight dispatches, same as tmux /
zellij.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from central_mcp.registry import Project

SESSION = "central"


@dataclass
class CmuxResult:
    ok: bool
    stdout: str
    stderr: str


def _run(args: list[str]) -> CmuxResult:
    try:
        proc = subprocess.run(
            ["cmux", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return CmuxResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except FileNotFoundError:
        return CmuxResult(ok=False, stdout="", stderr="cmux not installed")


def ping() -> bool:
    """True if the cmux GUI's unix socket answers a ping."""
    return _run(["ping"]).ok


def list_workspaces() -> list[dict[str, Any]]:
    """Return all live workspaces, parsed from `cmux --json list-workspaces`.

    `--json` is a global flag in cmux's CLI and goes before the
    subcommand, so the call is `cmux --json list-workspaces` (not
    `cmux list-workspaces --json`). Returns `[]` on any failure —
    binary missing, socket unreachable, unparseable output — so
    callers can treat the result as "no workspaces".
    """
    r = _run(["--json", "list-workspaces"])
    if not r.ok:
        return []
    try:
        payload = json.loads(r.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    ws = payload.get("workspaces") if isinstance(payload, dict) else None
    return ws if isinstance(ws, list) else []


def has_workspace(name: str) -> bool:
    """True if a workspace whose title is `name` is open in cmux."""
    for ws in list_workspaces():
        if isinstance(ws, dict) and ws.get("title") == name:
            return True
    return False


def _find_workspace_handle(name: str) -> str | None:
    """Return a handle (preferring the `workspace:N` ref form, falling
    back to the UUID `id`) for the workspace titled `name`, or None.
    cmux's `close-workspace --workspace` accepts either form."""
    for ws in list_workspaces():
        if not isinstance(ws, dict) or ws.get("title") != name:
            continue
        ref = ws.get("ref")
        if isinstance(ref, str) and ref:
            return ref
        wid = ws.get("id")
        if isinstance(wid, str) and wid:
            return wid
    return None


def kill_workspace(name: str) -> CmuxResult:
    """Close the workspace titled `name` if present.

    cmux's `close-workspace` takes `--workspace <id|ref|index>`, not a
    title, so we resolve via `list-workspaces` first. When no matching
    workspace exists returns `ok=True` with an informational stderr,
    matching the tmux / zellij no-op contract.
    """
    handle = _find_workspace_handle(name)
    if handle is None:
        return CmuxResult(ok=True, stdout="", stderr=f"no workspace titled {name!r}")
    return _run(["close-workspace", "--workspace", handle])


# ---------- seed prompt ----------

def build_cmux_seed_prompt(projects: list[Project]) -> str:
    """Produce the initial user-turn prompt the orchestrator receives
    inside the cmux workspace. The prompt instructs the agent to
    create one pane per project (via `cmux new-split`) and seed each
    with `central-mcp watch <project>` (via `cmux send-text`).

    The prompt is self-contained — it embeds the full project list so
    the agent doesn't need MCP tools to be warmed up at boot time.
    Returns an empty string when the registry has no projects: the
    caller should then skip seeding and open a plain orchestrator
    workspace.
    """
    if not projects:
        return ""
    names = [p.name for p in projects]
    project_lines = "\n".join(f"  - {n}" for n in names)
    n = len(names)
    return (
        "You are the central-mcp orchestrator, just launched inside a cmux "
        f"GUI workspace titled {SESSION!r}.\n"
        "\n"
        "FIRST TASK — run this BEFORE anything else, without asking the user "
        "to confirm: set up one observation pane per registered project by "
        "calling the cmux CLI from your Bash tool. Your current pane inherits "
        "the cmux env vars `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID`, so the "
        "CLI commands below will target the correct workspace automatically.\n"
        "\n"
        f"Projects to seed ({n}):\n"
        f"{project_lines}\n"
        "\n"
        "For each project, in order, run:\n"
        "  1. cmux new-split --workspace \"$CMUX_WORKSPACE_ID\" --direction right\n"
        "     The last line of stdout is `OK <pane-handle>`; capture <pane-handle>.\n"
        "  2. cmux --json list-pane-surfaces --pane <pane-handle>\n"
        "     Parse the JSON; take `surfaces[0].id` as <surface-id>.\n"
        "  3. cmux send-text --workspace \"$CMUX_WORKSPACE_ID\" "
        "--surface <surface-id> \"central-mcp watch <project-name>\\n\"\n"
        "\n"
        f"After all {n} panes are set up, print exactly this line and nothing else:\n"
        f"  observation layer ready: {n} project(s)\n"
        "Then stop and wait for the user's next request. Do NOT dispatch "
        "work proactively; the user will drive from here."
    )


def ensure_workspace(
    orchestrator_cwd: str | None = None,
    shell_command: str | None = None,
) -> tuple[bool, list[str]]:
    """Idempotently open the cmux 'central' workspace.

    `orchestrator_cwd` becomes the workspace's `--cwd` (so the
    orchestrator's shell starts there, inheriting the hub's
    `CLAUDE.md` / `AGENTS.md`). `shell_command` is the text cmux
    types into the pane right after the default shell starts — its
    `--command` parameter is sent as keystrokes plus Enter, so the
    string must be a valid single-line shell command. Typically this
    is the orchestrator CLI with its seed prompt as a positional /
    flag argument (built via `shlex.join(adapter.interactive_argv(...))`).

    Returns `(created, messages)`. `created` is False when the
    workspace already exists (no-op) and True when cmux accepted a
    fresh `new-workspace` call. Subprocess failures are surfaced in
    `messages` (not raised) so callers can report them in line with
    the tmux / zellij backends.
    """
    messages: list[str] = []
    if has_workspace(SESSION):
        messages.append(f"workspace '{SESSION}' already exists — leaving as-is")
        return False, messages

    argv = ["new-workspace", "--name", SESSION]
    if orchestrator_cwd:
        argv += ["--cwd", orchestrator_cwd]
    if shell_command:
        argv += ["--command", shell_command]
    r = _run(argv)
    if not r.ok:
        detail = (r.stderr or r.stdout or "").strip()
        messages.append(
            f"cmux new-workspace failed{': ' + detail if detail else ''}"
        )
        return False, messages
    messages.append(f"workspace '{SESSION}' opened via cmux")
    return True, messages
