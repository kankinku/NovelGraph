# [01/12] 실사용 전환 기준선 및 안전 감사 — 2026-11-05

> **판정: 기준선 검증 통과.** 기능 정확도/실제 오류 탐지율을 통과했다는 의미는 아니다. 독립 검수 정답표 준비는 [02/12]에서 별도로 진행한다.

## 1. 확인 범위

- 저장소: `kankinku/NovelGraph` (`main` 기준 SHA `41cdc4859061cb669cb08ed25b60a6fac20a1359`)
- 개발·검증: Moon `/shared/NovelGraph`, private 격리 worktree `feat/production-phase1-baseline`
- 런타임: Python 3.12.3 / SQLite 3.45.1 / `graphifyy==0.9.102`
- 감사 대상: `novelgraph/__main__.py`, `world_state.py`, `continuity.py`, `graphify_bridge.py`, `pilot_eval.py`, `batch_readiness.py`, `tests/`, 실제 비공개 1~5화 파일럿 DB의 **메타데이터**
- 적용 스킬: Superpowers (TDD·검증 게이트·단계별 실행), Karpathy Guidelines (불필요한 가정과 변경 최소화), Ponytail Full/Ultra (기존 경로 우선·위험 중심 감사)

## 2. 재현된 기준선

```bash
cd /shared/NovelGraph-data/research/production-phase1-20261105
/shared/NovelGraph/.venv/bin/python -m unittest discover -s tests -v
# Ran 73 tests in 201.135s
# OK
```

- 실제 코드 테스트: **73/73 통과**. 이는 합성 테스트 + CLI·상태 엔진·Graphify + 평가/배치 검사로 구성되어 있으며, 소설 의미 추출의 정확도 검증은 아니다.
- Git tracked 파일: 35개. 현재 저장소에서 실제 원고·후보 JSON·SQLite 파일 추적 발견 없음.
- 비공개 5화 파일럿 공식 DB: `proposed` 후보 26건 / 적용 사건 0건.
- 별도 검증용 shadow DB: 모델 검토 승인 형식 25건, 미검토 1건 / 적용 사건 0건. **사용자 확정 승인 아님.**
- 공식·shadow DB 모두 `PRAGMA integrity_check = ok`.

## 3. 데이터 안전 스냅샷

- 원본 경로: `/shared/NovelGraph-data/works/ashcroft-pilot-20261104`
- 별도 스냅샷: `/shared/NovelGraph-data/backups/phase01-20261105`
- 비공개 파일 **40개** 복제 및 비-DB 파일 SHA-256 동일성 대조.
- SQLite **2개**는 Python `sqlite3.Connection.backup()`으로 온라인 백업하고 양쪽 무결성을 확인.
- 디렉터리 권한 0700, 백업 파일 권한 0600.
- 원본 1~5화 별도 보존 및 판본 해시는 이전 `reports/source-manifest.json`에 기록돼 있다.
- 전체 백업 파일 목록 및 해시는 private `baseline-manifest.json`에 보관하며 공개 GitHub에 올리지 않는다.

이 스냅샷은 회복 가능성을 높이기 위한 복사본이지 아직 **전체 장애 복구 리허설**은 아니다. [11/12]에서 복구 후 동작까지 별도로 검증한다.

## 4. 위험 우선순위 감사

| 수준 | 실제 코드와 근거 | 확인한 한계·실패 가능성 | 다음 최소 작업 |
| --- | --- | --- | --- |
| **P0** | `novelgraph/pilot_eval.py:135` | 현재 비교기는 **연속성 오류 판정**만을 독립 정답표와 비교한다. 원고 사실 추출의 재현율과 누락률을 계산할 수 있는 독립 금표준은 아직 없다 | [02] 사람 검수 정답표를 만들고 평가 필요성부터 검증 |
| **P0** | `novelgraph/world_state.py:140-163` | `reviewer` 값이 자유 형식 식별자라 인증된 인간 승인으로 증명되지 않는다. 모델이 스스로 승인하는 운영 절차를 허용하면 정보가 부정확하게 확정될 수 있다 | [05] 모델 검토와 사용자 승인 구분 및 실행 절차 시험 |
| **P1** | `novelgraph/__main__.py:151-165` | 같은 작품·회차 원문 SHA가 바뀌면 수입을 거절한다. 안전하지만 수정본 재분석/판본 추적은 별도 지원이 필요하다 | [07] 원본·새 판본 별도 보존 및 영향 범위 검토 |
| **P1** | `novelgraph/world_state.py:58-71` | 공식 상태 사건은 현금 시작·지급·수령, 계약 체결, 지분 이전에 제한된다. 실제 작품의 채권·채무, 재평가, 계약 해지 등을 현재 엔진이 완전히 표현하지는 못한다 | [06] 독립 정답표에서 확인된 미지원 유형만 확장 |
| **P1** | `novelgraph/continuity.py:16-31` | 필드 기반 날짜·위치·행동·금액·계약 검사. 복잡한 장면 묘사나 인물의 숨은 의도를 LLM 수준으로 자동 이해하지 않는다 | [08] 실제 오류 정답표를 토대로 검출기 범위 판정 |
| **P1** | `novelgraph/batch_readiness.py:42-53` | 해시·회차·DB 등록 완료는 분석 '준비' 확인이지 의미 추출/정확도/승인 완료가 아니다 | [12] 준비 상태와 실제 품질/승인 게이트를 분리 |
| **P2** | `novelgraph/__main__.py:246-400` | 사용자는 순서에 맞춰 여러 CLI 명령을 호출해야 한다. 대형 원고에서는 재개/진행 이력의 운영 절차가 필요하다 | [10~11] 현 명령 조합부터 절차화, 필요 시만 보조 명령 |

**우선 수정 대상 하나:** 정보 추출의 실제 누락·오탐을 알기 위한 **[02/12] 독립 검수 정답표**. 근거 없는 대규모 재작성은 보류한다.

## 5. [02/12] 사전 준비 현황

공개 GitHub에 원고를 노출하지 않고, private `reports/fact-review-worksheet-20261105.json` 및 `.md`를 생성했다.

- 1~5화에서 수집한 후보 26건을 원본 문자 위치·회차·SHA·후보 ID로 연결해 목록화.
- 각 후보의 상태는 **unreviewed**, 각 회차의 전체 본문 점검 상태는 **not_started**.
- 인물·시간·장소·행동·계약·자산·관계·회상·장면 연속성 범주를 확인하는 체크리스트 및 **미추출 사실 추가란** 생성.
- 아직 사람의 독립 검수를 받지 않았으므로 **금표준 정답표가 아님**. 정밀도·재현율·F1은 미측정(`null`).

## 6. 다음 단계 진행 조건

**[01] 기준선·백업은 검증됨.** [02]는 작업표 작성까지 완료했지만 정답표 인간 독립 검증은 대기 중이다.

1. 검수자가 실제 원고 전체를 확인해 후보의 정확성과 누락된 사실을 표시한다.
2. 사람의 검수 내용과 모델 검토를 분리하고 각 사실의 근거 SHA·오프셋을 재검증한다.
3. 확정 gold를 기준으로 부족한 추출 유형만 [03]에서 테스트 우선으로 개선한다.

모든 개발 단계에 적용할 상세 작업과 정지 기준은 [Superpowers 실행 계획](superpowers/plans/2026-11-05-novelgraph-production-plan.md)에 작성했다.
