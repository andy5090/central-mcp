# 관찰 모드

central-mcp의 dispatch는 non-blocking입니다. 세 프로젝트에 작업을 보내달라고 orchestrator에 부탁하면 100ms 안에 세 개의 `dispatch_id`를 받고, 대화를 계속할 수 있죠. 에이전트들은 백그라운드에서 각자 프로젝트 디렉터리에서 돌면서 프로젝트별 이벤트 로그로 출력을 흘려보냅니다.

관찰 레이어는 그 모든 스트림을 **한 번에 보게 해주는 도구**입니다 — 프로젝트당 한 페인, orchestrator는 옆에, 모두 라이브.

세 가지 백엔드, 같은 모양:

| 백엔드 | 환경 | 언제 쓸지 |
|---|---|---|
| **[cmux](https://github.com/manaflow-ai/cmux)** | macOS GUI 앱 | 에이전트가 알아서 페인을 운영하는 네이티브 윈도우 매니저를 원할 때 |
| **tmux** | 모든 Unix 터미널 | 이미 tmux 안에서 살고 있을 때 |
| **zellij** | 모든 Unix 터미널 | zellij 디폴트가 더 편할 때 |

---

## central-mcp + cmux가 특별한 이유

cmux의 설계 철학은 단순합니다: **에이전트가 자기 페인을 직접 운영한다**. cmux가 띄우는 모든 페인의 환경 변수에 `CMUX_WORKSPACE_ID`와 `CMUX_SURFACE_ID`가 주입되고, 에이전트가 호출하는 CLI(`cmux new-split`, `cmux send-text`, `cmux tree --json`)로 자기 레이아웃을 직접 구성합니다.

이 철학은 central-mcp의 설계와 정확히 정렬됩니다:

- **Stateless** — 동기화할 daemon 없음; central-mcp은 프로젝트마다 `dispatch.jsonl`을 남기고, 무엇을 어디에 그릴지는 에이전트가 결정합니다.
- **Log-driven** — `cmcp watch <project>`는 프로젝트별 이벤트 스트림의 tail로, sticky 헤더와 컬러를 입혔을 뿐입니다. cmux는 이걸 진짜 GUI 윈도우로 띄워주죠 — 네이티브 폰트 렌더링, GPU 가속 스크롤, macOS Cmd-키 복붙.
- **에이전트 주도 셋업** — central-mcp의 런타임 가이드(`~/.central-mcp/AGENTS.md`)가 orchestrator에게 `cmux new-split`을 어떻게 호출할지 알려주므로, 레이아웃은 자연어 한 마디 (*"현재 워크스페이스의 watch 페인 셋업해줘"*)로 끝납니다. config 파일 한 줄 안 만져요.

결과적으로: 사용자는 진짜 macOS 앱 안에 있고, 에이전트(Claude Code / Codex / Gemini / opencode)는 한 cmux 페인에서 central-mcp과 대화하고 있고, 한 문장 후에 그 주변에 프로젝트 페인 그리드가 깔끔하게 잡힙니다 — 각 페인은 자기 프로젝트의 dispatch 출력을 라이브로 tail 합니다. tmux config 없음, 외울 키바인딩 없음, 터미널 에뮬레이터 오버헤드 없음.

---

## cmux 빠른 시작

1. <https://github.com/manaflow-ai/cmux>에서 cmux 설치 (macOS).
2. cmux.app 열고 워크스페이스 만들기.
3. 워크스페이스의 첫 페인에서 `cmcp` 실행 (orchestrator 띄우기).
4. orchestrator에게 한 마디: *"현재 워크스페이스의 모든 프로젝트에 watch 페인 셋업해줘."*
5. orchestrator가 `~/.central-mcp/AGENTS.md`(central-mcp 첫 실행 시 함께 설치됨 — 전체 cmux 레시피 포함)를 읽고, 프로젝트마다 `cmux new-split`을 한 번씩 호출해서 그리드를 깔아줍니다.

끝. 각 페인이 `cmcp watch <project>`를 돌면서 자기 프로젝트의 라이브 이벤트를 보여줍니다. 사용자는 orchestrator 페인에 머물면서 계속 dispatch 하면 됩니다.

> "한 도구 호출당 정확히 한 split, 엄격하게 순차" 룰은 `data/AGENTS.md`에 있고, 1개부터 8개+까지 페인 수에 관계없이 깔끔한 그리드를 만드는 핵심입니다. 사용자는 신경 안 써도 됩니다 — orchestrator가 알아서 처리.

---

## tmux 또는 zellij 빠른 시작

cmux GUI를 안 쓰셔도, 두 터미널 백엔드 모두 1급 시민입니다:

```bash
cmcp up                    # 인터랙티브 픽커 (tmux / zellij)
cmcp tmux                  # 직접 지정
cmcp zellij                # 직접 지정

cmcp tmux --workspace work # workspace 'work' 프로젝트만 띄우기
cmcp tmux --all            # workspace 별로 세션 하나씩
```

- 세션 이름은 `cmcp-<workspace>` (예: `cmcp-work`).
- 페인 0 = orchestrator, 페인 1+ = 등록된 프로젝트마다 `cmcp watch <project>`.
- `cmcp down`으로 세션 정리.

두 백엔드 모두 순수 Python — 별도 config 파일 없음, 외울 키바인딩 없음.

---

## 모든 백엔드 공통

`cmcp watch <project>`는 어떤 프로젝트 페인이든 거기서 도는 핵심:

- `~/.central-mcp/logs/<project>/dispatch.jsonl` 한 줄씩 tail.
- 프로젝트 이름, 현재 에이전트, 상태(idle / running / errored), 경과 시간을 sticky 헤더에 고정.
- ANSI 컬러 처리: 산문은 readable, 코드 블록은 magenta 톤, 폴백 전이는 `↻` 노랑색.
- 알려진 노이즈 필터링 — Codex 상태 배너, Gemini deprecation 경고, 빈 줄 스팸.

스탠드얼론으로도 쓸 수 있습니다: 일반 터미널에서 `cmcp watch my-app`.

---

## 스크린샷과 데모

!!! info "준비 중"
    실제 cmux + central-mcp 캡처(4-up 그리드, dispatch 진행 중 토큰 스트리밍, ~30초 화면 녹화)는 자산 녹화 후 여기에 올라갈 예정입니다. 그 전까지는 [cmux 프로젝트 페이지](https://github.com/manaflow-ai/cmux)에 앱 레벨 스크린샷이 있고, central-mcp 설치 시 함께 들어가는 `~/.central-mcp/AGENTS.md`에 정확한 흐름이 적혀 있습니다.

---

## 굳이 관찰 모드를 써야 할까?

안 쓰셔도 됩니다. dispatch는 non-blocking이고, 결과는 다음 MCP 도구 호출에 piggyback 되고, "어떻게 돼가?"는 언제든 동작합니다. 1–2개 프로젝트면 그냥 orchestrator와 대화만 해도 충분.

관찰 모드가 빛나는 지점:

- **3개 이상 동시 진행 중일 때.** 라이브 출력을 보면 멈춘 에이전트를 몇 초 안에 알아챕니다. "어떻게 됐어?" 다음 턴까지 기다릴 필요 없이.
- **2분 이상 걸리는 long-running dispatch.** sticky 헤더의 경과 시간이 "멈춘 거야 아니면 그냥 느린 거야?" 불안을 막아줍니다.
- **특정 프로젝트의 에이전트가 이상하게 굴 때** — 페인별 로그 스트림이 통합된 `orchestration_history` 응답보다 훨씬 읽기 편합니다.

위 상황이 안 닥치면 관찰 모드는 스킵하셔도 됩니다. central-mcp는 어느 쪽이든 동작합니다.
