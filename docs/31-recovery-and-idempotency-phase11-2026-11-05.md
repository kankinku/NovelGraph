# [11/12] SQLite 복구·멱등성·데이터 안전 — 2026-11-05

> 상태: **안전한 원장 백업·새 파일 복원 구현 및 합성/비공개 파일럿 검증**. 원본 DB·원고 덮어쓰기 없음. 사용자 승인·인간 금표준·실제 검출 정확도는 이 단계가 해결하지 않는다.

## 1. 기준 동작과 변경 범위

기존 `import-candidates`는 `candidate_id` 불변 해시를 이용하여 재수입을 멱등 처리한다. `review-candidate`는 검토를 한 차례만 기록하며 승인/거절을 확정한 후 재검토로 덮어쓰지 않는다. `apply-approved`는 `with db:` 트랜잭션에서 승인 로그, 거래의 `event_key`, 재생 가능한 상태를 확인한 후 적용한다. 같은 후보의 재적용은 `already_applied=true`, 동일 거래 ID를 사용한 다른 후보는 오류로 처리한다.

기존의 안전 동작을 바꾸지 않고, Python 표준 `sqlite3.Connection.backup` API로 비공개 파일에 일관된 SQLite 스냅샷을 만들고 **기존 파일을 절대 덮어쓰지 않는** 두 명령을 추가했다.

| 명령 | 기능 | 기존 원장 변경 |
| --- | --- | --- |
| `backup-database --output ...` | `--data-root/novelgraph.sqlite`을 읽기 전용으로 열고 완전성 확인 후 새 백업 생성 | 없음 |
| `restore-database --backup ... --output ...` | 비공개 백업을 검증한 뒤 사용자가 지정한 **존재하지 않는** 새 경로에 복원 | 없음 |

두 명령은 출력 파일을 개인 데이터 루트 내부, 권한 `0700`인 상위 폴더에만 허용한다. 파일은 `0600`으로 생성된다. 백업/복원 원본은 symlink/타인 읽기 가능 파일이면 거절한다. 내보내기 전후에 `PRAGMA integrity_check`, `foreign_key_check`, NovelGraph 최소 필수 테이블 존재를 확인한다.

복사 중에는 비공개 숨김 임시 파일을 사용하며, 검증에 성공한 파일만 원자적으로 **새 링크를 생성**해 게시한다. 이미 존재하는 경로로 출력을 요청하면 실패한다. 일반적인 예외 시 임시 파일은 제거하지만 `SIGKILL`/정전 중 남겨진 숨김 임시 파일은 사람이 확인하고 정리해야 한다. 기존 원본이나 새 이름의 완성 백업을 자동 정리·교체하지 않는다.

## 2. Moon 실행 예시

아래는 형식 예시이며 실제 작품 데이터 경로는 공개 Git에 기록하지 않는다. 명령 실행 전에 목적지 디렉터리를 직접 비공개로 만든다. **복원 대상은 새 파일이어야 한다.**

```bash
cd /shared/NovelGraph
ROOT=/shared/NovelGraph-data/works/<private-work>
mkdir -m 700 "$ROOT/backups-new"

.venv/bin/python -m novelgraph --data-root "$ROOT" \
  backup-database --output "$ROOT/backups-new/snapshot.sqlite"

mkdir -m 700 "$ROOT/backups-new/recovered"
.venv/bin/python -m novelgraph --data-root "$ROOT" \
  restore-database \
  --backup "$ROOT/backups-new/snapshot.sqlite" \
  --output "$ROOT/backups-new/recovered/novelgraph.sqlite"
```

복원된 DB를 운영 DB로 **바로 바꿔 끼우지 않는다**. 다음 순서로 별도 검사한다.

1. `integrity=ok` 및 백업/복원 `snapshot_sha256` 일치 확인.
2. SQLite 읽기 전용으로 `episodes`, `candidates`, `review_log`, `applied_events` 등 관련 테이블의 개수와 원장 상태 대조.
3. 등록된 작품·회차 `source_sha256`과 **현재 보유 원고 원본 바이트 SHA** 전수 대조. 파일이 다르면 자동 승인·적용 금지.
4. 사용하려는 작품의 `workflow-status`와 `source-version-audit`를 **해당 비공개 작품 루트와 실제 원고**로 점검. 판본이 다르면 `SOURCE_VERSION_AUDIT` 처리.
5. 실제 서비스 원장 교체/이전은 별도 데이터 이관 계획과 사용자 승인 후 수행해야 한다. 현재 CLI는 **복구본을 원본 DB 위에 덮어쓰는 기능을 제공하지 않는다**.

