# 워크스페이스

워크스페이스는 등록된 프로젝트 중 일부를 묶어서 이름을 붙인 부분집합입니다. 이런 식으로 씁니다.

- 클라이언트별로 분리합니다 (`client-a`, `client-b`, …). 한쪽 작업 중에 `list_projects` 했을 때 다른 쪽 프로젝트가 같이 떠다니지 않습니다.
- 한 프롬프트를 그룹 전체에 한 번에 보냅니다 (`dispatch("@frontend", "README 정리해줘")`).
- 여러 터미널에서 `cmcp`을 동시에 띄우되, 각 터미널을 다른 워크스페이스에 묶을 수 있습니다.
- 토큰 사용량과 quota 뷰를 단일 프로젝트가 아니라 그룹 단위로 봅니다.

처음 설치하면 `default`라는 워크스페이스가 하나 있고, 등록한 모든 프로젝트가 거기 들어가 있습니다. 따로 안 만들어도 됩니다.

---

## 자연어로 다루기

orchestrator 안에서 평소 말하듯 던져도 대부분 동작합니다.

> *"`~/Projects/my-app`을 client-a 워크스페이스에 추가해줘. 에이전트는 claude로."*

orchestrator는 `add_project(name="my-app", path="...", agent="claude", workspace="client-a")`로 풀어 호출합니다. `client-a`가 아직 없으면 같이 만들어지고요.

다른 자주 쓰는 패턴들:

> *"client-a 워크스페이스에 어떤 프로젝트들이 있어?"*
> → `list_projects(workspace="client-a")`

> *"내 워크스페이스 전부 보여줘."*
> → `list_projects(workspace="__all__")`

> *"client-a 프로젝트 전부에 같은 프롬프트 보내줘: README 정리."*
> → `dispatch("@client-a", "README 정리")` — 모든 멤버 프로젝트로 fan-out

> *"client-a가 이번 주에 토큰 얼마나 썼어?"*
> → `token_usage(period="week", workspace="client-a")`

새 빈 워크스페이스를 만들거나 활성 워크스페이스를 바꾸는 건 CLI가 더 빠릅니다.

```bash
cmcp workspace new client-a       # 빈 워크스페이스 생성
cmcp workspace use                # 인터랙티브 픽커로 전환
```

---

## 데이터는 어디 있나

| 파일 | 역할 |
|---|---|
| `~/.central-mcp/registry.yaml` | `projects:` 리스트와 `workspaces:` 맵 (`{이름: [프로젝트, …]}`) |
| `~/.central-mcp/config.toml` | `[user].last_workspace` — `cmcp workspace use`로 가장 최근에 고른 워크스페이스. `CMCP_WORKSPACE` 환경 변수가 없을 때의 디폴트입니다. |

같은 프로젝트가 여러 워크스페이스에 들어가도 됩니다. 어디에도 명시적으로 안 넣은 프로젝트는 `default`에 머뭅니다.

---

## CLI로 다루기

자주 쓰는 형태:

```bash
cmcp workspace list                                  # 워크스페이스 + 프로젝트 카운트
cmcp workspace current                               # 활성 워크스페이스 이름
cmcp workspace new <name>                            # 빈 워크스페이스 생성
cmcp workspace use [<name>]                          # 활성 전환 (이름 빼면 픽커)
cmcp workspace add <project> --workspace <name>      # 기존 프로젝트를 그룹에 넣기
cmcp workspace remove <project> --workspace <name>   # 그룹에서 빼기
```

`cmcp workspace use`를 인자 없이 부르면 화살표 키 픽커가 떠서, 워크스페이스마다 프로젝트 카운트와 활성 워크스페이스 옆에 `[current]` 마커가 표시됩니다.

`cmcp workspace use <name>`은 `config.toml`에 저장됩니다. 이 머신의 새 셸은 모두 그 값을 따라갑니다. 한 셸에서만 다른 워크스페이스를 쓰고 싶으면 `cmcp run --workspace <name>`이나 환경 변수 `CMCP_WORKSPACE`로 처리하세요 (아래 *동시에 여러 워크스페이스* 참고).

---

## orchestrator를 워크스페이스에 묶기

### 보통 (한 워크스페이스, 저장된 디폴트)

```bash
cmcp                # config.toml [user].last_workspace 사용
```

이 상태에서 orchestrator가 `list_projects()`를 인자 없이 부르면 그 워크스페이스 프로젝트만 봅니다. dispatch fan-out (`@workspace`) 도 같은 스코프를 탑니다.

### 한 번만 다른 워크스페이스로 (이 터미널만)

```bash
cmcp run --workspace client-a
```

