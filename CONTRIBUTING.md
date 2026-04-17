# Contributing to central-mcp

## Setup

```bash
git clone https://github.com/andy5090/central-mcp.git
cd central-mcp
uv tool install --editable .
```

## Running tests

```bash
uv run --group dev pytest             # 100+ unit tests (fast, no real CLIs)
uv run --group dev pytest -m live     # live tests — requires agent binaries on PATH
```

## Making changes

- Keep changes focused — one feature or fix per PR
- Add tests for new behavior
- If adding a new agent adapter, add it to `test_adapters.py` and `test_adapters_live.py`
- Run the full unit test suite before opening a PR

## Adding a new agent adapter

1. Add a `_AgentName(Adapter)` class in `src/central_mcp/adapters/base.py`
2. Register it in `_ADAPTERS` and `VALID_AGENTS`
3. Add tests to `tests/test_adapters.py`
4. Add to `AGENTS_UNDER_TEST` in `tests/test_adapters_live.py`
5. If it supports MCP as an orchestrator, add `_install_agentname()` in `src/central_mcp/install.py`
6. Update README.md and README_KO.md supported agents table

## Reporting issues

Use [GitHub Issues](https://github.com/andy5090/central-mcp/issues). For bugs, include:

- Output of `central-mcp --help`
- The command you ran
- What you expected vs. what happened
