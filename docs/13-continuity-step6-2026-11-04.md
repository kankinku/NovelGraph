# [6/9] 연속성 충돌 검출기 — 2026-11-04

> 범위: ChatGPT가 **원문을 근거로 구조화하고 사람이 승인한** 사건·설정 사실을 비교한다. `novelgraph/continuity.py` + `check-continuity` CLI. 독립적인 원고 자동 의미 추출기나 자동 수정 기능이 아니다.

## 1. 데이터 흐름

```text
Moon MCP → 원고 확인 → ChatGPT가 continuity_fact 후보 생성
        → import-candidates (원본 SHA·원문 문자 범위 검증)
        → review-candidate (검토자 명시 승인)
        → check-continuity --work-id <작품> --episode N
        → 판정 / 원인 코드 / 대조한 화·문자 위치·원고 해시
```

- 원고는 공개 Git 저장소 외부(`/shared/NovelGraph-data`)에 둔다.
- 명시적으로 `approved` 처리된 사실·변경 사건만 검사에 포함한다. 승인되지 않은 후보는 공식 설정/판정에 반영하지 않는다.
- `reviewer` 이름은 **기록용 텍스트이며 실제 인증이 아니다**.
- `as_of_episode=N`은 **N화까지 원고에 등장한 정보**만 검사한다. 미래 회차의 주장을 과거 결과에 끼워 넣지 않는다.

## 2. 원문 후보 계약

`kind`는 `continuity_fact`, `payload`는 아래 필드를 따른다. 외부 래퍼(`work_id`, `episode`, `source_sha256`, `evidence`)는 [4단계 입력 계약](11-candidate-intake-mvp-2026-11-04.md)과 동일하다.

```json
{
  "fact_type": "amount",
  "subject_id": "contract:warehouse",
  "field": "amount",
  "value": "150000",
  "currency": "USD",
  "effective_episode": 4,
  "certainty": "confirmed",
  "context_id": "scene:negotiation-1"
}
```

`effective_episode`은 사실이 발생한 화이며 생략 시 인용한 원문이 등장한 화로 본다. `context_id`는 **같은 장면/같은 순간이라고 확인한 경우에만** 사용한다. 억지로 같은 값으로 합치면 오탐이 발생한다. `certainty`는 `confirmed` 또는 `uncertain`이며 기본값은 `confirmed`다.

| fact_type | field | value 예시 / 주의 |
| --- | --- | --- |
| time | date, weekday | `2026-11-04`, `wednesday` (그레고리력·영문 소문자 요일) |
| location | location_id | `warehouse-1` (동일 장소라면 같은 ID) |
| action | action_state | `planned`, `started`, `completed`, `reopened`, `cancelled` |
| amount | amount | `150000` + 필수 `currency: USD`; 정규화 Decimal |
| contract | current_status | `pending`, `signed`, `transferred`, `cancelled`, `expired` |

**중요한 동일성 조건:** 시간 사실의 `subject_id`는 `meeting:unique-id`처럼 **특정 사건**을 가리킨다. 위치의 `subject_id`는 사람·물체이고, 동일 순간의 모순을 확정하려면 동일한 `context_id`도 있어야 한다. 서로 다른 장소·장면을 섞어 같은 사건으로 확정해서는 안 된다.

## 3. 정당한 상태 변경을 증명하는 별도 후보

```json
{
  "fact_type": "change",
  "subject_id": "contract:warehouse",
  "field": "amount",
  "from_value": "150000",
  "to_value": "300000",
  "currency": "USD",
  "effective_episode": 5,
  "reason_code": "amended"
}
```

이 역시 **원고 근거를 가진 별도 후보**로 등록하고 승인한다. 변경된 값만 확인됐을 뿐 변경 사유가 입증되지 않았다면 `change` 후보를 만들지 않는다.

지원 이유: `amended`, `rescheduled`, `moved`, `corrected`, `reopened`, `repeated`, `refinanced`, `revalued`. 이전 값과 다음 값, 대상·필드·통화가 모두 일치하고 발생 시점이 연결될 때만 정당한 변경으로 처리한다.

## 4. 판정과 출력 원칙

| 판정 | 사용 조건 | 예시 |
| --- | --- | --- |
| `CONFIRMED_CONFLICT` | 동일 특정 사건·순간의 확인된 사실이 직접 충돌 | 같은 회담의 월요일/화요일 기록, 날짜·요일 역산 불일치, 같은 장면의 위치 모순 |
| `NEEDS_REVIEW` | 시점이 다른 변동이나 반복인데 변경 사유가 확인되지 않음 | 같은 계약액 15만→30만, 이동 묘사 없이 장소 변경, 동일 행동의 완료 반복 |
| `EXPLAINED_CHANGE` | 승인된 독립적 변경 사건이 앞뒤 사실을 연결 | 계약 변경 합의, 인물의 이동 |
| `INSUFFICIENT_EVIDENCE` | 확정하기에는 추정이 섞였거나 변경 사건의 앞뒤 근거가 미완성 | 불확실한 날짜·금액, 연결되지 않은 변경 승인 |

