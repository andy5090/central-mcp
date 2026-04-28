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
  <img src="logo.png?v=0.11.0" alt="central-mcp" width="300" class="cmcp-hero-light"/>
  <img src="logo-dark.png?v=0.11.0" alt="central-mcp" width="300" class="cmcp-hero-dark"/>
</p>

<h1 class="cmcp-hero-title">Tokenmaxxing, <span class="cmcp-hero-emph">영리하게.</span></h1>

<p class="cmcp-hero-sub">Claude Code, Codex, Gemini, opencode를 등록된 모든 프로젝트에 병렬로 띄우세요. 토큰을 <span class="cmcp-hero-counter" data-min="10" data-max="100">10×</span> 태우면서도 — non-blocking, observable, 단일 에이전트에 발목 잡히지 않게.</p>

[시작하기](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/andy5090/central-mcp){ .md-button }
[PyPI](https://pypi.org/project/central-mcp/){ .md-button }

</div>

central-mcp은 모든 MCP 클라이언트(Claude Code, Codex, Gemini, opencode 등)를 코딩 에이전트 프로젝트 포트폴리오의 컨트롤 플레인으로 바꿉니다. 자연어로 말하면, orchestrator가 적절한 프로젝트의 에이전트로 요청을 라우팅 — non-blocking에, 결과는 비동기로 보고됩니다.

---

## 왜 central-mcp인가

여러 코딩 에이전트를 같이 쓰고 계실 겁니다. 각자 자기 터미널, 자기 세션, 자기 로그를 가집니다. 이리저리 옮겨다니는 비용이 큰데, *어느 에이전트가 무엇을 답했는지* 한 눈에 보는 곳이 없죠.

central-mcp은 그 허브를 제공합니다:

- **Dispatch** — 어떤 프로젝트의 에이전트에든 프롬프트를 보내고 MCP로 응답을 받습니다
- **병렬 작업** — 여러 프로젝트에 동시에 dispatch를 던져두고 대화를 계속하세요
- **레지스트리 관리** — `add_project` / `remove_project`로 프로젝트 추가·제거
- **클라이언트 자유** — 어떤 MCP 클라이언트든 orchestrator로 쓸 수 있어요. 한 곳에 묶이지 않습니다

각 dispatch는 프로젝트 cwd에서 새로 띄우는 서브프로세스입니다 (예: `claude -p "..." --continue`). long-lived 프로세스 없음, screen scraping 없음, 핵심 경로에 tmux 의존성 없음.

## 디자인 원칙

1. **에이전트 중립.** MCP 도구가 정식 인터페이스입니다. 어떤 MCP 클라이언트든 orchestrator가 될 수 있고, 지원되는 어떤 코딩 에이전트 CLI든 dispatch 대상이 될 수 있습니다.
2. **Non-blocking dispatch.** `dispatch`는 100ms 안에 `dispatch_id`를 반환합니다. 결과는 비동기로 도착하고요. 대화는 절대 멈추지 않습니다.
3. **Dispatch-router 프리앰블.** orchestrator는 순수 라우터로 동작하도록 지시받습니다 — 프로젝트 이름 파싱하고 `dispatch` 부르고 다음으로 넘어가기. 한 턴당 LLM 추론 지연을 1–2초 수준으로 유지합니다.
4. **파일 기반 상태.** `registry.yaml`이 유일한 진실의 원천.

## 라이브 관찰 — cmux 친화적

여러 프로젝트를 병렬로 돌리면서 모두 라이브로 보세요. central-mcp은 세 백엔드의 관찰 모드를 제공합니다: **[cmux](https://github.com/manaflow-ai/cmux)** (macOS GUI), tmux, zellij.

cmux는 의도적으로 1급 시민입니다 — "에이전트가 자기 페인을 직접 관리한다"는 cmux의 설계 철학이 central-mcp의 stateless / log-driven 모델과 정확히 맞아떨어지거든요. orchestrator에게 한 문장만 던지면 — *"현재 워크스페이스의 watch 페인을 셋업해줘"* — config 파일 한 줄 안 거치고 깨끗한 그리드가 잡힙니다.

[관찰 모드 가이드 →](observation.md){ .md-button }

## 설치

```bash
curl -fsSL https://central-mcp.org/install.sh | sh
```

uv가 없으면 자동 부트스트랩, PyPI에서 `central-mcp` 설치, `central-mcp init`까지 한 줄로.

## 지원 플랫폼

| 플랫폼 | 상태 |
| --- | --- |
| **macOS** | 주 개발·테스트 환경 |
| **Linux** | 동작할 것으로 예상; 정기 검증 X |
| **Windows** | 공식 테스트 X; cmux 백엔드는 macOS 전용 |

## 다음으로

- **[빠른 시작](quickstart.md)** — 설치 + 첫 dispatch
- **[CLI 레퍼런스](cli.md)** — 모든 서브커맨드
- **[MCP 도구](mcp-tools.md)** — API 표면
- **[관찰 모드](observation.md)** — 멀티 페인 라이브 뷰 (cmux / tmux / zellij)
- **[워크스페이스](architecture/workspaces.md)** — 프로젝트 그룹핑
- **[로드맵](ROADMAP.md)** — 앞으로 계획
- **[변경 이력](changelog.md)** — 출시된 변경
