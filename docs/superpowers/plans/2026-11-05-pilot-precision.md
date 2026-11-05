# [1/N] 37건 재검수와 금액·서명 정규화 구현 계획

**Goal:** 기존 NovelGraph의 모호 금액과 대리 서명 분리, 37개 개인 검수 보류의 안전한 교정 초안.
**Architecture:** 기존 continuity.py / world_state.py의 선택적 필드만 확장, 원고는 Moon 비공개 파일에만.
**Spec:** docs/34-pilot-precision-2026-11-05.md

## Constraints / review focus
- 기존 118건 제안 상태/출처/승인·적용 불변.
- 55만 이상 vs 정확 55만 및 약 38만 vs 정확 38만 구별.
- trust actor와 grandfather signer 분리, 과거 승인 계약 하위호환.
- 다른 작품/회차 금액 및 실제 원고는 공개 Git 금지.

## Task 1 — qualified money
- [x] tests/test_continuity.py에 relation, 동일 금액 다른 relation, 유효성 실패 테스트 먼저 추가.
- [x] RED 확인, continuity.py 최소 수정, GREEN 확인.

## Task 2 — delegate signer
- [x] tests/test_world_state.py에 economic holder/representative signer, 계약→지급→이전 테스트 추가.
- [x] RED 확인, world_state.py 최소 수정, GREEN 확인.

## Task 3 — 비공개 37건 교정 초안
- [x] 원문 전체 재대조, 37/37 old candidate IDs별 문제 유형·이전/새 사실·증거 보존.
- [x] 에피소드별 correction proposal candidate batches를 preflight하고 DB에 import 하지 않음.

## Task 4 — 검증·Git 통합
- [x] 전체 unittest 통과, 기존 118 후보/원본 SHA/승인 0 변동 없음.
- [ ] 공개 문서·코드·합성 테스트만 PR, 리뷰·CI 및 main 동기화.

## 실측
- 신규 합성 테스트 5건 RED를 실제 관찰한 후 GREEN; 전체 185/185 통과(425.415초).
- 실제 37/37 검수, 20개 수정 초안 preflight 통과, 17건 내용 유지/범위 해석 경고. 대상 1·3·4·5·8·10·11화.
- 3→5화 코카콜라 계약 ID는 동일하므로 ID 불일치 모델 경고를 오인으로 확인. 서명자와 권리 귀속자 구분.
- 개인 검수 파일·원고·DB는 공유 영역 비공개(0600)에만 보관, 공식 후보·승인·적용 불변.
