# [10/12] ChatGPT ↔ Moon 단일 회차 분석·재개 운영 절차 — 2026-11-05

> **코드 범위:** 읽기 전용 `workflow-status` 조회와 실행 절차 문서. 원고 추출·승인·적용을 한 번에 자동 실행하지 않으며, 기존 Moon MCP·SQLite·Graphify 인터페이스 유지. 실제 의미 정확도와 독립 인간 검수는 별도 미완료 게이트.

## 1. 실행 주체와 보안 경계

| 주체 | 수행 작업 | 수행하지 않는 작업 |
| --- | --- | --- |
| ChatGPT(현재 대화 안) | Moon으로 원고 열람 후 서사적 의미 해석, 원본 위치가 있는 JSON 후보 작성, 검수 필요 항목 보고 | 무인 예약 추출·ChatGPT 모델을 Moon 서버 내부에서 자동 호출 |
| Moon MCP | 비공개 원고 읽기, 후보 파일 전달, NovelGraph CLI 실행·결과 반환 | 별도 유료 LLM 호출·독자적인 자연어 의미 확인 |
| NovelGraph CLI | 입력 해시·형식 검증, 후보 격리, 승인 기록 확인, 명시적 사건 적용, 세계 상태 재생·연속성 보고 | 사용자 검수 없이 확정 승인, 임의 자산 추정, 자동 집필·퇴고 |
| 사용자/독립 검수자 | 중요한 사실과 인물/거래 동일성 검토, 공식 승인 결정 | `--reviewer`라는 문자열만으로 실제 신원 인증이 됐다고 간주 |

실제 원고·후보 JSON·DB·보고서·검수 로그는 **공개 Git 외부** `/shared/NovelGraph-data/works/<작품-비공개-폴더>`에 둔다. 작품마다 별도 비공개 데이터 루트·작품 ID·원고 SHA 기록을 권장한다. `work_id`를 생략하거나 파일 이름만으로 작품을 추정하지 말고, 같은 이름의 1화라도 작품별로 구별한다.

## 2. 단계별 표준 실행 (한 회차)

아래 `ROOT`, `WORK`, `EP` 및 `SOURCE`는 **같은 작품의 같은 회차**를 가리켜야 한다. 기존 후보 파일은 덮어쓰지 않고 작성·검증한다. 서버에서 실제로 직접 실행할 때 기준 저장소는 `/shared/NovelGraph`이다.

```bash
cd /shared/NovelGraph
ROOT=/shared/NovelGraph-data/works/<private-work>
WORK=<registered-work-id>
EP=1
SOURCE="$ROOT/source/001.txt"
INPUT="$ROOT/candidates/001.json"
PY=.venv/bin/python

# 1. 파일 본문/판본의 바이트 해시와 문자 길이 확인 (DB 쓰기 없음)
"$PY" -m novelgraph --data-root "$ROOT" source-info --source "$SOURCE"

# 2. 중단/재개 지점 확인 (DB 없어도 읽기 전용 결과 반환)
"$PY" -m novelgraph --data-root "$ROOT" workflow-status \
  --work-id "$WORK" --episode "$EP" --source "$SOURCE"

# 3. ChatGPT가 이전 회차 승인 상태·현재 원문과 근거를 읽고
#    schema_version=1 후보 JSON을 비공개 INPUT에 작성한다.
#    별도 프롬프트: docs/23-extraction-contract-and-preflight-2026-11-05.md
"$PY" -m novelgraph --data-root "$ROOT" preflight-candidates \
  --source "$SOURCE" --input "$INPUT"

# 4. 형식·원문 근거 통과 후만 제안 상태로 저장; 재수입 중복은 새 승인 아님
"$PY" -m novelgraph --data-root "$ROOT" import-candidates \
  --source "$SOURCE" --input "$INPUT"
# 출력된 work_id/episode가 $WORK/$EP와 일치하는지 반드시 확인한다.

# 5. 상태·후보 ID 확인. 모델 의견은 assess-candidate 별도 로그에 둔다.
"$PY" -m novelgraph --data-root "$ROOT" status \
  --work-id "$WORK" --episode "$EP"
"$PY" -m novelgraph --data-root "$ROOT" list-candidates \
  --work-id "$WORK" --episode "$EP"

# 6. 사용자가 개별 후보의 원문·ID·계약/자금 의미를 검수하고
#    실제 승인을 명확히 지시했을 때만 각각 실행:
# "$PY" -m novelgraph --data-root "$ROOT" review-candidate \
#   --source "$SOURCE" --candidate-id "<verified-candidate-id>" \
#   --decision approve --reviewer "<label>" --reason "<review-reason>"

# 7. approved 상태의 실제 state_change만 개별 검증 후 적용:
# "$PY" -m novelgraph --data-root "$ROOT" apply-approved \
#   --source "$SOURCE" --candidate-id "<approved-state-change-id>"

# 8. 회차까지 알려진 승인 정보만 조회; 누락 사실은 자동 생성하지 않는다.
"$PY" -m novelgraph --data-root "$ROOT" world-state \
  --work-id "$WORK" --episode "$EP"
"$PY" -m novelgraph --data-root "$ROOT" check-continuity \
  --work-id "$WORK" --episode "$EP"
"$PY" -m novelgraph --data-root "$ROOT" continuity-report \
  --work-id "$WORK" --episode "$EP"

# 9. 원고가 현재 판본 그대로인지 별도 대조한다.
"$PY" -m novelgraph --data-root "$ROOT" source-version-audit \
  --work-id "$WORK" --episode "$EP" --source "$SOURCE"
```

