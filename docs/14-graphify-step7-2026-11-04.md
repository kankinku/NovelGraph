# [7/9] Graphify 실제 연동 및 원문 근거 추적 — 2026-11-04

> **병합 완료:** PR #3 `feat/graphify-step7` → `main`, 커밋 `efc903afb73446589624094a7dc61de3c0d8fe6a`. 이 문서는 **공개 GitHub의 합성 픽스처 테스트 결과**를 설명한다. Moon MCP 연결 오류로 현재 Moon `/shared/NovelGraph`에서 6·7단계를 재검증하거나 동기화하지 못했다. 그 작업을 완료했다고 표기하지 않는다.

## 1. 역할 및 불변 조건

- **ChatGPT**: 원고의 의미를 읽어 인물, 사건, 관계, 상태 변화를 JSON 후보로 추출.
- **Moon MCP**: 원고·JSON 전달 및 NovelGraph CLI 실행. 새로운 MCP 서버 또는 외부 유료 LLM API 호출 불필요.
- **SQLite**: 승인 후보, 적용 완료 사건, 원문 근거·회차·해시 및 상태 전이의 **기준 원장**.
- **Graphify (`graphifyy==0.9.102`)**: SQLite를 읽어 만든 승인 사실들의 **파생 관계 그래프**를 `graph.json`에 직렬화하고 경로를 탐색한다. 그래프가 공식 세계 상태를 수정하지 않는다.

**보안:** 현재 저장소는 `public`이다. Graphify 출력, 사용자 원고, 승인 후보 및 SQLite 데이터는 Git에 커밋하지 않는다. 출력 경로는 권한을 제한한 private 데이터 루트 아래 `graph.json`만 허용한다. 테스트는 전부 가상 문장으로 작성했다.

## 2. 실제 구현 범위

코드: [`novelgraph/graphify_bridge.py`](../novelgraph/graphify_bridge.py) 및 [`novelgraph/__main__.py`](../novelgraph/__main__.py).

| SQLite 입력 | Graphify 파생 표현 | 승인 규칙 |
| --- | --- | --- |
| `entity` 후보 | `entity:<entity_id>` 노드 | `approved`만 |
| `event` 후보 | `event:<candidate_id>` 노드 및 참여자·대상 관계 | `approved`만 |
| `relation` 후보 | `relation:<candidate_id>` 노드 + 출발·도착 연결 | `approved`만 |
| `continuity_fact` 후보 | `assertion:<candidate_id>` 노드 및 대상 연결 | `approved`만 |
| `state_change` 후보 | `event:<candidate_id>` 상태 사건 노드 | **승인 + `apply-approved` 적용 완료**만 |
| 후보별 Evidence | `evidence:<candidate_id>` 노드, `supported_by` 연결 | SHA-256, 회차, Unicode 시작·끝 위치만 포함 |

동일 두 엔티티 사이에 서로 다른 관계가 여러 개 있어도 하나의 단순 엣지로 덮어쓰지 않고 **관계 후보마다 중간 노드**를 사용해 각각 보존한다.

원고에서 식별되지 않은 엔티티 이름은 `unresolved_reference`로 표시한다. 그 대상의 인물·회사 분류나 별칭을 임의로 추론하지 않는다. 승인된 두 주장에 동일 엔티티 ID의 상충하는 정체성이 들어 있으면 조용히 합치지 않고 내보내기를 거부한다.

**특히 상태 엔진과 분리:** 계약 서명·현금 지급·지분 이전은 각각 별도 승인 사건으로 기록된다. Graphify의 관계 노드를 통하여 현금 잔액이나 총자산을 계산하지 않는다.

## 3. Entity / Relation / Event 후보의 최소 스키마

상위 후보 래퍼 및 `evidence` 구조는 [4단계 문서](11-candidate-intake-mvp-2026-11-04.md)와 동일하다. 아래는 `payload` 예시다.

```json
{"entity_id":"evelyn","entity_type":"person","name":"에블린"}
```

```json
{"source_id":"evelyn","target_id":"aurora","relation_type":"collaborates_with"}
```

```json
{"event_type":"visit","actor_id":"evelyn","target_id":"aurora"}
```

- `entity_type`: `person`, `organization`, `place`, `contract`, `asset`, `object` 중 하나.
- `event`의 `target_id`는 선택값이다. `state_change`의 이벤트 계약은 [5단계 문서](12-world-state-step5-2026-11-04.md)를 따른다.
- 원고 근거 없는 관계는 확정하지 않는다. 스키마가 틀린 승인 후보도 내보내기 과정에서 거부한다.

## 4. Moon CLI 사용법

현재 코드가 Moon에 동기화된 뒤 아래 명령을 사용할 수 있다.

```bash
cd /shared/NovelGraph
PY=.venv/bin/python
PRIVATE=/shared/NovelGraph-data

# 승인한 후보·적용 사건을 5화까지의 지식 그래프로 내보낸다.
$PY -m novelgraph --data-root "$PRIVATE" graphify-export \
  --work-id novel --episode 5 --output "$PRIVATE/graph.json"

# 같은 시점의 관계 경로를 조회하고 후보·근거 회차·해시·문자 위치 확인
$PY -m novelgraph --data-root "$PRIVATE" graphify-trace \
  --work-id novel --episode 5 --graph "$PRIVATE/graph.json" \
  --from-node entity:evelyn --to-node entity:aurora

# 재생성이 필요한 경우에만 명시적으로 기존 파생 파일 덮어쓰기
$PY -m novelgraph --data-root "$PRIVATE" graphify-export \
  --work-id novel --episode 5 --output "$PRIVATE/graph.json" --overwrite

# Graphify 기본 CLI로도 같은 graph.json 관계 경로 탐색 가능
$PY -m graphify path 에블린 오로라 --graph "$PRIVATE/graph.json"
```