띄운 orchestrator 환경에 `CMCP_WORKSPACE=client-a`를 셋합니다. MCP 서버 자식 프로세스도 stdio로 상속받습니다. `config.toml`은 안 건드리니까, 다른 터미널에서 `cmcp`을 띄우면 거기는 여전히 저장된 디폴트를 씁니다.

### 동시에 여러 워크스페이스 (여러 터미널)

```bash
# 터미널 1 — Claude Code on client-a
cmcp run --workspace client-a

# 터미널 2 — 같은 시간에 Codex on client-b
cmcp run --workspace client-b
```

두 인스턴스는 `list_projects`, dispatch fan-out, `token_usage(workspace=…)` 모두 격리됩니다. 디스크의 `tokens.db`, `dispatches.db`, `registry.yaml`은 공유하지만 워크스페이스 스코프로 읽으니까 서로 끼어들지 않습니다 (multi-process 안전).

명령마다 `--workspace` 다는 게 번거로우면 셸에서 한 번만 `export CMCP_WORKSPACE=client-a` 해두면 됩니다.

### `current_workspace()` 해석 순서

1. `CMCP_WORKSPACE` 환경 변수 (per-process)
2. `config.toml [user].last_workspace` (저장된 디폴트)
3. 리터럴 `default`

---

## orchestrator 안에서 도구 동작이 어떻게 바뀌나

orchestrator 세션이 워크스페이스에 묶이면, `workspace` 파라미터를 받는 도구는 디폴트로 활성 워크스페이스를 봅니다.

| 도구 | 디폴트 동작 |
|---|---|
| `list_projects()` | 활성 워크스페이스 프로젝트만 |
| `list_projects(workspace="__all__")` | 모든 워크스페이스의 모든 프로젝트 |
| `orchestration_history()` | 활성 워크스페이스로 필터 |
| `token_usage()` | 활성 워크스페이스 기준 집계 |
| `dispatch("@workspace", prompt)` | *이름으로 지정한* 워크스페이스에 fan-out (활성과 자동 같지 않음 — `@<이름>`은 명시적) |
| `dispatch("project-name", prompt)` | 단일 프로젝트; 워크스페이스 스코프와 무관 |

`@workspace` 해석: 한 이름이 프로젝트와 워크스페이스 양쪽에 매칭되면 프로젝트가 이깁니다. 명시적으로 워크스페이스를 가리키려면 `@<이름>`.

---

## 관찰 페인

`cmcp up`, `cmcp tmux`, `cmcp zellij`도 워크스페이스를 따라갑니다.

```bash
cmcp tmux --workspace client-a    # cmcp-client-a 세션, client-a 프로젝트만
cmcp tmux --all                   # 워크스페이스마다 세션 하나씩
cmcp tmux switch <workspace>      # 현재 세션에서 빠지고 다른 워크스페이스 세션에 붙기
```

`cmcp tmux/zellij`에 `--workspace`를 명시하면, orchestrator 페인의 launch 명령에 `CMCP_WORKSPACE=<name>`이 같이 들어갑니다. `cmcp tmux`을 실행한 셸의 환경과 무관하게 orchestrator는 정확한 스코프를 봅니다.

cmux도 레이아웃 단계에서 같은 식으로 동작합니다 — 에이전트 주도 셋업([관찰 모드](../observation.md))이 활성 워크스페이스의 프로젝트마다 페인 하나씩 깔아줍니다.

---

## 워크스페이스 단위 토큰 사용량

```python
# orchestrator 안에서
token_usage(period="week", workspace="client-a")
# → breakdown은 client-a 프로젝트로 한정
# → quota 스냅샷은 글로벌 (구독은 계정별이지 워크스페이스별이 아닙니다)
```

응답의 `summary_markdown` 필드도 같은 스코프로 렌더됩니다.

---

## 워크스페이스가 아닌 것

- **격리된 레지스트리가 아닙니다.** 모든 워크스페이스가 같은 `registry.yaml`을 씁니다. 워크스페이스를 지운다고 안의 프로젝트가 사라지지 않습니다 — `default` 소유로 떨어집니다.
- **별도 토큰 / dispatch DB가 아닙니다.** `tokens.db`와 `dispatches.db`는 글로벌입니다. 워크스페이스 필터링은 read 시점에 레지스트리 조회로만 처리됩니다.
- **접근 제어가 아닙니다.** `~/.central-mcp/`에 셸 접근이 가능한 사람은 모든 워크스페이스를 봅니다. 더 단단한 분리가 필요하면 OS 레벨 권한을 쓰세요.
- **프로젝트 경로에서 자동 추론하지 않습니다.** 멤버십은 명시적입니다 — `cmcp workspace add` 또는 `add_project --workspace`만이 워크스페이스에 프로젝트를 넣는 방법입니다.
