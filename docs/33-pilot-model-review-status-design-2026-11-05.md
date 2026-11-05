# 회차별 모델 검수 진행 상태: 설계

**목적:** 기존 NovelGraph에 등록된 회차별 제안 후보가 실제로 모델에게 검수되었는지, 어디가 보류되었는지를 확인 가능하게 만든다. 사람 승인과 분리한 채 11화 후보의 모델 예비 검수를 수행한다.

## 현재 발견
- 실제 작품 `harrington_1883_pilot_20261105` 1~11화 후보 118건, 1~10화 모델 의견 103건(추가확인 27), 11화 미검수 15건.
- `review-audit`는 누적 **의견 행 수**만 제공한다. 같은 후보를 재평가하면 중복 의견 수가 늘고 현재 최종 검수상태가 불명확하다.
- `workflow-status`는 각 화의 `proposed` 후보/상태 사건 수를 이미 알고 있으므로 **새 CLI 대신** 이 조회에 최종 모델 판단 건수와 미검수 건수만 추가한다.

## 선택한 해법
1. `workflow-status` 반환에 `model_review` 객체를 추가: `supports`, `needs_review`, `unsupported`, `unassessed`. **현 회차의 현재 proposed 후보만** 분모이며, 후보마다 가장 마지막 `assessment_id`의 의견 하나만 채택. 모델 검수가 0이면 `unassessed=proposed`. DB와 원고는 읽기 전용.
2. 현재 `review-audit` 응답/기존 `next_actions`와 공식 승인 의미를 변경하지 않는다. 사람 신원 확인·실제 gold·정밀도/재현율도 계산하지 않는다.
3. 동일 후보 재평가, 다른 회차/작품의 의견 격리, 다른 상태 후보·없어진 검수표, 원고 SHA 변경 시에도 검수 현황 표시가 실제로 맞는지 합성 테스트.
4. 11화 원문과 10화 종료시점 관측을 대조해 15건 `assess-candidate` 의견을 **비공개 공식 DB의 별도 모델 의견 테이블**에 기록한다. 승인 0·상태 적용 0 불변. `needs_review`는 명시적으로 남기고 가짜 금표준·정확한 현금잔액을 생성하지 않는다.

## 제외
- 가상의 현금/총자산 확정, 근삿값을 exact event로 생성, 1~10화의 27건을 별도 판정 없이 임의 수정하거나 승인, 새 LLM API/MCP, 자동 집필.
- 사용자 확정 승인 없는 `review-candidate`/`apply-approved` 호출.

## 현재 파일럿 적용 실측 (2026-11-05, 독립 검수 아님)
Moon의 같은 작품 `harrington_1883_pilot_20261105` 1~11화 기준.

| 구간 | 등록 후보 | 모델이 지지 | 추가 확인 | 모델 미검수 |
| --- | ---: | ---: | ---: | ---: |
| 1~10화 | 103 | 76 | 27 | 0 |
| 11화 전 | 15 | 0 | 0 | 15 |
| **11화 모델 검수 후 1~11화 합계** | **118** | **81** | **37** | **0** |

11화는 기존 공식 후보 15건에 `assess-candidate`로 의견을 추가했으며, 다섯 건은 모델이 주장/원문 문맥을 지지, 열 건은 인용 범위·계약 확정 시점·근삿값 처리 등의 근거 보강이 필요하다고 판단했다. 개인별 의견과 원문 연결은 **비공개** `reports/model-review-011-20261105.json`에만 보관한다.

특히 이리 철도 풋옵션의 38만 달러는 원고에서 **수수료 포함 약 38만 달러의 계약 비용**이며, 11화 후반의 정산 지시는 정산 완료·현금 수취가 아니다. 계약 비용이 약수치라 공식 현금 38만 달러 정확 차감 또는 정산금 자동 가산을 하지 않았다. 코디지 수익 39만 달러 이상은 이전 화의 거래 실현 결과로, 11화 신규 수익으로 재적용하지 않는다.

**공식 상태:** 118건 모두 proposed, 승인 0, 지급/지분/계약 공식 적용 0. 모델 판정은 승인 아님. 검수표의 37건도 확정 오류가 아닌 추가 검토 요청이며, 독립 precision/recall/F1은 미측정이다.

## CLI 사용

```bash
cd /shared/NovelGraph
ROOT=/shared/NovelGraph-data/works/harrington-1883-pilot-20261105
.venv/bin/python -m novelgraph --data-root "$ROOT" workflow-status \
  --work-id harrington_1883_pilot_20261105 --episode 11 \
  --source "$ROOT/source/011.txt"
```

새 필드 `model_review`는 **해당 회차의 proposed 후보에만** 적용된다. 모델이 같은 후보를 여러 차례 검수하면 가장 최근 의견만 집계한다. 과거 모델 판정 기록은 삭제하지 않는다. 새 테이블·승인 자동화·원문 출력은 없다.

## 실행·검증 결과
- 합성 회차 테스트는 변경 전 **12건 중 2건 RED**(`model_review` 필드 부재), 코드 최소 확장 후 **12/12 GREEN**.
- Moon 전체 회귀: `/shared/NovelGraph/.venv/bin/python -m unittest discover -s tests -v` **180/180 통과 (417.188초)**. 기록은 비공개 `/shared/NovelGraph-data/research/pilot-model-review-full-suite-20261105.log`에만 보관.
- 공식 DB 쓰기 전 `backup-database`로 별도 백업 파일 생성, 원본 후보 118건/검수 기존 103건 확인. 새 모델 의견은 11화 15건만 등록해 **118 후보/118 의견, 승인 0, 적용 0**.
- 3·5·10·11화의 계약/현금 사건 **10개 근거 위치와 SHA**를 비공개 결과 `reports/financial-transition-model-audit-003-005-010-011-20261105.json`에 재확인했다. 정확 잔액은 생성하지 않음.
- 현 작품의 **인간 독립 골드 0건**, `precision/recall/F1=null`, 정식 출시 NO-GO는 여전히 유효하다.

## 완료 기준
- [x] RED→GREEN + 180개 전체 테스트 통과.
- [x] 공식 후보/원고 SHA 불변, 후보 ID 중복 없음.
- [x] 11화 모델 검수 15건과 1~11화 전체 상태를 Moon에서 재조회.
- [ ] 37건 재검증·실제 상태 변경 근삿값 설계·승인 없는 공식 상태 적용 불가 문제는 후속 작업.

- 실 원장 `1~10화 27 needs_review` 유지 및 11화 `unassessed 15→0` 실측, official approved/applied 0.
- public Git diff에 개인 원고·DB·본문 인용 없음; 독립 코드 리뷰 없으면 자체 리뷰로 명시.