위 명령의 작품 ID·후보·데이터는 **실제 입력에 맞게 교체해야 한다**.

`graphify-trace`는 출발·목적지 ID가 모두 존재해야 하고, 연결 경로를 반환한다. 관계 방향과 반대로 탐색한 홉은 `traversed_forward: false`로 구별한다. 반환된 `evidence`에는 원고 자체 문장이 들어가지 않고 `candidate_id`, `episode`, `source_sha256`, `start`, `end`가 포함된다.

## 5. 그래프 최신성·일관성 검증

- 그래프에는 작품 ID, 조회 회차, NovelGraph 포맷 버전 및 **SQLite에서 재구성된 그래프 지문**이 저장된다.
- 조회 시 SQLite에서 그래프를 다시 투영하고, **방향성·노드/엣지 집합·주요 속성·근거 SHA·문자 위치**를 비교한다.
- 검증 중 승인 사실이 추가되거나 사건 적용이 완료된 경우 기존 `graph.json`을 오래된 상태로 간주해 조회를 거부한다. 재내보내기가 필요하다.
- 저장된 그래프에 승인되지 않은 노드나 출처 없는 속성을 주입해도 거부한다.
- 내보내기는 SQLite의 공식 상태를 변경하지 않는다. `graph.json`은 삭제·재생성 가능한 **캐시**이며 기준 원장이 아니다.

**제한:** 승인 당시 확인된 원문 해시는 SQLite에 저장되지만, 현재 설계에는 실제 파일 경로·판본을 찾는 전체 원문 리졸버가 없다. 따라서 해시·회차·문자 위치는 반환해도 원고의 원문 문장을 직접 찾아 출력하는 자동 해석까지 제공하지 않는다. 실제 인용문 회수 시 Moon에서 해당 작품·회차 파일의 SHA를 검증하는 절차가 추가로 필요하다.

## 6. 테스트 및 기술 판정

- 테스트: [`tests/test_graphify_projection.py`](../tests/test_graphify_projection.py)
- 합성 픽스처 전용 신규 15개 테스트: 승인 엔티티/사건/관계 및 Evidence, Graphify CLI 경로, 복수 관계 손실 방지, 미승인 후보 제외, 상태 변경 적용 후 포함, 회차 필터링, 오래된 그래프 차단, 변조 차단, 비공개 경로 보호, 역방향 관계 표시, 원장 비변경, 스키마 오류 처리.
- GitHub Actions: **전체 56/56 통과**, Python 3.12, `graphifyy==0.9.102` (2026-11-04 UTC 기준 실행).
- 신규 15개 + 종전 41개 테스트. 이는 장편 실증 정확도를 보증하지 않는다.
- **Moon 검증 대기:** 현재 Moon 접속 문제로 `/shared/NovelGraph` 코드를 최신 GitHub에 동기화하지 못했고 Moon에서 56개 테스트를 재현하지 못했다.

## 7. 다음 단계

1. Moon 접속 복구 즉시 `git status` 등 현재 상태 확인 → `git pull --ff-only origin main` → `.venv/bin/python -m unittest discover -s tests -v`로 6·7단계를 재검증한다. 무단 `git reset --hard` 또는 기존 개인 데이터 덮어쓰기를 금지한다.
2. [8/9] 실제 1~3화 파일럿을 시작하기 전에 **원문 파일 경로·판본 확인 및 정답표 기반 분석 비교 절차**를 설계한다.
3. 실제 소설 원고와 DB는 공개 저장소 외부에만 보관한다.

원본 구형 NovelGraph 커밋 `909e00d` 복구는 여전히 미완료다.

## 8. 추가 보안 검증 (2026-11-04)

후보 등록 때 계산한 SHA-256 식별자를 Graphify 투영 직전에 재검증한다. SQLite의 `evidence_text`가 원본과 **동일한 문자 수**를 유지한 채 바뀌더라도 후보 ID 재계산 결과가 일치하지 않아 내보내기를 중단한다. 그래프 파일의 무단 추가 속성도 거부한다. 이 검증은 원본 원고 파일 자체의 별도 버전 검증을 대체하지 않는다.

## 9. GitHub 병합 완료 기록

- PR #3: https://github.com/kankinku/NovelGraph/pull/3
- `main` squash 병합: `efc903afb73446589624094a7dc61de3c0d8fe6a`
- 합성 테스트: **GitHub Actions 56/56 통과** (Graphify 신규 15개 포함)
- 공개 저장소 변경 파일: `README.md`, 개발 계획, Graphify 연동 보고서, `novelgraph/__main__.py`, `novelgraph/graphify_bridge.py`, `tests/test_graphify_projection.py` — 실제 원고와 DB 없음
- **Moon:** 신규 6·7단계 코드 미동기화 / 테스트 미실행 (MCP 연결 실패). GitHub CI 통과와 동일시하지 않음.
