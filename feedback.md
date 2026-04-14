# central-mcp feedback log

실사용 중 느낀 점을 여기에 쌓아두면, 다음 설계 세션에서 우선순위 매겨 Phase 3로 반영.

## 사용 방법

항목 하나당 3–5줄이면 충분. 완벽한 문장 쓰려고 애쓰지 말 것 — 나중에 제가 정리 가능.

**분류:**
- `bug` — 명백한 오동작
- `ux` — 동작은 하지만 불편함
- `missing` — 없는 기능
- `flaw` — 구조적 설계 문제
- `idea` — 단순 아이디어

---

## 템플릿

```
### [YYYY-MM-DD] <한 줄 요약>
- **분류:** bug | ux | missing | flaw | idea
- **상황:** (뭐 하고 있었는지)
- **기대:** (원한 동작)
- **실제:** (실제 동작)
- **회피:** (있으면 적어둘 것)
```

---

## 예상되는 초기 마찰 (참고용)

사용 전 예측한 항목들 — 실제 체감되면 아래 "관측된 피드백"으로 옮기기.

- dispatch_query 완료 시점 모름 (fire-and-forget)
- send-keys 특수문자 이스케이프 (`'"\`$`)
- start_project 후 에이전트 로딩 대기 필요
- hub 로그 tail pane에 여러 프로젝트 출력 섞임 (접두어 없음)
- pane 번호 ↔ registry 동기화 꼬임
- SessionStart hook uv run 콜드스타트 지연

## 관측된 피드백

### [2026-04-14] tmux 의존은 장기적으로 탈피하고 싶음
- **분류:** flaw / idea
- **상황:** 초기 설계 리뷰
- **기대:** 헤드리스 동작이 기본이고, tmux는 "눈으로 보고 싶을 때" 켜는 선택지
- **실제:** 모든 어댑터가 tmux pane을 전제로 동작
- **방향:** Phase 4 이후 `adapter.stream_dispatch()` 추상화 추가 — PTY(pexpect/ptyprocess) 또는 ACP JSON-RPC 경로를 tmux와 병렬로 제공. tmux는 선택적 "뷰 레이어"로 강등


