---
description: central-mcp가 노출하는 모든 MCP 도구 — list_projects, dispatch, check_dispatch, token_usage, 레지스트리 / 워크스페이스 변경 — 디폴트 동작과 파라미터 정리.
---

# MCP 도구

central-mcp가 orchestrator에 노출하는 MCP 도구 목록입니다. 정식 진실의 원천은 [`server.py`](https://github.com/andy5090/central-mcp/blob/main/src/central_mcp/server.py)이고, 이 페이지는 큐레이션된 레퍼런스입니다.

!!! note
    `server.py`에서 풀 시그니처와 docstring을 자동 추출하는 작업은 로드맵에 있습니다.

---

## 포트폴리오 조회

### `list_projects(workspace=None)`
디폴트로 활성 워크스페이스의 프로젝트만 보여줍니다. 다른 워크스페이스는 `workspace="<name>"`, 모든 워크스페이스를 가로지르려면 `workspace="__all__"` (alias `"*"`).

### `project_status(name)`
프로젝트 하나의 레지스트리 정보 — 에이전트, 경로, 워크스페이스 멤버십. `project_pulse`도 이 값들을 전부 담고 있으니, 메타데이터만 필요할 때 쓰세요. 파일 한 번 읽고 끝이라 subprocess를 띄우지 않습니다.

### `project_pulse(name, commits=5, history=5, include_pr=True)` (0.15.0+)
프로젝트에서 실제로 무슨 일이 있었고, 지금 어디에 있고, 뭐가 아직 돌고 있는지. 오래 비웠던 프로젝트로 복귀할 때, 또는 "X 상태 어때?"라는 질문에 씁니다.

`dispatch_history` / `orchestration_history`는 central-mcp를 *거쳐간* 작업만 압니다. pulse는 레포 자체를 읽으므로 직접 커밋, 인터랙티브 에이전트 세션, 수동 편집도 잡힙니다.

섹션:

- `git`: 브랜치, upstream `ahead` / `behind`, 워킹 트리 변경(staged / unstaged / untracked / conflicted 카운트 + 제한된 파일 샘플), 최근 `commits`개 커밋
- `dispatches`: `in_flight`, `stale`(몇 시간째 running으로 남은 행 — 서버가 죽어 종료 상태를 못 쓴 것이므로 진행 중이 아니라 미완료로 보고), 최근 `history`개 결과(프롬프트·출력 미리보기 포함), 전체 기간 카운트
- `sessions`: 어댑터가 열거할 수 있는 에이전트의 재개 가능한 대화
- `pull_requests`: `gh` 경유 열린 PR — 유일한 네트워크 호출이므로 여러 프로젝트를 훑을 땐 `include_pr=False`

각 섹션은 독립적으로 degrade하며 사용 불가 시 `reason`을 담습니다 — 섹션이 비었다고 "아무 일도 없었다"는 뜻이 아닙니다. 저장하는 상태는 없고 매 호출마다 원본에서 새로 계산합니다.

### `orchestration_history(workspace=None, include_archives=False)`
포트폴리오 전체 스냅샷: 진행 중 dispatch, 최근 milestone, 프로젝트별 카운트(dispatched / succeeded / failed / cancelled).

### `portfolio_digest(workspace=None, since_hours=24, quiet_days=7, include_quota=True)` (0.17.0+)
사전 렌더링된 포트폴리오 요약 — Portfolio PM 트랙의 푸시 리포트입니다. 구조화된 섹션들과 함께 `digest_markdown`을 반환하며, 호출자는 이를 **그대로** 전달합니다: 포맷이 서버 쪽에 고정돼 있어(`token_usage.summary_markdown`과 같은 이유), Hermes cron이 Telegram에 올리든, 일반 crontab이 `cmcp digest`를 notifier로 파이프하든, 터미널 orchestrator가 "전체 요약해줘"에 답하든 같은 리포트가 나옵니다.

pulse 기반이라 `orchestration_history`와 달리 central-mcp를 거치지 않은 작업도 셉니다. 섹션:

- `active` — 윈도우 안에 활동이 있는 프로젝트: 커밋(최신 제목 포함), dispatch ✅/❌ 카운트, 진행 중 개수, 미커밋 파일
- `warnings` — 윈도우 안의 실패한 dispatch, 몇 시간째 `running`에 갇힌 dispatch(진행 중이 아니라 미완료), `quiet_days`를 넘긴 조용한 프로젝트에 방치된 미커밋 작업
- `quiet` — 나머지 전부, 가장 오래 쉰 것부터
- `quota` — 에이전트별 구독 윈도우 압축 표시

일간은 `since_hours=24`, 주간은 `168`; `workspace`는 `list_projects`와 같은 의미. 아무것도 저장하지 않으며 — 스케줄과 알림 워터마크는 호출자의 몫입니다.

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

### `list_dispatches(status=None, since=None)`
진행 중 + 최근 완료된 dispatch 전체. 각 행에 `ok`, `finished_at` 포함 (0.17.0+).

- `status`: `running` / `complete` / `error` / `timeout` / `cancelled`, 또는 alias `failed` (나쁘게 끝난 전부; cancelled는 의도된 중단이라 제외)
- `since`: ISO 8601 — `finished_at`이 *엄격히* 이후인 것만; running 행은 항상 통과

이 둘이 무상태 failure watch를 지탱합니다: 상주 에이전트가 주기적으로 `list_dispatches(status="failed", since=<watermark>)`를 부르고, 돌아온 것을 알리고, 방금 본 최대 `finished_at`으로 워터마크를 전진시킵니다. 엄격 비교라 워터마크가 안 변하면 같은 실패를 재알림하지 않고 — 워터마크는 central-mcp가 아니라 구독자가 보관합니다.

### `dispatch_history(name, limit=20)`
프로젝트 한 곳의 최근 N개 dispatch (`prompt_preview`, `output_preview` 포함). `project_pulse`의 `dispatches` 섹션과 같은 로그를 읽지만 원하는 만큼 깊이 들어갑니다 — pulse는 git·세션 맥락과 함께 최근 몇 건만 의도적으로 보여줍니다. 브리핑은 pulse, 파고들 땐 이쪽.

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

---

## 실험 기능: MCP Tasks wire (0.13.0+)

서버 환경변수에 `CENTRAL_MCP_TASKS=1`을 설정하면 central-mcp가 MCP Tasks 프로토콜 — `tasks/get`, `tasks/cancel`, `tasks/result` — 을 추가로 서빙합니다. 위의 도구들과 정확히 같은 dispatch 상태를 공유하고, `taskId`는 `dispatch`가 반환하는 `dispatch_id` 그대로입니다. Tasks를 말하는 MCP 클라이언트라면 `check_dispatch` 대신 프로토콜 네이티브 폴링 라이프사이클로 dispatch를 구동할 수 있습니다.

- `tasks/get` — task 객체 반환 (`working` / `completed` / `failed` / `cancelled`, `pollInterval: 3000`)
- `tasks/result` — 종료 후 최종 출력 반환, 실행 중에는 에러
- `tasks/list` — 의도적으로 미제공 (2026-07-28 MCP 릴리즈에서 제거되는 메서드; `list_dispatches`로 충분)

`check_dispatch` / `cancel_dispatch`는 어느 쪽이든 그대로입니다 — 확장은 같은 상태 위의 추가 wire shape이지 대체가 아닙니다. 플래그를 끄면(기본값) 서버는 이전과 완전히 동일합니다. 방향성은 [로드맵의 MCP Tasks alignment 섹션](ROADMAP.md#mcp-tasks-alignment) 참고.
