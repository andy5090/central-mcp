---
description: central-mcp의 앞으로 계획 — Visibility, Routing, Workspaces, Distribution, Architecture 트랙. 제안은 GitHub 이슈로.
---

# 로드맵

central-mcp의 앞으로 계획만 모았습니다. 이미 출시된 변경은 [변경 이력](changelog.md)을 보세요.

> **제안하실 게 있으신가요?** [GitHub 이슈](https://github.com/andy5090/central-mcp/issues)로 던져주세요. 모든 이슈 읽고 있습니다.

표기: 📋 계획 · 💭 아이디어 · 🚧 진행 중

---

## Visibility

포트폴리오 뷰가 모든 화면에서 같은 모양이 되도록 정리합니다.

📋 **`token_usage.summary_markdown`을 monitor와 watch에서도 그대로 씁니다.** 0.10.18에서 만든 HUD가 지금은 orchestrator에서만 보입니다. 같은 렌더러를 curses monitor와 watch sticky 헤더에도 끼우면 화면 간 표기 차이가 사라집니다.

📋 **토큰 예산 + 알림.** `config.toml`에 프로젝트 / 워크스페이스 단위 토큰 캡을 두고, 임계 도달 시 dispatch 시작 시점에 노란 배너. 90% 넘으면 기존 quota fallback 체인이 토큰 예산도 같이 보고 다른 에이전트로 빠집니다.

💭 **Watch 모드에 누적 사용량 한 줄.** 지금은 `+ 42s`만 보이는데, `+ 42s · 8.97M tokens` 식으로 long-running dispatch의 비용이 한 눈에 들어오게.

---

## TUI · 1.0 마일스톤

자체 터미널 앱이 PTY로 orchestrator 에이전트를 안에 띄우고, 그 주변을 우리 chrome (token HUD, 활성 dispatch, 알림)으로 둘러싸는 트랙입니다. dispatch 완료에 *즉시* 반응 — MCP 클라이언트가 `notifications/resources/updated`를 forward해 주든 말든 우리가 직접 채널을 잡으니 무관해집니다. 이 트랙이 4개 orchestrator 모두에서 안정적으로 끝나는 시점이 **1.0 마일스톤**: central-mcp가 0.x를 졸업하고 1.0.0으로 올라가면서 SemVer 약속이 시작됩니다.

🚧 **Phase 0 (0.12.0) — `cmcp tui --experimental`, claude 단독.** 새 experimental 서브커맨드. `textual`로 outer chrome (header / sidebar / footer / 알림), `pyte`로 PTY emulation. 메인 페인 안: claude REPL pass-through. 사이드바: `token_usage.summary_markdown` + 활성 dispatch + 최근 완료. `dispatches.db`를 watch하는 데몬 형태의 watcher가 알림을 인라인으로 띄워줍니다. `--experimental` 플래그 강제 (없으면 actionable 에러). 설치는 옵션으로 `pip install central-mcp[tui]`.

📋 **Phase B (0.13.0) — codex 추가.** 같은 셸, 두 번째 에이전트 어댑터. `adapters/base.py`에 패턴이 이미 있어서 확장은 기계적.

📋 **Phase C (0.14.0) — gemini + opencode.** central-mcp이 알고 있는 4개 orchestrator를 모두 채움.

📋 **Phase D (0.15.0–0.x) — 안정화.** 자체 scrollback / search / copy. 한국어 IME와 더블폭 문자 corner case. 알림 정책 미세 조정 (`config.toml [tui].auto_inject = passive | hint | prompt`).

🎉 **1.0.0 — TUI production.** `--experimental` 플래그는 no-op (하위 호환), API 표면 잠김, 버전 pin 윈도우 닫힘, breaking change는 2.0 대상.

💭 **Open questions**
- 멀티 페인 레이아웃 — TUI 안에서 watch 페인을 여러 개 호스팅할지, 아니면 단일 페인 유지하고 사용자가 cmux / tmux / zellij로 위에 올리게 둘지.
- prompt injection을 얼마나 투명하게 할지. `hint` 모드는 사이드바에만 메시지를 띄우고 멈춤; `prompt` 모드는 그 hint를 에이전트 stdin에 그대로 타이핑. "도움됨"과 "방해됨" 사이 선이 흐림.

---

## Routing

"매번 사용자가 에이전트를 고른다"에서 "central-mcp가 추천한다"로 점진 이동합니다.

📋 **`suggest_dispatch(project, prompt)` MCP 도구.** dispatch는 안 하고 `{agent, model, reasoning, fallback}`만 돌려줍니다. orchestrator가 추천을 보여주면 사용자가 받아들이거나 무시할 수 있습니다. 처음엔 휴리스틱(프롬프트 길이, 키워드, 현재 quota)으로 가다가, 데이터가 쌓이면 LLM 보조 분류기를 얹습니다.

📋 **예산 기반 fallback.** 지금은 quota 임계만 보고 다른 에이전트로 넘기는데, 토큰 예산도 같이 봐서 막히지 않게 합니다. Visibility의 예산 작업과 묶입니다.

💭 **`auto_dispatch` opt-in.** classify + dispatch를 한 번에. `config.toml [routing].auto = true`로만 켜집니다. `suggest_dispatch` 추천 수락률이 70% 넘는다는 게 데이터로 보이면 그때.

💭 **워크스페이스별 routing 오버라이드.** 워크스페이스마다 선호 에이전트가 다를 수 있으니 (`client-a`는 claude, `client-b`는 codex).

---

## Workspaces

per-process 워크스페이스 스코프(`CMCP_WORKSPACE`)는 0.11.0에서 출시했습니다. 다음은 세션 단위 가시성과 shared context.

📋 **영속 세션 ID.** `cmcp run` 인스턴스마다 `id`, `workspace`, `started_at`, `last_seen_at`, `pid`, `terminal_kind`을 추적하는 새 `sessions` 테이블. 새 `cmcp sessions ls` 명령의 backend가 되고, 각 `dispatch_id`를 시작한 세션과 링크합니다. 워크스페이스 3개 이상을 동시에 굴릴 때 어느 터미널이 어느 dispatch를 띄웠는지 구별이 필요해지면 유용합니다.

📋 **세션별 history.** `orchestration_history(session=<id>)`로 그 세션이 시작한 dispatch만 보기. opt-in, 디폴트 off — 대부분은 워크스페이스 단위 격리만 있어도 충분합니다.

💭 **워크스페이스별 `CLAUDE.md` / `AGENTS.md` overlay.** `~/.central-mcp/workspaces/<name>/AGENTS.md`가 그 워크스페이스로 launch 시 base orchestrator 가이드에 추가됩니다. 클라이언트마다 작업 합의가 다를 때 유용합니다.

💭 **워크스페이스별 user 프롬프트.** 그 워크스페이스 안의 모든 dispatch에 적용되는 워크스페이스 전용 `user.md` overlay.

---

## Distribution

📋 **CLI / MCP 도구 레퍼런스 자동 생성.** 지금은 [CLI](cli.md), [MCP 도구](mcp-tools.md) 페이지가 손으로 큐레이션 중입니다. `scripts/gen_docs.py`가 `argparse._SubParsersAction`을 walk하고 `server.py`에 `inspect.signature`를 돌려서 페이지를 만들면, CI 가드가 소스와 drift 발생 시 빌드를 실패시킵니다.

💭 **Windows 인스톨러 (PowerShell).** 지금 `install.sh`는 macOS / Linux만 커버합니다. 평행선으로 PowerShell 버전이 있으면 Windows 진입이 풀립니다.

---

## Architecture

천천히 결정할 변경들. 사용 데이터가 복잡성을 정당화할 때만 실제로 손댑니다.

💭 **MCP push notifications.** 완료된 dispatch에 대한 server-initiated `notifications/resources/updated` 이벤트. MCP 클라이언트 중 한 곳이라도 LLM 턴으로 surface하기 시작하면 합류 — 그 전까진 `cmcp tui`가 권장 알림 경로입니다.

💭 **에이전트 capability registry override.** 지금은 `agents.AGENTS`가 단일 진실의 원천. `config.toml`의 `[agents.<name>]` 블록으로 호스트별 capability 오버라이드를 허용합니다 (예: 일부 환경에서 OAuth 흐름이 깨진 codex의 `has_quota_api = false` 처리).

---

## 안 할 것들

이건 의도적으로 "안 합니다" — 사용자 시간 + 우리 시간 양쪽을 아끼는 결정입니다.

- **브라우저 UI.** central-mcp는 터미널 네이티브. 관찰은 tmux/zellij 페인이나 로그 tail로.
- **에이전트 상태 동기화.** 각 에이전트 CLI가 자기 대화 상태를 갖습니다. central-mcp는 dispatch를 orchestrate, 라이프사이클을 관찰, 토큰 사용량을 집계 — 세션 history를 복제하지는 않습니다.
- **인터랙티브 승인 / worker 모드.** dispatch는 의도적으로 non-interactive. 중간에 액션 승인이 필요하면 사용자가 에이전트를 직접 터미널에서 돌리세요.
- **별도 daemon 프로세스.** `cmcp tui`가 long-running watcher 역할을 합니다 — asyncio task가 LLM 턴과 무관하게 `dispatches.db`를 tail하고 완료를 바로 surface합니다. 추가로 설치·관리·디버깅할 두 번째 프로세스 없음.

---

## 변경 제안하기

위에 어디에도 안 맞는 use case가 있나요? 새 MCP 도구 아이디어? "이거 매일 나를 느리게 한다" 같은 불편?

→ **[GitHub 이슈를 올려주세요](https://github.com/andy5090/central-mcp/issues/new)**. 짧은 설명과 컨텍스트(어떤 orchestrator, 어떤 워크스페이스, 무엇을 시도했는지)면 충분합니다. 추상적 phasing보다 실사용 시그널이 로드맵을 더 많이 움직입니다 — 좋은 이슈 하나가 종종 💭를 📋로 끌어올립니다.
