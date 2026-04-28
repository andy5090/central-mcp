# CLI 레퍼런스

`central-mcp`이 풀 네임, `cmcp`은 `central-mcp init`이 만들어주는 단축 alias.

!!! note
    `--help` 텍스트 자동 추출은 로드맵에 있습니다. 그 전까지 이 페이지는 큐레이션된 개요 — 정확한 최신 텍스트는 `central-mcp <서브커맨드> --help`로 확인하세요.

## Top-level

```text
central-mcp [SUBCOMMAND] [OPTIONS]
```

서브커맨드 없이 호출하면 `central-mcp run`과 동일.

---

## orchestrator 띄우기

### `central-mcp run`
설정된 orchestrator (claude / codex / gemini / opencode) 띄우기. launch마다 PyPI에서 새 릴리스 probe하고 인터랙티브 업그레이드 픽커 제공. 선호 orchestrator가 quota 임계 넘으면 fallback 체인을 따라갑니다.

### `central-mcp serve`
MCP stdio 서버로 동작. MCP 클라이언트가 호출하는 진입점 — 직접 부를 일은 거의 없습니다.

---

## 관찰 레이어

### `central-mcp up [--workspace NAME] [--all] [--backend tmux|zellij]`
프로젝트마다 페인 하나(`cmcp watch <project>`) + orchestrator를 옆에 두는 multiplexer 세션 생성.

### `central-mcp tmux` / `central-mcp zellij`
백엔드 직접 지정. 픽커 스킵하고 싶을 때.

### `central-mcp down`
관찰 세션 정리.

### `central-mcp watch <project>`
프로젝트의 `dispatch.jsonl`을 휴먼 친화 포맷으로 tail (ANSI 컬러, 코드 블록 감지, sticky 헤더).

### `central-mcp monitor`
curses 포트폴리오 대시보드: 에이전트별 quota 바, 프로젝트별 dispatch stats.

---

## 레지스트리

### `central-mcp list [--workspace NAME]`
등록된 프로젝트 목록.

### `central-mcp brief`
일회성 텍스트 포트폴리오 개요 (curses 안 씀).

### `central-mcp add <name> <path> [--agent AGENT] [--workspace NAME]`
프로젝트 등록.

### `central-mcp remove <name>`
프로젝트 등록 해제.

### `central-mcp reorder <name>...`
프로젝트 순서 재배치 (`cmcp up` 페인 레이아웃 순서에 영향).

---

## 워크스페이스

### `central-mcp workspace list`
워크스페이스 + 프로젝트 카운트 보기.

### `central-mcp workspace current`
활성 워크스페이스 이름 출력.

### `central-mcp workspace new <name>`
새 워크스페이스 생성.

### `central-mcp workspace use [NAME]`
활성 워크스페이스 전환. `NAME` 생략 시 화살표 키 픽커.

### `central-mcp workspace add <project> <workspace>`
프로젝트를 워크스페이스에 할당.

### `central-mcp workspace remove <project> <workspace>`
할당 해제.

---

## MCP 클라이언트 셋업

### `central-mcp install <client>`
central-mcp을 클라이언트의 MCP 서버로 등록. 선택지: `claude`, `codex`, `gemini`, `opencode`, `all`.

### `central-mcp alias [name]`
`cmcp` 단축 alias 출력 또는 생성.

### `central-mcp unalias`
alias 제거.

---

## 유지보수

### `central-mcp init [--force]`
일회성 셋업: `~/.central-mcp/` 스캐폴드, `cmcp` alias, 감지된 MCP 클라이언트에 자동 등록.

### `central-mcp upgrade`
PyPI 최신 릴리스로 업그레이드.
