# central-mcp

<p align="center">
  <img src="docs/logo.png" alt="central-mcp logo" width="280"/>
</p>

**여러 코딩 에이전트를 하나의 허브에서 디스패치하는, 오케스트레이터 비종속 MCP 서버.**

> **멈추지 마세요. 프로젝트마다 에이전트를 병렬로 돌려 처리량을 10배, 100배로 키우세요.**

하나의 MCP 서버로 어떤 MCP 클라이언트(Claude Code, Codex CLI, Gemini CLI, opencode 등)든 여러 코딩 에이전트 프로젝트의 컨트롤 플레인이 됩니다. 자연어로 요청하면 오케스트레이터가 해당 프로젝트의 에이전트에게 작업을 보내고, 논블로킹으로 결과를 비동기 보고합니다.

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
2. **논블로킹 디스패치.** `dispatch`는 `dispatch_id`를 <100ms에 반환. 결과는 비동기로 도착. 대화가 멈추지 않음.
3. **디스패치 라우터 프리앰블.** 오케스트레이터는 순수 라우터로 동작 — 프로젝트명 파싱, `dispatch` 호출, 다음 요청. LLM 추론 지연 ~1-2초.
4. **파일 기반 상태.** `registry.yaml`이 유일한 진실의 원천.

## 상태

