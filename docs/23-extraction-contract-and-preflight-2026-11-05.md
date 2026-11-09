# [03/12] NovelGraph 원고 의미 추출 지침 및 저장 전 검사 v1 — 2026-11-05

> **상태: 실사용 정확도 검증 전 단계.** 이 문서의 지침과 `preflight-candidates`는 모델 후보의 의미를 자동으로 판별하거나 독립 금표준을 대체하지 않는다. 기존 JSON 입력 계약 및 SQLite 승인 흐름을 유지한다.

## 1. 목적·처리 경계

입력은 비공개 원고 **한 회차의 정확한 UTF-8 판본**, `source-info`로 확인한 SHA-256, 이전 회차의 승인된 설정·변경 이력이다. 이전 회차를 보지 않았다면 현재 회차에서 밝힌 사실 외의 상태를 추측하지 않는다.

처리 순서:

1. ChatGPT가 해당 회차 전체를 순서대로 읽고, 인물·조직·장소·사건·시간·금액·계약·권한·관계를 식별한다.
2. 각 정보에 대해 **실제 발생·서명·이행·완료 / 제안·계획·지시 / 부정·거절 / 과거 사실 반복 / 진술·추측·미확정**을 구분한다.
3. 기존 인물 ID와 계약·거래 ID를 우선 대조하고, 동일 거래·지급 합계·사건이 재언급됐는지 확인한다. ID가 같은 대상을 뜻한다는 근거가 없다면 새 ID 또는 검토 대기 대상으로 분리한다.
4. 앞뒤 문맥을 고려하되 각 후보는 원문에서 **주장의 의미가 확인되는 정확한 구간**을 갖도록 한다. 단독 인용이 불충분하면 더 넓은 연속 구간을 사용하거나 후속 근거 검토가 필요하다고 분리 기록한다.
5. 현재 NovelGraph가 지원하는 `schema_version=1` 후보만 JSON으로 출력한다. 감지하지 못한 사실을 임의로 생성하지 않는다.
6. 저장 전 `preflight-candidates`로 원문 해시·문자 오프셋·후보 구조·일부 도메인 스키마를 검사한다.
7. **검수 전에는 절대 승인·상태 적용하지 않는다.** 검토를 거친 후보만 기존 `import-candidates`로 `proposed` 상태에 격리 저장한다.

**지원하지 않는 것:** 자체 LLM 실행, 외부 API 호출, 완전한 법률적 판단, 사람 검수 인증, 자동 집필·자동 원고 수정.

## 2. 현재 코드의 후보 형식과 도메인 필드

문서 최상위 구조는 `schema_version: 1`, `work_id`, `episode`, `source_sha256`, `candidates`이다. 각 후보는 `kind`, `payload`, `evidence`를 갖는다. `evidence`에는 원문 **0부터 시작하고 끝은 제외하는 Unicode 문자 오프셋** `start`, `end`, 그리고 `text`를 넣는다. `source[start:end] == text`이어야 한다.

| kind | payload 구조 | 사용 시점 |
| --- | --- | --- |
| `entity` | `entity_id`, `entity_type`, `name` | 식별되는 인물·조직·장소·계약·자산 |
| `relation` | `source_id`, `target_id`, `relation_type` | 소유·소속·관계가 근거로 확인될 때 |
| `event` | `actor_id`, `event_type`, 선택적 `target_id` | 제안·지시·거절·조사·계약 미체결 등 서사적 사건 |
| `continuity_fact` | `fact_type`, `subject_id`, `field`, `value` 등 | 날짜·요일·위치·동작·금액·계약 상태를 비교할 때 |
| `state_change` | 아래 지원 event type별 정확한 필드 | 증거로 확인되고 **공식 승인된** 계약 제안·거절 상태, 실제 현금·서명·지분 이전 등 |

