# 워크스페이스

워크스페이스는 등록된 프로젝트의 명명된 부분집합입니다. 이런 식으로 활용:

- 클라이언트 분리 (`client-a`, `client-b`, …) — 한 클라이언트 안에서 `list_projects` 했을 때 다른 클라이언트의 프로젝트가 같이 떠다니지 않도록.
- 한 프롬프트를 그룹 전체에 fan-out (`dispatch("@frontend", "README 정리해줘")`).
- 여러 터미널에서 `cmcp` 인스턴스를 동시에 띄우되, 각자 다른 워크스페이스에 묶기.
- 토큰 사용량과 quota 뷰를 단일 프로젝트가 아니라 그룹 단위로 슬라이싱.

설치 직후엔 `default`라는 워크스페이스 하나만 있고, 등록한 모든 프로젝트가 거기 들어갑니다.

---

## 빠른 예시

```bash
# 워크스페이스 하나 만들고 프로젝트 추가
cmcp workspace new client-a
cmcp workspace add my-app    --workspace client-a
cmcp workspace add api-server --workspace client-a

# 저장된 디폴트를 client-a로 전환 (새 셸에 적용)
cmcp workspace use client-a

# orchestrator 세션이 client-a 스코프로 잡힌 상태라면, 이 fan-out은
# 워크스페이스의 모든 프로젝트로 한 번에 dispatch 됩니다
"내 프로젝트 전부에 같은 프롬프트 보내줘: README 정리."
```

---

## 데이터는 어디 사는가

| 파일 | 역할 |
|---|---|
| `~/.central-mcp/registry.yaml` | `projects:` 리스트 + `workspaces:` 맵 (`{이름: [프로젝트, …]}`). |
| `~/.central-mcp/config.toml` | `[user].current_workspace` — 저장된 디폴트 워크스페이스. |

같은 프로젝트가 여러 워크스페이스에 들어갈 수 있습니다 — central-mcp이 mutual exclusion을 강제하지 않거든요. 어느 워크스페이스에도 명시적으로 안 넣은 프로젝트는 `default`에 머뭅니다.

---

## CLI

워크스페이스 명령은 모두 `cmcp workspace` 아래:

```bash
cmcp workspace list              # 워크스페이스 + 프로젝트 카운트 보기
cmcp workspace current           # 현재 활성 워크스페이스 이름 출력
cmcp workspace new <name>        # 빈 워크스페이스 생성
cmcp workspace use [<name>]      # 활성 워크스페이스 전환 (이름 생략 시 픽커)
cmcp workspace add <project> --workspace <name>      # 프로젝트 할당
cmcp workspace remove <project> --workspace <name>   # 할당 해제
```

`cmcp workspace use`를 인자 없이 부르면 화살표 키 픽커가 뜹니다 — 워크스페이스마다 프로젝트 카운트와 활성 워크스페이스에는 `[current]` 마커가 표시됩니다.

`cmcp workspace use <name>`은 `config.toml`에 기록되어 **영속적**입니다 — 이 머신의 모든 새 셸이 그 값을 상속합니다. 일회성 오버라이드(셸 하나에만, config 파일에 쓰지 않음)가 필요하면 `cmcp run --workspace <name>`을 쓰거나 그 셸의 환경 변수에 `CMCP_WORKSPACE`를 export 하세요 (아래 *동시 워크스페이스* 섹션 참고).

---

## orchestrator를 워크스페이스에 묶기

### 디폴트 동작 (단일 워크스페이스, 저장)

```bash
cmcp                # config.toml [user].current_workspace 사용
```

orchestrator가 인자 없이 `list_projects()`를 호출하면 그 워크스페이스의 프로젝트만 봅니다. dispatch fan-out (`@workspace`)도 같은 스코프를 타겟합니다.

### 일회성 오버라이드 (이 터미널만)

```bash
cmcp run --workspace client-a
```

띄운 orchestrator의 환경에 `CMCP_WORKSPACE=client-a`를 셋합니다. MCP 서버 자식 프로세스도 stdio 통해 상속받고요. `config.toml`의 저장된 디폴트는 **건드리지 않습니다** — 그래서 다른 터미널을 열어 `cmcp`를 실행하면 여전히 저장된 디폴트를 따릅니다.

### 동시 워크스페이스 (여러 터미널)

