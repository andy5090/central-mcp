# Gemini CLI session transcript storage

Research pass for Option B (`harvest_session(session_id) -> canonical
jsonl`). Investigated against `gemini` v0.38.2 on macOS, observing
real session data under `~/.gemini/`.

## 1. Storage location

Per-session JSON files are at:

```
~/.gemini/tmp/<project-slug>/chats/session-<YYYY-MM-DDTHH-MM>-<sessionId-prefix>.json
```

Each project slug also contains:

```
~/.gemini/tmp/<project-slug>/.project_root      # resolved cwd path (sanity marker)
~/.gemini/tmp/<project-slug>/logs.json          # USER-ONLY prompt log (not a transcript)
~/.gemini/tmp/<project-slug>/chats/             # the real session files
~/.gemini/history/<project-slug>/.project_root  # mirror dir (mostly empty in practice)
```

Slug ↔ cwd resolution lives in `~/.gemini/projects.json`:

```json
{ "projects": { "/Users/<user>/Projects/my-app": "my-app", ... } }
```

Sessions *also* carry a `projectHash` (sha256 hex) inside each session
JSON. That hash — not the slug — is what `--list-sessions` /
`--resume` filter on, so files for a project can exist on disk yet be
invisible to the CLI from another cwd.

## 2. Format / schema

Each session is a **single JSON object** (NOT JSONL). Top-level:

```json
{
  "sessionId": "<uuid>",
  "projectHash": "<sha256-hex>",
  "startTime": "<ISO8601>",
  "lastUpdated": "<ISO8601>",
  "messages": [ ... ],
  "kind": "main"
}
```

`messages[]` entries share a common envelope `{id, timestamp, type,
content, ...}` where `type` is one of `user`, `gemini`, `info`,
`error`. User turns put their content in `[{text: "..."}]` (list
wrapper); assistant (`gemini`) turns put it in a bare string plus
optional extras:

```json
{
  "id": "<uuid>",
  "timestamp": "<ISO8601>",
  "type": "gemini",
  "content": "<assistant text, may be empty when tool-only>",
  "thoughts": [
    { "subject": "...", "description": "...", "timestamp": "..." }
  ],
  "toolCalls": [
    {
      "id": "<tool-call-id>",
      "name": "<tool>",
      "args": { ... },
      "result": [{
        "functionResponse": {
          "id": "...", "name": "...", "response": { ... }
        }
      }],
      "status": "success" | "cancelled" | ...,
      "timestamp": "...",
      "description": "<json-encoded args>",
      "displayName": "<human label>"
    }
  ],
  "tokens": { "input", "output", "cached", "thoughts", "tool", "total" },
  "model": "gemini-3-flash-preview"
}
```

User messages occasionally include a `displayContent` field — the
cosmetic form (e.g. `/generate "..."`) while `content` holds the
expanded system prompt the model actually saw.

Mapping to canonical `{ts, role, text, tool_name?, tool_args?,
tool_result?}` is direct:

| gemini `type`                                | canonical emission |
|----------------------------------------------|--------------------|
| `user`                                       | one `role=user` turn, `text = content[0].text` |
| `gemini` (no tool calls)                     | one `role=assistant` turn, `text = content` |
| `gemini` with `toolCalls[]`                  | assistant turn (if `content`), then for each call: `{role=tool_use, tool_name, tool_args}` + `{role=tool_result, tool_name, tool_result}` from `result[0].functionResponse.response` |
| `info` / `error`                             | skip or emit as `role=system` (CLI chrome: update notices, discovery errors, "Request cancelled") |

## 3. CLI surface

`gemini --help` exposes exactly three session verbs: `--list-sessions`,
`--resume <n|latest>`, `--delete-session <n>`. The subcommand tree
(`gemini mcp|skills|extensions|hooks`) is unrelated to sessions —
nothing like `gemini session show` or `--export` exists. Harvesting
must go direct to the JSON on disk.

## 4. Gotchas

- **Auto-pruning**. Running `--list-sessions` from a cwd whose
  `projectHash` no longer matches existing files appears to trigger
  cleanup — observed during this research: one slug's
  `~/.gemini/tmp/<slug>/chats/` went from 4 populated files to empty
  mid-session after a single `--list-sessions` probe from the real
  cwd. Harvest opportunistically; assume files may vanish.
- **`logs.json` is NOT a transcript.** It's a per-project array of
  user-only entries `{sessionId, messageId, type:"user", message,
  timestamp}`. Useful as an index-of-user-intent, useless as a
  replay source.
- **`projectHash`, not slug, is authoritative.** The slug is just a
  filesystem-friendly dir name; the CLI only surfaces sessions whose
  `projectHash` matches the current cwd's hash. So `--list-sessions`
  underreports reality.
- **`.project_root` can carry a doubled path** (observed: the absolute
  cwd appearing twice in a row inside a single slug's `.project_root`
  file — i.e., `/Users/<user>/Projects/<name>/Users/<user>/Projects/<name>`).
  Treat as informational, don't parse-and-trust.
- **`kind: "main"`** is the only value seen; subagent / alternate
  kinds may appear and should be filtered if present.
- No encryption, no binary blobs, no rotation — files just grow
  until the pruning heuristic fires.

## 5. Recommendation

Direct file read, no shell-out. Implementation sketch:

```python
def harvest_gemini_session(session_id: str, cwd: str | Path) -> list[dict]:
    # 1. Resolve cwd → slug via ~/.gemini/projects.json (fallback: scan all slugs).
    # 2. Glob ~/.gemini/tmp/<slug>/chats/session-*.json; also glob
    #    ~/.gemini/tmp/*/chats/session-*.json as a belt-and-suspenders
    #    pass because `--list-sessions` ≠ on-disk reality.
    # 3. Parse each candidate's top-level `sessionId`; match by full id
    #    OR by `session_id` being a short prefix (the CLI's index-N
    #    form isn't stable, so callers should already pass the uuid).
    # 4. Iterate `messages[]`, emit canonical turns via the mapping
    #    table in §2. Drop `info`/`error` types by default; surface
    #    them only when caller asks for raw trace.
    ...
```

The CLI provides no read-side primitive to wrap, so there's nothing
to wait for on the upstream side — reading the JSON is the cheapest,
most faithful path. Parsing `--list-sessions` output stays relevant
only for *enumerating* sessions (matching the existing
`_Gemini.list_sessions` behavior in `adapters/base.py`); harvesting
the transcript should bypass the CLI entirely.