Graphify 파생 조회가 필요한 경우, **승인·적용된 근거만 대상으로** `graphify-export`를 사용한다. `$ROOT/graphs` 같은 `0700` 비공개 디렉터리에 새 `graph.json`으로 출력하며, 기존 그래프가 존재하면 명시적으로 검토하기 전에는 `--overwrite`를 사용하지 않는다. Graphify는 원장의 기준 진실이 아니며, Graphify 결과가 최신 승인 기록과 같은지 확인한다.

## 3. 중단 후 재개 명령

```bash
.venv/bin/python -m novelgraph --data-root "$ROOT" workflow-status \
  --work-id "$WORK" --episode "$EP" --source "$SOURCE"
```

응답은 파일이나 원본 인용을 쓰지 않는 JSON이다. 주요 필드:

| 필드/상태 | 의미 | 다음 처리 |
| --- | --- | --- |
| `database_missing` | 비공개 DB가 없음 | 원고 SHA 확인 → ChatGPT 추출 → preflight. **명령 자체는 DB 생성 안 함** |
| `episode_unregistered` | 해당 `work_id`·회차 미등록 | 현재 회차·작품·원고를 확인하고 preflight/import |
| `matches_registered` | 입력 원고와 최초 등록 SHA가 같음 | 기존 후보 상태에 따라 검수·적용·조회 |
| `source_mismatch` | 입력 판본과 등록 SHA 불일치 | `halt_mutations=true`, `SOURCE_VERSION_AUDIT`; **기존 승인을 새 판본으로 이월하지 않음** |
| `EXTRACT_AND_PREFLIGHT` | 등록 후보가 없거나 회차 미등록 | 후보 추출·형식 검증부터 진행. 완료 또는 누락 0을 뜻하지 않음 |
| `HUMAN_REVIEW` | `proposed` 후보 존재 | 사용자/독립 검수자에게 근거와 후보를 보여주고 승인 여부 확인 |
| `APPLY_APPROVED` | 승인된 상태 사건 중 적용되지 않은 ID 존재 | 개별 사건·지급 중복 확인 후 명시적 `apply-approved` |
| `READ_ONLY_CHECKS` | 현재 등록된 후보에 검토/미적용 항목 없음 | 상태·연속성·판본·Graphify 조회. **원고 전체 분석 완료 판정 아님** |

`next_actions`가 여러 개면 `HUMAN_REVIEW`와 `APPLY_APPROVED`를 별도로 진행한다. `approved_state_changes_pending_apply`와 `applied_state_change_ids`는 회차별 ID만 출력하며, 설명 없이 적용·재적용하지 않는다. `read_only=true`, `extraction_completeness_verified=false`, `human_identity_authenticated=false`, `semantic_accuracy_measured=false`는 의도적으로 유지된다.

**작업 기록 유지:** 매번 재개 전 `workflow-status`를 새로 호출한 결과를 운영 로그에 기록한다. 필요하면 `umask 077`을 설정하고 표준 출력을 **이미 존재하지 않는** 비공개 파일로 저장한다. 이전 JSON 스냅샷은 참고용이며, 다음 세션에서는 반드시 명령을 다시 실행해 새 상태를 확인한다. 별도 자동 실행 데몬이나 영구 체크포인트 테이블을 추가하지 않았다.

