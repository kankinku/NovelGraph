# Pilot model review status implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Follow RED→GREEN and preserve private manuscripts.

**Goal:** 회차별 최신 모델 검수 의견과 미검수 후보를 조회하고, 실제 11화 모델 검수까지 검증한다.

**Architecture:** 기존 `novelgraph/workflow.py::workflow_status`에서 같은 회차 `proposed` 후보만 기준으로 최신 `model_assessments` 레코드 집계. 기존 CLI/DB 스키마 불변. 실 원고 리뷰는 비공개 원장에서 `assess-candidate`만 실행.

**Tech Stack:** Python 3.12, stdlib sqlite3, unittest, Moon MCP.

**Spec:** [회차별 검수 진행 상태 설계](../../33-pilot-model-review-status-design-2026-11-05.md)

## Global Constraints
- 공개 repo에 원고/개인 평가/DB/증거 인용 금지.
- 추가 LLM API/MCP/영구 DB 스키마 금지.
- 모델 의견은 승인도 사람 gold도 아님.
- 코드는 기존 `workflow-status` 출력 확장만. 기존 소비자 및 `next_actions` 호환.
- 이전 27건 보류를 강제로 해소하지 않음.

## Review Focus
1. 같은 후보가 두 번 모델 평가되면 중복 카운트 금지.
2. 같은 DB의 다른 작품/회차 의견과 혼합 금지.
3. 모델 평가 없는 11화는 누락 15건으로 정확하게 표시.
4. 승인·거절 후보는 제안 후보의 미검수로 계산하지 않음.
5. 읽기 전용 조회가 공식 DB나 승인 상태를 변경하지 않아야 함.

### Task 1 — 회차별 최신 검수 상태 조회
**Files:** `novelgraph/workflow.py`, `tests/test_workflow_status.py`

**Interfaces:** `workflow_status(root,work,episode,observed_sha)->dict`; append `model_review: {supports:int,needs_review:int,unsupported:int,unassessed:int}`.
- [x] 합성 테스트 추가: 모델 평가 없는 proposed 2개는 unassessed 2, 최신 판정만 1회, 다른 작품/회차 제외, 승인/거절 제외, SHA/DB 읽기 전용.
- [x] `python -m unittest discover -s tests -p test_workflow_status.py -q`에서 RED 확인.
- [x] `model_assessments`가 존재할 때만 회차별 행 가져와 최신 의견을 집계하는 최소 수정. 별도 신규 모듈/테이블 금지.
- [x] GREEN 동일 명령 후 full suite 실행.
- [x] 실제 1~11화에 CLI 적용해 기본 분포 관찰.

### Task 2 — 실제 11화 내용 검수
**Files:** 비공개 `reports/`/Moon 공식 DB `model_assessments`만 기록.
- [x] 기존 후보 15건을 10화 기록·11화 원문과 비교, 부정확/미확정은 needs_review로 보존.
- [x] 기존 `assess-candidate`로 출처 검증되는 의견만 기록(11화 모델 의견 15건, 공식 상태 변화 0).
- [x] 두 번째 조회에서 11화 unassessed=0; 1~10화 기존 27건 needs_review 유지.
- [x] 실제 DB 무결성·SHA·공식 승인/적용 불변성 검증. 이전 원고/후보 JSON 불변.

### Task 3 — 운영 문서 및 Git 변경 감사
**Files:** `README.md`, `docs/33-...`, 계획 문서
- [x] 모델 리뷰 지표와 실제 상태 원장 차이 설명.
- [x] full suite, diff check, 비공개 파일 없음 확인 및 자체 리뷰.
- [ ] GitHub PR 작성, CI/검증 확인. 사용자는 평소 main 병합 지시했지만 이번 명령에 병합 승인 구체 없음: 기존 워크플로와 호환되는 검증 PR까지 진행.
