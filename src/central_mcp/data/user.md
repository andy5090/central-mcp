# User preferences — central-mcp

This file is yours. Edit it to shape how the dispatch router behaves
in every session. The orchestrator reads it at startup and applies your
preferences on top of the shared defaults in AGENTS.md / CLAUDE.md.

Your settings here win over router defaults, but they do not override
developer constraints or system-level instructions. Your current-turn
instructions still take the highest priority.

---

## Reporting style

<!-- Examples — uncomment and edit what you want:

- Always summarize dispatch results in bullet points.
- Use Korean for all responses ("한국어로 답변해줘").
- Show elapsed time and token usage when reporting dispatch results.
- Keep responses under 5 sentences unless I ask for detail.

-->

## Routing hints

<!-- Examples:

- Prefer claude for any task involving architecture decisions.
- Use codex for shell-scripting tasks.
- Always dispatch UI work to the `my-frontend` project.

-->

## Process management rules

<!-- Examples:

- Never dispatch two tasks to the same project simultaneously.
- Ask before dispatching to more than 3 projects at once.

-->

## Other preferences

<!-- Anything else that affects how the router should behave. -->