`snapshot_sha256`은 생성된 SQLite 파일의 바이트 해시다. 동시 작업 시 원본 DB의 순간 파일 해시와 무조건 동일하다고 주장하지 않는다. 스냅샷은 SQLite 온라인 백업 시점의 일관된 DB 상태를 복사한다. SQLite WAL 부속 파일이 있는 환경에서도 DB 파일을 단순 `cp`하지 않고 SQLite API를 사용한다.

## 3. 단계별 실패·중단 대응

- **작업 중단 후 재개:** 기존 `workflow-status --work-id --episode --source`로 매번 현재 등록 상태를 재조회한다. 오래된 스냅샷·대화 기록만으로 승인/지급을 이어서 실행하지 않는다.
- **후보 중복 제출:** 같은 `source_sha256`·정규화 payload·근거 위치의 후보 ID는 동일하다. 재수입 시 `duplicates`만 증가하고 공식 사건은 새로 생성되지 않는다.
- **부분 승인·부분 적용:** `proposed`, `approved`, `rejected`와 `approved_state_changes_pending_apply`를 분리하고 사용자 검수 기록을 확인한 경우에만 한 사건씩 적용한다.
- **중복 지급:** 동일 `transaction_id`·동일 후보를 중복 실행하면 현금의 중복 차감이 허용되지 않는다. 다른 후보로 동일 거래 키를 재사용하면 적용 오류로 중단한다.
- **손상 DB/백업:** 무결성 검사에 실패한 파일은 복사/복원을 끝내지 않으며, 기존 원본이나 완성 출력 파일을 변경하지 않는다.
- **원고가 바뀐 경우:** 원고 SHA와 근거 위치 확인을 먼저 통과해야 승인·적용 가능하다. 변경 판본을 기존 승인에 몰래 연결하지 않는다.
- **강제 종료:** 합성 테스트에서 진행 중인 미커밋 SQLite 트랜잭션을 강제 종료한 후 원장이 원래 상태로 롤백되며 백업·복원이 가능한 것을 검증했다.

## 4. 합성 테스트 및 비공개 파일럿

신규 `tests/test_recovery.py`의 **12개**는 백업/새 경로 복원·표/근거 보존, 출력 덮어쓰기 거절, 손상된 live/backup 차단, 경로 탈출·공개 권한·symlink 차단, 원장 또는 백업의 소유자 읽기 권한이 없는 경우 거부, 원고 변경 검출, 동일 후보/지급 멱등성, SQLite 미커밋 트랜잭션 강제 종료 후 복원까지 포함한다. 신규 CLI가 없던 시점 실패 재현 7건 및 기존 동작 테스트 통과 4건을 기록했다. 구현 후 새 테스트 **12/12 통과**를 확인했다.

비공개 실데이터는 `ashcroft_pilot`의 기존 1~5화와 후보 26건을 사용했다. **원본 DB와 원고에는 쓰기 실행을 하지 않았다.** 별도 `0700` 비공개 폴더에 `0600`인 백업·복원 파일을 새로 생성하고, `episodes=5`, `candidates=26`, 1~5화 등록 SHA 모두 원본 원고 바이트와 일치함을 확인했다. 공식 DB SHA-256은 작업 전후 동일했다.

별도 문제: 원고 추출이 완전한지, 26건의 의미가 정확한지, 인간 승인 절차의 신원 보증 여부는 이 복구 테스트에서 확인하지 않았다.

## 5. 후속 단계

[12/12] 동일 작품 전수 점검 및 출시 게이트에서 독립 정답표·오탐·누락 및 전체 대상 회차의 분석 범위를 검사한다. 현재 비공개 파일럿 1~5화와 과거 43화 목표 작품은 **서로 같은 작품이라고 가정하지 않는다**. 기존 원장 보호·재처리 안전만으로 실제 원고 분석 정확도가 검증됐다고 보고하지 않는다.

관련: [10단계 재개 운영](30-moon-workflow-phase10-2026-11-05.md), [12단계 계획](superpowers/plans/2026-11-05-novelgraph-production-plan.md).
