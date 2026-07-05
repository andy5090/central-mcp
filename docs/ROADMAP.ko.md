---
description: central-mcp의 앞으로 계획 — Visibility, Routing, Upstream agents, Workspaces, Ecosystem alignment, Distribution, Architecture 트랙. 제안은 GitHub 이슈로.
---

# 로드맵

central-mcp의 앞으로 계획만 모았습니다. 이미 출시된 변경은 [변경 이력](changelog.md)을 보세요.

> **제안하실 게 있으신가요?** [GitHub 이슈](https://github.com/andy5090/central-mcp/issues)로 던져주세요. 모든 이슈 읽고 있습니다.

표기: 📋 계획 · 💭 아이디어 · 🚧 진행 중

## 2026년 스택에서 central-mcp의 자리

코딩 에이전트 생태계는 3계층 구조로 정리됐습니다: 실시간 협업은 **IDE 에이전트**, 터미널 실행은 **로컬 CLI 에이전트**, 비동기 위임은 **클라우드 에이전트**. 오케스트레이션도 표준화 중입니다 — Claude Code는 레포 내부 병렬화를 위한 네이티브 agent teams를 내놨고, 크로스 벤더 프로토콜(MCP Tasks 확장, A2A 1.0)이 장기 실행 위임 작업을 커버하기 시작했습니다.

central-mcp의 차선은 그 어디에도 없는 것입니다: **터미널 네이티브 허브 하나에서 크로스 프로젝트, 크로스 벤더 dispatch.** agent teams는 한 벤더 아래 한 레포를 병렬화하지만, central-mcp는 포트폴리오 전체를 각 프로젝트가 쓰는 에이전트 CLI로 라우팅합니다. 아래 우선순위가 이 포지셔닝에서 나옵니다 — 표준이 선 곳(Tasks, A2A)은 프로토콜 정렬, 단일 벤더 도구가 못 주는 visibility/routing 레이어는 더 깊게.

---

## Visibility

포트폴리오 뷰가 모든 화면에서 같은 모양이 되도록 정리하고, "dispatch가 돌고는 있는데 뭘 하는지 안 보인다" 갭을 메웁니다.

### 결과 retrieval

📋 **`tail_dispatch(dispatch_id, since_ts=null)` MCP 도구.** 진행 중인 dispatch의 최근 출력 청크를 시각 기준으로 받아옵니다. 지금 `check_dispatch`은 subprocess가 끝나야 `output`이 채워져서, orchestrator(와 TUI 사이드바)가 진행 중 출력을 보려면 `dispatch.jsonl`을 직접 파싱해야 합니다. 이걸 캡슐화.

📋 **`dispatches` 테이블 progress 컬럼.** `last_output_ts`, `output_bytes`, `attempt_count` 추가. 출력 청크마다 싸게 update, 읽기는 "이 dispatch가 살아있나 멈췄나" 표시기로 모든 관찰 화면에서 활용.

💭 **`wait_for_dispatch(dispatch_id, timeout_sec=300)` MCP 도구.** 서버 사이드에서 dispatch 종료 시점까지 폴링한 뒤 row 반환. "codex / gemini는 지속 폴링이 약하다" 갭을 메움 — LLM이 폴링 루프 대신 도구 호출 한 번. claude는 잘 해왔으니 이건 다른 두 에이전트용. [MCP Tasks 정렬](#ecosystem-alignment)이 먼저 끝나면, Tasks 확장을 말하는 클라이언트는 이 동작을 네이티브로 얻게 되어 이 도구는 호환 shim으로 축소됩니다.

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

✅ **Phase B (0.12.2) — codex 추가.** 2026-05-10 출시. 같은 chrome, 두 번째 에이전트가 allowlist에 합류. `--agent claude|codex`가 constrained choice가 되고 Phase 0의 CSI / 공백 emphasis fix가 codex에도 그대로 적용.

✅ **Phase C (0.14.0) — opencode + gemini.** 2026-07-04 출시. 4개 orchestrator 전부 임베딩 가능. 바이트 레벨 PTY 렌더링 프로브(실제 CLI → leak 필터 + pyte)로 새 필터 규칙이 필요 없음을 확인 — Phase 0의 `<`/`>` private-prefix CSI 필터가 새 에이전트들의 출력까지 이미 커버합니다.

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

이 트랙의 근거는 더 강해졌습니다: 프런티어 CLI들의 순수 능력이 수렴하면서(Terminal-Bench 2.1에서 Codex CLI와 Claude Code가 0.5포인트 이내), 흥미로운 라우팅 신호는 더 이상 "어느 에이전트가 더 똑똑한가"가 아니라 **비용, 쿼터 여유, 작업 형태, 프로젝트 적합도** — 정확히 central-mcp가 이미 에이전트별로 추적하는 상태들입니다.

📋 **`suggest_dispatch(project, prompt)` MCP 도구.** dispatch는 안 하고 `{agent, model, reasoning, fallback}`만 돌려줍니다. orchestrator가 추천을 보여주면 사용자가 받아들이거나 무시할 수 있습니다. 처음엔 휴리스틱(프롬프트 길이, 키워드, 현재 quota)으로 가다가, 데이터가 쌓이면 LLM 보조 분류기를 얹습니다.

📋 **예산 기반 fallback.** 지금은 quota 임계만 보고 다른 에이전트로 넘기는데, 토큰 예산도 같이 봐서 막히지 않게 합니다. Visibility의 예산 작업과 묶입니다.

💭 **`auto_dispatch` opt-in.** classify + dispatch를 한 번에. `config.toml [routing].auto = true`로만 켜집니다. `suggest_dispatch` 추천 수락률이 70% 넘는다는 게 데이터로 보이면 그때.

💭 **워크스페이스별 routing 오버라이드.** 워크스페이스마다 선호 에이전트가 다를 수 있으니 (`client-a`는 claude, `client-b`는 codex).

---

## Upstream agents

오케스트레이터를 외부 호출자에게 엽니다 — 개인용 자율 에이전트(스케줄 데몬, persistent self-referential 루프, 챗 / 브라우저 브릿지)가 사용자가 REPL 앞에 없어도 central-mcp에 작업을 위임할 수 있도록.

지금은 오케스트레이터가 `cmcp run`으로 띄우는 인터랙티브 REPL로만 존재합니다. upstream MCP 클라이언트가 `dispatch`를 직접 부를 수는 있지만, 그러면 오케스트레이터의 routing / fallback / localization / 충돌 감지 레이어를 우회 — central-mcp가 더하는 가치를 잃습니다. 이 갭을 메우려면 오케스트레이터에 비대화 진입 채널이 필요합니다.

✅ **Hermes Agent (Nous Research) 통합 (0.12.2).** Hermes는 OpenClaw 후계 — 멀티플랫폼 delivery (Telegram / Discord / Slack), 내장 cron, skill curation, 양방향 MCP를 갖춘 self-improving agentOS. 신규 `_Hermes` 어댑터가 `hermes -z PROMPT`을 dispatch용으로 감싸고 (`--continue` / `--resume <id>` / bypass용 `--yolo --accept-hooks`), `cmcp install hermes`이 `~/.hermes/config.yaml`의 `mcp_servers.central`에 central-mcp를 등록해서 Hermes의 LLM이 `dispatch` / `list_projects` / `check_dispatch`를 자기 도구로 봅니다. `cmcp run --agent hermes`로 Hermes를 오케스트레이터로 띄우거나 `add_project --agent hermes`로 dispatch 대상으로 등록 — 프로젝트별 선택. Hermes의 gateway 층은 dispatch 완료를 비-CLI 표면에 surface하기 자연스러운 곳이고 (장시간 dispatch 끝났을 때 Telegram alert), cron으로 daily / weekly central-mcp 요약을 봇 인프라 없이 chat 플랫폼에 보낼 수 있습니다.

📋 **`dispatch_orchestrator(prompt, agent=None, workspace=None)` MCP 도구.** 비대화 오케스트레이터 서브프로세스(claude `-p`, codex `exec`, gemini `-p`, opencode 동등 옵션)를 띄우고, central-mcp MCP 도구를 로드하고, 프롬프트를 전달한 뒤 `dispatch_id`를 즉시 반환 — 호출자는 `check_dispatch`로 최종 stdout을 폴링. `_launch_dispatch` 배관을 그대로 재활용.

📋 **`cmcp ask "<prompt>"` CLI.** MCP를 안 쓰는 upstream 에이전트용 동기 셸 래퍼. 에이전트 resolution은 `cmcp run`과 동일.

💭 **에이전트별 비대화 모드 MCP 로딩 검증.** claude `-p` / codex `exec`는 확정 경로, gemini `-p` / opencode는 짧은 스파이크 필요. phasing은 TUI 트랙과 동일 — claude 먼저, 나머지 후속.

💭 **Persistent 오케스트레이터 세션.** 매 ask마다 서브프로세스를 띄우는 대신 long-lived 오케스트레이터를 재사용. 사용 데이터가 spawn 비용이 LLM 지연 대비 무시할 수 없다는 걸 보여줄 때만 정당화.

💭 **오케스트레이터 A2A 엔드포인트.** A2A가 Linux Foundation 아래에서 150+ 기관의 지지를 받으며 1.0에 도달 — 에이전트 간 위임의 공용어가 되어가고 있고, MCP와는 보완 관계입니다(에이전트 사이는 A2A, 에이전트와 도구 사이는 MCP). `dispatch_orchestrator`를 얇은 A2A 서버 뒤에 노출하면 A2A를 말하는 어떤 에이전트든(엔터프라이즈 프레임워크, 클라우드 에이전트, 남의 데몬) MCP나 우리 CLI를 몰라도 포트폴리오 작업을 central-mcp에 위임할 수 있습니다. `dispatch_orchestrator`가 먼저 출시되고 구체적인 upstream 소비자가 나타나야 착수 — 호출자가 없는데 엔드포인트부터 만들지는 않습니다.

💭 **클라우드 에이전트를 dispatch 타깃으로.** 2026년 스택은 작업을 로컬 CLI와 비동기 클라우드 에이전트(Codex cloud task, Claude Code cloud 세션)로 나눕니다. 지금 dispatch는 항상 "프로젝트 cwd의 로컬 subprocess"인데, `target: cloud` 변형이 프롬프트를 에이전트의 클라우드 백엔드에 넘기고 PID 대신 API를 폴링하게 할 수 있습니다. `dispatch_id` / `check_dispatch` 계약은 동일, executor만 다름. 벤더별 API가 안정화된 후에 — 표면이 아직 출렁입니다.

---

## Workspaces

per-process 워크스페이스 스코프(`CMCP_WORKSPACE`)는 0.11.0에서 출시했습니다. 다음은 세션 단위 가시성과 shared context.

📋 **영속 세션 ID.** `cmcp run` 인스턴스마다 `id`, `workspace`, `started_at`, `last_seen_at`, `pid`, `terminal_kind`을 추적하는 새 `sessions` 테이블. 새 `cmcp sessions ls` 명령의 backend가 되고, 각 `dispatch_id`를 시작한 세션과 링크합니다. 워크스페이스 3개 이상을 동시에 굴릴 때 어느 터미널이 어느 dispatch를 띄웠는지 구별이 필요해지면 유용합니다.

📋 **세션별 history.** `orchestration_history(session=<id>)`로 그 세션이 시작한 dispatch만 보기. opt-in, 디폴트 off — 대부분은 워크스페이스 단위 격리만 있어도 충분합니다.

💭 **워크스페이스별 `CLAUDE.md` / `AGENTS.md` overlay.** `~/.central-mcp/workspaces/<name>/AGENTS.md`가 그 워크스페이스로 launch 시 base orchestrator 가이드에 추가됩니다. 클라이언트마다 작업 합의가 다를 때 유용합니다.

💭 **워크스페이스별 user 프롬프트.** 그 워크스페이스 안의 모든 dispatch에 적용되는 워크스페이스 전용 `user.md` overlay.

---

## Ecosystem alignment

MCP 스펙이 출시 이후 최대 개편을 지나고 있습니다 — **2026-07-28 릴리즈**가 프로토콜 코어를 stateless로 만들고(`initialize` 핸드셰이크·세션 헤더 제거, capability는 매 요청 `_meta`에), 장기 실행 작업을 공식 **Tasks 확장**으로 승격합니다: 서버가 `tools/call`에 task handle로 답하고, 클라이언트가 `tasks/get` / `tasks/update` / `tasks/cancel`로 구동하는 구조.

이 라이프사이클은 central-mcp가 첫날부터 출하한 `dispatch` → `check_dispatch` → `cancel_dispatch` 패턴과 *정확히* 같습니다 — 프로토콜이 방금 표준화한 설계에 우리가 독자적으로 수렴해 있었던 셈입니다. 정렬 비용은 낮고, 네이티브 클라이언트 지원이 따라옵니다.

v2 베타를 기다릴 필요도 없었습니다: 설치된 스택(fastmcp 3.x / mcp 1.x)이 2025-11-25 스펙의 experimental Tasks 프로토콜 타입을 이미 싣고 있어서, Phase 1–2를 그 위에 바로 출하했습니다. Phasing:

✅ **Phase 1 — task 모델 기반 작업, SDK 의존성 없음.** 출하 완료: dispatch 상태 어휘를 Tasks 라이프사이클(`working` / `input_required` / `completed` / `failed` / `cancelled`)에 매핑하고 dispatch entry를 스펙 형태의 task 객체로 렌더링하는 `tasks_adapter` 모듈. deprecated 3종(Roots / Sampling / Logging — 12개월 유예) 의존성 감사는 깨끗. 노트는 [architecture/mcp-2026-spec-prep](architecture/mcp-2026-spec-prep.md).

✅ **Phase 2 — Tasks wire, 플래그 뒤에.** 출하 완료: `CENTRAL_MCP_TASKS=1`이면 서버가 같은 `dispatches.db` 상태를 백엔드로 `tasks/get` / `tasks/cancel` / `tasks/result` 핸들러를 등록 — taskId가 곧 dispatch_id. `check_dispatch` / `cancel_dispatch`는 무기한 유지; 확장은 같은 상태 위의 추가 wire shape이지 대체가 아닙니다. `tasks/list`는 의도적으로 미제공(2026-07-28 릴리즈에서 제거). 플래그 off 기본값은 이전과 바이트 단위로 동일.

📋 **Phase 3 (stable v2 출시 시) — shape 마이그레이션 + 기본값 전환.** fastmcp / 공식 SDK가 최종 확장 모델을 출시하면: Phase-2 핸들러를 experimental core-protocol shape에서 공식 Tasks 확장으로 마이그레이션(capability 광고, `tools/call`의 task handle 반환), 플래그 제거, 기계적 stateless-core conformance 스윕. central-mcp는 설계상 이미 요청 간 stateless(load-bearing 불변식)라 아키텍처 작업은 없을 전망입니다.

💭 **Agent-teams 보완 노트.** Claude Code의 네이티브 agent teams(experimental)는 *한 레포, 한 벤더 안에서* 팀원을 병렬화합니다. 둘은 경쟁이 아니라 조합입니다: team lead 세션이 central-mcp MCP 도구를 들고 팀 세션 중간에 크로스 프로젝트 작업을 dispatch할 수 있습니다. agent teams가 experimental을 졸업하면 `data/CLAUDE.md`에 짧은 레시피로 — cmux 레시피와 같은 패턴, 코드가 아니라 문서.

---

## Distribution

📋 **CLI / MCP 도구 레퍼런스 자동 생성.** 지금은 [CLI](cli.md), [MCP 도구](mcp-tools.md) 페이지가 손으로 큐레이션 중입니다. `scripts/gen_docs.py`가 `argparse._SubParsersAction`을 walk하고 `server.py`에 `inspect.signature`를 돌려서 페이지를 만들면, CI 가드가 소스와 drift 발생 시 빌드를 실패시킵니다.

💭 **Windows 인스톨러 (PowerShell).** 지금 `install.sh`는 macOS / Linux만 커버합니다. 평행선으로 PowerShell 버전이 있으면 Windows 진입이 풀립니다.

---

## Architecture

천천히 결정할 변경들. 사용 데이터가 복잡성을 정당화할 때만 실제로 손댑니다.

💭 **MCP push notifications.** 완료된 dispatch에 대한 server-initiated `notifications/resources/updated` 이벤트. 2026-07-28 스펙 방향은 이게 실현되지 *않는* 쪽을 가리킵니다: 프로토콜 코어가 stateless·poll-first로 갔고(Tasks 확장이 push 스타일 결과를 `tasks/get` 폴링으로 의도적으로 대체), 클라이언트의 server-initiated 알림 지원은 늘기보다 줄어들 가능성이 큽니다. `cmcp tui`(직접 db 폴링)가 권장 알림 경로로 유지되고, MCP 호출자에게는 [Tasks 매핑](#ecosystem-alignment)이 표준 트랙의 답입니다. 어떤 클라이언트가 알림 surface를 1급으로 출시할 경우를 대비해 아이디어로만 유지.

💭 **에이전트 capability registry override.** 지금은 `agents.AGENTS`가 단일 진실의 원천. `config.toml`의 `[agents.<name>]` 블록으로 호스트별 capability 오버라이드를 허용합니다 (예: 일부 환경에서 OAuth 흐름이 깨진 codex의 `has_quota_api = false` 처리).

---

## 안 할 것들

이건 의도적으로 "안 합니다" — 사용자 시간 + 우리 시간 양쪽을 아끼는 결정입니다.

- **브라우저 UI.** central-mcp는 터미널 네이티브. 관찰은 tmux/zellij 페인이나 로그 tail로.
- **에이전트 상태 동기화.** 각 에이전트 CLI가 자기 대화 상태를 갖습니다. central-mcp는 dispatch를 orchestrate, 라이프사이클을 관찰, 토큰 사용량을 집계 — 세션 history를 복제하지는 않습니다.
- **`dispatch()`에 인터랙티브 승인을 베이크인.** 기본 dispatch는 non-interactive 유지 — `stdin=DEVNULL`, bypass 모드, 사람이 루프에 없음. 중간 승인은 [Live agent panes](#live-agent-panes) 트랙으로, 세션 단위 opt-in (PTY 패널). 두 경로는 데이터와 registry를 공유하고, 정책 선택은 글로벌이 아니라 프로젝트 단위.
- **레포 내부 agent teams / swarm.** 한 레포 안에서 에이전트 여럿을 병렬화하는 건 벤더들의 홈그라운드입니다(Claude Code agent teams, Codex 멀티 에이전트, 그리고 붐비는 커뮤니티 오케스트레이터들). central-mcp는 한 단계 위에 머뭅니다: 프로젝트당 dispatch 하나, 프로젝트와 벤더를 가로질러. 한 레포에 에이전트 5개가 필요하면 central-mcp가 dispatch한 프로젝트 안에서 벤더의 team 기능을 돌리세요.
- **별도 daemon 프로세스.** `cmcp tui`가 long-running watcher 역할을 합니다 — asyncio task가 LLM 턴과 무관하게 `dispatches.db`를 tail하고 완료를 바로 surface합니다. 추가로 설치·관리·디버깅할 두 번째 프로세스 없음.

---

## 변경 제안하기

위에 어디에도 안 맞는 use case가 있나요? 새 MCP 도구 아이디어? "이거 매일 나를 느리게 한다" 같은 불편?

→ **[GitHub 이슈를 올려주세요](https://github.com/andy5090/central-mcp/issues/new)**. 짧은 설명과 컨텍스트(어떤 orchestrator, 어떤 워크스페이스, 무엇을 시도했는지)면 충분합니다. 추상적 phasing보다 실사용 시그널이 로드맵을 더 많이 움직입니다 — 좋은 이슈 하나가 종종 💭를 📋로 끌어올립니다.
