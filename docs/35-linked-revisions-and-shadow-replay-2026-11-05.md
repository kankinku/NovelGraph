# [2/N] 회차 교정안 계보·실제 등록과 독립 모의 재생 — 2026-11-05

## 목표 및 보존 계약
비공개 1~11화의 모델 검수 37건 중 기존 후보와 내용 또는 증거가 달라진 교정안 20건을 `proposed`로만 등록한다. 기존 후보는 변경/삭제/공식 거절하지 않는다. 대신 old→new 계보를 별도 테이블에 기록하고 과거 후보의 추후 공식 승인을 차단하여 동일 사건 중복 확정 위험을 막는다. 이미 검수자의 실제 신원 인증·독립 gold가 존재하는 것으로 가장하지 않는다.

## 데이터 구분
- 현재 11화 등록/118 후보/118 모델 의견/0 승인/0 적용. 대상 교정안 7개 회차에 20건, 모두 공식 DB에 없는 새 ID 확인.
- 교정안 입력 전 create-only 온라인 SQLite 백업. 공식 DB와 비공개 원고/후보 스냅샷 SHA 보존.
- 새 `candidate_revisions(old_candidate_id PRIMARY KEY, new_candidate_id UNIQUE, revised_at)` 테이블은 작품 ID·회차·원문 SHA가 같은 두 후보만 연결. old는 proposed이고 미대체, new는 아직 미등록된 본문 검증 후보여야 함. 같은 매핑 재입력은 멱등, 다른 매핑/부분 실패는 전부 롤백.
- `review-candidate`는 이 테이블에서 old가 대체됐으면 승인/거절 모두 차단(기존 권한 인증 경계는 그대로). 최신 new는 사람 확인 전 proposed.
- `workflow-status`에는 raw 역사 건수와 별개로 active proposed 및 superseded proposed, active proposed에 대한 `model_review` 집계 제공. 신규 의견 없는 교정안 20건은 unassessed로 나타남.

## 모의 재생 경계
- 기존 실제 DB 승인/적용 0 유지. **별도 복구한 SQLite 복제 DB에서만** 근거를 추출해 시뮬레이션 리뷰와 적용. 그 승인 레이블은 'synthetic_shadow'으로 반드시 구분한다.
- 3→5화: 조부 법적 서명·에블린 신탁 경제적 귀속, 계약 지분 15%, 1월 소급된 5화의 2만5천 달러 지급 및 지분 이전. 신탁 총자산 25만을 현금 개시 잔액이라고 임의 가정하지 않음. 따라서 정확 현금 잔액은 null, cash_movement는 -25000만 검증.
- 10→11화: 코디지 수익/잔액 55만 이상과 이리 풋 약 38만 지출은 `continuity_fact`로 정밀도 명시. 정산 준비는 `event`이지 `cash_receipt`가 아님. exact cash_payment 380000으로 확정하지 않고 현금 변동/총자산 미상 유지.
- 회차 시점 조회는 source episode와 effective episode 차이를 보존하고, 동일 거래 재실행 불가 증명.

## 검증 게이트
Superpowers RED→GREEN 실패 테스트(중복 ID/작품간 연결/부분실패 롤백/대체 이전 후보 승인차단/조회 제외), 전체 회귀, 실제 20개 교정안 일괄·멱등 테스트, 원고 SHA 11/11, 비공개 모의 복원, 보안 경로 검토, GitHub PR/CI, main 재검증.
완료 이전까지 사용자에게 의미 정확도가 독립 검증됐거나 현금 잔액이 확정됐다고 보고하지 않는다.

## 실 원고 파일럿 실측 — 2026-11-05

| 항목 | 실측 |
| --- | --- |
| 현재 원고 범위 | 동일 작품 1~11화 SHA 일치 |
| 수정 후보 준비 | 7개 회차의 20개 수정 JSON 전부 preflight 완료 |
| 교정 후보 공식 `proposed` 입력 | **20/20** 새로 등록 |
| 원본 후보 이력 | **118건 모두 보존**, 원문·불변 후보 ID 수정 0건 |
| DB에 남은 후보 이력 합계 | **138건** (옛 118+교정 20) |
| 대체 관계 | **20건** (old→new, 둘 다 같은 작품/회차/SHA) |
| 승인 대기 **현재 활성 후보** | **118건** (기존 118−대체된 20+새 20) |
| 활성 후보 모델 검수 상태 | 지지 81, 재검토 17, 신규 교정안 미검수 20 |
| 반복 import | 같은 7개 파일로 재실행 시 신규 등록 **0건**, DB 해시 동일 |
| 공식 승인·적용 | **0건 / 0건**, 계좌 잔액 변경 없음 |

등록 원본의 `candidate_counts.proposed=138`은 **역사 기록 수**이다. `workflow-status.revision_summary.active_proposed=118`이 실제 승인 대기 분모이며 `model_review`도 이 **활성 후보만** 집계한다. 옛 후보 20건을 조작된 공식 거절 상태로 승격하지 않고, 정식 승인 시도 자체를 차단한다. 새로운 교정안 20건은 모델 의견도 아직 확정해두지 않았으므로 `unassessed=20`으로 정직하게 유지한다.

## 별도 복제 DB를 이용한 회차별 재생

**중요:** 다음 수치는 공식 SQLite와 분리한 비공개 복원본에서 `synthetic_shadow` 리뷰 레이블로 가상 승인 후 실행한 결과다. 신원 인증이나 사람의 검수는 아니다. 공식 DB에 승인 기록을 추가하지 않았다.

