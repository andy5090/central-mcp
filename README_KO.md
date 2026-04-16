# central-mcp

**여러 코딩 에이전트를 하나의 허브에서 디스패치하는, 오케스트레이터 비종속 MCP 서버.**

하나의 MCP 서버로 어떤 MCP 클라이언트(Claude Code, Codex CLI, Cursor, Gemini CLI 등)든 여러 코딩 에이전트 프로젝트의 컨트롤 플레인이 됩니다. 자연어로 요청하면 오케스트레이터가 해당 프로젝트의 에이전트에게 작업을 보내고, 논블로킹으로 결과를 비동기 보고합니다.

## 왜 필요한가

여러 코딩 에이전트를 쓰고 있다면, 각각 별도의 터미널·세션·로그를 갖고 있을 것입니다. 사이를 오가는 건 마찰이고, *어디서 뭐가 응답했는지* 한눈에 보이지 않습니다.

`central-mcp`는 하나의 허브를 제공합니다:

- **디스패치** — 프로젝트별 에이전트에 프롬프트를 보내고 MCP를 통해 응답 수신
- **병렬 작업** — 여러 프로젝트에 동시 디스패치하고 대화를 계속
- **관리** — `add_project` / `remove_project`로 레지스트리 편집
- **오케스트레이터 비종속** — 어떤 MCP 클라이언트든 오케스트레이터 가능

모든 디스패치는 프로젝트 cwd에서 새 서브프로세스를 띄우는 방식(예: `claude -p "..." --continue`). 장기 프로세스 관리 불필요, 화면 스크래핑 없음, 크리티컬 패스에 tmux 의존 없음.

## 설계 원칙

1. **오케스트레이터 비종속.** MCP 도구가 정규 인터페이스. 어떤 MCP 클라이언트든 오케스트레이터 가능.
2. **논블로킹 디스패치.** `dispatch`는 `dispatch_id`를 <100ms에 반환. 백그라운드에서 결과 폴링. 대화가 멈추지 않음.
3. **디스패치 라우터 프리앰블.** 오케스트레이터는 순수 라우터로 동작 — 프로젝트명 파싱 → `dispatch` 호출 → 다음 요청. LLM 추론 지연 ~1-2초.
4. **파일 기반 상태.** `registry.yaml`이 유일한 진실의 원천.

## 상태

프리릴리즈. `uv tool install --editable .`로 로컬 체크아웃에서 설치.

## 빠른 시작

