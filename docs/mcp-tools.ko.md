# MCP 도구

central-mcp이 orchestrator에 노출하는 MCP 도구 목록입니다. 정식 진실의 원천은 [`server.py`](https://github.com/andy5090/central-mcp/blob/main/src/central_mcp/server.py)이고, 이 페이지는 큐레이션된 레퍼런스입니다.

!!! note
    `server.py`에서 풀 시그니처와 docstring을 자동 추출하는 작업은 로드맵에 있습니다.

---

## 포트폴리오 조회

### `list_projects(workspace=None)`
디폴트로 활성 워크스페이스의 프로젝트만 보여줍니다. 다른 워크스페이스는 `workspace="<name>"`, 모든 워크스페이스를 가로지르려면 `workspace="__all__"` (alias `"*"`).

### `project_status(name)`
프로젝트 하나의 레지스트리 정보 — 에이전트, 경로, 워크스페이스 멤버십.

### `orchestration_history(workspace=None, include_archives=False)`
포트폴리오 전체 스냅샷: 진행 중 dispatch, 최근 milestone, 프로젝트별 카운트(dispatched / succeeded / failed / cancelled).

### `token_usage(period="today", project=None, workspace=None, group_by="project", include_quota=True, include_summary=True)`
토큰 집계.

- `period`: `today` / `week` / `month` / `all`
- `group_by`: `project` / `agent` / `source`
- `include_quota` (디폴트 True): 에이전트별 구독 quota 윈도우 포함
- `include_summary` (디폴트 True): 채팅 응답에 그대로 붙여넣을 수 있는 사전 렌더링된 HUD 마크다운 (`summary_markdown`)

---

## Dispatch 라이프사이클

### `dispatch(name, prompt, agent=None, model=None, ...)`
프로젝트의 작업 디렉터리에서 일회성 에이전트 실행. **Non-blocking** — 100ms 안에 `dispatch_id`를 돌려줍니다.

`name="@workspace"` 형식으로 부르면 그 워크스페이스의 모든 프로젝트로 한 번에 fan-out 됩니다 (리스트로 `dispatch_id`들 반환).

### `check_dispatch(dispatch_id)`
dispatch 상태 폴링: `running` / `complete` / `error` / `cancelled`. 완료된 경우 풀 출력까지 같이 반환.

### `cancel_dispatch(dispatch_id)`
진행 중 dispatch 중단.

### `list_dispatches()`
진행 중 + 최근 완료된 dispatch 전체.

### `dispatch_history(name, limit=20)`
프로젝트 한 곳의 최근 N개 dispatch (`prompt_preview`, `output_preview` 포함).

---

## 레지스트리 변경

### `add_project(name, path, agent=None, workspace=None, ...)`
프로젝트 등록. `workspace`를 같이 넘기면 그 워크스페이스에 들어갑니다 (없으면 자동 생성).

### `remove_project(name)`
프로젝트 등록 해제.

### `update_project(name, **fields)`
재등록 없이 레지스트리 필드만 수정.

### `reorder_projects(order)`
프로젝트 순서 재배치 — `cmcp up`의 페인 등장 순서에 반영됩니다.

---

## 세션 (지원되는 경우)

### `list_project_sessions(name)`
에이전트 측 대화 세션 목록. 현재 Claude Code와 Codex에서 지원합니다.

---

## 사용자 환경설정

### `get_user_preferences()`
`~/.central-mcp/user.md` 콘텐츠와 prompt 작성용 scaffold 예시 읽기.

### `update_user_preferences(content)`
`~/.central-mcp/user.md` 덮어쓰기.

---

## orchestrator는 이걸 어떻게 쓰라고 안내받나

런타임 가이드는 [`src/central_mcp/data/AGENTS.md`](https://github.com/andy5090/central-mcp/blob/main/src/central_mcp/data/AGENTS.md)에 있고, 첫 launch 시 `~/.central-mcp/AGENTS.md`로 함께 깔립니다. MCP 서버도 `instructions` payload에 압축 요약을 주입하니까 — MCP 클라이언트 쪽도 같은 가이드를 봅니다.
