# 관찰 모드

central-mcp의 dispatch는 non-blocking입니다. 세 프로젝트에 작업을 보내달라고 부탁하면, 100ms 안에 세 개의 `dispatch_id`만 돌려주고 사용자는 곧바로 다음 대화로 넘어갈 수 있죠. 그 동안 에이전트들은 백그라운드에서 각자 프로젝트 디렉터리에서 일하면서, 자기 출력을 프로젝트별 이벤트 로그에 흘려보냅니다.

관찰 모드는 그 흐름들을 **한눈에 보게 해주는 화면**입니다. 프로젝트마다 한 페인, orchestrator는 옆에, 모든 게 라이브로.

세 가지 백엔드, 모양은 같습니다.

| 백엔드 | 환경 | 언제 어울리는지 |
|---|---|---|
| **[cmux](https://github.com/manaflow-ai/cmux)** | macOS GUI 앱 | 에이전트가 알아서 페인을 다루는 네이티브 윈도우가 익숙할 때 |
| **tmux** | 모든 Unix 터미널 | 평소 tmux로 살고 있을 때 |
| **zellij** | 모든 Unix 터미널 | zellij 디폴트가 더 편할 때 |

---

## central-mcp과 cmux는 왜 잘 맞나

cmux의 설계는 단순합니다. **에이전트가 자기 페인을 직접 다룬다**. cmux가 띄우는 모든 페인의 환경 변수에 `CMUX_WORKSPACE_ID`와 `CMUX_SURFACE_ID`가 들어 있고, 에이전트는 그 정보를 가지고 `cmux new-split`, `cmux send-text`, `cmux tree --json` 같은 CLI로 자기 레이아웃을 만듭니다.

이 방식은 central-mcp의 설계와 정확히 결이 같습니다.

- **상주 데몬 없음.** central-mcp은 프로젝트마다 `dispatch.jsonl`만 남깁니다. 무엇을 어디에 그릴지는 에이전트가 결정합니다.
- **로그 기반.** `cmcp watch <project>`는 결국 그 이벤트 로그의 tail에 sticky 헤더와 컬러를 입힌 것뿐입니다. cmux가 거기에 진짜 GUI 윈도우를 얹어주죠 — 네이티브 폰트, GPU 가속 스크롤, macOS Cmd-키 복붙.
- **에이전트 주도 셋업.** 첫 실행 시 `~/.central-mcp/AGENTS.md`가 같이 깔리는데, 거기에 cmux 호출 레시피가 들어 있습니다. 그래서 사용자는 *"watch 페인 셋업해줘"* 한 마디만 던지면 됩니다. 설정 파일 한 줄 안 만져요.

결과: 사용자는 진짜 macOS 앱 안에 있고, 한쪽 페인에서는 에이전트(Claude Code / Codex / Gemini / opencode)와 대화하고 있고, 한 문장 뒤에 그 주변으로 프로젝트 페인 그리드가 깔립니다. 각 페인은 자기 프로젝트의 dispatch 출력을 라이브로 보여줍니다. tmux 설정도, 외울 키 바인딩도, 터미널 에뮬레이터 오버헤드도 없습니다.

---

## cmux 시작하기

1. <https://github.com/manaflow-ai/cmux>에서 cmux를 설치합니다 (macOS).
2. cmux.app을 열고 워크스페이스를 하나 만듭니다.
3. 워크스페이스의 첫 페인에서 `cmcp`로 orchestrator를 띄웁니다.
4. orchestrator에게 한 마디: *"현재 워크스페이스의 모든 프로젝트에 watch 페인 깔아줘."*
5. orchestrator가 `~/.central-mcp/AGENTS.md`(설치 시 함께 들어가는 cmux 레시피 포함 가이드)를 읽고, 프로젝트마다 `cmux new-split`을 한 번씩 호출해 그리드를 만듭니다.

끝입니다. 각 페인이 `cmcp watch <project>`를 돌면서 자기 프로젝트 이벤트를 보여주고, 사용자는 orchestrator 페인에서 다음 dispatch로 넘어가면 됩니다.

> 그리드가 깔끔하게 잡히는 비결은 "한 번에 한 split, 순서대로"라는 룰입니다. 페인이 1개든 8개든 같은 규칙으로 작동하고, 사용자는 신경 쓰지 않아도 됩니다 — orchestrator가 알아서 처리합니다.

---

## tmux나 zellij로 시작하기

cmux GUI를 안 쓰셔도 두 터미널 백엔드 모두 1급 시민입니다.

```bash
cmcp up                    # 인터랙티브 픽커 (tmux / zellij 중 선택)
cmcp tmux                  # 바로 tmux로
cmcp zellij                # 바로 zellij로

cmcp tmux --workspace work # 워크스페이스 'work'의 프로젝트만
cmcp tmux --all            # 워크스페이스마다 세션을 하나씩
```

- 세션 이름은 `cmcp-<workspace>` (예: `cmcp-work`).
- 페인 0번은 orchestrator, 1번부터는 등록된 프로젝트마다 `cmcp watch <project>`.
- 정리할 땐 `cmcp down`.

두 백엔드 모두 별도 설정 파일이 없고, 외울 키 바인딩도 없습니다.

---

## 세 백엔드 공통 — `cmcp watch`

어느 백엔드를 쓰든 프로젝트 페인 안에서 도는 건 결국 이거 하나입니다.

- `~/.central-mcp/logs/<project>/dispatch.jsonl`을 한 줄씩 tail합니다.
- sticky 헤더에 프로젝트 이름, 현재 에이전트, 상태(idle / running / errored), 경과 시간을 고정합니다.
- ANSI 컬러로 가독성 챙김 — 산문은 그대로, 코드 블록은 magenta, 폴백 전이는 노랑 `↻`.
- 알려진 노이즈는 자동 필터 (Codex 상태 배너, Gemini deprecation 경고, 빈 줄 스팸 등).

평범한 터미널에서도 단독으로 띄울 수 있습니다: `cmcp watch my-app`.

---

## 스크린샷과 데모

!!! info "준비 중"
    실제 cmux + central-mcp 캡처(4-up 그리드, dispatch 진행 중 토큰 스트리밍, 30초 분량 화면 녹화)는 자산 녹화 후 이 자리에 올라갑니다. 그 전에는 [cmux 프로젝트 페이지](https://github.com/manaflow-ai/cmux)의 앱 스크린샷과, 설치 시 함께 들어가는 `~/.central-mcp/AGENTS.md`의 정확한 레시피를 참고하세요.

---

## 그래서, 관찰 모드 꼭 써야 하나요?

안 쓰셔도 됩니다. dispatch는 non-blocking이고, 결과는 다음 도구 호출에 묻어 돌아오고, "어떻게 됐어?"는 언제든 통합니다. 프로젝트가 한두 개라면 orchestrator와 대화만 해도 충분합니다.

이런 상황에선 빛납니다.

- **세 개 이상이 동시에 진행 중일 때.** 멈춘 에이전트를 다음 폴링까지 기다리지 않고 몇 초 안에 알아챕니다.
- **2분 이상 걸리는 long-running dispatch.** sticky 헤더의 경과 시간이 "멈춘 거야 느린 거야?" 하는 불안을 잠재워줍니다.
- **특정 프로젝트의 에이전트가 이상하게 굴 때.** 페인별 로그가 통합된 `orchestration_history` 응답보다 훨씬 읽기 쉽습니다.

위에 해당하지 않으면 관찰 모드는 건너뛰셔도 됩니다. central-mcp은 어느 쪽이든 똑같이 동작합니다.
