# CLI 레퍼런스

`central-mcp`이 풀 네임이고, `cmcp`은 `central-mcp init`이 깔아주는 단축 alias입니다.

!!! note
    `--help` 텍스트 자동 추출은 로드맵에 있습니다. 그 전까지 이 페이지는 큐레이션된 개요입니다 — 정확한 최신 텍스트는 `central-mcp <서브커맨드> --help`로 확인하세요.

## 전체 형식

```text
central-mcp [SUBCOMMAND] [OPTIONS]
```

서브커맨드 없이 부르면 `central-mcp run`과 동일하게 동작합니다.

---

## orchestrator 띄우기

### `central-mcp run`
설정된 orchestrator(claude / codex / gemini / opencode 중 하나)를 띄웁니다. 매 launch마다 PyPI에 새 릴리스가 있는지 확인하고, 있으면 인터랙티브 픽커로 업그레이드 안내. 선호 orchestrator가 quota 임계를 넘으면 fallback 체인을 따라 다른 에이전트로 빠집니다.

### `central-mcp serve`
MCP stdio 서버로 동작합니다. MCP 클라이언트가 호출하는 진입점이라, 직접 부를 일은 거의 없습니다.

---

## 관찰 모드

### `central-mcp up [--workspace NAME] [--all] [--backend tmux|zellij]`
프로젝트마다 페인 하나씩 깔고(`cmcp watch <project>`), orchestrator는 옆에 두는 multiplexer 세션을 만듭니다.

### `central-mcp tmux` / `central-mcp zellij`
백엔드 직접 지정. 픽커를 건너뛰고 싶을 때.

### `central-mcp down`
관찰 세션 정리.

### `central-mcp watch <project>`
프로젝트 하나의 `dispatch.jsonl`을 사람이 읽기 좋은 포맷으로 tail 합니다 (ANSI 컬러, 코드 블록 감지, sticky 헤더).

### `central-mcp monitor`
curses 기반 포트폴리오 대시보드: 에이전트별 quota 바, 프로젝트별 dispatch 통계.

---

## 레지스트리

### `central-mcp list [--workspace NAME]`
등록된 프로젝트 목록.

### `central-mcp brief`
포트폴리오 한눈에 보기 (curses 안 씁니다, 단순 텍스트).

### `central-mcp add <name> <path> [--agent AGENT] [--workspace NAME]`
프로젝트 등록.

### `central-mcp remove <name>`
프로젝트 등록 해제.

### `central-mcp reorder <name>...`
프로젝트 순서 재배치 (`cmcp up`의 페인 순서에 영향).

---

## 워크스페이스

### `central-mcp workspace list`
워크스페이스와 각 프로젝트 카운트.

### `central-mcp workspace current`
활성 워크스페이스 이름 출력.

### `central-mcp workspace new <name>`
빈 워크스페이스 생성.

### `central-mcp workspace use [NAME]`
활성 워크스페이스 전환. `NAME` 빼면 화살표 키 픽커.

### `central-mcp workspace add <project> <workspace>`
프로젝트를 워크스페이스에 넣기.

### `central-mcp workspace remove <project> <workspace>`
워크스페이스에서 빼기.

---

## MCP 클라이언트 셋업

### `central-mcp install <client>`
central-mcp를 클라이언트의 MCP 서버로 등록합니다. 선택지: `claude`, `codex`, `gemini`, `opencode`, `all`.

### `central-mcp alias [name]`
`cmcp` 단축 alias 출력 / 생성.

### `central-mcp unalias`
alias 제거.

---

## 유지보수

### `central-mcp init [--force]`
첫 셋업: `~/.central-mcp/` 만들고, `cmcp` alias 잡고, 감지된 MCP 클라이언트에 자동 등록.

### `central-mcp upgrade`
PyPI 최신 릴리스로 업그레이드.