- `entity_type`은 `person`, `organization`, `place`, `contract`, `asset`, `object`를 지원한다.
- 인물·회사·거래·계약 등 식별자(`*_id`)는 **안정된 ASCII 영문·숫자·밑줄·하이픈 등 현행 검증기가 허용하는 형태**로 유지한다. 이름 자체는 한국어로 적는다.
- `continuity_fact`의 비교 필드는 `time.date`, `time.weekday`, `location.location_id`, `action.action_state`, `amount.amount`, `contract.current_status`다. 금액은 `currency` 필수, 실제 불확실성이 있으면 `certainty: "uncertain"` 사용. **금액 관측의 정밀도:** `amount_relation` 생략 시 `exact`, 초과는 `greater_than`, 이상은 `at_least`, 약/내외는 `approximate`로 입력한다. `amount_relation`은 `fact_type: amount`에서만 사용하며, 공식 현금 지급 이벤트나 `change`에 붙일 수 없다. 비교 시 관계가 다른 금액을 정확한 동일값·확정 충돌로 단정하지 않는다.
- 계약 상태 값은 `pending`(기존 호환용), `proposed`, `refused`, `signed`, `transferred`, `cancelled`, `expired`다. **제안과 거절을 실제 계약 서명/해지로 바꾸지 않는다.** `contract_refused`는 이전의 같은 ID 제안이 승인·적용된 경우에만 허용한다. 독립 근거가 없으면 확정 상태 적용 대신 사건 `event` 또는 검토 대상으로 남긴다.
- `state_change`에서 지원하는 이벤트는 `cash_opening`, `cash_payment`, `cash_receipt`, `contract_proposed`, `contract_refused`, `contract_signed`, `equity_transfer`다. 제안·거절 이벤트는 **계약 상태만** 바꾸며, 실제 현금·지분에는 영향이 없다. 모든 이벤트는 공식 승인 후에만 적용한다. `effective_episode`은 생략 가능하지만 지정하면 소스 회차 이하의 양의 정수여야 한다. 소급 서술이라고 해서 그 사실이 과거에 **알려져 있었던** 것처럼 자동 처리하지 않는다.
- `cash_payment`/`cash_receipt`는 `actor_id`, 3글자 대문자 `currency`, **정확한** 문자열 금액 `amount`, 유일한 `transaction_id`, 선택적 `contract_id`가 필요하다. `약 38만 달러`만 확인되는 경우 `cash_payment.amount: "380000"`으로 원장을 확정하지 않는다. 이 경우 금액은 `continuity_fact`의 `amount_relation: "approximate"` 관측으로 기록하고, 지급 사실은 별도의 근거 있는 사건으로 구별한다. 양도 대상 권리와 실제 지급 주체를 구분한다.
- `contract_proposed`는 `actor_id`, `contract_id`, `company_id`가 필요하며 계약 제안 사실만 기록한다. `contract_refused`는 `actor_id`, `contract_id`로 기존 제안의 거절을 기록한다. `contract_signed`는 `actor_id`, `contract_id`, `company_id`, 문자열 `equity_pct`가 필요하다. **대리 서명이 명확하면 선택적 `signer_id`**를 추가한다. `actor_id`는 경제적 권리 귀속 주체(예: 미성년자 신탁 계좌), `signer_id`는 실제 서명한 법적 대리인이며 양자를 무조건 합치지 않는다. 앞선 제안이 있다면 `actor_id`와 대상 회사가 일치해야 하고 거절 후 같은 계약 ID의 서명은 허용하지 않는다. `equity_transfer`에는 `actor_id`와 `contract_id`가 필요하며, 실제 체결·양도 근거 없이는 생성하지 않는다.

**중요한 호환성 제약:** `event`에 임의로 `certainty`, `stage` 같은 확장 필드를 넣지 않는다. 이 값들은 현재 Graphify 승인 후보 스키마에 존재하지 않는다. 제안/이행 구별은 `event_type`과 별도의 검토 기록으로 표현한다.

