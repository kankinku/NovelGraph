# [5/9] 승인된 사건의 동적 세계 상태 엔진

> 상태: **GitHub 개발 브랜치 구현 및 CI 검증 진행 중**. 기준 저장소: `kankinku/NovelGraph`, 브랜치 `feat/world-state-step5`. 기존 Moon MCP 연결 장애로 Moon 실행·동기화는 재확인 필요. 공개 GitHub에는 가상 테스트 데이터와 코드만 보관한다.

## 1. 처리 흐름

```text
ChatGPT 의미 분석 → JSON 후보(stage 4) → list-candidates
  → review-candidate --decision approve|reject --reviewer ... --reason ...
  → apply-approved → SQLite applied_events(불변 사건 원장)
  → world-state --episode N (사건 재생, 특정 시점 상태)
```

**승인과 실제 적용은 서로 다른 명령**이다. 수입된 후보는 `proposed` 상태를 유지하고, 검토 기록 없이 사건이 적용되지 않는다. `reviewer`는 감사 추적을 위한 문자열로 **본인 인증이나 권한 제어 기능이 아니다**. 사전 동의 없는 자동 승인은 하지 않는다.

## 2. 지원 사건 (state_change 후보 payload)

공통 필수: `event_type`, `actor_id`. `effective_episode`는 선택 사항이며 지정하면 사건이 실제로 발생한 화(1 이상, 기록된 회차 이하)다. 기록한 화와 발생한 화를 구별한다.

| event_type | 추가 필수 | 상태 반영 |
| --- | --- | --- |
| `cash_opening` | `currency`, `amount` | 현금 잔액의 명시적 기준 설정 |
| `contract_signed` | `contract_id`, `company_id`, `equity_pct` | 서명 계약만 기록, 현금·지분 변화 없음 |
| `cash_payment` | `currency`, `amount`, `transaction_id` | 현금 차감; `contract_id`는 선택적으로 연결 |
| `cash_receipt` | `currency`, `amount`, `transaction_id` | 현금 증가 |
| `equity_transfer` | `contract_id` | 서명 계약에 따른 지분을 보유 자산에 이전 |

- 금액·지분율은 **JSON 숫자 대신 십진수 문자열**을 사용한다. `Decimal`만 계산에 사용한다.
- `cash_opening`은 동일 계정에 기존 입출금이 기록되기 전에만 적용된다.
- 초기 잔액을 모르면 현금 잔액은 `null`이고 별도 `cash_movement`(증감 누계)만 표시한다.
- `total_assets`는 증거 없이 계산하지 않으므로 현재 `null`이다. 현금, 총자산, 미실현 평가액은 서로 다른 개념이다.
- 지분은 계약 서명과 분리된 `equity_transfer`가 있을 때만 보유로 인정한다.
- 계약 조건별 분할 지급, 소유권 분할 이전, 취소·정정·회계 인식은 아직 지원하지 않는다. 지원되지 않은 사건을 임의 변환하지 않는다.

### 가상 지급 후보 예시

```json
{
  "kind": "state_change",
  "payload": {
    "event_type": "cash_payment",
    "actor_id": "evelyn",
    "currency": "USD",
    "amount": "25000",
    "transaction_id": "transfer-001",
    "contract_id": "aurora-15"
  },
  "evidence": {
    "start": 0,
    "end": 12,
    "text": "<원문 위치와 정확히 일치하는 부분>"
  }
}
```

`evidence`는 **설명용 자리표시자**이며 실제 등록 시 문장·범위가 정확히 일치해야 한다. 특정 화의 입력 JSON 전체 형식은 [4단계 문서](11-candidate-intake-mvp-2026-11-04.md) 참조.

## 3. Moon CLI 명령 예시

```bash
cd /shared/NovelGraph
PY=.venv/bin/python
PRIVATE=/shared/NovelGraph-data/works/demo

$PY -m novelgraph --data-root "$PRIVATE" import-candidates --source "$PRIVATE/001.txt" --input "$PRIVATE/001.candidates.json"
$PY -m novelgraph --data-root "$PRIVATE" list-candidates --work-id demo --episode 1
# 반환된 candidate_id를 확인하고 원문을 직접 검토한 뒤
$PY -m novelgraph --data-root "$PRIVATE" review-candidate --source "$PRIVATE/001.txt" --candidate-id CANDIDATE_ID --decision approve --reviewer reviewer1 --reason "원문 근거 확인"
$PY -m novelgraph --data-root "$PRIVATE" apply-approved --source "$PRIVATE/001.txt" --candidate-id CANDIDATE_ID
$PY -m novelgraph --data-root "$PRIVATE" world-state --work-id demo --episode 1
```

`CANDIDATE_ID`는 실제 후보 목록에 표시된 값으로 대체한다. **그대로 실행되는 테스트 데이터가 아닌 명령 사용 예**다.

## 4. 시점별 상태 복원과 중복 방지

- `applied_events`의 각 행은 후보 ID·작품·원문이 처음 기록된 화(`source_episode`)·사건 발생 화(`effective_episode`)·근거 시작 위치·구조화된 사건을 보존한다.
- `world-state --episode N`은 **N화까지 기록된 사건**만 선택하고, 발생 화·기록 화·근거 순서대로 재생한다.
- 5화에서 새롭게 밝혀진 2화 사건은 3화 당시에 알고 있던 상태에 소급 반영되지 않는다.
- 동일 `candidate_id` 적용은 멱등 처리한다.
- 별개의 후보가 동일한 `transaction_id`를 이용해 송금을 또 차감하려 하면 `event_key` 충돌로 적용을 거부한다.
- 사건 추가 후 전체 재생이 실패하면 삽입 트랜잭션 자체를 취소한다.
- 잔액이 확정된 계정의 지출로 음수가 되면 보수적으로 거부한다. 대출·마이너스 계좌는 별도 사건 모델이 마련되어야 한다.

## 5. 테스트 및 남은 작업

가상 데이터로 다음을 검증한다: 명시 승인 필요·승인 이력·중복 승인 금지, 계약 서명·송금·지분 이전 분리, 100000→75000 정확 계산, 동일 송금 중복 방지, 허위 금액 거부, 잔액 초과 지급 롤백, 선행 계약 없는 지분 이전 거부, 초기 현금 미상, 나중에 밝혀진 과거 사건, 원고 수정 후 적용 거부, 후보 ID 조회 시 원문 비노출.

- 자동화: `.github/workflows/novelgraph-tests.yml`에 Python 3.12 / `graphifyy==0.9.102` 고정 및 전체 `unittest` 실행.
- **검증 기준:** GitHub Actions 통과와 Moon 환경 동기화·재실행을 별도로 기록한다. 실행하지 않은 테스트는 통과로 표기하지 않는다.
- 기존 `[1/9]` 원본 복구는 여전히 별도 미해결 과제다.

**후속 [6/9]:** 시간·위치·행동·금액·계약의 연속성 위반을 근거 링크와 함께 찾아내는 충돌 검출기.
