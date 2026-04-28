# 빠른 시작

central-mcp을 처음 들은 시점에서 "방금 세 프로젝트에 동시에 dispatch 했어"까지 3분.

## 1. 설치

```bash
curl -fsSL https://central-mcp.org/install.sh | sh
```

설치 스크립트가 하는 일:

1. [`uv`](https://docs.astral.sh/uv/)가 없으면 부트스트랩.
2. `uv tool install central-mcp` 실행 — PyPI에서 최신 버전을 가져옵니다.
3. `central-mcp init` — `~/.central-mcp/registry.yaml` 스캐폴드 + `cmcp` 단축 alias 생성.

??? info "수동 설치 (curl 스크립트 안 쓰고)"
    ```bash
    # 1. uv 설치 (이미 있으면 스킵)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # 2. central-mcp 설치
    uv tool install central-mcp

    # 3. 일회성 셋업
    central-mcp init
    ```

    `pip install central-mcp`도 동작합니다 (uv 대신 pip 선호 시).

## 2. 프로젝트 하나 등록

아무 터미널에서:

```bash
cmcp add my-app ~/Projects/my-app --agent claude
```

다른 프로젝트도 같은 방식으로. 등록된 목록 확인:

```bash
cmcp list
```

## 3. orchestrator 띄우기

```bash
cmcp
```

선호하는 orchestrator(claude / codex / gemini / opencode)를 띄우고 그 안으로 central-mcp의 MCP 도구가 노출됩니다.

## 4. 자연어로 말하기

orchestrator 세션 안에서:

> *"my-app에 다크 모드 토글 추가해줘."*

orchestrator가 하는 일:

1. 프로젝트 이름(`my-app`) 파싱.
2. `dispatch("my-app", "다크 모드 토글 추가")` 호출 — 즉시 `dispatch_id` 반환.
3. 에이전트 작업이 끝나면 비동기로 결과 보고 (3가지 채널: 다음 도구 호출에 piggyback / 백그라운드 폴링 / "어떻게 됐어?" 직접 질문).

대화는 그동안 끊기지 않습니다.

## 5. (선택) 라이브 관찰

```bash
cmcp up
```

tmux / zellij 중 인터랙티브 픽커. 프로젝트마다 한 페인씩 `cmcp watch <project>`를 돌리고, orchestrator는 옆에 둡니다.

## 다음으로

- [CLI 레퍼런스](cli.md) — 모든 서브커맨드.
- [MCP 도구](mcp-tools.md) — orchestrator가 실제로 호출하는 API.
- [워크스페이스](architecture/workspaces.md) — 프로젝트 그룹핑, 한 프롬프트로 그룹 전체에 fan-out.