| 회차 | 모의 상태 |
| --- | --- |
| 3화 | 코카콜라 계약 **서명**. `actor_id=evelyn_trust_account`, `signer_id=harrington_grandfather`, 15% 계약, 현금 유출 미발생 |
| 4화 조회 | 5화에서 뒤늦게 공개되는 1892년 1월 지급·지분 이전은 아직 **알려지지 않아 보이지 않음** |
| 5화 조회 | 코카콜라 지분 **15% 이전**, 계약 대금 **2만 5천 달러** 지출 효과 **1회**, 실제 개시 신탁 현금이 불명확해 정확 잔액 **null**, 현금 이동 **−25,000 USD** |
| 10화 조회 | 코디지 매매 후 운용 현금은 **55만 달러 초과**라는 `continuity_fact`만 확인. 정확 잔액은 **null** |
| 11화 조회 | 코디지 이후 현금의 근사 언급과 이리 철도 풋옵션 비용 **약 38만 달러**를 수치 정밀도를 지닌 주장으로 기록. 이리 풋 **정산 요청**은 수령과 구분되어 현금 이동 추가 **0건** |

10·11화 비교의 `QUALIFIED_AMOUNT_COMPARISON`은 `INSUFFICIENT_EVIDENCE=1`, `CONFIRMED_CONFLICT=0`. 이것은 두 값이 동등하거나 모든 설정에 오류가 없다는 판정이 아니다. 코디지 수익과 이리 풋 계약 규모를 실제 계좌의 정확한 증감으로 자동 계산하지 않았기 때문에 10·11화의 `world-state` **정확 현금잔액은 미확정**이다. 신규 현금 효과는 해당 구간 0건이며 중복 지출/정산 수익 추가도 0건.

모의 복제 DB에서 승인 의견 7건, 상태 이벤트 3건만 적용하고 재적용 시 0건 추가. **공식 원장의 승인 0/적용 0과 분명히 분리**한다.

## 안전한 명령어 예시

```bash
ROOT=/shared/NovelGraph-data/works/<private-work>
PYTHONPATH=/shared/NovelGraph /shared/NovelGraph/.venv/bin/python -m novelgraph --data-root "$ROOT" import-revisions \
  --source "$ROOT/source/003.txt" \
  --input "$ROOT/reports/private-revision-batches/revisions-003.json" \
  --mapping "$ROOT/reports/private-mappings/mapping-003.json"
```

`mapping-003.json`은 `schema_version=1`, `work_id`, `episode`, `revisions` 배열의 각 `{replaces_candidate_id, new_candidate_id}`를 담는다. 새 후보 JSON을 수동으로 생성할 때 기존 `candidate_id`를 직접 바꾸지 않는다. 모델이 작성한 교정안도 정확한 기존 후보의 ID와 **일대일**로 연결되어야 한다. 이미 승인된 원본, 잘못된 회차/작품, 불완전한 매핑은 전체 트랜잭션을 실패 처리한다.

## 보존과 남은 위험

- 공식 DB의 교정 입력 전후 백업(온라인/새 파일)과 모의 DB 복원은 모두 개인 `reports/` 영역 안에 있다. 비공개 원고·원본 후보·수정 후보 JSON과 추론 기록은 공개 GitHub에 올리지 않는다.
- 본문에 등장하는 근삿값은 임의의 정확 송금액·정확 총자산에 대입하지 않는다. 코카콜라 지급 사건의 정확 비용만 원문 간 근거가 있는 시뮬레이션에서 적용.
- **출시 판정은 NO-GO**: 교정안 20건의 독립 인간 검수 0건, 실제 의미 precision/recall/F1 미측정, 승인자 실제 신원 인증 미지원.

## 테스트·검수 기록

- TDD: 변경 전 신규 교정 명령 관련 테스트의 예상 실패를 확인했다. 구현 후 회차·작품 분리, 원본 승인 차단, 원자적 부분 실패 롤백, 반복 입력 무변경, 2단 교정 계보의 테스트를 통과했다.
- 전체 회귀: Moon 격리 작업 트리에서 `python -m unittest discover -s tests -v` **192/192 통과 (413.990초)**. 기존 185개 + 새로운 계보·검증 7개. 상세 출력은 공개 Git이 아닌 비공개 `/shared/NovelGraph-data/research/revision-phase2-full-suite-20261105.log`에 보관.
- 실 원고 파일럿: 7개 회차 최초 `inserted=20`, 동일 7개 파일 재입력 시 `inserted=0`·`already_recorded=20`, 공식 DB SHA 두 번째 실행 전후 일치. DB 무결성과 FK 검사를 통과했다.
- 1~11화 원본 SHA 일치, 원본 118건·모델 의견 118건 보존. `candidate_revisions=20`; 원본 공식 승인 0, 원본 실제 적용 0. 수정된 옛 후보가 공식 검수 대상으로 다시 올라가지 않도록 `review-candidate`를 차단한다.
- 모의 DB는 create-only 복원한 별도 SQLite. 지분 15% 이전과 2만 5천 달러 지급을 5화 정보로 최초 확인하고, 4화 시점에는 사후 발견 사실을 유출하지 않는다. 10~11화에서 정확한 현금계산을 하지 않는 보수적 처리를 확인했다.
- 기존 승인자 인증과 독립 정답표가 없기 때문에 이 작업을 정식 출시 합격이나 실제 의미 정확도 95% 달성으로 보고하지 않는다.
