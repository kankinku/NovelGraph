# [05/12] 모델 검토·공식 승인 신뢰 경계 — 2026-11-05

> **판정 범위:** 기술적 분리·승인 근거·저장 무결성 검사 구현. **사람 신원 인증은 구현되지 않았음.** 사람의 실제 동의나 저작물 내용의 진실성을 증명하지 않는다.

## 1. 확인된 문제

기존 `review-candidate`는 `--reviewer`에 입력된 임의의 문자열을 검토자 이름으로 기록한다. 이 값은 인증이 아니다. 원고 SHA와 인용 오프셋은 검사했지만, 직접 수정된 SQLite에서 후보의 `status='approved'`라는 값만 바꾸면 다음 경로에 들어갈 수 있었다.

- `apply-approved`의 현금·계약·지분 적용
- Graphify 승인 엔티티/관계 투영
- 연속성 검사의 승인 사실 비교

기존 `review_log`를 확인하지 않기 때문이었다. 또한 승인 목적의 `review_log`와 분리된 **모델 평가만의 공식 저장 경로가 없었다.**

## 2. 최소 구현

### 모델 평가와 공식 검토 분리

새 `assess-candidate` 명령은 모델의 잠정 의견을 `model_assessments`라는 별도 SQLite 로그에 기록한다.

- 지원 판정: `supports`, `needs_review`, `unsupported`
- 기존 후보 원문 SHA·Unicode 근거 범위·불변 후보 ID 해시 검사 후 기록
- **`candidates.status`, `review_log`, `applied_events` 변경 없음**
- 모델 이름(`model_label`)은 기록용 문자열이며 인증이 아님
- 공식 후보가 `proposed`인 동안에만 모델 의견 추가 허용
- 승인·거절 후 변경 이력은 유지하고 모델 의견으로 상태를 되돌리지 않음

예시 — 실제 사용자 원고가 아닌 별도 합성 테스트 데이터에 대한 명령 형태:

```bash
PY=.venv/bin/python
ROOT=/private/work
$PY -m novelgraph --data-root "$ROOT" assess-candidate \
  --source "$ROOT/source/001.txt" \
  --candidate-id "<실제_후보_ID>" \
  --assessment needs_review \
  --model-label chatgpt \
  --reason "미서명 제안을 완료된 계약으로 오인했을 가능성"
```

**이 명령은 평가 기록만 남기고 절대로 공식 승인을 수행하지 않는다.**

### 공식 승인 로그 재검증

`apply-approved`, `world-state`, Graphify 투영, `check-continuity`는 사용하려는 각 승인 후보에 다음 항목을 확인한다.

1. 현재 후보의 `status='approved'`
2. 해당 후보에 대해 **정확히 하나의** `review_log` 승인 기록이 실제로 존재하는지
3. 승인 결정이 `approved`인지, `reviewer`·`reason` 문자열이 비어 있지 않은지
4. 저장 후보의 종류·payload·원문 SHA·오프셋·인용을 기준으로 재계산한 SHA-256이 불변 `candidate_id`와 일치하는지(후보 검토 시점)

승인 로그가 없거나 모순되면 명확한 오류로 거부한다. 공식 적용은 기존 SQLite 트랜잭션과 전체 리플레이 검증을 유지한다.

**중요한 한계:** 이 검사는 승인 *기록의 존재 및 일관성*을 검증한다. `--reviewer human`이라는 문자열이 실제 사람의 동의라는 사실이나, 권한을 가진 운영자의 직접 DB 조작까지 방지한다는 의미가 아니다. 실사용 사용자 인증/확정 승인 절차는 별도로 연결해야 한다.

### 읽기 전용 감사

`review-audit` 명령은 원고 인용 없이 모델 평가와 공식 상태를 분리해 보여준다.

```bash
$PY -m novelgraph --data-root "$ROOT" \
  review-audit --work-id "<작품_ID>" --episode 5
```

출력: `model_assessments`, `official_proposed`, `official_approved`, `official_rejected`, `approved_with_review_log`, `approved_missing_review_log`, `human_identity_authenticated: false`. 인증된 사용자 수라고 주장하지 않는다.

## 3. 합성 테스트 확인 범위

- 모델의 `supports` 의견만으로 후보 승인·계약 이행·현금 변경 불가
- 모델 의견을 남긴 뒤 별도로 명시적으로 기록한 공식 승인만 적용 가능
- 모델 검토 로그와 승인 로그를 분리해 조회 가능
- 승인 없이 `status`만 위조한 후보는 `apply-approved`, Graphify, `check-continuity`에서 거부
- 저장된 후보 payload 금액을 원문 인용과 무관하게 직접 바꾸면 승인 시 **후보 해시 불일치**로 거부
- 원본 파일 해시가 달라진 경우 모델 평가 거부·DB 로그 미생성
- 모델 의견으로 `approve`를 보낼 수 없고 거절된 후보를 되살릴 수도 없음
- 기존 승인·현금·계약·주식 이행 및 거래 중복 적용 방지 기능 유지

테스트 입력은 전부 합성 한국어 문장이다. 실제 소설 원문은 공개 저장소의 테스트·문서에 넣지 않았다.

**Moon 전체 회귀 테스트:** `/shared/NovelGraph/.venv/bin/python -m unittest discover -s tests -v` → **122/122 통과, 322.108초**. 이전 113개에 신규 테스트 9개를 추가했다.

## 4. 실제 원고 1~5화에 대한 비파괴 확인

비공개 파일럿 작품의 공식 SQLite DB에는 후보 **26건 전부 `proposed`**, 공식 `approved` 0건, `applied_events` 0건이 기록되어 있다. `review-audit`로 현재 상태를 **읽기 전용** 확인했다.

따라서 이번 작업에서는 실제 후보를 임의 승인하거나 사용자 동의 없이 새 모델 평가 로그를 기록하지 않는다.

## 5. 운영 원칙과 남은 게이트

- 소설 본문을 읽는 LLM/ChatGPT의 **예비 판단**은 `assess-candidate`에만 기록한다.
- `review-candidate --decision approve`는 **실제 사용자가 그 후보·근거·상태 효과를 직접 확인하고 승인한 이후에만** 운영 절차로 호출한다. 단순 `--reviewer` 문자열은 사용자 인증이 아니다.
- `apply-approved`는 공식 승인 기록과 원문·후보 무결성이 확인된 상태 변경 후보에만 사용한다.
- 향후 사용자 인증·승인 증빙을 신뢰할 수 있는 외부 도구로 연결하거나, 검증자가 물리적으로 직접 실행하는 운영 제약을 마련하기 전에는 **무단 사용자를 완전히 차단했다**고 주장하지 않는다.
- [02/12]의 인간 독립 정답표 부재로 추출 의미 정확도와 실제 장편 정합성 품질은 여전히 미측정이다.

관련: [전체 실행 계획](superpowers/plans/2026-11-05-novelgraph-production-plan.md), [03단계 추출 계약](23-extraction-contract-and-preflight-2026-11-05.md), [04단계 인물 검사](24-identity-audit-phase4-2026-11-05.md).