- 단순히 다른 회차의 숫자/장소가 달라졌다고 **확정 모순으로 처리하지 않는다**.
- `context_id` 없이 인물의 같은 화 내 위치 차이가 나와도 자동 확정하지 않는다.
- 금액은 Decimal 문자열과 통화 단위로 비교한다. 서로 다른 통화는 근거 없는 환율 환산을 하지 않는다.
- 시간 `date`는 그레고리력의 날짜·요일을 검사한다. 역사적 달력 개혁, 시간대, 상대 날짜 등은 아직 별도 지원하지 않는다.
- 이미 승인·적용된 계약 사건 원장의 `signed`/`transferred` 상태와, 같은 시점에 대한 `current_status`의 충돌도 검사한다.
- 과거의 계약 서명 상태를 나중의 지분 이전 상태로 덮어쓰지 않는다.
- 결과는 `finding_id`, `category`, `reason_code`, `subject_id`, `field`, 구별되는 비교값과 `evidence` 배열로 나온다. 근거는 원고 SHA·회차·문자 시작/끝 위치·후보 ID이며 **원문 인용 전체는 기본 출력하지 않는다**.

## 5. CLI

```bash
cd /shared/NovelGraph
.venv/bin/python -m novelgraph --data-root /shared/NovelGraph-data \
  check-continuity --work-id novel --episode 6
```

잘못된 형태의 `continuity_fact`는 승인 단계에서 거절한다. 검출 명령은 원고와 세계 상태를 변경하지 않는다.

## 6. 검증 시나리오와 제한

자동화 테스트: [`tests/test_continuity.py`](../tests/test_continuity.py)

- 같은 사건 요일·날짜 불일치
- 계약액 변경 사유 부재 vs 승인된 변경 합의
- 제삼자의 별도 장소 무오탐, 장면 식별자 부재 vs 동일 장면의 충돌
- 위치 이동 사건에 의한 정상 변화
- 행동 완료 중복과 검토 경고
- 불확실성/미승인 변경/승인 변경의 분리
- 원장에 기록된 계약 상태와 문장의 충돌 및 과거 상태 보존
- 향후 정보의 과거 검사 오염 방지
- 입력 스키마 검증 및 검사 반복 결과의 결정성

**제약:** 원고를 LLM이 자동으로 의미 추출하는 정확도, 인물 동일성 추론, 날짜가 명시되지 않은 행동 이동 추론, 다중 통화 환산, 모든 소설의 복선/대사 맥락 해석은 테스트하지 않는다. `CONFIRMED_CONFLICT` 또한 **정확히 승인한 ID/시점/맥락을 전제한 기계적 충돌**이며 원고의 실제 오류 최종 판정은 검토가 필요하다. 인용 원본이 사후 교체됐는지 전체 재검증하는 기능과 판본 관리는 후속 작업이다.

## 7. 다음 단계

[7/9] Graphify에 승인된 인물·사건·근거·변경 관계를 내보내고, 경로 조회 결과에서 원본 근거까지 회수하는 파생 그래프 기능을 구현한다.

## 8. 검증 결과

- GitHub Actions: 개발 브랜치 커밋 `5372a8b` 기준 **41개 전체 테스트 통과** (Python 3.12, `graphifyy==0.9.102`). 기존 테스트 23개, 신규 연속성 테스트 18개.
- 첫 실행에서는 **테스트 픽스처 구성 오류 1건**이 발생했다. 동일 화에 서로 다른 원문 텍스트를 붙인 실수였으며 픽스처를 분리한 후 수정했고, 이후 41개 전체 테스트가 성공했다.
- Moon MCP: 이 작업 중 **Connection failed / 내부 오류**로 연결이 불안정해 현재 신규 코드의 Moon 내 테스트와 `/shared/NovelGraph` 동기화를 검증하지 못했다.
- 따라서 GitHub CI 통과와 Moon 검증을 동등하게 기록하지 않으며, 실제 원고 분석의 정확도를 검증한 것으로 간주하지 않는다.

> **GitHub main 병합 완료:** PR #2, squash 커밋 `ee40bc466b333e5f3a23c0552b64cf5ffcf760f8`. GitHub CI 41/41 통과. **Moon의 6단계 코드 동기화 및 Moon 내 테스트는 연결 장애로 미완료**이며, 검증한 것으로 주장하지 않는다.