```bash
# 터미널 1 — Claude Code on client-a
cmcp run --workspace client-a

# 터미널 2 — 동시에 Codex on client-b
cmcp run --workspace client-b
```

각 인스턴스는 `list_projects`, dispatch fan-out, `token_usage(workspace=…)` 측면에서 완전히 격리됩니다. `tokens.db`, `dispatches.db`, `registry.yaml`은 공유하지만(워크스페이스 스코프 read, 모두 multi-process 안전) 각자 자기 영역만 보게 됩니다.

매 명령마다 `--workspace` 다는 게 번거로우면 셸별로 `export CMCP_WORKSPACE=client-a` 한 번만 해두면 됩니다.

### `current_workspace()` 해석 순서

1. `CMCP_WORKSPACE` 환경 변수 (per-process)
2. `config.toml [user].current_workspace` (저장된 디폴트)
3. 리터럴 `default`

---

## orchestrator 안에서 MCP 도구 동작

orchestrator 세션이 워크스페이스에 묶이면, `workspace` 파라미터를 받는 모든 도구의 디폴트가 활성 워크스페이스로 잡힙니다:

| 도구 | 디폴트 동작 |
|---|---|
| `list_projects()` | 활성 워크스페이스의 프로젝트만 반환. |
| `list_projects(workspace="__all__")` | 모든 워크스페이스의 모든 프로젝트. |
| `orchestration_history()` | 활성 워크스페이스로 필터링. |
| `token_usage()` | 활성 워크스페이스 기준 집계. |
| `dispatch("@workspace", prompt)` | *이름 명시한* 워크스페이스의 모든 프로젝트로 fan-out (활성 워크스페이스 자동 X — `@<이름>`은 명시적). |
| `dispatch("project-name", prompt)` | 단일 프로젝트; 워크스페이스 스코프 영향 받지 않음. |

`@workspace` 해석: 한 이름이 프로젝트와 워크스페이스 양쪽에 매칭되면 프로젝트가 이깁니다. 워크스페이스로 강제하려면 `@<이름>` 형식.

---

## 관찰 페인

`cmcp up`, `cmcp tmux`, `cmcp zellij`도 워크스페이스를 존중합니다:

```bash
cmcp tmux --workspace client-a    # cmcp-client-a 세션, client-a 프로젝트만
cmcp tmux --all                   # 워크스페이스마다 cmcp-<workspace> 세션 하나씩
cmcp tmux switch <workspace>      # 현재 세션에서 detach, 다른 워크스페이스 세션에 attach
```

`cmcp tmux/zellij`에 `--workspace`를 명시하면, orchestrator 페인의 launch 명령에 `CMCP_WORKSPACE=<name>`이 주입됩니다 — 그래서 orchestrator는 `cmcp tmux`를 실행한 셸의 환경과 무관하게 올바른 스코프를 봅니다.

cmux도 레이아웃 레벨에서 같은 방식: 에이전트 주도 셋업([관찰 모드](../observation.md) 참고)이 활성 워크스페이스가 가진 프로젝트마다 페인 하나를 깔아줍니다.

---

## 워크스페이스 단위 토큰 사용량

```python
# orchestrator 안에서
token_usage(period="week", workspace="client-a")
# → breakdown은 client-a 프로젝트로만 한정
# → quota 스냅샷은 글로벌 (구독은 계정별이지 워크스페이스별이 아님)
```

응답의 `summary_markdown` 필드도 같은 워크스페이스 스코프로 렌더됩니다.

---

## 워크스페이스가 *아닌 것*

- **격리된 레지스트리 X.** 모든 워크스페이스는 같은 `registry.yaml`에 삽니다. 워크스페이스 삭제는 그 안의 프로젝트를 지우지 않고, `default` 소유로 떨어집니다.
- **별도 토큰 / dispatch DB X.** `tokens.db`와 `dispatches.db`는 글로벌; 워크스페이스 필터링은 read 시점에 레지스트리 조회로 처리됩니다.
- **접근 제어 X.** `~/.central-mcp/`에 셸 접근 가능한 사람은 모든 워크스페이스를 볼 수 있습니다. 더 강한 분리가 필요하면 OS 레벨 권한을 쓰세요.
- **프로젝트 경로 자동 추론 X.** 멤버십은 명시적 — `cmcp workspace add`만이 프로젝트를 워크스페이스에 넣는 방법입니다.