## 4. 오류/예외 처리

1. **같은 원고·같은 후보 재수입:** `import-candidates`의 `duplicates`와 `inserted`를 확인한다. 동일 입력은 후보만 멱등 삽입이며 '원고 추출이 완전하다'는 증거가 아니다.
2. **회차 중간의 승인/적용:** `workflow-status`에서 아직 제안 상태인 ID와 승인되었으나 미적용 상태 사건을 분리한다. 원장과 `review-audit`를 확인하고, 이미 적용된 상태 사건은 두 번 실행하지 않는다.
3. **원고 수정/오류:** `source_mismatch` 상태에서 기존 증거 오프셋·승인·적용 내용을 자동 이전하거나 DB/원고를 덮어쓰지 않는다. `source-version-audit` 후 새로운 판본 절차를 별도 수립한다.
4. **계약과 돈:** 제안·거절·서명·송금·지분 양도는 각각 독립 근거와 사건 ID를 요구한다. 재언급은 신규 송금으로 간주하지 않으며, 현금과 총자산은 다르다.
5. **다른 작품/회차:** `work_id`와 `episode`로 DB 조회를 제한한다. 오입력 원고 SHA가 맞지 않으면 진행을 중단한다. 원고 내용이 우연히 완전히 같더라도 작품 ID 자체를 추론해 복원할 수는 없다.
6. **승인 위조:** 승인 로그 없거나 불일치하는 `approved` 상태는 상태 조회 단계에서 실패한다. `--reviewer` 문자열은 본인 인증 수단이 아니다.
7. **결과 품질:** 승인 사실 0건이나 검출 경고 0건은 실제 소설 오류 0건이 아니다. 독립 정답표가 없으므로 정밀도·재현율·F1을 계산하지 않는다.

## 5. 가능한 것과 불가능한 것

**한 번의 ChatGPT 요청에서 가능한 것:** Moon으로 접근할 수 있는 특정 원고 회차를 읽고, 후보를 작성·사전 검증·제안 상태로 등록하며, 기존 기록과 비교해 **검토 대기 결과까지** 전달. 정보량과 대화 세션의 제약 범위 안에서만 순차 실행한다.

**자동 완료로 주장할 수 없는 것:** Moon CLI가 ChatGPT와 독립적으로 원고의 모든 의미 후보를 생성하거나 독립 인간 검수를 마치는 일, 여러 대화에 걸친 무인 의미 추출, 사용자의 승인 없이 사건을 공식 적용하는 일, 수십 회차의 사실 추출 정확도가 이미 95%에 도달했다는 주장.

## 6. 검증 범위와 다음 단계

신규 합성 테스트 10개로 DB 미존재, 작품·회차 범위, 후보 제안, 승인·미적용·적용 완료, 제안/거절 혼재, 원고 변경, 위조 승인, 후보 0건, 결정적 재조회/DB SHA 불변, 다른 작품 원고 오입력 차단을 재현했다. 신규 명령 구현 전 **10개 RED**, 구현 후 **10/10 GREEN**. Moon 전체 회귀 명령 `/shared/NovelGraph/.venv/bin/python -m unittest discover -s tests -v` 결과는 **166/166 통과 (377.575초)**이며, 비공개 기록은 `/shared/NovelGraph-data/research/production-phase10-full-suite.log`에 보관했다.

실제 비공개 파일럿 `ashcroft_pilot` 1~5화 모두 `matches_registered`를 반환했다. 회차별 `proposed`는 12/2/4/3/5건으로 총 26건이며, `approved=0`, `rejected=0`, `next_actions=[HUMAN_REVIEW]`다. 5화만 별도로 조회한 결과에서도 제안 5건이 확인됐다. DB SHA-256은 전후 일치했다. 재개 시점 기록은 **비공개 전용** `reports/workflow-resume-checkpoint-20261105.jsonl`로 별도 남겼다(권한 `0600`). **후보 추출 완전성이나 실제 오류 검출력을 평가한 실험은 아니다.**

[11/12]에서는 SQLite 백업·복원 및 중단/중복 적용 안전성을 별도 TDD로 강화한다. 관련: [전체 계획](superpowers/plans/2026-11-05-novelgraph-production-plan.md), [09단계 보고서](29-writer-continuity-report-phase9-2026-11-05.md).
