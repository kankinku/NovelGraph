# NovelGraph Current State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task, TDD before code and review after each task.

**Goal:** 확정 원고에서 검증한 정보로 현재 상태를 요청 범위와 근거에 맞게 조회한다.

**Architecture:** 기존 SQLite 승인/사건 원장을 보존한다. 제한된 state_set 이벤트로 최신 상태를 재생하고, query-state를 제공하며 Graphify는 파생 그래프로만 이용한다.

**Tech Stack:** Python 3, sqlite3, decimal, networkx, graphifyy (기존 설치).

**Spec:** docs/superpowers/specs/2026-11-09-novelgraph-current-state-design.md

## Global Constraints
- 비공개 원고·개인 자료·실 DB git 반영 금지, 합성 픽스처만.
- 신규 LLM API/별도 DB/서비스 금지, AST 변환 불필요.
- 자동 사실 추론/승인 금지. 원문 증거·상태 이력·승인 및 적용 경계 유지.
- 테스트: /shared/NovelGraph/.venv/bin/python -m unittest discover -s tests.

## Review Focus
- 한 항목이 여러 번 변경되면 마지막 확정값만 반환하는가?
- 미확정·미승인·미적용·미래 예정이 현재값에 유입되지 않는가?
- 서로 다른 통화/주식 수량/지분율을 금액으로 더하지 않는가?
- 동일 개체의 여러 관계와 출처를 덮어쓰지 않는가?
- 조회 중 데이터베이스에 변경이 발생하지 않는가?

### Task 1: 현재 상태 이벤트
**Files:** novelgraph/world_state.py, tests/test_current_state.py
**Interfaces:** world_state(db, work_id, episode) -> dict; 'facts', 'current_time' 추가. 새 'state_set' 이벤트: actor_id/category/item_id/value, 선택 unit/relation_status.
- [ ] RED: 회차별 자산/관계/시간/지식 갱신과 부적절한 음수·시간 역행 테스트 작성
- [ ] RED 실행 후 기대한 실패 확인
- [ ] GREEN: 기존 _payload/_replay를 최소 수정, Decimal/date 엄격 검사, 변경 이력과 출처 보존
- [ ] 신규 테스트 및 world_state 회귀
- [ ] 차분 검토 후 커밋

### Task 2: 요청 범위별 읽기 전용 질의
**Files:** novelgraph/state_query.py, novelgraph/__main__.py, tests/test_state_query.py
**Interfaces:** query_state(db, work_id: str, episode: int, subject_id: str, scope: str, *, history=False)->dict; CLI query-state --work-id --episode --subject --scope [--history].
- [ ] RED: 현금/자산/주식/관계/시간/내역 분리 및 정확 범위, 단위 불일치 테스트
- [ ] RED 실행, 실패 확인
- [ ] GREEN: 기존 replay 재사용, 현재값과 증거만 응답, 내역은 명시 옵션
- [ ] 신규+전체 회귀 테스트
- [ ] 차분 검토 후 커밋

### Task 3: Graphify 현재 상태 투영
**Files:** novelgraph/graphify_bridge.py, tests/test_graphify_projection.py
**Interfaces:** 최신 state_set을 state:<actor>:<category>:<item> 노드로 투영하고 entity, evidence에 연결.
- [ ] RED: 미적용 배제/최신 값/복수 관계/경로·근거 테스트
- [ ] 실패 확인
- [ ] GREEN: project_graph에 읽기 전용 최신 노드 투영
- [ ] Graphify 호환성 회귀
- [ ] 차분 검토 후 커밋

### Task 4: AI 인터페이스 및 차단 계약
**Files:** docs/02-architecture.md, README.md, tests/test_state_query.py
- [ ] RED: 미승인 및 원문 해시 불일치의 현재값 유입 방지 테스트
- [ ] 실패 확인 혹은 이미 동작하면 기존 회귀 증거 제시
- [ ] GREEN: 원고→LLM 후보→검증/반려→공식 적용→조회 사용 절차 명시. 안전 입증 없는 자동승인은 구현하지 않음
- [ ] 전체 통합 테스트 + 독립 리뷰 + 중요 문제 수정/재검증
- [ ] 문서 및 코드 차분 검토 후 커밋

## 별도 후속 단계
안전한 자동 승인 정책, 별칭 자동 매칭, DB 오류 이후 영향범위 자동 복구, 실원고 전 회차 파일럿은 현재 기능 통합 후 별도 구현 계획으로 추진한다.
