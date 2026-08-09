---
title: central-mcp
description: central-mcp는 에이전트 기반 프로젝트를 여러 개 동시에 굴리는 사람을 위한 포트폴리오 PM — Claude Code · Codex · Gemini · opencode · Hermes Agent · OpenClaw · gajae-code에 dispatch하고, 프로젝트로 복귀하면 pulse 브리핑을 받고, 매일 다이제스트가 찾아옵니다.
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

<h1 class="cmcp-hero-title">모든 프로젝트는 <span class="cmcp-hero-emph">central로 통합니다.</span></h1>

<p class="cmcp-hero-sub">Claude Code · Codex · Gemini · opencode · Hermes Agent · OpenClaw · gajae-code를 모든 프로젝트에 한꺼번에 풀어두세요. 그 중심에 Ultra PM이 서 있습니다 — 무슨 일이 있었고, 지금 어디에 있고, 다음이 무엇인지 항상 알고 있습니다. 토큰은 전부 일에 쓰고, 어디까지 했는지 떠올리는 데는 한 톨도 쓰지 않습니다.</p>

[시작하기](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/andy5090/central-mcp){ .md-button }
[PyPI](https://pypi.org/project/central-mcp/){ .md-button }

</div>

central-mcp는 에이전트 기반 프로젝트를 여러 개 동시에 굴리는 사람을 위한 **포트폴리오 PM**입니다. 어떤 MCP 클라이언트에서든 자연어로 요청만 던지면 orchestrator가 알맞은 프로젝트의 에이전트로 보내고 — non-blocking, 결과는 비동기로 — 프로젝트에 복귀하는 순간 그 프로젝트의 진짜 상태를 브리핑해 줍니다.

---

## 왜 central-mcp인가

에이전트는 프로젝트 4개, 8개, 15개를 동시에 *굴리는* 비용을 없앴습니다. 하지만 그것들을 *놓치지 않는* 비용은 그대로입니다. 컨텍스트 스위칭마다 재적응 비용이 청구되고 — *내가 자리 비운 사이 무슨 일이 있었지? 지금 어떤 상태지? 다음에 뭘 하려고 했었지?* — 아무도 PM 역할을 하지 않습니다.

central-mcp가 그 PM입니다:

- **Dispatch** — 어느 프로젝트의 에이전트에든 병렬로 일을 보내고, 도는 동안 계속 대화
- **Pulse** — 프로젝트로 복귀하면 "무슨 일이 있었고 / 지금 어디고 / 다음이 뭔지"를 레포 자체에서 계산 — 허브를 거치지 않은 작업(직접 커밋, 인터랙티브 세션)도 셉니다
- **Digest** — 고정 포맷의 일간/주간 포트폴리오 리포트, 상주 에이전트든 일반 crontab이든 chat으로 배달 가능
- **Observe** — 지금 따라가는 dispatch에 라이브 페인
- **어디서든 orchestrate** — 어떤 MCP 클라이언트든 프런트엔드가 되고, 특정 벤더에 묶이지 않습니다

dispatch는 매번 프로젝트의 작업 디렉터리에서 새로 띄우는 서브프로세스입니다 (`claude -p "..." --continue` 같은 식). 상주 프로세스도, 화면 긁기도 없고, 핵심 경로가 tmux에 묶이지도 않습니다.

## 어디서 만나는가 — 세 개의 층

central-mcp는 장소가 아니라 레이어입니다. 찾아가야 하는 전용 orchestrator는 잊히기 마련이라, 표면들은 나에게 닿는 방식 순으로 배열돼 있습니다:

1. **Ambient (주 진입로).** `cmcp install claude` 한 번이면 매일 쓰는 CLI의 모든 세션이 평소 도구들과 나란히 `dispatch`, `project_pulse`를 갖게 됩니다. 프로젝트를 열고 *"지금 어디까지 됐지?"* 물으면 브리핑이 그 자리에서 일어납니다.
2. **Reach.** [상주 agentOS 브릿지](#agentos-hermes-agent-openclaw)(Hermes 또는 OpenClaw)가 일일 다이제스트와 실패 알림을 Telegram/Discord로 보냅니다 — 터미널이 안 열려 있을 때 *나를 찾아오는* 유일한 채널.
3. **Focus.** `cmcp tui`(experimental) — 오케스트레이션 자체가 주 업무인 세션용. 뿌리고, 지켜보고, 감독하는 날.

## 디자인 원칙

1. **에이전트 중립.** MCP 도구가 정식 인터페이스. orchestrator도, dispatch 대상도 — 어느 한쪽에 묶이지 않게 설계됐습니다.
2. **Non-blocking dispatch.** `dispatch`는 100ms 안에 `dispatch_id`만 던져주고 빠집니다. 결과는 비동기로 돌아옵니다. 대화가 멈추는 일은 없습니다.
3. **Dispatch-router 프리앰블.** orchestrator는 순수 라우터로 동작하도록 안내됩니다 — 이름 파싱, dispatch 호출, 다음으로. 한 턴당 LLM 추론 시간을 1–2초 안쪽에 묶어둡니다.
4. **파일 기반 상태.** `registry.yaml` 하나가 전부의 진실. 별도 DB도, 동기화 매커니즘도 없습니다.

## 라이브 관찰 — cmux와 잘 맞습니다

페인은 지도가 아니라 현미경입니다: 프로젝트 하나의 원본 출력을 가까이 보여줌으로써 화면을 차지할 자격을 얻고, 포트폴리오 전체는 `cmcp pulse`와 다이제스트의 몫입니다. 그래서 관찰 그리드는 포커스를 유지합니다 — 등록된 전부를 타일링하는 대신, 지금 따라가는 프로젝트들(기본은 최근 활동순, `--projects`로 직접 선택)에 페인을 엽니다. 백엔드는 셋 — **[cmux](https://github.com/manaflow-ai/cmux)** (macOS GUI), tmux, zellij.

cmux는 의도적으로 1급 시민입니다. cmux의 "에이전트가 자기 페인을 직접 다룬다"는 철학과 central-mcp의 stateless / 로그 기반 설계가 정확히 맞아떨어지거든요. orchestrator에게 *"현재 워크스페이스의 watch 페인 깔아줘"* 한 마디만 던지면, 설정 파일 한 줄 안 만지고 깔끔한 그리드가 잡힙니다.

[관찰 모드 가이드 →](observation.md){ .md-button }

## agentOS와도 잘 맞습니다 — Hermes Agent, OpenClaw

상주 agentOS 런타임 둘이 central-mcp와 1급으로 짝이 됩니다: [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research)와 [OpenClaw](https://github.com/openclaw/openclaw). 둘 다 터미널에 묶인 orchestrator가 못 가진 것 — **내장 cron과 멀티 플랫폼 챗 게이트웨이**(Telegram · Discord · Slack 등) — 를 들고 오는데, 위 2단(Reach)이 필요로 하는 게 정확히 그것입니다. 그리고 둘 다 MCP를 양방향으로 다룹니다.

`cmcp install hermes` / `cmcp install openclaw` 한 줄이면 central-mcp가 각 런타임의 `central` MCP 서버로 등록되고, 그 순간부터 `dispatch` / `project_pulse` / `portfolio_digest`가 native tool이 됩니다. 설치는 각 런타임의 스킬 라이브러리에 **central-mcp orchestration 스킬**까지 넣습니다 — 번들 파일 하나가 두 런타임을 담당합니다. 그래서 도구만 쥐여주는 게 아니라 orchestration하는 법을 가르칩니다: 논블로킹 dispatch 루프, `@workspace` fan-out, 어떤 질문에 어떤 도구를 쓰는지, 그리고 아래 푸시 보고 레시피까지. `cmcp run --agent <둘 중 하나>`로 orchestrator로 띄우고, `add_project --agent <둘 중 하나>`로 dispatch 대상으로 등록 — 명령 하나로 양방향.

이런 조합이 흥미롭습니다:

- **일일 다이제스트, 실제 배달.** cron 잡이 `portfolio_digest`를 호출해 고정 포맷 리포트를 챗으로 그대로 전달합니다 — 커밋·dispatch 결과가 있는 활동 프로젝트, 경고(실패했거나 종료 안 된 dispatch, 미커밋 작업이 방치된 조용한 프로젝트), 쿼터 라인까지. 설치되는 스킬에 레시피가 단계별로 들어 있습니다.
- **재알림 없는 실패 경보.** `list_dispatches(status="failed", since=…)`가 런타임에게 커서를 줍니다: 새 것만 알리고, 워터마크를 전진시키고, 같은 실패를 두 번 알리지 않음 — 워터마크는 구독자가 보관하므로 central-mcp는 무상태 그대로.
- **휴대폰에서 포트폴리오 답변.** 텔레그램으로 한 줄 — *"오늘 뭐가 출시됐는지 정리해줘"* — 던지면 같은 도구들이 돌아갑니다. 터미널 안 열어도 됨.
- **dispatch 대상으로 잡기.** skills curation, 웹 검색, 멀티 모델 fallback이 프로젝트 앞단에 — 일회성 CLI보다 풍부한 추론이 필요한 경우에.

Hermes는 토큰 사용량도 추적됩니다. 토큰 HUD의 `SUBSCRIPTION QUOTA` 블록에 `hermes [ledger]` 라인이 있습니다 — `~/.hermes/state.db`를 시간/일/주 토큰 합계 + 비용으로 집계.

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
