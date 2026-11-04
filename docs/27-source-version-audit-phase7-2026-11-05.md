# [07/12] 회차의 정보 공개 시점과 원고 판본 점검 — 2026-11-05

> **결과:** 소급 공개 사건의 시점 분리 회귀 테스트와 읽기 전용 원고 SHA·영향 범위 감사 구현. 원고 교체·DB 마이그레이션·자동 재승인은 수행하지 않았다.

## 1. 기존 동작 확인

NovelGraph는 세계 상태의 `source_episode`(독자가 정보를 알게 된 회차)와 `effective_episode`(사건이 발생한 회차)를 구분한다. 회차별 `world-state`는 **해당 회차까지 공개된** 승인·적용 사건만 반영한다.

원고는 `episodes(work_id,episode,source_sha256)`에 최초 등록한 해시로 고정된다. 동일 작품·동일 회차에 내용이 변경된 입력을 `import-candidates`로 다시 저장할 수 없다. `review-candidate`·`apply-approved`는 호출 때 제공한 원고 내용의 SHA 및 불변 후보 해시와 Unicode 근거 구간을 검증한다.

**부족했던 기능:** 현재 파일의 내용이 변경됐을 때, 어느 승인·적용 후보가 그 판본에 의존하는지 한눈에 확인하는 안전한 조회 기능.

## 2. 추가한 명령: `source-version-audit`

비공개 파일에 대해 기존 등록본과 실제 파일의 SHA-256을 비교한다.

```bash
ROOT=/shared/NovelGraph-data/works/ashcroft-pilot-20261104
cd /shared/NovelGraph

.venv/bin/python -m novelgraph --data-root "$ROOT" \
  source-version-audit \
  --work-id ashcroft_pilot --episode 1 \
  --source "$ROOT/source/001.txt"
```

출력 범위:

| 필드 | 의미 |
| --- | --- |
| `registered_source_sha256` | 해당 작품·회차의 원래 등록 판본 |
| `observed_source_sha256` | 입력 파일의 현재 바이트 해시 |
| `source_matches_registered` | 등록 판본과 현재 판본이 같은지 |
| `candidate_counts` | `proposed`·`approved`·`rejected` 개수 |
| `affected_approved_ids` | 판본이 달라졌을 때 다시 확인할 승인 후보 ID |
| `affected_applied_ids` | 판본이 달라졌을 때 다시 확인할 이미 적용된 사건 후보 ID |
| `requires_new_version_workflow` | 현재 원고가 등록 판본과 달라서 **별도의 새 판본 검토·마이그레이션 절차가 필요함** |
| `read_only` | 기록·승인·원고를 변경하지 않음 |

원고 문장과 인용 텍스트를 출력하지 않는다. SQLite는 `mode=ro`로 연다. 경로는 비공개 데이터 루트 안에 있어야 하며 DB는 소유자 전용 권한이어야 한다. 일치 여부를 확인하는 명령이 **실제 정답 판정이나 사용자 승인이라고 주장하지 않는다.**

## 3. 변경 판본 처리 원칙

현재 시스템은 **불변 단일 판본**이다. `source-version-audit`는 판본 차이와 영향 범위를 경고하지만, 새 판본으로 덮어쓰기·원고 버전 히스토리 생성·기존 승인 로그 자동 이전을 수행하지 않는다.

원고 수정이 발견되면:

1. 원본 및 현재 원고를 별도로 백업하고 수정된 부분을 사람이 확인한다.
2. 기존 승인·적용 후보는 새 판본을 통해 자동 재사용하거나 다시 적용하지 않는다.
3. 위 감사의 `affected_approved_ids`·`affected_applied_ids`를 검토 대기 대상으로 기록한다.
4. 새로운 판본을 공식 상태로 승격하기 전에는 **기존 판본을 보존하고 별도 버전 관리·정정 절차를 설계**해야 한다. 기존 DB를 강제로 수정하거나 삭제하지 않는다.

**한계:** `world-state`·Graphify 조회 명령에는 원고 파일 경로가 입력되지 않는다. 이 명령들은 DB의 기존 등록 판본 기준으로 재생·투영한다. 따라서 파일을 수정했다고 해당 조회가 자동 중지되지는 않는다. **판본 감사는 운영자가 실행해야 하는 별도 점검 단계**이며, 자동 감시·자동 판본 전환·모든 조회의 무조건적 최신 원고 검증 기능이 아니다.

## 4. TDD 및 실제 파일럿

합성 원고 기반 7개 신규 테스트로 실패를 확인한 다음 최소 구현:

- 원고 동일: 해시 일치, 후보 개수 확인, DB 바이트 변화 없음
- 원고 수정: 기존 승인·적용 후보의 ID를 영향 범위로 표시; 소스 SHA 불일치 상태로 이전 승인 사건 재적용 거부
- 미승인 원고 수정: 후보 재등록 거부 및 등록 판본 불변
- 두 작품의 같은 회차가 섞이지 않음
- 2화에 발생한 사건이 **5화에서 처음 공개**됐을 때 3화 세계 상태는 그대로이고 5화에만 새 지식 반영
- 미등록 회차·DB 부재는 새 DB 생성 없이 오류 반환

**Moon 전체 회귀 테스트:** `/shared/NovelGraph/.venv/bin/python -m unittest discover -s tests -v` → **142/142 통과 (343.958초)**. 기존 135개에 신규 7개를 추가했다.

실제 비공개 작품 `ashcroft_pilot` **1~5화 모두 현재 원고 SHA가 등록 판본과 일치**했다. 공식 후보 상태는 `proposed` 26건/승인 0건/적용 0건이고, 감사 실행 전후 실제 SQLite 파일 SHA-256은 동일하다. 이 작품의 전체 인물·금전·서사 정합성을 평가한 결과는 아니다.

## 5. 다음 단계의 범위

독립 정답표가 없는 동안에는 잘못된 거래·날짜·요일을 일괄 확정하지 않는다. 대규모 버전 마이그레이션, 승인의 자동 승계, 파일 감시 데몬, 별도 DB·API·MCP 서비스는 필요가 검증되기 전까지 추가하지 않는다.

관련: [12단계 개발 계획](superpowers/plans/2026-11-05-novelgraph-production-plan.md), [추출 계약](23-extraction-contract-and-preflight-2026-11-05.md).
