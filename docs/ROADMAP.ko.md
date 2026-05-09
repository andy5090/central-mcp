---
description: central-mcp의 앞으로 계획 — Visibility, Routing, Upstream agents, Workspaces, Distribution, Architecture 트랙. 제안은 GitHub 이슈로.
---

# 로드맵

central-mcp의 앞으로 계획만 모았습니다. 이미 출시된 변경은 [변경 이력](changelog.md)을 보세요.

> **제안하실 게 있으신가요?** [GitHub 이슈](https://github.com/andy5090/central-mcp/issues)로 던져주세요. 모든 이슈 읽고 있습니다.

표기: 📋 계획 · 💭 아이디어 · 🚧 진행 중

---

## Visibility

포트폴리오 뷰가 모든 화면에서 같은 모양이 되도록 정리하고, "dispatch가 돌고는 있는데 뭘 하는지 안 보인다" 갭을 메웁니다.

### 결과 retrieval

📋 **`tail_dispatch(dispatch_id, since_ts=null)` MCP 도구.** 진행 중인 dispatch의 최근 출력 청크를 시각 기준으로 받아옵니다. 지금 `check_dispatch`은 subprocess가 끝나야 `output`이 채워져서, orchestrator(와 TUI 사이드바)가 진행 중 출력을 보려면 `dispatch.jsonl`을 직접 파싱해야 합니다. 이걸 캡슐화.

📋 **`dispatches` 테이블 progress 컬럼.** `last_output_ts`, `output_bytes`, `attempt_count` 추가. 출력 청크마다 싸게 update, 읽기는 "이 dispatch가 살아있나 멈췄나" 표시기로 모든 관찰 화면에서 활용.

💭 **`wait_for_dispatch(dispatch_id, timeout_sec=300)` MCP 도구.** 서버 사이드에서 dispatch 종료 시점까지 폴링한 뒤 row 반환. "codex / gemini는 지속 폴링이 약하다" 갭을 메움 — LLM이 폴링 루프 대신 도구 호출 한 번. claude는 잘 해왔으니 이건 다른 두 에이전트용.

### 시각화

📋 **TUI 사이드바 expanded row.** 선택된 dispatch row가 펼쳐져서: 마지막 N줄 라이브 tail, elapsed, 토큰 델타, "마지막 output Xs 전" 헬스 힌트. 다른 row는 collapsed. `tail_dispatch` + 새 schema 컬럼 위에 바로 얹힘.

📋 **`token_usage.summary_markdown`을 monitor와 watch에서도 그대로 씁니다.** 0.10.18에서 만든 HUD가 지금은 orchestrator에서만 보입니다. 같은 렌더러를 curses monitor와 watch sticky 헤더에도 끼우면 화면 간 표기 차이가 사라집니다.

📋 **토큰 예산 + 알림.** `config.toml`에 프로젝트 / 워크스페이스 단위 토큰 캡을 두고, 임계 도달 시 dispatch 시작 시점에 노란 배너. 90% 넘으면 기존 quota fallback 체인이 토큰 예산도 같이 보고 다른 에이전트로 빠집니다.

💭 **휴리스틱 progress markers.** 출력 스트림에서 의미 있는 이벤트를 정규식으로 추출 — 파일 읽기/쓰기, 도구 호출, 테스트 실행, 빌드 단계 — dispatch당 작은 stripe로 표시("I/O: 2 reads · Tools: 5 · Tests: 3✓"). 패턴은 에이전트별로 다르니 `agents.AGENTS` adapter record에 `progress_markers: list[regex]` 필드로 들어감.

💭 **Dispatch 상세 화면.** TUI 키바인딩 (Enter)로 row → 전체 화면. prompt / output / chain / tokens / duration / progress-marker 타임라인. output이 markdown이면 markdown 렌더, 아니면 raw text.

💭 **Watch 모드에 누적 사용량 한 줄.** 지금은 `+ 42s`만 보이는데, `+ 42s · 8.97M tokens` 식으로 long-running dispatch의 비용이 한 눈에 들어오게.

---

## TUI · 1.0 마일스톤

자체 터미널 앱이 PTY로 orchestrator 에이전트를 안에 띄우고, 그 주변을 우리 chrome (token HUD, 활성 dispatch, 알림)으로 둘러싸는 트랙입니다. dispatch 완료에 *즉시* 반응 — MCP 클라이언트가 `notifications/resources/updated`를 forward해 주든 말든 우리가 직접 채널을 잡으니 무관해집니다. 이 트랙이 4개 orchestrator 모두에서 안정적으로 끝나는 시점이 **1.0 마일스톤**: central-mcp가 0.x를 졸업하고 1.0.0으로 올라가면서 SemVer 약속이 시작됩니다.

✅ **Phase 0 (0.12.0) — `cmcp tui --experimental`, claude 단독.** 2026-05-03 출시. `textual`로 outer chrome (header / sidebar / footer / 알림), `pyte`로 PTY emulation. 메인 페인 안: claude REPL pass-through. 사이드바: `token_usage.summary_markdown` + 활성 dispatch + 최근 완료. `dispatches.db`를 watch하는 데몬 형태의 watcher가 알림을 인라인으로 띄워줍니다. `--experimental` 플래그 강제 (없으면 actionable 에러). 설치는 옵션으로 `pip install 'central-mcp[tui]'`.

✅ **Phase B (0.13.0) — codex 추가.** 2026-05-03 출시. 같은 chrome, 두 번째 에이전트가 allowlist에 합류. `--agent claude|codex`가 constrained choice가 되고 Phase 0의 CSI / 공백 emphasis fix가 codex에도 그대로 적용.

📋 **Phase C (0.14.0) — gemini + opencode.** central-mcp이 알고 있는 4개 orchestrator를 모두 채움.

📋 **Phase D (0.15.0–0.x) — 안정화.** 자체 scrollback / search / copy. 한국어 IME와 더블폭 문자 corner case. 알림 정책 미세 조정 (`config.toml [tui].auto_inject = passive | hint | prompt`).

🎉 **1.0.0 — TUI production.** `--experimental` 플래그는 no-op (하위 호환), API 표면 잠김, 버전 pin 윈도우 닫힘, breaking change는 2.0 대상.

💭 **Open questions**
- 멀티 페인 레이아웃 — TUI 안에서 watch 페인을 여러 개 호스팅할지, 아니면 단일 페인 유지하고 사용자가 cmux / tmux / zellij로 위에 올리게 둘지.
- prompt injection을 얼마나 투명하게 할지. `hint` 모드는 사이드바에만 메시지를 띄우고 멈춤; `prompt` 모드는 그 hint를 에이전트 stdin에 그대로 타이핑. "도움됨"과 "방해됨" 사이 선이 흐림.

---

## Live agent panes

두 번째 실행 모드 — opt-in, 세션 단위, 기본 비대화 dispatch 경로의 보완재.

지금 모든 dispatch는 `stdin=DEVNULL`으로 떨어진 fresh subprocess라, 권한 프롬프트가 떠도 답할 수 없어서 `--dangerously-skip-permissions` (bypass 모드)가 사실상 강제였습니다. PTY 모드는 에이전트를 실제 TTY pair 안에서 돌려서, 권한 프롬프트가 라이브 패널에 그대로 떠 사용자가 실시간 답변, 대화 컨텍스트는 턴 사이에 유지, prompt cache는 warm하게 유지됩니다. 트레이드오프는 active 프로젝트당 상주 에이전트 프로세스 1개 — 그래서 100개 포트폴리오 전체가 아니라, 지금 실제로 옆에서 supervising하는 2~3개에만 띄우는 모델입니다.

두 모드는 같은 데이터 모델(`dispatches.db` + `dispatch.jsonl`, `mode="pty"` 마커만 다름)을 공유하므로 `cmcp watch`, TUI 사이드바, `orchestration_history` 모두 두 종류 dispatch를 구분 없이 보여줍니다.

✅ **Building blocks (0.12.2 unreleased).** `PtyTerminal(project=, agent=, cwd=)`이 dispatch event writer 역할 겸비: `submit_prompt(text)`이 `dispatches.db`에 `start` / `complete` 행 + `dispatch.jsonl`에 매칭 이벤트를 기록. 화면 안정성 watcher (커서 + 하단 6행 해시가 1.5s 동안 일치)가 status를 `complete`로 전환. PTY-mode dispatch는 reader 입장에서 MCP-mode dispatch와 구분 불가 — `mode="pty"` 마커만 차이.

📋 **`pty_sessions/<project>.json` 라이프사이클 + dispatch 가드.** PTY 위젯이 spawn 시 `{pid, agent, started_at}` 등록, unmount 시 제거; 읽기 시 stale-PID 청소. `dispatch()`이 이 registry를 참조해서 active PTY 프로젝트는 거부 (`{ok: false, error: "...", mode: "pty"}`). 사람이 패널 운전 중인데 백그라운드 fan-out이 prompt를 끼워넣는 사고를 차단.

📋 **PTY 모드용 output capture.** `pyte.HistoryScreen` (10000행 scrollback)을 `_capture_text()` helper와 묶어서 `_mark_complete` 시점에 전체 세션 텍스트를 `dispatches.output`에 스냅샷. 0.12.2에 명시한 "PTY-mode는 output 빈 문자열" 갭 해소. `check_dispatch(did)`이 실행 모드 무관하게 같은 shape 반환.

📋 **`pty_inbox` 큐 + `pty_submit(project, prompt)` MCP 도구.** 프로세스 경계 넘는 prompt 라우팅: orchestrator가 어느 프로세스에서든 `pty_submit` 호출 → 작은 SQLite 큐 테이블에 INSERT. TUI의 PtyTerminal이 250ms 주기로 자기 프로젝트 행만 폴링 → `submit_prompt()`로 라우팅. SQLite를 transport로 쓰는 이유는 `dispatches.db`로 같은 패턴이 이미 검증됨 — MCP는 API 표면에만 머물고 transport에는 안 끼어듦.

📋 **`list_projects`에 mode 노출.** 각 row가 `pty_sessions/` registry에서 파생된 `mode: "pty" | "mcp"` 캐리. orchestrator가 한 눈에 어느 프로젝트가 PTY-bound인지 보고 `pty_submit` vs `dispatch`을 선택. `data/CLAUDE.md`에 한 줄 정책 ("mode=pty 프로젝트는 dispatch 호출 금지")도 추가해서 LLM 가이드와 registry 강제가 일치.

💭 **tmux / zellij / cmux 레이아웃의 옵션 PTY 패널.** 지금 `cmcp tmux` / `cmcp zellij`은 프로젝트 패널을 `central-mcp watch <p>` (passive jsonl tail)로 채움. `--mode=pty` 같은 플래그나 프로젝트별 오버라이드로 그 패널을 프로젝트의 에이전트 CLI 자체로 채우면, 사용자가 passive 로그 tail 대신 라이브 인터랙티브 supervision 패널을 받음. watch 경로는 에이전트 상주가 부담스러운 프로젝트용으로 그대로.

💭 **Persistent REPL 대화 컨텍스트.** Long-lived 에이전트 REPL이면 후속 dispatch가 직전 상태를 잃지 않음 — 캐시 자동, `--resume` 플러밍 불필요. 트레이드오프: 상태 drift / 컨텍스트 비대. "/clear" 훅 또는 세션 회전 정책 필요. opt-in이 합리적.

💭 **권한 프롬프트 가시성.** PTY 모드에서는 에이전트가 `--dangerously-skip-permissions` **없이** 돌 수 있음 — 권한 프롬프트가 사용자가 답할 수 있는 패널에 그대로 뜨니까. 향후 `[live].permissions = ask | bypass` config가 프로젝트별 디폴트를 결정, `ask`이 진짜로 더 안전(이전엔 구조적으로 불가능했던) 선택지로 들어감.

---

## Routing

"매번 사용자가 에이전트를 고른다"에서 "central-mcp가 추천한다"로 점진 이동합니다.

📋 **`suggest_dispatch(project, prompt)` MCP 도구.** dispatch는 안 하고 `{agent, model, reasoning, fallback}`만 돌려줍니다. orchestrator가 추천을 보여주면 사용자가 받아들이거나 무시할 수 있습니다. 처음엔 휴리스틱(프롬프트 길이, 키워드, 현재 quota)으로 가다가, 데이터가 쌓이면 LLM 보조 분류기를 얹습니다.

📋 **예산 기반 fallback.** 지금은 quota 임계만 보고 다른 에이전트로 넘기는데, 토큰 예산도 같이 봐서 막히지 않게 합니다. Visibility의 예산 작업과 묶입니다.

💭 **`auto_dispatch` opt-in.** classify + dispatch를 한 번에. `config.toml [routing].auto = true`로만 켜집니다. `suggest_dispatch` 추천 수락률이 70% 넘는다는 게 데이터로 보이면 그때.

💭 **워크스페이스별 routing 오버라이드.** 워크스페이스마다 선호 에이전트가 다를 수 있으니 (`client-a`는 claude, `client-b`는 codex).

---

## Upstream agents

오케스트레이터를 외부 호출자에게 엽니다 — 개인용 자율 에이전트(스케줄 데몬, persistent self-referential 루프, 챗 / 브라우저 브릿지)가 사용자가 REPL 앞에 없어도 central-mcp에 작업을 위임할 수 있도록.

지금은 오케스트레이터가 `cmcp run`으로 띄우는 인터랙티브 REPL로만 존재합니다. upstream MCP 클라이언트가 `dispatch`를 직접 부를 수는 있지만, 그러면 오케스트레이터의 routing / fallback / localization / 충돌 감지 레이어를 우회 — central-mcp가 더하는 가치를 잃습니다. 이 갭을 메우려면 오케스트레이터에 비대화 진입 채널이 필요합니다.

✅ **Hermes Agent (Nous Research) 통합 (0.12.2 unreleased).** Hermes는 OpenClaw 후계 — 멀티플랫폼 delivery (Telegram / Discord / Slack), 내장 cron, skill curation, 양방향 MCP를 갖춘 self-improving agentOS. 신규 `_Hermes` 어댑터가 `hermes -z PROMPT`을 dispatch용으로 감싸고 (`--continue` / `--resume <id>` / bypass용 `--yolo --accept-hooks`), `cmcp install hermes`이 `~/.hermes/config.yaml`의 `mcp_servers.central`에 central-mcp를 등록해서 Hermes의 LLM이 `dispatch` / `list_projects` / `check_dispatch`를 자기 도구로 봅니다. `cmcp run --agent hermes`로 Hermes를 오케스트레이터로 띄우거나 `add_project --agent hermes`로 dispatch 대상으로 등록 — 프로젝트별 선택. Hermes의 gateway 층은 dispatch 완료를 비-CLI 표면에 surface하기 자연스러운 곳이고 (장시간 dispatch 끝났을 때 Telegram alert), cron으로 daily / weekly central-mcp 요약을 봇 인프라 없이 chat 플랫폼에 보낼 수 있습니다.

📋 **`dispatch_orchestrator(prompt, agent=None, workspace=None)` MCP 도구.** 비대화 오케스트레이터 서브프로세스(claude `-p`, codex `exec`, gemini `-p`, opencode 동등 옵션)를 띄우고, central-mcp MCP 도구를 로드하고, 프롬프트를 전달한 뒤 `dispatch_id`를 즉시 반환 — 호출자는 `check_dispatch`로 최종 stdout을 폴링. `_launch_dispatch` 배관을 그대로 재활용.

📋 **`cmcp ask "<prompt>"` CLI.** MCP를 안 쓰는 upstream 에이전트용 동기 셸 래퍼. 에이전트 resolution은 `cmcp run`과 동일.

💭 **에이전트별 비대화 모드 MCP 로딩 검증.** claude `-p` / codex `exec`는 확정 경로, gemini `-p` / opencode는 짧은 스파이크 필요. phasing은 TUI 트랙과 동일 — claude 먼저, 나머지 후속.

💭 **Persistent 오케스트레이터 세션.** 매 ask마다 서브프로세스를 띄우는 대신 long-lived 오케스트레이터를 재사용. 사용 데이터가 spawn 비용이 LLM 지연 대비 무시할 수 없다는 걸 보여줄 때만 정당화.

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
- **`dispatch()`에 인터랙티브 승인을 베이크인.** 기본 dispatch는 non-interactive 유지 — `stdin=DEVNULL`, bypass 모드, 사람이 루프에 없음. 중간 승인은 [Live agent panes](#live-agent-panes) 트랙으로, 세션 단위 opt-in (PTY 패널). 두 경로는 데이터와 registry를 공유하고, 정책 선택은 글로벌이 아니라 프로젝트 단위.
- **별도 daemon 프로세스.** `cmcp tui`가 long-running watcher 역할을 합니다 — asyncio task가 LLM 턴과 무관하게 `dispatches.db`를 tail하고 완료를 바로 surface합니다. 추가로 설치·관리·디버깅할 두 번째 프로세스 없음.

---

## 변경 제안하기

위에 어디에도 안 맞는 use case가 있나요? 새 MCP 도구 아이디어? "이거 매일 나를 느리게 한다" 같은 불편?

→ **[GitHub 이슈를 올려주세요](https://github.com/andy5090/central-mcp/issues/new)**. 짧은 설명과 컨텍스트(어떤 orchestrator, 어떤 워크스페이스, 무엇을 시도했는지)면 충분합니다. 추상적 phasing보다 실사용 시그널이 로드맵을 더 많이 움직입니다 — 좋은 이슈 하나가 종종 💭를 📋로 끌어올립니다.
