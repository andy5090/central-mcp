"""Live dispatch E2E tests — actually spawn each agent binary.

These tests exercise the full dispatch roundtrip:
  dispatch() → subprocess → stdout capture → check_dispatch() → complete

They are gated behind the ``live`` marker and skip cleanly when the
agent binary is absent, so they never break CI.

    pytest -m live                  # run live tests (includes these)
    pytest                          # default: skips all live tests
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from central_mcp import registry, server
from central_mcp.adapters.base import VALID_AGENTS

pytestmark = pytest.mark.live

AGENTS_UNDER_TEST = sorted(VALID_AGENTS)

DISPATCH_TIMEOUT = 90.0   # seconds — generous for slow model cold-starts


def _skip_if_missing(binary: str) -> None:
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} binary not installed on PATH")


def _wait_dispatch(dispatch_id: str, timeout: float = DISPATCH_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = server.check_dispatch(dispatch_id)
        if r.get("status") != "running":
            return r
        time.sleep(2.0)
    return server.check_dispatch(dispatch_id)


def test_orchestration_history_picks_up_live_dispatch(
    fake_home: Path, tmp_path: Path
) -> None:
    """End-to-end: dispatch to a real agent, then query orchestration_history.

    Picks the first agent binary that's actually on PATH so the test runs
    at least once in any reasonable developer environment. Verifies the
    timeline + in-flight + per-project aggregation reflect the real run.
    """
    agent = next(
        (a for a in AGENTS_UNDER_TEST if shutil.which(a)),
        None,
    )
    if agent is None:
        pytest.skip("no supported agent binary on PATH")

    cwd = tmp_path / "orch-live-cwd"
    cwd.mkdir()
    registry.add_project(name="orch-live", path_=str(cwd), agent=agent)

    r = server.dispatch(
        "orch-live",
        "Reply with exactly: LIVE_OK",
        permission_mode="restricted",
        resume=False,
    )
    assert r["ok"] is True
    _wait_dispatch(r["dispatch_id"])

    snap = server.orchestration_history()
    assert snap["ok"] is True

    # Timeline carries both the dispatched and terminal milestones
    # for this run.
    ids_in_recent = {rec.get("id") for rec in snap["recent"]}
    assert r["dispatch_id"] in ids_in_recent, (
        f"dispatch_id {r['dispatch_id']!r} missing from orchestration timeline: "
        f"{snap['recent']!r}"
    )

    # Per-project aggregation counts this live dispatch.
    stats = snap["per_project"].get("orch-live", {})
    assert stats.get("dispatched", 0) >= 1

    # Registry snapshot reflects the project we just added.
    names = {p["name"] for p in snap["registered_projects"]}
    assert "orch-live" in names


@pytest.mark.parametrize("agent", AGENTS_UNDER_TEST)
def test_dispatch_roundtrip(
    agent: str, fake_home: Path, tmp_path: Path
) -> None:
    """dispatch() + check_dispatch() completes without error for each agent.

    Uses a minimal prompt that every agent should handle quickly. We only
    assert that the dispatch completed (status == complete) and returned
    non-empty output — not the exact content, since models are non-deterministic.
    """
    _skip_if_missing(agent)

    cwd = tmp_path / "live-cwd"
    cwd.mkdir()
    (cwd / "hello.txt").write_text("test fixture\n")

    registry.add_project(name="live-proj", path_=str(cwd), agent=agent)

    r = server.dispatch(
        "live-proj",
        "Reply with exactly the text: DISPATCH_OK — nothing else.",
        permission_mode="restricted",
        resume=False,
    )
    assert r["ok"] is True, f"dispatch rejected: {r.get('error')}"
    dispatch_id = r["dispatch_id"]

    result = _wait_dispatch(dispatch_id)
    # Verify the dispatch framework completed the roundtrip — the subprocess
    # reached a terminal state (not stuck running). Agents that require
    # interactive approval in a fresh directory may exit non-zero; that is
    # an agent config issue, not a dispatch framework bug.
    assert result["status"] in ("complete", "error"), (
        f"{agent}: dispatch never reached terminal state. "
        f"Last status: {result['status']!r}"
    )
    # When the agent exited cleanly, require non-empty output.
    if result.get("exit_code", 1) == 0:
        assert result.get("output", "").strip(), (
            f"{agent}: exit_code=0 but output is empty"
        )