[PyPI](https://pypi.org/project/central-mcp/)에서 설치 가능합니다.

## 지원 플랫폼

실제로 검증된 플랫폼과 그 외의 체감 상태:

- **macOS** — 주 개발·테스트 환경.
- **Linux** — 동작할 것으로 예상 (순수 Python, tmux/zellij 모두 크로스-플랫폼)이지만 정기적으로 검증하지는 않음. 이상 동작이 있으면 이슈로 알려주세요.
- **Windows** — 미지원.

## 빠른 시작

```bash
# uv가 없다면 먼저 설치 (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> pip도 사용 가능합니다: `pip install central-mcp`

(선택적 관찰 레이어를 쓰려면 `tmux`도.)

```bash
# 1. central-mcp 설치
uv tool install central-mcp

# 2. 바로 실행 — 한 번에 모든 설정
central-mcp
```

첫 실행 시 `~/.central-mcp/registry.yaml`이 자동 생성되고, PATH에서 발견된 모든 MCP 클라이언트(claude, codex, gemini, opencode)에 central-mcp가 자동 등록됩니다. 그 다음 선택된 에이전트로 오케스트레이터가 기동됩니다.

> 수동으로 세밀하게 제어하려면:
> - `central-mcp install all` — 다시 감지 후 모든 클라이언트에 재등록
> - `central-mcp install claude` — 특정 클라이언트만 등록
> - `central-mcp init` — 레지스트리만 생성 (기동 안 함)

오케스트레이터 세션 안에서 자연어로:

- *"~/Projects/my-app을 허브에 추가해줘, agent=claude."*
- *"내 프로젝트 목록은?"*
- *"my-app에 보내줘: auth 모듈에 에러 핸들링 추가해."*
- *"gluecut-dawg에도 보내줘: 프로젝트 구조 요약해."*

오케스트레이터는 `dispatch`를 호출하고 **즉시 대화를 이어갑니다** — 기다릴 필요 없음. 결과는 세 가지 경로로 도착:

- **피기백 (자동):** 모든 MCP 도구 응답에 완료된 dispatch 결과가 `completed_dispatches` 배열로 포함.
- **백그라운드 폴링 (최선):** 서브에이전트가 3초마다 `check_dispatch`를 폴링하고 완료 시 자동 보고.
- **사용자 질문 (100% 신뢰):** "결과는?" / "업데이트 있어?" 하면 즉시 답변.

여러 디스패치가 병렬로 실행됩니다.

## MCP 도구

`central-mcp`는 `central` 서버명으로 11개 도구를 노출합니다:

| 도구 | 블로킹? | 용도 |
|---|---|---|
| `list_projects` | sync | 레지스트리 열거. |
| `project_status` | sync | 프로젝트 메타데이터. |
| `dispatch` | **<100ms** | 프로젝트 에이전트에 프롬프트 전송. 일회성 에이전트 오버라이드 및 fallback 체인 지원. `dispatch_id` 즉시 반환. |
| `check_dispatch` | sync | 디스패치 폴링 — `running` / `complete` / `error` + 출력. |
| `list_dispatches` | sync | 모든 활성 + 최근 완료 디스패치. |
| `cancel_dispatch` | sync | 실행 중인 디스패치 중단. |
| `dispatch_history` | sync | **특정 프로젝트**의 최근 N개 디스패치 이력 (해당 프로젝트 jsonl 로그 기반). |
| `orchestration_history` | sync | 포트폴리오 전체 스냅샷 — 진행 중인 디스패치 + 프로젝트 간 최근 milestone + 프로젝트별 집계. "전반적으로 어떻게 돌아가?" 한 번에. |
| `add_project` | sync | 새 프로젝트 등록. 에이전트 이름 검증. Codex 디렉토리 자동 trust. |
| `list_project_sessions` | sync | 프로젝트의 에이전트가 가진 resumable 세션 목록. 반환된 `id`를 `dispatch(session_id=...)`에 넘겨 thread 전환. |
| `update_project` | sync | 기존 프로젝트의 agent / description / tags / permission_mode / fallback / session_id 변경. |
| `reorder_projects` | sync | 레지스트리 순서 재정렬. 관대 모드 (listed 이름만 앞으로 이동, 나머지는 원래 순서 유지). strict 모드는 전체 이름 명시 필요. |
| `remove_project` | sync | 프로젝트 등록 해제. |

### 디스패치 동작 방식

```
dispatch("my-app", "auth에 에러 핸들링 추가")
  → subprocess.Popen(["claude", "-p", "...", "--continue"], cwd="~/Projects/my-app")
  → {dispatch_id: "a1b2c3d4"} 즉시 반환 (<100ms)
  → 백그라운드 스레드가 프로세스 종료 시 stdout 캡처
  → check_dispatch("a1b2c3d4") → {status: "complete", output: "...", duration_sec: 45}
```

### 지원 에이전트

| 에이전트 | 비인터랙티브 호출 | `bypass` 모드 플래그 | `auto` 모드 플래그 |
|---|---|---|---|
| `claude` | `claude -p "<프롬프트>" --continue` | `--dangerously-skip-permissions` | `--enable-auto-mode --permission-mode auto` |
| `codex` | `codex exec "<프롬프트>"` | `--dangerously-bypass-approvals-and-sandbox` | — |
| `gemini` | `gemini -p "<프롬프트>"` | `--yolo` | — |
| `droid` | `droid exec "<프롬프트>"` | `--skip-permissions-unsafe` | — |
| `opencode` | `opencode run "<프롬프트>" --continue` | `--dangerously-skip-permissions` | — |

에이전트 이름은 등록 시점에 검증됩니다 — `cursor-agent` 같은 오타는 dispatch 시점이 아니라 즉시 잡힙니다.

### 프로젝트 에이전트 변경

프로젝트에 등록된 에이전트를 언제든 변경할 수 있습니다 — 특정 코드베이스가 다른 CLI와 더 잘 맞는 경우 유용:

```
update_project(name="my-app", agent="codex")
```

`update_project`는 `description`, `tags`, `permission_mode`, `fallback` 도 받습니다 — 생략된 필드는 그대로 유지. `codex`로 전환하면 프로젝트 디렉토리가 `~/.codex/config.toml` trust 리스트에 자동 등록됩니다.

### 일회성 에이전트 오버라이드

레지스트리를 변경하지 않고 *한 번만* 다른 에이전트로 작업을 보내고 싶을 때 — 예를 들어 디자인에 특화된 에이전트에게 디자인 작업만 보내고 프로젝트는 원래 에이전트 유지:

```
dispatch(name="my-app", prompt="...", agent="codex")
```

레지스트리는 유지됩니다. `agent=` 없이 다음 dispatch는 다시 저장된 에이전트로.

### 실패 시 fallback 체인

주 에이전트가 non-zero로 종료될 때 (rate limit, 토큰 한도, 크래시), central-mcp가 백업 에이전트로 자동 재시도:

```
# 일회성 (저장 안됨):
dispatch(name="my-app", prompt="...", fallback=["codex", "gemini"])

# 이 프로젝트의 기본값으로 저장:
update_project(name="my-app", fallback=["codex", "gemini"])
```

결과에는 실제로 응답을 생성한 에이전트(`agent_used`), fallback이 발동되었는지(`fallback_used`), 그리고 모든 시도의 목록이 포함됩니다. 타임아웃은 재시도되지 *않습니다* — 멈춘 에이전트 때문에 전체 체인을 소모하기보다 사용자에게 바로 보여주는 것이 낫기 때문.

저장된 fallback 체인을 일회성으로 비활성화하려면 `fallback=[]` 전달.

### Permission 모드

대부분의 코딩 에이전트는 파일 수정·명령어 실행·패키지 설치 전에 "이거 해도 돼?"를 물어봅니다. 사람이 터미널 앞에 있으면 괜찮지만, central-mcp가 돌아가는 어느 경로에도 응답할 TTY가 없어서 **승인을 기다리며 영원히 멈출 수 있습니다**. central-mcp가 띄우는 모든 에이전트 인스턴스(오케스트레이터 pane이든, dispatch로 spawn되는 프로젝트 에이전트든)는 아래 세 가지 **permission 모드** 중 하나로 실행됩니다:

| 모드 | 자동 승인 범위 | 사용 시점 |
|---|---|---|
| `bypass` | 전부. 각 에이전트의 permission-skip 플래그를 부착합니다 (아래 매핑 표 참고). | 기본값. 가장 빠름. 프롬프트 인젝션 방어 없음. 모든 에이전트 지원. |
| `auto` | cwd 내 로컬 파일 작업, 이미 선언된 의존성 설치, read-only HTTP, Claude가 만든 브랜치 푸시. 그 외엔 백그라운드 **분류기**가 검토 — `curl \| bash`, 프로덕션 배포, force-push, 클라우드 벌크 삭제 등은 차단. | 프롬프트 인젝션에 대한 방어가 중요한 민감 레포. **`claude`만 지원** (Team/Enterprise/API 플랜 + **Sonnet 4.6 또는 Opus 4.6** 필요 — Haiku, 4.7, 타사 제공자 불가). `auto`를 non-claude 에이전트·폴백 체인에 지정하면 central-mcp가 명시적으로 거절. |
| `restricted` | 없음. 원래라면 승인을 요구할 도구 호출은 그대로 실패. | 읽기 전용 작업 강화 — Q&A, 코드 설명, 리포트. 쓰기/빌드/쉘은 모두 hang/실패. 모든 에이전트 지원. |

각 벤더가 permission-skip을 부르는 이름이 다르므로, central-mcp의 `bypass`/`auto`는 아래 매핑을 통해 각 에이전트의 해당 플래그로 번역됩니다:

| central-mcp 모드 | claude | codex | gemini | droid | opencode |
|---|---|---|---|---|---|
| `bypass` | Skip permissions<br>`--dangerously-skip-permissions` | Bypass approvals + sandbox<br>`--dangerously-bypass-approvals-and-sandbox` | YOLO<br>`--yolo` | Skip permissions (unsafe)<br>`--skip-permissions-unsafe` | Skip permissions<br>`--dangerously-skip-permissions` |
| `auto` | Auto mode<br>`--enable-auto-mode --permission-mode auto` | — | — | — | — |
| `restricted` | *(플래그 없음)* | *(플래그 없음)* | *(플래그 없음)* | *(플래그 없음)* | *(플래그 없음)* |

다른 벤더가 나중에 claude의 `auto`에 해당하는 모드를 추가하면 (codex sandbox-warn, gemini review-mode 등) central-mcp가 동일한 `auto` alias에 연결 — 기존 설정은 그대로 유지됩니다.

모드는 서로 다른 두 레이어에 적용됩니다:

#### 1. 오케스트레이터 레이어 — `central-mcp run` / `central-mcp tmux` / `central-mcp up` / `central-mcp zellij`

**사용자가 직접 대화하는** 오케스트레이터 pane(MCP 도구를 호출하는 에이전트)에 적용됩니다. **기본값: `bypass`.** `--permission-mode`로 변경:

```bash
central-mcp tmux   --permission-mode auto        # claude 전용, 분류기 검토
central-mcp run    --permission-mode restricted  # 자동 승인 없음 — 프롬프트는 멈춤
central-mcp zellij --permission-mode bypass      # 기본값 명시
```

오케스트레이터 `bypass`로 기동하면 오케스트레이터가 `~/.central-mcp` 내부에서 물어보지 않고 파일을 읽고 씁니다 — `CLAUDE.md`, scratch note, 허브 편집이 마찰 없이 진행됩니다. `auto`(claude + Sonnet/Opus 4.6 전용)는 분류기가 개별 action을 검토합니다. non-claude 오케스트레이터에서 `auto`를 지정하면 플래그 없이 기동(경고 출력). 이 레이어의 모드는 dispatch로 spawn되는 프로젝트 에이전트에는 **영향을 주지 않습니다** — 각 프로젝트는 자체 값을 별도로 들고 있습니다.

#### 2. 프로젝트 dispatch 레이어 — `dispatch(..., permission_mode=...)` / `registry.yaml`

프로젝트 cwd에서 한 번 spawn되는 에이전트에 적용됩니다. 값은 첫 dispatch에서 `registry.yaml`에 저장되고(기본 `"bypass"`) 이후 재사용됩니다. 언제든 덮어쓸 수 있음:

```
dispatch(name="my-app", prompt="…", permission_mode="bypass")      # 자동 승인, 설정 저장
dispatch(name="my-app", prompt="…", permission_mode="auto")        # claude 전용, 분류기 검토
dispatch(name="my-app", prompt="…", permission_mode="restricted")  # skip 없음
update_project(name="my-app", permission_mode="auto")              # dispatch 없이 값만 변경
```

`"auto"`를 지정했는데 프로젝트의 에이전트 체인이 `claude` 이외를 포함하면 central-mcp가 명시적으로 거절 — fallback에서 `auto`가 `bypass`로 **암묵적 다운그레이드되지 않습니다**. `"restricted"`면 읽기 전용 dispatch(질문 답변, 파일 읽기, 코드 설명)는 정상 동작하지만 승인이 필요한 작업(편집, 쉘, 의존성 설치)은 타임아웃까지 hang — `bypass`/`auto`로 재시도하거나, 해당 프로젝트 cwd에서 에이전트를 인터랙티브로 직접 띄워 수동 승인하세요.

> ### ⚠️ `bypass`는 강력합니다 — 본인 책임
>
> `bypass` 모드(어느 쪽 레이어든)에서는 에이전트가 **사용자 확인 없이** 파일 수정·쉘 명령 실행·패키지 설치·네트워크 서비스 호출·코드 push를 수행할 수 있습니다. 이게 멈춤 없는 오케스트레이션을 가능케 하지만, 잘못된 프롬프트·외부 프롬프트 인젝션·에이전트 hallucination이 실제 피해(테이블 drop, 강제 푸시, 파일 삭제, 자격증명 유출, 의도하지 않은 API 비용 등)로 이어질 수 있습니다.
>
> `auto` 모드는 중간 지대입니다 — 여전히 headless로 동작하지만 분류기가 표준 파괴적 패턴 집합을 차단합니다 (기본 정책은 [Claude Code permission-modes 문서](https://code.claude.com/docs/permission-modes) 참고). 프롬프트 인젝션 리스크를 낮추지만 제거하지는 않습니다. `restricted`가 가장 안전하지만 쓰기가 필요 없는 에이전트에만 유효.
>
> 차이점 정리:
> - **오케스트레이터 모드**는 *허브 레벨* 에이전트가 `~/.central-mcp` 및 MCP 도구 호출 과정에서 할 수 있는 일을 제어. 허브 디렉토리에 프로덕션 코드가 없으므로 리스크는 상대적으로 낮지만 읽기/쓰기는 자동.
> - **프로젝트 모드**는 각 *프로젝트 레벨* 에이전트가 해당 프로젝트 cwd 안에서 할 수 있는 일을 제어. 소스 재작성, 빌드 실행, 브랜치 푸시가 일어나는 **고위험** 레이어.
>
> **다음에 해당하면 `bypass` 대신 `auto`(claude) 또는 `restricted`로 전환하세요**:
> - 프로젝트(또는 `~/.central-mcp`)에 민감한 코드/비밀번호/프로덕션 데이터가 있음
> - 안전망이 될 커밋/푸시가 아직 준비되지 않음
> - 프롬프트를 꼼꼼히 확인하지 않았거나, 신뢰할 수 없는 소스의 작업을 위임
> - 에이전트가 실행할 명령을 매번 리뷰하고 싶음
>
> **면책**: central-mcp는 라우팅 레이어로서 에이전트가 어떤 작업을 수행하는지 감독하지 않습니다. 선택한 모드로 인해 발생한 dispatch의 범위·대상·결과에 대한 책임은 사용자 본인에게 있습니다. central-mcp 저자와 기여자는 `bypass`(또는 `auto`) 사용으로 인한 데이터 손실·보안 침해·비용 발생·기타 피해에 대해 **어떤 책임도 지지 않습니다**. 스냅샷(git 커밋, 백업, 브랜치 보호), 최소 권한 자격증명, 오프라인/샌드박스 환경을 최대한 활용하세요.

### 세션 관리 (대화 연속성)

기본적으로 모든 dispatch는 프로젝트 cwd의 **가장 최근에 수정된 대화 세션**을 이어받습니다 — `claude --continue`, `codex exec resume --last`, `gemini --resume latest`, `opencode --continue`. **droid만 예외** — headless `droid exec` 에는 "resume latest" 가 없어서 session id 없이 dispatch하면 매번 새 thread로 시작됩니다.

사용자가 특정 세션으로 전환하고 싶거나 ambient drift (같은 cwd에서 인터랙티브 세션이 "latest"를 흔들어 놓은 경우) 를 복구하려면, `dispatch(session_id=...)` 로 **one-shot 오버라이드**:

```
list_project_sessions("my-app")
  → [{id: "a1b2...", title: "auth refactor", modified: "..."}, ...]

dispatch("my-app", "저기서 이어서", session_id="a1b2...")
  # → claude -p "..." -r a1b2...
```

이 한 번의 dispatch 이후 이어받은 세션이 "최근 수정" 으로 바뀌므로 다음 기본 `dispatch("my-app", "...")` 는 `--continue` 로 자연스럽게 같은 세션을 집음. thread 를 또 바꿀 때만 id를 다시 명시하면 됩니다.

Drift 방지용 영구 pin (droid는 세션 연속성을 원하면 pin 필수):

```
update_project("my-app", session_id="a1b2...")
# 이후 모든 dispatch가 ambient 상태와 무관하게 -r/-s <id> 로 고정.

update_project("my-app", session_id="")
# 빈 문자열로 pin 해제.
```

dispatch 시 session_id 해결 우선순위: 호출 인자 > 프로젝트에 저장된 `session_id` > 에이전트의 resume-latest 플래그.

| 에이전트 | specific-session 플래그 | 세션 목록 소스 |
|---|---|---|
| `claude` | `-r <uuid>` | `~/.claude/projects/<slug(cwd)>/*.jsonl` |
| `codex` | `resume <uuid>` | `~/.codex/sessions/**/*.jsonl` (session_meta의 `cwd` 필드로 필터) |
| `gemini` | `--resume <index>` | `gemini --list-sessions` (UUID 아닌 숫자 인덱스) |
| `droid` | `-s <uuid>` | `~/.factory/sessions/<slug(cwd)>/*.jsonl` |
| `opencode` | `-s <uuid>` | `opencode session list` (cwd 스코프 없음, 전역) |

### 디스패치 히스토리 (프로젝트별)

모든 dispatch는 `~/.central-mcp/logs/<project>/dispatch.jsonl`에 `start` / `output` / `complete` 이벤트를 append로 기록합니다. `dispatch_history`는 terminal 이벤트를 start와 merge해서 반환:

```
dispatch_history(name="my-app")          # my-app 최근 10개
dispatch_history(name="my-app", n=50)    # 최근 50개
```

포트폴리오 차원의 관찰은 `orchestration_history` (아래) 사용.

### 오케스트레이션 히스토리 (포트폴리오 뷰)

"전체적으로 어떻게 돌아가?"를 한 번의 호출로 답합니다. 전역 타임라인 `~/.central-mcp/timeline.jsonl` + 서버 메모리의 in-flight 테이블을 합쳐 반환:

```
orchestration_history()                  # 진행 중 + 전체 프로젝트 최근 20개 milestone
orchestration_history(n=100)             # 더 긴 이력
orchestration_history(window_minutes=60) # 최근 1시간 활동만
```

응답에는 `in_flight` (현재 실행 중), `recent` (최근 milestone), `per_project` (프로젝트별 dispatched/succeeded/failed/cancelled 카운트 + 최근 ts), 레지스트리 스냅샷이 포함됩니다. 오케스트레이터가 이 한 번의 호출로 복수 프로젝트 현황을 자연어로 요약할 수 있습니다.

### 성능 팁: 오케스트레이터에 빠른 모델 사용

오케스트레이터는 라우팅만 하므로 최상위 모델이 필요 없습니다:

| 오케스트레이터 클라이언트 | 팁 |
|---|---|
| Claude Code | `/model sonnet` — 턴당 ~1-2초 vs Opus ~5-8초 |
| Codex CLI | 경량 모델 사용 (예: `-spark` 변형) `/model` 또는 `config.toml`에서 설정 |
| Gemini CLI | 가능하면 Pro 대신 Flash 사용 |
| opencode | `-m provider/model` 또는 `opencode.json`에서 빠른 모델 선택 |

서브에이전트 모델은 독립적 — 각 `dispatch`는 프로젝트 에이전트의 기본 모델로 자체 프로세스를 생성합니다.

## CLI 레퍼런스

```
central-mcp                        # 인자 없음 → 오케스트레이터 기동 (`run`과 동일)
central-mcp run [--agent X] [--pick] [--permission-mode {bypass,auto,restricted}]
                                   # 오케스트레이터 기동 (기본: bypass; auto는 claude 전용)
central-mcp serve                  # stdio에서 MCP 서버 실행 (MCP 클라이언트가 사용)
central-mcp install CLIENT         # claude | codex | gemini | opencode에 등록
central-mcp alias [NAME]           # 짧은 이름 심링크 (기본: cmcp)
central-mcp unalias [NAME]
central-mcp init [PATH]            # registry.yaml 스캐폴드 (기본: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|droid|opencode]
central-mcp remove NAME
central-mcp reorder NAME [NAME ...]  # 레지스트리 재정렬 — 명시 안 한 것은 원래 순서 유지
central-mcp list                   # 한 줄씩 레지스트리 출력
central-mcp brief                  # 오케스트레이터용 마크다운 스냅샷
central-mcp up [--no-orchestrator] [--permission-mode {bypass,auto,restricted}] [--max-panes N]
                                   # 선택적 tmux 관찰 레이어 생성
central-mcp tmux [up과 동일 플래그]   # 세션이 없으면 생성 후 tmux로 attach
central-mcp zellij [up과 동일 플래그] # 동일, 단 zellij로 (KDL 레이아웃 생성)
central-mcp down                   # 관찰 세션 종료
central-mcp watch NAME [--from-start]
                                   # 프로젝트의 dispatch 이벤트 실시간 스트리밍
central-mcp upgrade [--check]      # PyPI에서 최신 버전 확인 후 자동 업그레이드 (uv → pip fallback)
```

## 선택적 관찰 레이어

### 왜 *선택적* 인가

- **오케스트레이터가 메인 인터페이스.** `dispatch` / `check_dispatch` / `orchestration_history` 가 구조화된 요약을 반환하고, 오케스트레이터가 자연어로 상황을 보고 — stdout을 눈으로 쫓을 필요 없음.
- **어디서든 작업이 가능해야 함.** 폰·태블릿에서 SSH로 붙는 순간에도 진도가 나가도록 설계. 허브가 멀티-pane 대시보드를 요구해서는 안 됨.
- **실시간 뷰가 실제 이득일 때만 관찰 레이어를 켜세요** — 멈춘 에이전트 디버깅, 긴 마이그레이션 tail, 세션 중 플릿 screen-share 같은 경우. 일반 운영에선 signal보다 noise가 더 많음.

### 백엔드

세 가지 백엔드를 지원합니다 (세 번째는 macOS 전용):

- **tmux** — `central-mcp tmux` (세션 없으면 생성 후 attach)
- **zellij** — `central-mcp zellij` (KDL 레이아웃 생성 후 `central` 세션 실행 / attach)
- **cmux** — `central-mcp cmux` (macOS 전용; [cmux.app](https://github.com/manaflow-ai/cmux) GUI 터미널에 워크스페이스를 엶. 레이아웃은 오케스트레이터 에이전트가 시드 프롬프트로 직접 구성 — 아래 [cmux 관찰모드](#cmux-관찰모드) 참조.)

tmux / zellij 는 동일한 레이아웃(허브 탭 + 오버플로우 탭, 각 프로젝트 pane 이 `central-mcp watch <project>` 실행)을 만듭니다. 설치되어 있는 쪽을 고르면 됩니다. cmux 는 agent-driven 방식이라 별도 섹션에서 설명합니다.

`central-mcp up`은 tmux 세션 `central`을 만듭니다:

- **Pane 0 — 오케스트레이터** (Claude Code / Codex / Gemini / opencode). `~/.central-mcp`에서 기동되어 허브의 `CLAUDE.md` / `AGENTS.md`를 읽음.
- **Pane 1…N — 프로젝트당 하나**. 각 pane은 `central-mcp watch <project>`를 실행해 해당 프로젝트의 dispatch 활동(프롬프트, 출력, exit code, duration)을 실시간 스트리밍.

윈도우 이름은 `cmcp-<N>` 형식. 오케스트레이터가 포함된 첫 윈도우는 `-hub` 접미사(`cmcp-1-hub`)가 붙어 한눈에 구분됩니다. `Ctrl+b n` / `Ctrl+b <숫자>`로 pane 전환. 레지스트리가 한 윈도우에 담기 어려운 규모면 `cmcp-2`, `cmcp-3`, … 윈도우가 자동 생성됩니다. `--max-panes N` 은 윈도우당 pane 개수 상한 — 생략하면 현재 터미널 크기를 읽어 readability floor (~70 cols × 15 rows per pane, 13-15" 노트북 전체화면이 2 column slice로 떨어지도록 튜닝) 위에서 몇 개까지 담을지 자동 계산.

**오케스트레이터 배치**: 첫 윈도우는 오케스트레이터 pane을 **전체 세로 높이를 차지하는 좌측 열**로 배치하고, 열 너비는 프로젝트 열 하나와 동일하게 맞춥니다. `orch + 1 project` → 50/50, `orch + 3 projects` → 4열 동등 (한 row), `orch + 9 projects` → orch가 1/6 너비 + 우측 2×5 프로젝트 격자.

```bash
central-mcp tmux                   # 원샷: 세션 없으면 생성, 바로 attach
central-mcp tmux --permission-mode auto        # claude 전용, 분류기 검토 오케스트레이터
central-mcp tmux --permission-mode restricted  # 자동 승인 없이 기동 (프롬프트는 멈춤)
central-mcp tmux --no-orchestrator # watch pane만
central-mcp tmux --max-panes 6
central-mcp up                     # attach 없이 세션만 생성 (스크립트용)
central-mcp down                   # 세션 종료
```

Hub 윈도우(`cmcp-1-hub`)는 tmux의 `main-vertical` 레이아웃을 사용합니다 — 오케스트레이터 pane이 왼쪽에 두 칸 크기를 차지하고, 프로젝트 pane들이 오른쪽에 세로로 쌓입니다. 그래서 hub는 `panes_per_window − 1`개 pane(기본 3 — 오케스트레이터 + 프로젝트 2개)을 담고, 오버플로우 윈도우는 `panes_per_window`개 프로젝트를 그대로 담습니다. 모든 pane은 상단 border에 역할 이름이 표시되고, 오케스트레이터 border는 굵은 노란색으로 강조됩니다.

`central-mcp down`으로 종료해도 MCP 디스패치 경로는 이 레이어에 의존하지 않으므로 진행 중인 dispatch에 영향 없습니다. `watch`는 `~/.central-mcp/logs/<project>/dispatch.jsonl`을 읽기 전용으로 tail하는 구조라 어떤 터미널에서도 독립 실행 가능합니다.

#### zellij watch pane에 "<ENTER> to run, <Ctrl-c> to exit" 이 뜰 때

zellij watch pane이 dispatch 이벤트를 스트리밍하지 않고 `<ENTER> to run, <Ctrl-c> to exit` 메시지를 보여주면, 내부 `central-mcp watch <project>` 자식 프로세스가 죽었거나 시작하지 못한 상태입니다. zellij의 기본 안전장치 — pane을 계속 열어 scroll back을 보존하고, 자동 재실행이나 쉘로 떨어지지 않고 사용자의 명시적 행동을 기다립니다. **ENTER를 누르지 마세요**: 그 시점의 pane은 이미 central-mcp 파이프라인과 분리된 상태라, 여기서 수동으로 재실행해도 central-mcp 로 흘러들어오지 않습니다. 해결은 세션 재빌드: `cmcp zellij` (0.6.8+ 부터 자동 teardown + rebuild) 한 번 실행하면 모든 pane이 새 watch 자식을 가진 채 respawn됩니다.

#### 관찰 세션이 attach된 상태에서 central-mcp 업그레이드했다면

관찰 레이어를 쓰지 않는다면 (dispatch 전용 워크플로우) 이 소절은 건너뛰어도 됩니다.

`cmcp up` 세션이 살아 있는 상태에서 `central-mcp upgrade` (또는 `pip install -U central-mcp`) 를 실행하면, 각 pane은 **이전 버전의** orchestrator CLI와 `central-mcp watch` 자식 프로세스를 그대로 붙들고 있습니다. 이 프로세스들은 실행 도중 바이너리 변경을 반영하지 않아서, 새로 추가된 이벤트 타입, 변경된 argv 플래그, `~/.central-mcp/` 내 인스트럭션 파일 갱신 등이 pane에 도달하지 못합니다. 재접속 시 오래된 에이전트 출력이 보이거나, watch pane에서 자식이 죽은 채 zellij의 `Exit: 0 — Enter로 재실행` 메시지가 떠 있을 수 있습니다.

**0.6.8+**: 신경 쓸 필요 없습니다. `cmcp tmux` / `cmcp zellij` 를 호출할 때마다 기존 관찰 세션이 있으면 자동으로 내리고 현재 터미널 크기 기준으로 새로 생성한 뒤 attach 합니다. 결과적으로 항상 최신 바이너리로 돌아가는 fresh pane 들이 현재 터미널 비율에 맞춰 배치됩니다. `central-mcp upgrade` 도 바이너리 교체 전에 관찰 세션을 자동으로 내려주므로 "업그레이드 중 세션 attach" 케이스도 커버됩니다.

트레이드오프: 두 터미널이 같은 세션에 동시에 attach 되어 있을 때 한 쪽에서 `cmcp tmux` 를 실행하면 나머지 한 쪽은 disconnect 됩니다. 대신 "세션에 남아있는 옛 바이너리" 를 신경 쓸 일이 영구적으로 사라집니다.

### cmux 관찰모드

[cmux.app](https://github.com/manaflow-ai/cmux) 은 macOS 네이티브 GUI 터미널 (AppKit + Ghostty) 로, `~/.cmux/cmux.sock` 을 통해 CLI 를 노출합니다. `central-mcp cmux` 는 `central` 이라는 워크스페이스를 열어 오케스트레이터 에이전트를 시드 프롬프트와 함께 기동시키고, 에이전트가 직접 프로젝트별 관찰 pane 을 구성합니다 — cmux 는 자식 pane 에 `CMUX_WORKSPACE_ID` 환경변수를 주입하도록 설계돼 있어, claude / codex / gemini 오케스트레이터가 자신의 Bash 도구로 cmux CLI 를 호출해 레이아웃을 짤 수 있습니다.

**요구사항**
- macOS.
- cmux.app 설치 + 실행 중 (CLI 는 실행 중인 앱과 통신; 앱이 안 떠 있으면 ping-failed 에러).
- cmux CLI 가 `PATH` 에 — 보통 `/Applications/cmux.app/Contents/Resources/bin/cmux`.

```bash
central-mcp cmux                          # bypass 모드 (기본값) — 권장
central-mcp cmux --permission-mode auto   # claude 전용, 분류기 검토 부트스트랩
central-mcp cmux --no-orchestrator        # 빈 워크스페이스; pane 은 직접 구성
central-mcp down                          # 워크스페이스 종료
```

**주의사항 (사용 전 반드시 읽어주세요)**
- **오케스트레이터 호환성.** claude / codex / gemini 만 지원합니다 — 이 세 CLI 만 interactive 세션에 시드 프롬프트를 주입할 수 있고, 그게 부트스트랩을 에이전트에 넘기는 수단이기 때문입니다. `opencode` / `droid` 프로젝트는 이 백엔드로 실행할 수 없습니다; 해당 에이전트는 `central-mcp tmux` / `central-mcp zellij` 를 쓰세요.
- **`--permission-mode restricted` 는 부트스트랩을 멈춥니다.** 시드는 에이전트에게 `cmux new-split` / `cmux send-text` 를 호출하도록 지시하는데, restricted 모드에서는 각 쉘 명령이 별도 승인 프롬프트로 뜨면서 첫 승인 대기에서 셋업이 멈춥니다. 기본값 `bypass` 나 `auto` (claude 전용) 를 쓰시면 됩니다; `restricted` 를 고르면 `cmd_cmux` 가 경고를 출력합니다.
- **`--max-panes` 없음.** cmux 는 GUI 에서 responsive 하게 pane 을 resize 하므로 char-cell readability floor 튜닝이 불필요합니다. 에이전트가 레지스트리 크기(프로젝트당 1 pane)만큼 알아서 split 합니다.
- **레이아웃은 agent-driven 이지 declarative 가 아닙니다.** central-mcp 는 세션당 CLI 호출 딱 1 번 (`cmux new-workspace`) 만 합니다; 그 이후는 전부 에이전트의 Bash 도구 호출로 일어납니다. 부트스트랩 중 에이전트가 실패하면 레이아웃이 부분적으로만 뜰 수 있고, 그럴 땐 `central-mcp cmux` 를 다시 실행해서 teardown + 재시도 하시면 됩니다.

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

## 환경 변수

- `CENTRAL_MCP_HOME` — 사용자 상태 디렉토리 (기본: `~/.central-mcp`)
- `CENTRAL_MCP_REGISTRY` — 레지스트리 경로 오버라이드

## 개발

```bash
uv tool install --editable .
uv run --group dev pytest             # 141개 단위 테스트 (빠름, 실제 CLI 호출 없음)
uv run --group dev pytest -m live     # 20개 라이브 테스트 — 실제 에이전트 바이너리
                                      # (claude/codex/gemini/droid) 호출.
                                      # 해당 바이너리가 PATH에 없으면 자동 skip
```

## 라이선스

MIT.