## 3. 추출 판단 규칙

| 가상의 문장·상황 | 허용 후보 방향 | 금지할 오판 |
| --- | --- | --- |
| '지분을 사기로 제안했다' | 미확정일 때 `event`, 원문 근거와 공식 승인이 있을 때 `state_change:contract_proposed` | 실제 서명·지급·지분 소유로 취급 |
| '계약서에 서명하지 않겠다고 거절했다' | 미확정일 때 `event`, 기존 제안과 동일성이 확인되고 공식 승인된 경우 `state_change:contract_refused` | 서명·기존 계약 해지·현금 지급으로 취급 |
| '대금은 다음 달 송금할 예정이다' | `event`: `cash_payment_planned` | 현금 잔액 즉시 차감 |
| '회사 계좌에서 3만 달러를 실제 송금했다' | 실제 지급 주체·거래 ID·근거가 확인될 때만 `state_change:cash_payment` | 수령인과 지급 주체 혼동 |
| '과거 집행한 3만 달러를 다시 언급했다' | 이전 사건과 연결된 `continuity_fact` 등 | 재언급을 신규 지급으로 중복 차감 |
| '부당 지출이 아직 입증되지 않았다' | 증거 부족·미확정 사건 또는 검토 메모 | 불법 지출 발생/미발생 모두 단정 |
| '조건부 성공보수 8만 달러 초안' | `event` 제안 및 계약 문서 정보 | 실제 지급·확정 채무로 기록 |
| '올해 자산 총액은 아직 계산하지 않았다' | 미확정 상태와 계산 요청 | 현금/총자산 수치 임의 산출 |
| 동일 성을 가진 두 사람 등장 | 기존 ID 증거 대조, 구별되면 다른 ID | 인물 자동 병합 |
| 회상으로 과거 사건 공개 | source episode·effective episode 구분 | 미래에 밝혀진 사실이 과거 당시 이미 알려진 듯 처리 |

계약 의사·체결·대금 지급·지분 이전은 각각 별개의 근거와 승인 절차를 필요로 한다. 진술·계획은 **관찰된 사건**일 수 있지만 실제 현금·소유권 변동이 될 수 없다.

## 4. ChatGPT 집필 분석 지침(공통 프롬프트용)

다음 지침은 작가 자동 집필 프롬프트와 **완전히 별도**로 유지한다.

> 제공된 소설 원고 한 회차를 처음부터 끝까지 읽고 인물·조직·사건·시간·위치·금액·계약·권리·상태 변화를 추출한다. 모든 정보는 해당 회차의 원문 구간과 연결한다. 제안·계획·지시·거절·기존 사건의 재언급·실제 이행·확정 사실·화자의 추측을 구분하라. 실제 서명·송금·이전이 입증되지 않았다면 `contract_signed`·`cash_payment`·`equity_transfer`를 생성하지 마라. 제안·거절이 근거로 확인되면 각각 `contract_proposed`·`contract_refused`를 **계약 상태에만** 사용하며, 사람의 공식 검수 전에는 이를 적용하지 마라. 같은 과거 금액이나 거래를 반복 언급한 경우 같은 사건에 연결하고 중복 변경을 금지하라. 법적 효력, 동명이인의 동일성, 미확정 자산 금액을 추측하지 마라. 기존 ID·원본 SHA를 제공받지 않았다면 결과를 공식 적용하지 말고 검토 대상으로 두라. 기존 NovelGraph `schema_version=1` 계약에 맞는 JSON만 출력하고, JSON 바깥의 모델 판단 메모는 별도 비공개 검토 기록으로 보관하라. 모든 인용의 `[start,end)`는 실제 입력 텍스트의 Unicode 문자 위치와 정확히 일치해야 한다. 내용에 불확실성이 있으면 '확정'이라고 꾸미지 마라.

## 5. 저장 전 검증 명령

