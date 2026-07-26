---
description: central-mcp의 앞으로 계획 — 포트폴리오 PM이라는 본질을 중심으로 재편. Pulse 브리핑, 상태 장부, 멀티에이전트 협업, 보고 표면, dispatch 코어, 생태계 정렬. 제안은 GitHub 이슈로.
---

# 로드맵

central-mcp의 앞으로 계획만 모았습니다. 이미 출시된 변경은 [변경 이력](changelog.md)을 보세요.

> **제안하실 게 있으신가요?** [GitHub 이슈](https://github.com/andy5090/central-mcp/issues)로 던져주세요. 모든 이슈 읽고 있습니다.

표기: 📋 계획 · 💭 아이디어 · 🚧 진행 중

## 본질 — 디스패치 허브가 아니라 포트폴리오 PM

*2026-07 재정의. 이전 포지셔닝 — "터미널 네이티브 허브 하나에서 크로스 프로젝트, 크로스 벤더 dispatch" — 은 수단을 설명했습니다. 이번 것은 일 자체를 설명합니다.*

central-mcp는 한 가지 인간의 문제를 위해 존재합니다: **에이전트 기반 프로젝트를 4개 이상 동시에 굴리는 사람은 반드시 맥락을 잃습니다.** 에이전트가 느려서가 아니라 — 그 어느 때보다 빠릅니다 — 아무도 PM 역할을 하지 않기 때문입니다. 컨텍스트 스위칭마다 재적응 비용이 청구됩니다: *내가 자리 비운 사이 여기서 무슨 일이 있었지? 지금 어떤 상태지? 다음에 뭘 하려고 했었지?*

central-mcp의 일은 그 PM이 되는 것입니다. 등록된 모든 프로젝트에 대해 **무슨 일이 있었고, 지금 어디에 있고, 다음이 무엇인지**를 항상 말할 수 있어야 하고 — 필요한 순간에 말해줘야 합니다: 프로젝트로 복귀할 때, 뭔가 끝나거나 실패했을 때, 그리고 정기 다이제스트 주기마다. 성공 지표는 단순합니다: 프로젝트 복귀 시 재적응 시간이 0에 수렴하고, 새는 일감이 없을 것.

이 페이지의 나머지 전부가 그 일을 위해 존재합니다:

- **Dispatch** (크로스 프로젝트, 크로스 벤더)는 PM의 *손* — 위임한 일이 실제로 처리되는 방법.
- **Surfaces** (TUI 관제탑, watch 페인, 라이브 PTY 페인)는 PM의 *보고 채널*.
- **멀티에이전트 협업**은 PM이 한 프로젝트에 계약자 한 명 대신 *팀*을 투입하는 것.
- **생태계 엔드포인트** (MCP Tasks, A2A)는 사람만이 아니라 다른 에이전트도 PM에게 물어볼 수 있게 하는 것.

이번 재정의가 정면으로 마주하는 갭: 지금 허브는 자기를 *거쳐간* 일만 압니다 — `orchestration_history`는 dispatch 이벤트를 읽으므로, 직접 커밋·인터랙티브 에이전트 세션·수동 편집은 보이지 않습니다. 진짜 PM은 상태 보고를 기다리지 않고 레포를 직접 읽습니다. 이 갭을 메우는 것이 아래 [Portfolio PM](#portfolio-pm) 트랙의 첫 항목입니다.

2026년 스택에서의 자리를 압축하면: 벤더의 agent teams는 *한 벤더 아래 한 레포*를 병렬화하고, 클라우드 에이전트는 비동기 단일 작업을 흡수하고, IDE 에이전트는 실시간 페어링을 맡습니다. central-mcp는 그 누구도 차지하지 않은 층 — 벤더를 가로지르는 포트폴리오 전체 — 을 유지하면서, 이제 한 단계 더 깊이 들어갑니다: **한 프로젝트 안에서의 크로스 벤더 협업**, 어떤 단일 벤더 팀 기능도 제공할 수 없는 조합입니다.

---

## 1.0 마일스톤 — PM이 작동하는 순간

이전에는 TUI 안정화 단독이 1.0을 정의했습니다. 재정의: **4개 orchestrator 전부에서 PM 루프가 실제로 작동하는 시점에 1.0을 출시합니다.**

1. **복귀 브리핑** — `project_pulse` + 브리핑 레시피가 어떤 프로젝트에 대해서든 신뢰할 수 있는 "무슨 일이 있었고 / 지금 어디고 / 다음이 뭔지"를 내놓음. central-mcp 밖에서 이뤄진 작업 포함.
2. **관제탑** — TUI가 4개 orchestrator를 안정적으로 호스팅(Phase D 완료)하고 포트폴리오 인지 사이드바를 갖춤.
3. **다이제스트** — 정기 포트폴리오 다이제스트가 실제로 눈이 가는 곳(터미널, 또는 Hermes 브릿지 경유 chat)에 도착.

1.0 시점에 TUI의 `--experimental` 플래그는 no-op이 되고(하위 호환 유지), API 표면이 잠기고, breaking change는 2.0 대상이 됩니다.

---

## Portfolio PM

새 무게중심 트랙입니다. 아키텍처는 의도적으로 2단계 — **pulse 먼저(stateless), 장부는 그 다음(durable)** — 라서 PM의 ground truth는 항상 레포에서 새로 계산되고, 저장 상태는 하중을 받지 않는 부가물로 남습니다.

✅ **`project_pulse(project)` MCP 도구 + `cmcp pulse [project]` (0.15.0).** 프로젝트에 대해 *지금* 알 수 있는 모든 것의 stateless 즉석 집계: git(브랜치, 최근 커밋, 워킹 트리 변경, upstream 대비 ahead/behind), dispatch(진행 중·stale·최근 결과·카운트), 기존 에이전트별 session reader를 통한 세션 활동, `gh` 경유 열린 PR 상태. 새 저장소 없음 — pulse는 매 호출마다 새로 계산되므로, central-mcp를 전혀 거치지 않은 작업(직접 커밋, 인터랙티브 세션)도 git이 진실의 원천이기 때문에 잡힙니다. 각 섹션이 `reason`과 함께 독립적으로 degrade하므로 신호 하나가 빠져도 pulse 전체가 무너지지 않습니다. 다른 모든 PM 기능이 딛고 서는 데이터 척추입니다.

📋 **복귀 브리핑.** PM의 대표 순간: 며칠 만에 프로젝트로 돌아오면 "무슨 일이 있었고 / 지금 어디고 / 다음이 뭔지"를 한 번에 받습니다. `cmcp brief`가 registry 나열에서 pulse 기반 포트폴리오 다이제스트로 승격되고, `data/{CLAUDE,AGENTS}.md`의 레시피가 orchestrator에게 사용자가 프로젝트로 컨텍스트 스위칭할 때마다 `project_pulse`로 내러티브 브리핑을 합성하도록 가르칩니다.

📋 **상태 장부 (phase 2).** `~/.central-mcp/projects/<name>/STATUS.md` — 프로젝트별 영속 기억: dispatch 완료 시 덧붙는 구조화된 델타(뭘 했고 뭐가 남았는지), 열린 질문들, 그리고 세션과 orchestrator를 넘어 살아남는 "다음 할 일" 목록. `cmcp note <project> "…"`로 수동 항목 추가. 이후 브리핑은 장부(의도, 다음 할 일)와 pulse(ground truth)를 결합하고 둘 사이의 드리프트를 표시합니다. registry와 같은 평문 파일 — 요청 간 stateless 불변식은 유지됩니다.

📋 **푸시 보고.** 일간/주간 다이제스트와 이벤트 알림(dispatch 실패, 장시간 dispatch 완료)을 새 데몬 없이 배달: TUI watcher가 로컬에서 surface하고, Hermes 브릿지(cron + Telegram/Discord gateway, 0.12.2–0.14.0 출하)가 터미널 밖으로 운반합니다. Hermes skill의 스케치를 pulse 기반 다이제스트 포맷을 갖춘 1급 레시피로 승격.

💭 **물으면 답하는 비서 강화.** `orchestration_history`에 git 인지 결합 — 포트폴리오 답변이 더 이상 dispatch 이벤트에 갇히지 않습니다. 프로젝트별 저비용 pulse 읽기를 fan-out하는 `include_pulse` 플래그가 유력.

💭 **워크스페이스별 overlay.** `~/.central-mcp/workspaces/<name>/AGENTS.md`가 그 워크스페이스의 orchestrator 가이드를 보강하고, 워크스페이스 단위 `user.md`가 그 안의 모든 dispatch에 얹힙니다. 포트폴리오 그룹핑은 PM 개념이므로 이제 여기 삽니다(구 Workspaces 트랙에서 이동).

---

## Multi-agent collaboration

**명시적 non-goal에서 승격.** 예전 논리 — 레포 내부 병렬화는 벤더들의 홈그라운드 — 는 *단일 벤더* 팀(Claude Code agent teams, Codex 멀티에이전트)에는 여전히 참입니다. 놓쳤던 것: **크로스 벤더** 조합. 한 에이전트가 구현하고 다른 벤더의 에이전트가 리뷰하는 것 — central-mcp가 이미 소유한 크로스 벤더 라우팅을 한 단계 깊이 적용한 것일 뿐입니다. 어떤 벤더 팀 기능도 못 하는 일입니다.

📋 **순차 역할 체인 먼저.** `dispatch_chain(project, steps)` — 각 step이 에이전트와 역할 프롬프트를 지정하고, 이전 step의 출력이 다음 step의 컨텍스트로 주입됩니다. 대표 체인: 구현(에이전트 A) → 리뷰(에이전트 B) → 리뷰 반영(에이전트 A). step들은 `chain_id`를 공유하는 연결된 dispatch로 이력에 나타나고, 체인을 폴링하면 step별 상태가 돌아옵니다. 기존 dispatch 배관 위에 거의 그대로 얹히기 때문에 먼저 갑니다.

📋 **동시 병렬 스웜.** 같은 레포에 N개 에이전트가 동시 작업하되 git worktree로 격리 — `dispatch(..., isolation="worktree")`가 각 dispatch에 `~/.central-mcp/worktrees/<project>/<dispatch_id>` 아래 자기 체크아웃을 줍니다. central-mcp가 dispatch별 worktree를 추적하고 결과 안착을 돕습니다: 병합 순서, 충돌 표시 — 자동 병합이 아니라 보고 후 orchestrator/사람이 결정하는 쪽. 체인 다음 단계로 phasing; 충돌 UX가 어려운 부분입니다.

💭 **역할 프리셋.** 자주 쓰는 체인(구현→리뷰→수정, 리서치→구현, 테스트 작성→통과까지 구현)을 `config.toml`의 이름 붙은 프리셋으로 — 표준 체인이 step 목록 수작업 대신 프리셋 이름 하나로.

---

## Surfaces

PM의 보고 채널: TUI 관제탑, 감독 세션용 라이브 PTY 페인, 외부 멀티플렉서의 watch 페인.

### 관제탑 (TUI)

새 본질 아래 TUI의 역할: **항상 켜져 있는 관제탑** — 포트폴리오 전체가 한눈에 보이고 dispatch 완료가 즉시 surface되는 표면입니다(watcher가 `dispatches.db`를 직접 폴링하므로 MCP 클라이언트 협조가 필요 없습니다).

✅ **Phase 0 (0.12.0) — `cmcp tui --experimental`, claude 단독.** `textual` chrome (header / sidebar / footer / 알림), `pyte` PTY emulation, 사이드바에 `token_usage.summary_markdown` + 활성 dispatch + 최근 완료.

✅ **Phase B (0.12.2) — codex.** 같은 chrome, 두 번째 에이전트가 allowlist에 합류.

✅ **Phase C (0.14.0) — opencode + gemini.** 4개 orchestrator 전부 임베딩 가능. Phase 0의 CSI leak 필터가 새 에이전트들의 출력까지 이미 커버.

📋 **Phase D — 안정화.** 자체 scrollback / search / copy. 한국어 IME와 더블폭 문자 corner case. 알림 정책 미세 조정 (`config.toml [tui].auto_inject = passive | hint | prompt`). 1.0 게이트에 들어가는 항목.

📋 **포트폴리오 사이드바.** 사이드바를 dispatch 중심에서 PM 중심으로 진화: dispatch 피드만이 아니라 `project_pulse` 기반 프로젝트별 상태 라인(브랜치, 마지막 활동, 장부의 다음 할 일 힌트).

📋 **Expanded dispatch row.** 선택된 row가 펼쳐져서 마지막 N줄 라이브 tail, elapsed, 토큰 델타, "마지막 output Xs 전" 헬스 힌트. [Dispatch 코어](#dispatch-core-routing) 트랙의 `tail_dispatch` + progress 컬럼 위에 얹힘.

📋 **`token_usage.summary_markdown`을 `cmcp monitor`와 `cmcp watch`에서도 재사용.** 사전 렌더링된 HUD가 지금은 orchestrator에서만 보입니다. curses monitor와 watch 페인 sticky 헤더에 끼우면 표면 간 렌더링 드리프트가 사라집니다.

💭 **Dispatch 상세 화면.** row에서 Enter로 전체 화면 진입: prompt / output / chain / tokens / duration / progress-marker 타임라인.

💭 **휴리스틱 progress markers.** 출력 스트림에서 의미 있는 이벤트(파일 쓰기, 도구 호출, 테스트 실행)를 추출해 dispatch별 배지 stripe로. 패턴은 에이전트별이라 `agents.AGENTS`의 `progress_markers`에 삽니다.

💭 **Watch 모드에 누적 사용량.** `+ 42s` 대신 `+ 42s · 8.97M tokens`.

💭 **Open questions.** TUI 내부 멀티 페인 vs 외부 멀티플렉서와의 조합; prompt injection을 얼마나 투명하게 할지(`hint` vs `prompt` 모드).

### Live agent panes

opt-in, 세션 단위의 두 번째 실행 모드로, 기본 비대화 dispatch의 보완재입니다. PTY 모드는 에이전트를 실제 TTY pair 안에서 돌립니다: 권한 프롬프트가 사용자가 답할 수 있는 라이브 페인에 뜨고, 대화 컨텍스트가 턴 사이에 유지되고, prompt cache가 warm하게 유지됩니다. 트레이드오프는 활성 프로젝트당 상주 프로세스 1개 — 포트폴리오 전체가 아니라 지금 실제로 감독 중인 2~3개 프로젝트용입니다. 두 모드는 같은 데이터 모델(`dispatches.db` + `dispatch.jsonl`, `mode="pty"` 마커)을 공유하므로 모든 관찰 표면이 수정 없이 양쪽을 보여줍니다.

✅ **Building blocks + 세션 registry (0.12.2).** `PtyTerminal`이 dispatch event writer 겸업(`submit_prompt`가 start/complete 기록, 화면 안정성 watcher가 상태 전환). `pty_sessions/<project>.json` 라이프사이클 + stale-PID 청소, 그리고 `dispatch()`가 라이브 PTY 페인이 있는 프로젝트 호출을 거부해서 백그라운드 fan-out이 대화 중간에 prompt를 끼워넣지 못합니다.

📋 **PTY 모드 output capture.** `pyte.HistoryScreen` scrollback을 완료 시점에 `dispatches.output`으로 스냅샷 — 0.12.2에 명시한 갭 해소. `check_dispatch`가 실행 모드 무관하게 같은 shape을 반환하게 됩니다.

📋 **`pty_inbox` 큐 + `pty_submit(project, prompt)` MCP 도구.** 작은 SQLite inbox를 통한 프로세스 경계 넘는 prompt 라우팅; TUI의 PtyTerminal이 자기 프로젝트 행만 폴링해 `submit_prompt()`로 라우팅.

📋 **`list_projects`에 mode 노출.** 각 row가 `mode: "pty" | "mcp"`를 캐리해 orchestrator가 `pty_submit` vs `dispatch`를 한눈에 선택, `data/CLAUDE.md`에 대응 정책 한 줄.

💭 **tmux / zellij / cmux 레이아웃의 옵션 PTY 페인.** `--mode=pty` 플래그나 프로젝트별 오버라이드로 페인을 passive `watch` tail 대신 프로젝트의 에이전트 CLI로 채움.

💭 **Persistent REPL 대화 컨텍스트.** long-lived REPL이면 dispatch 간 컨텍스트가 공짜로 유지됩니다. 컨텍스트 비대에 대비한 "/clear" 훅 또는 세션 회전 정책 필요.

💭 **권한 프롬프트 가시성.** 사람이 페인을 보고 있으면 에이전트가 bypass 모드 *없이* 돌 수 있습니다: 프로젝트별 `[live].permissions = ask | bypass`, PTY 모드가 비로소 가능하게 만든 진짜 더 안전한 선택지가 `ask`입니다.

---

## Dispatch core & routing

PM의 손: dispatch 파이프라인 자체와, 일을 어디로 보낼지에 대한 지능. 프런티어 CLI들의 순수 능력이 수렴했으므로, 흥미로운 라우팅 신호는 비용·쿼터 여유·작업 형태·프로젝트 적합도 — central-mcp가 이미 추적하는 상태들입니다.

📋 **`tail_dispatch(dispatch_id, since_ts=null)` MCP 도구.** 완료를 기다리지 않고 시각 기준 최근 출력 청크 반환 — 지금은 subprocess가 끝나야 `output`이 채워져서 `dispatch.jsonl`을 직접 파싱하지 않으면 진행 중 출력을 보여줄 수 없습니다.

📋 **`dispatches` 테이블 progress 컬럼.** `last_output_ts`, `output_bytes`, `attempt_count` — 청크마다 싼 쓰기; 읽기는 모든 표면의 "살아있나 멈췄나" 표시기를 구동.

📋 **토큰 예산 + 알림.** `config.toml`의 프로젝트/워크스페이스별 캡; 임계 도달 시 dispatch 시작 시점에 배너.

📋 **`suggest_dispatch(project, prompt)` MCP 도구.** dispatch 없이 `{agent, model, reasoning, fallback}` 반환 — orchestrator가 추천을 보여주고 사용자가 수락하거나 무시. 휴리스틱 먼저; LLM 보조 분류기는 값어치가 증명되면.

📋 **예산 인지 fallback 체인.** quota 인지 체인(저장된 선호 → fallback → 남은 설치본)이 설정된 토큰 예산을 초과한 에이전트도 건너뜁니다.

📋 **영속 세션 ID.** `cmcp run` 인스턴스별 `sessions` 테이블(`id`, `workspace`, `started_at`, `pid`, `terminal_kind`) — `cmcp sessions ls`의 backend가 되고 각 dispatch를 시작한 세션과 링크. 워크스페이스 3개를 동시에 굴릴 때 유용.

📋 **세션별 history.** `orchestration_history(session=<id>)`로 그 세션의 dispatch만 필터.

💭 **`wait_for_dispatch(dispatch_id, timeout_sec=300)` MCP 도구.** 지속 폴링에 약한 클라이언트용 서버 사이드 blocking 폴링. MCP Tasks 정렬이 먼저 끝나면 Tasks를 말하는 클라이언트는 네이티브로 얻고 이 도구는 shim으로 축소.

💭 **`auto_dispatch` opt-in.** `[routing].auto = true` 뒤의 classify + dispatch 결합 — `suggest_dispatch` 수락률 70% 초과가 데이터로 보인 뒤에만.

💭 **워크스페이스별 routing 오버라이드.** 워크스페이스마다 다른 선호 에이전트(워크스페이스 `client-a`는 이 벤더, `client-b`는 저 벤더).

💭 **에이전트 capability registry override.** `config.toml`의 `[agents.<name>]` 블록으로 호스트별 capability 플래그 오버라이드(예: OAuth 흐름이 깨진 환경에서 `has_quota_api = false`).

---

## Ecosystem & distribution

바깥을 향한 얼굴들: 프로토콜 정렬, PM을 프로그램적으로 쓰려는 upstream 호출자, 패키징.

### MCP Tasks alignment

MCP 2026-07-28 릴리즈가 프로토콜 코어를 stateless로 만들고 장기 실행 작업을 공식 **Tasks 확장**으로 승격합니다 — central-mcp가 첫날부터 출하한 `dispatch` → `check_dispatch` → `cancel_dispatch` 라이프사이클과 정확히 같습니다. 정렬 비용은 낮고 네이티브 클라이언트 지원이 따라옵니다.

✅ **Phase 1 — task 모델 기반 작업 (0.13.0).** dispatch 상태를 Tasks 라이프사이클에 매핑하는 `tasks_adapter`; deprecated 3종(Roots / Sampling / Logging) 감사는 깨끗.

✅ **Phase 2 — 플래그 뒤의 Tasks wire (0.13.0).** `CENTRAL_MCP_TASKS=1`이 같은 dispatch 상태를 백엔드로 `tasks/get` / `tasks/cancel` / `tasks/result`를 등록 — taskId가 곧 dispatch_id. 플래그 off 기본값은 바이트 단위 동일.

📋 **Phase 3 — shape 마이그레이션 + 기본값 전환.** 공식 SDK가 최종 확장 모델을 출시하면: capability 광고, `tools/call`의 task handle 반환, 플래그 제거, 기계적 stateless-core conformance 스윕(central-mcp는 설계상 이미 요청 간 stateless).

### Upstream agents

오케스트레이터를 프로그램적 호출자에게 엽니다 — 사람이 REPL 앞에 없어도 포트폴리오 작업을 위임하고 싶은 개인용 자율 에이전트들. `dispatch`를 직접 부르면 오케스트레이터의 routing / fallback / 충돌 감지 레이어를 우회합니다; 아래 항목들은 upstream 호출자에게 온전한 오케스트레이터를 줍니다.

✅ **Hermes Agent 브릿지 (0.12.2–0.14.0).** `_Hermes` 어댑터(dispatch 대상 *겸* orchestrator), Hermes 설정에 central-mcp를 등록하는 `cmcp install hermes` + 번들 orchestration skill, quota HUD의 Hermes 사용량. Hermes의 cron + Telegram/Discord gateway가 [Portfolio PM 푸시 보고](#portfolio-pm) 항목의 배달 레일입니다.

📋 **`dispatch_orchestrator(prompt, agent=None, workspace=None)` MCP 도구.** central-mcp 도구를 로드한 fresh 비대화 orchestrator(claude `-p`, codex `exec`, …)를 띄우고 `dispatch`와 같은 의미의 `dispatch_id` 반환.

📋 **`cmcp ask "<prompt>"` CLI.** MCP를 안 쓰는 upstream 에이전트용 `dispatch_orchestrator` 동기 셸 래퍼.

💭 **에이전트별 비대화 MCP 로딩 검증.** claude `-p` / codex `exec`는 확정; gemini `-p`와 opencode는 스파이크 필요.

💭 **Persistent orchestrator 세션.** 여러 upstream 호출에 걸친 long-lived orchestrator 1개 — spawn 비용이 무시 못 할 수준으로 증명되면.

💭 **A2A 엔드포인트.** `dispatch_orchestrator` 위의 얇은 A2A 서버로 A2A를 말하는 어떤 에이전트든 MCP나 우리 CLI를 몰라도 포트폴리오 작업을 위임 가능. `dispatch_orchestrator` 출시와 구체적 upstream 소비자의 존재가 선행 조건.

💭 **클라우드 에이전트를 dispatch 타깃으로.** 프롬프트를 벤더의 클라우드 백엔드에 넘기고 PID 대신 API를 폴링하는 `target: cloud` 변형 — 같은 `dispatch_id` / `check_dispatch` 계약, 다른 executor. 벤더별 API 안정화가 먼저.

💭 **Agent-teams 보완 노트.** team lead 세션이 central-mcp 도구를 들고 팀 세션 중간에 크로스 프로젝트 작업을 dispatch할 수 있습니다; 벤더 agent teams가 experimental을 졸업하면 `data/CLAUDE.md`에 짧은 레시피로.

💭 **MCP push notifications.** 2026-07-28 스펙 방향이 반대를 가리킵니다(stateless, poll-first 코어); 어떤 클라이언트가 알림 surface를 1급으로 출시할 경우에 대비한 아이디어로만 유지. TUI watcher와 Tasks 폴링이 답으로 유지됩니다.

### Distribution

📋 **CLI / MCP 도구 레퍼런스 자동 생성.** `scripts/gen_docs.py`가 argparse + `server.py`의 `inspect.signature`를 walk; drift 시 CI 실패.

💭 **Windows 인스톨러 (PowerShell).** 순수 Python 코어는 이미 돌아갑니다; 마찰은 설치 + alias 셋업.

---

## 안 할 것들

의도적인 "안 합니다" — 모두의 시간을 아끼는 결정입니다:

- **브라우저 UI.** central-mcp는 터미널 네이티브. 관찰은 TUI, 멀티플렉서 페인, 로그 tail로.
- **에이전트 상태 동기화.** 각 에이전트 CLI가 자기 대화 상태를 소유합니다. pulse는 브리핑을 위해 세션 활동과 git 이력을 *읽을* 뿐 — 에이전트 세션을 복제하거나 변경하지 않습니다.
- **`dispatch()`에 인터랙티브 승인 베이크인.** 기본 dispatch는 비대화 유지(`stdin=DEVNULL`, bypass 모드). 중간 승인은 [Live agent panes](#live-agent-panes) 트랙에서 세션 단위 opt-in.
- **단일 벤더 레포 내부 팀.** *(2026-07 개정 — 이전에는 레포 내부 멀티에이전트 작업 전체가 금지 대상이었습니다.)* 한 벤더의 자체 팀 기능으로 한 레포를 병렬화하는 건 여전히 벤더 몫입니다; 한 벤더의 팀원 5명이 필요하면 dispatch된 세션 안에서 그 벤더의 팀 기능을 돌리세요. 범위 안으로 들어온 것은 **크로스 벤더** 버전 — 벤더를 섞는 역할 체인과 worktree 스웜 — 으로, 이제 [멀티에이전트 협업](#multi-agent-collaboration) 트랙입니다.
- **별도 daemon 프로세스.** `cmcp tui`가 long-running watcher이고, 터미널 밖 스케줄링은 Hermes cron이 커버합니다. 추가로 설치·관리·디버깅할 두 번째 프로세스 없음.

---

## 변경 제안하기

위에 어디에도 안 맞는 use case가 있나요? 새 MCP 도구 아이디어? "이거 매일 나를 느리게 한다" 같은 불편?

→ **[GitHub 이슈를 올려주세요](https://github.com/andy5090/central-mcp/issues/new)**. 짧은 설명과 컨텍스트(어떤 orchestrator, 어떤 워크스페이스, 무엇을 시도했는지)면 충분합니다. 추상적 phasing보다 실사용 시그널이 로드맵을 더 많이 움직입니다 — 좋은 이슈 하나가 종종 💭를 📋로 끌어올립니다.