[`uv`](https://docs.astral.sh/uv/) 필수. (선택적 관찰 레이어를 쓰려면 `tmux`도.)

```bash
# 1. 클론 및 설치 (editable, 개발 모드)
git clone <repo> ~/Projects/central-mcp
cd ~/Projects/central-mcp
uv tool install --editable .

# 2. 빈 레지스트리 생성 (~/.central-mcp/registry.yaml)
central-mcp init

# 3. MCP 클라이언트에 central-mcp 등록 — 클라이언트당 1회
central-mcp install claude    # Claude Code MCP 설정에 추가
central-mcp install codex     # ~/.codex/config.toml 패치
central-mcp install cursor    # ~/.cursor/mcp.json 패치

# 4. 오케스트레이터 기동
central-mcp run
```

오케스트레이터 세션 안에서 자연어로:

- *"~/Projects/my-app을 허브에 추가해줘, agent=claude."*
- *"내 프로젝트 목록은?"*
- *"my-app에 보내줘: auth 모듈에 에러 핸들링 추가해."*
- *"gluecut-dawg에도 보내줘: 프로젝트 구조 요약해."*

오케스트레이터는 `dispatch`를 호출하고 **즉시 대화를 이어갑니다** — 기다릴 필요 없음. 결과는 두 가지 경로로 도착:

- **백그라운드 폴링 (최선):** 서브에이전트가 3초마다 `check_dispatch`를 폴링하고 완료 시 자동 보고.
- **사용자 질문 (100% 신뢰):** "결과는?" / "업데이트 있어?" 하면 오케스트레이터가 `check_dispatch` 또는 `list_dispatches`를 직접 호출해서 즉시 답변.

여러 디스패치가 병렬로 실행됩니다.

## MCP 도구

`central-mcp`는 `central` 서버명으로 8개 도구를 노출합니다:

| 도구 | 블로킹? | 용도 |
|---|---|---|
| `list_projects` | sync | 레지스트리 열거. |
| `project_status` | sync | 프로젝트 메타데이터. |
| `dispatch` | **<100ms** | 프로젝트 에이전트에 프롬프트 전송. `dispatch_id` 즉시 반환. |
| `check_dispatch` | sync | 디스패치 폴링 — `running` / `complete` / `error` + 출력. |
| `list_dispatches` | sync | 모든 활성 + 최근 완료 디스패치. |
| `cancel_dispatch` | sync | 실행 중인 디스패치 중단. |
| `add_project` | sync | 새 프로젝트 등록. Codex 디렉토리 자동 trust. |
| `remove_project` | sync | 프로젝트 등록 해제. |

### 디스패치 동작 방식

```
dispatch("my-app", "auth에 에러 핸들링 추가")
  → subprocess.Popen(["claude", "-p", "...", "--continue"], cwd="~/Projects/my-app")
  → {dispatch_id: "a1b2c3d4"} 즉시 반환 (<100ms)
  → 백그라운드 스레드가 프로세스 종료 시 stdout 캡처
  → check_dispatch("a1b2c3d4") → {status: "complete", output: "...", duration_sec: 45}
```

| 에이전트 | 비인터랙티브 호출 |
|---|---|
| `claude` | `claude -p "<프롬프트>" --continue` (cwd 대화 재개) |
| `codex` | `codex exec "<프롬프트>"` (무상태) |
| `gemini` | `gemini -p "<프롬프트>"` (무상태) |
| `cursor` | `cursor-agent -p "<프롬프트>" --resume` (마지막 세션 재개) |

### 성능 팁: 오케스트레이터에 빠른 모델 사용

오케스트레이터는 라우팅만 하므로 최상위 모델이 필요 없습니다. 가벼운 모델로 전환하면 턴당 지연을 크게 줄이면서도, 실제 작업을 하는 서브에이전트는 최고 모델을 유지할 수 있습니다:

| 오케스트레이터 클라이언트 | 팁 |
|---|---|
| Claude Code | `/model sonnet` — 턴당 ~1-2초 vs Opus ~5-8초 |
| Codex CLI | 경량 모델 사용 (예: `-spark` 변형) `/model` 또는 `config.toml`에서 설정 |
| Gemini CLI | 가능하면 Pro 대신 Flash 사용 |

서브에이전트 모델은 독립적 — 각 `dispatch`는 프로젝트 에이전트의 기본 모델로 자체 프로세스를 생성합니다.

## CLI 레퍼런스

```
central-mcp                        # 인자 없음 → stdio에서 MCP 서버 실행
central-mcp serve                  # 동일, 명시적
central-mcp run [--agent X] [--pick] [--bypass]  # 오케스트레이터 기동
central-mcp install CLIENT         # claude | codex | cursor에 등록
central-mcp alias [NAME]           # 짧은 이름 심링크 (기본: cmcp)
central-mcp unalias [NAME]
central-mcp init [PATH]            # registry.yaml 스캐폴드 (기본: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|cursor|shell]
central-mcp remove NAME
central-mcp list                   # 한 줄씩 레지스트리 출력
central-mcp brief                  # 오케스트레이터용 마크다운 스냅샷
central-mcp up                     # 선택적 tmux 관찰 (프로젝트당 pane 1개)
central-mcp down                   # 관찰 세션 종료
```

## 선택적 관찰 레이어

`central-mcp up`은 tmux 세션 `central`에 프로젝트당 인터랙티브 pane을 하나씩 만듭니다. `Ctrl+b n` / `Ctrl+b <숫자>`로 pane 전환. **순수 시각적** — MCP 디스패치 경로는 이 pane을 읽거나 쓰지 않습니다. `central-mcp down`으로 종료해도 오케스트레이터에 영향 없음.

## 레지스트리 경로 해결

3단계 캐스케이드:

1. `$CENTRAL_MCP_REGISTRY` (명시적 오버라이드)
2. cwd의 `./registry.yaml` (프로젝트별 오버라이드)
3. `$HOME/.central-mcp/registry.yaml` (글로벌 기본값)

레지스트리는 사용자별 상태입니다 — 커밋하지 마세요.

## 오케스트레이터 변경

```bash
central-mcp run --pick         # 피커 재실행, 새 선택 저장
central-mcp run --agent codex  # 1회성 오버라이드
$EDITOR ~/.central-mcp/config.toml
```

## 권한 우회 모드

```bash
central-mcp run --bypass
```

| 에이전트 | 추가되는 플래그 |
|---|---|
| Claude Code | `--dangerously-skip-permissions` |
| Codex CLI | `--dangerously-bypass-approvals-and-sandbox` |
| Gemini CLI | `--yolo` |

## 환경 변수

- `CENTRAL_MCP_HOME` — 사용자 상태 디렉토리 (기본: `~/.central-mcp`)
- `CENTRAL_MCP_REGISTRY` — 레지스트리 경로 오버라이드

## 라이선스

MIT (예정).
