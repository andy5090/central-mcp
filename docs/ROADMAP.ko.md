# 로드맵

central-mcp의 앞으로 계획. 이 페이지는 **앞으로 진행될 내용만** 보여줍니다 — 이미 출시된 변경은 [변경 이력](changelog.md)에서 보세요.

> **제안하실 내용이 있으신가요?** [github.com/andy5090/central-mcp/issues](https://github.com/andy5090/central-mcp/issues)에 이슈를 올려주세요. 모든 이슈를 읽고 있습니다.

상태 표기: 📋 계획됨 · 💭 아이디어 · 🚧 진행 중

---

## Visibility

프로젝트 포트폴리오 뷰가 모든 표면에서 일관되도록.

📋 **`token_usage.summary_markdown`을 `cmcp monitor`와 `cmcp watch`에서 재사용.** 0.10.18에 들어간 pre-rendered HUD가 지금은 orchestrator 쪽에서만 보입니다. 같은 렌더러를 curses monitor와 watch sticky 헤더에도 연결하면 표면 간의 렌더링 drift가 사라집니다.

📋 **토큰 예산 + 알림.** `config.toml`에 프로젝트별 / 워크스페이스별 토큰 캡; 임계 도달 시 dispatch 시작 단계에서 노란 배너, 90% 넘으면 기존 quota-aware fallback 체인이 budget-aware fallback으로 확장됩니다.

💭 **Watch 모드: 경과 시간 옆에 누적 사용량.** `+ 42s` 단독이 아니라 `+ 42s · 8.97M tokens` 처럼 long-running dispatch의 비용을 가시화.

---

## Routing

"매 dispatch마다 사용자가 에이전트를 고르는" 방식에서 "central-mcp이 추천하는" 방식으로.

📋 **`suggest_dispatch(project, prompt)` MCP 도구.** 디스패치 안 하고 `{agent, model, reasoning, fallback}`만 반환 — orchestrator가 추천을 표시하면 사용자가 수락하거나 override 합니다. 휴리스틱 먼저 (프롬프트 길이, "refactor" / "research" / "review" 같은 키워드, 현재 quota 상태); LLM 보조 분류기는 가치가 입증되면 나중에.

📋 **Budget-aware fallback 체인.** 기존 quota-aware 체인(저장된 선호 → fallback → 나머지 설치된)이 토큰 예산을 초과한 에이전트도 스킵하도록 확장. Visibility의 budget 작업과 결합.

💭 **`auto_dispatch` opt-in.** classify + dispatch 결합; `config.toml [routing].auto = true`로 게이트. `suggest_dispatch` 데이터에서 사용자가 추천을 70% 이상 수락하는 게 입증된 후에만.

💭 **워크스페이스별 routing override.** 워크스페이스마다 다른 선호 에이전트 (예: `client-a`는 claude 디폴트, `client-b`는 codex).

---

## Workspaces

per-process 워크스페이스 스코프(`CMCP_WORKSPACE`)는 출시 완료. 다음 단계는 세션 레벨 가시성과 shared context.

📋 **영속 세션 ID.** `cmcp run` 인스턴스마다 `id`, `workspace`, `started_at`, `last_seen_at`, `pid`, `terminal_kind`을 추적하는 새 `sessions` 테이블. 새 `cmcp sessions ls` 명령의 backend가 되고, 각 `dispatch_id`를 그걸 시작한 세션에 링크합니다. 3개 이상 워크스페이스를 동시에 굴리면서 어느 터미널이 어느 dispatch를 소유하는지 보고 싶을 때 유용.

📋 **세션별 history 뷰.** `orchestration_history(session=<id>)`가 그 세션이 시작한 dispatch만 반환. opt-in, 디폴트는 off — 대부분 사용자는 워크스페이스 레벨 격리만 있어도 충분합니다.

💭 **워크스페이스별 `CLAUDE.md` / `AGENTS.md` overlay.** `~/.central-mcp/workspaces/<name>/AGENTS.md`가 그 워크스페이스 launch 시 base orchestrator 지시문에 추가됩니다. 작업 합의가 다른 client engagement에 유용.

💭 **Shared context: 워크스페이스별 user 프롬프트.** 그 워크스페이스 안의 모든 dispatch에 적용되는 워크스페이스 전용 `user.md` overlay.

---

## Distribution

📋 **CLI + MCP-tool 레퍼런스 페이지 자동 생성.** 지금 [CLI](cli.md), [MCP 도구](mcp-tools.md) 페이지는 수동으로 큐레이션 중. 작은 `scripts/gen_docs.py`가 `argparse._SubParsersAction`을 walk하고 `server.py`에 `inspect.signature`를 돌려 페이지를 재생성, CI 가드가 소스에서 drift 발생 시 빌드를 실패시키게.

💭 **Windows 인스톨러 (PowerShell).** macOS + Linux는 `install.sh`로 동작. PowerShell 평행선이 Windows 사용자의 진입을 풀어줄 것 — 순수 Python core는 거기서도 돌아가고, 마찰은 설치 + alias 셋업 부분.

---

## Architecture

천천히 굳혀갈 변경들 — 사용 데이터가 복잡성을 정당화할 때만 착수.

💭 **Lazy daemon.** 첫 MCP 연결이 백그라운드 daemon을 spawn, PID lock 잡고 Unix 소켓 노출; stdio `central-mcp serve`는 daemon 자동 감지하고 proxy. 이득: MCP 클라이언트당 cold-start ~150ms 절감, 세션 스캐너 중앙화, pre-work을 모을 한 곳. 0.10.9의 `dispatches.db`로 cross-process state는 이미 해결됐기에 시급성은 낮음.

💭 **MCP 클라이언트가 forward해줄 때 push notifications.** 완료된 dispatch에 대한 server-initiated `notifications/resources/updated` 이벤트. 현재 막힌 상태: 어떤 MCP 클라이언트도 이걸 LLM 턴에 surface하지 않음. 업스트림 추적 중; 적어도 한 클라이언트가 forward를 약속하면 착수.

💭 **에이전트 capability registry override.** 지금 `agents.AGENTS`가 단일 진실의 원천. `config.toml`의 `[agents.<name>]` 블록이 호스트별로 capability override를 허용 (예: 일부 환경에서 OAuth 흐름이 깨진 codex의 `has_quota_api = false` 마크).

---

## 의도된 비목표

이건 의도적 "안 할 것" — 모두의 시간을 절약합니다:

- **브라우저 UI.** central-mcp은 터미널 네이티브. 관찰은 tmux/zellij 페인이나 로그 tail에서.
- **에이전트 상태 동기화.** 각 에이전트 CLI가 자기 대화 상태를 관리. central-mcp은 dispatch를 orchestrate 하고, 라이프사이클을 관찰하고, 토큰 사용량을 집계 — 세션 history를 복제하지는 않습니다.
- **인터랙티브 승인 / worker 모드.** dispatch는 의도적으로 non-interactive. mid-run에 액션 승인이 필요하면 사용자가 에이전트를 터미널에서 직접 돌려야 합니다.
- **`central-mcp install <client>`의 stdio 대체.** daemon 모드가 들어와도 stdio가 디폴트 transport. daemon이 그 뒤에서 proxy, 클라이언트는 모릅니다.

---

## 변경 제안하기

위 어디에도 안 맞는 use case가 있나요? 새 MCP 도구 아이디어? "이게 매일 나를 느리게 만든다" 같은 불만?

→ **[GitHub 이슈를 올려주세요](https://github.com/andy5090/central-mcp/issues/new)** — 짧은 설명과 컨텍스트(어떤 orchestrator, 어떤 워크스페이스, 무엇을 시도했는지)와 함께. 추상적인 phasing보다 실사용 시그널이 로드맵을 더 많이 움직입니다 — 좋은 이슈 하나가 종종 💭를 📋로 promote 시킵니다.
