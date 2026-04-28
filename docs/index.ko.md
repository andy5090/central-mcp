---
title: central-mcp
hide:
  - toc
---

<div class="cmcp-hero" markdown="1">

<div class="cmcp-hero-bg" aria-hidden="true">
  <span class="cmcp-lane" style="--speed: 6.0s; --offset: 0.0s; --top: 18%;"></span>
  <span class="cmcp-lane" style="--speed: 7.5s; --offset: 0.6s; --top: 32%;"></span>
  <span class="cmcp-lane" style="--speed: 5.5s; --offset: 1.1s; --top: 62%;"></span>
  <span class="cmcp-lane" style="--speed: 8.5s; --offset: 0.3s; --top: 78%;"></span>
</div>

<p class="cmcp-hero-logo">
  <img src="/logo.png?v=0.11.0" alt="central-mcp" width="300" class="cmcp-hero-light"/>
  <img src="/logo-dark.png?v=0.11.0" alt="central-mcp" width="300" class="cmcp-hero-dark"/>
</p>

<h1 class="cmcp-hero-title">Tokenmaxxing을 <span class="cmcp-hero-emph">영리하게.</span></h1>

<p class="cmcp-hero-sub">Claude Code · Codex · Gemini · opencode를 모든 프로젝트에 한꺼번에 풀어두세요. 컨텍스트 스위칭은 central-mcp이 대신 — 토큰은 <span class="cmcp-hero-counter" data-min="10" data-max="100">10×</span>까지, 집중력은 그대로.</p>

[시작하기](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/andy5090/central-mcp){ .md-button }
[PyPI](https://pypi.org/project/central-mcp/){ .md-button }

</div>

central-mcp은 어떤 MCP 클라이언트든(Claude Code, Codex, Gemini, opencode 등) 여러 코딩 에이전트 프로젝트를 한 번에 다루는 컨트롤 플레인으로 바꿔줍니다. 자연어로 요청만 던지면 orchestrator가 알맞은 프로젝트의 에이전트로 보내고, 결과는 비동기로 돌아옵니다. 대화는 멈추지 않습니다.

---

## 왜 central-mcp인가

여러 코딩 에이전트를 같이 쓰다 보면 매번 같은 문제에 부딪힙니다. 각자 자기 터미널, 자기 세션, 자기 로그를 갖고, 어느 창에 무슨 답이 있었는지 찾는 데 시간을 씁니다. 무엇이 무엇에 답했는지 한눈에 보이지 않죠.

central-mcp은 이걸 한 곳으로 모아줍니다.

- 어느 프로젝트의 에이전트에든 프롬프트를 던지고 MCP로 응답 받기
- 여러 프로젝트에 동시에 일을 맡겨두고 계속 다음 대화 이어가기
- `add_project` / `remove_project`로 등록 관리
- Claude Code든 Codex든, 손에 잡히는 MCP 클라이언트로 orchestrate

dispatch는 매번 프로젝트의 작업 디렉터리에서 새로 띄우는 서브프로세스입니다 (`claude -p "..." --continue` 같은 식). 상주 프로세스도, 화면 긁기도 없고, 핵심 경로가 tmux에 묶이지도 않습니다.

## 디자인 원칙

1. **에이전트 중립.** MCP 도구가 정식 인터페이스. orchestrator도, dispatch 대상도 — 어느 한쪽에 묶이지 않게 설계됐습니다.
2. **Non-blocking dispatch.** `dispatch`는 100ms 안에 `dispatch_id`만 던져주고 빠집니다. 결과는 비동기로 돌아옵니다. 대화가 멈추는 일은 없습니다.
3. **Dispatch-router 프리앰블.** orchestrator는 순수 라우터로 동작하도록 안내됩니다 — 이름 파싱, dispatch 호출, 다음으로. 한 턴당 LLM 추론 시간을 1–2초 안쪽에 묶어둡니다.
4. **파일 기반 상태.** `registry.yaml` 하나가 전부의 진실. 별도 DB도, 동기화 매커니즘도 없습니다.

## 라이브 관찰 — cmux와 잘 맞습니다

여러 프로젝트를 동시에 굴릴 때, 모든 진행 상황을 한 화면에서 볼 수 있어야 안심이죠. central-mcp은 세 가지 관찰 모드 백엔드를 지원합니다 — **[cmux](https://github.com/manaflow-ai/cmux)** (macOS GUI), tmux, zellij.

cmux는 의도적으로 1급 시민입니다. cmux의 "에이전트가 자기 페인을 직접 다룬다"는 철학과 central-mcp의 stateless / 로그 기반 설계가 정확히 맞아떨어지거든요. orchestrator에게 *"현재 워크스페이스의 watch 페인 깔아줘"* 한 마디만 던지면, 설정 파일 한 줄 안 만지고 깔끔한 그리드가 잡힙니다.

[관찰 모드 가이드 →](observation.md){ .md-button }

## 설치

```bash
curl -fsSL https://central-mcp.org/install.sh | sh
```

uv가 없으면 알아서 설치하고, PyPI에서 `central-mcp`을 받고, `central-mcp init`까지 한 번에 끝냅니다.

## 지원 플랫폼

| 플랫폼 | 상태 |
| --- | --- |
| **macOS** | 주 개발·테스트 환경 |
| **Linux** | 동작 예상 (정기 검증은 안 합니다) |
| **Windows** | 공식 검증 X. cmux 백엔드는 macOS 전용 |

## 어디부터 볼까

- [빠른 시작](quickstart.md) — 설치하고 첫 dispatch까지 3분
- [CLI 레퍼런스](cli.md) — 모든 서브커맨드
- [MCP 도구](mcp-tools.md) — orchestrator가 호출하는 API
- [관찰 모드](observation.md) — 멀티 페인 라이브 뷰 (cmux / tmux / zellij)
- [워크스페이스](architecture/workspaces.md) — 프로젝트 그룹핑
- [로드맵](ROADMAP.md) — 앞으로 계획
- [변경 이력](changelog.md) — 출시된 변경