```bash
ROOT=/shared/NovelGraph-data/works/<private-work>
cd /shared/NovelGraph

.venv/bin/python -m novelgraph --data-root "$ROOT" source-info \
  --source "$ROOT/source/001.txt"

.venv/bin/python -m novelgraph --data-root "$ROOT" preflight-candidates \
  --source "$ROOT/source/001.txt" \
  --input "$ROOT/candidates/001.json"
```

`preflight-candidates`는 기존 `_valid_candidates`, `world_state._payload`, `continuity.validate_fact`를 **다시 사용**해 SHA·근거 구간·종류·상태 이벤트 형식·연속성 필드 구조를 확인하고 DB에 쓰지 않는다. 후보 수와 종류별 건수 및 중복 항목 수만 반환하며 원문 인용을 출력하지 않는다.

사전 검증은 **다음 기능이 없다**: 계약이 실제로 체결됐는지 자연어 이해, 자금 중복 의미 판별, 사람 검수 인증, 추출 누락 검출, 의미 정확도 계산. 예를 들어 '계약서에 서명하지 않았다'는 인용에 `event_type:contract_signed`를 잘못 작성한 경우 형식이 맞으면 통과할 수도 있다. 반드시 모델·독립 검수가 남아야 한다.

## 6. 검증 결과 및 단계 판정

- TDD: 합성 원고로 먼저 실패를 확인한 후 최소 CLI 구현.
- 신규 **11/11** 구조 검사 테스트가 통과했다. 계약 거절/미서명, 계획된 지급, 실제 지급, 잘못된 연속성 필드, source SHA 위조, 인용 변조, 미래 사건 적용, 중복 항목, DB 비변경 등을 다룸.
- 신규 11건을 포함한 **전체 101개 회귀 테스트 통과** (`/shared/NovelGraph/.venv/bin/python -m unittest discover -s tests -v`, Moon 격리 worktree, 225.999초).
- 실제 1~5화의 기존 후보 26건을 읽기 전용으로 검사: 26건 모두 형식 검사 통과; 그중 `continuity_fact` 7건 구조 검사; `state_change` 0건.
- 공식 DB SHA-256은 사전 검증 전후 동일. 새 후보 승인·적용 없음.
- **[02/12] 독립 인간 금표준 정답표는 미완료**. 따라서 실제 원고 추출 정밀도·재현율·F1은 미측정. [03/12]의 실제 품질 개선 게이트는 아직 열리지 않았다.
- 신규 LLM API, MCP 서버, DB, 외부 의존성 도입 없음.

관련 문서: [전체 계획](superpowers/plans/2026-11-05-novelgraph-production-plan.md), [모델 71건 예비 검토](22-model-71-semantic-triage-2026-11-05.md).

## 2026-11-09 상태 사건 확장

기존 사건 유형에 state_set을 추가한다. 예전 문서에 기록된 유형 목록은 당시 기준으로 유지한다.

- 필수: event_type=state_set, actor_id, category, item_id, value.
- numeric 카테고리(liquid/stock/bond/real_estate/liability)는 unit 필수. 금액은 소수 문자열, liability는 음수이며 완전 상환 시 0을 허용한다. 같은 자산의 주수와 평가금액은 item_id를 분리한다.
- time은 actor_id=작품ID, item_id=current, YYYY-MM-DD 날짜만. 작중 시간 경과가 확인되지 않으면 갱신하지 않는다.
- relationship은 relation_status=active/ended; knowledge는 known/not_known/unverified; thread는 open/resolved/cancelled.
- 대사·소문·추측·예정된 미래는 현재 확정 사실을 만드는 state_set으로 제출하지 않는다.
- preflight 통과는 의미가 정확하다는 증명이 아니므로, 승인되지 않은 후보는 상태에 반영하지 않는다.
- query-state 명령은 범위에 맞는 현재 상태만 반환, 변경 이력은 --history로 명시해야 한다.
