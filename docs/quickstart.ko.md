---
description: central-mcp 설치, orchestrator 띄우기, 첫 병렬 dispatch까지 3분. 프로젝트 등록부터 fan-out까지 자연어 한 줄 흐름으로.
---

# 빠른 시작

central-mcp를 처음 듣는 시점부터 "방금 세 프로젝트에 동시에 일을 시켰어"까지 3분이면 됩니다.

## 1. 설치

```bash
curl -fsSL https://central-mcp.org/install.sh | sh
```

이 한 줄이 다음을 처리합니다.

1. [`uv`](https://docs.astral.sh/uv/)가 없으면 받아옵니다.
2. `uv tool install central-mcp` — PyPI에서 최신을 가져옵니다.
3. `central-mcp init` — `~/.central-mcp/registry.yaml`을 만들고 `cmcp` 단축 alias를 잡아둡니다.

??? info "직접 설치하고 싶다면"
    ```bash
    # 1. uv 설치 (이미 있으면 건너뛰기)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # 2. central-mcp 설치
    uv tool install central-mcp

    # 3. 첫 셋업
    central-mcp init
    ```

    pip를 더 좋아하신다면 `pip install central-mcp`도 됩니다.

## 2. orchestrator 띄우기

```bash
cmcp
```

선호 orchestrator(claude / codex / gemini / opencode 중 하나)를 골라 띄우고, 그 안으로 central-mcp의 MCP 도구가 자동 노출됩니다. 이후 작업은 모두 이 세션 안에서 자연어로 진행합니다.

## 3. 프로젝트 등록 (말로 던지기)

```text
~/Projects/my-app을 허브에 추가해줘. 에이전트는 claude로.
```

orchestrator가 이걸 `add_project(name="my-app", path="...", agent="claude")`로 풀어 호출하고 확인 응답을 줍니다. 다른 프로젝트도 같은 식으로 더 추가하면 됩니다. 등록 상태 확인:

```text
내 프로젝트 목록 보여줘.
```

??? info "CLI가 더 편하다면"
    같은 작업을 셸에서:

    ```bash
    cmcp add my-app ~/Projects/my-app --agent claude
    cmcp list
    ```

## 4. 작업 보내기

여전히 같은 세션 안에서:

> *"my-app에 다크 모드 토글 좀 추가해줘."*

이 한 마디로 orchestrator가 처리하는 것:

1. 프로젝트 이름(`my-app`)을 골라냅니다.
2. `dispatch("my-app", "다크 모드 토글 추가")`를 호출하고, `dispatch_id`를 즉시 받습니다.
3. 에이전트가 작업을 끝내면 결과를 비동기로 알려줍니다 — 다음 도구 호출에 묻어 오거나, 백그라운드 폴링으로, 또는 *"어떻게 됐어?"* 한 마디에 답해서.

그동안 사용자의 대화는 끊기지 않습니다.

## 5. 라이브로 보고 싶다면

```bash
cmcp up
```

tmux / zellij 중에 골라 띄울 수 있습니다. 프로젝트마다 한 페인씩 `cmcp watch <project>`를 깔고, orchestrator는 옆에 둡니다. 작업 흐름 전체가 한 화면에서 보입니다.

## 다음으로

- [CLI 레퍼런스](cli.md) — 사용할 수 있는 모든 명령
- [MCP 도구](mcp-tools.md) — orchestrator가 실제로 부르는 API
- [워크스페이스](architecture/workspaces.md) — 프로젝트를 그룹으로 묶고 한 번에 dispatch
