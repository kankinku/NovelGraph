# [3/9] Graphify 적용성 실증 보고 — 2026-11-04

> **판정: 목표 범위에서 통과 (조건부 적용).** 이미 LLM이 구조화한 소설 Entity / Event / Evidence를 Graphify 그래프에 저장하고 재조회하는 것은 실제 실험에서 동작한다. Graphify의 **원고 자체 의미 추출은 확인되지 않았고**, API/LLM 없이 단독 `.txt` 파일을 스캔하는 실험에서는 코드 그래프가 생성되지 않았다.

## 1. 검증 환경과 외부 버전

| 항목 | 실증값 |
| --- | --- |
| Moon | `/shared/NovelGraph` |
| Python | 격리된 `.venv/bin/python` 3.12.3 |
| Graphify 패키지 | PyPI 공식 `graphifyy==0.9.102` |
| Graphify 소스 | `Graphify-Labs/graphify`, 브랜치 `v8`, `59b5ab1151e031fb42e39cfc9a50bf96f2d57ae0` (2026-11-03 기준 커밋) |
| Graphify 그래프 형식 | `graph.json` / `graph.schema_version = 1`, `graph.graphify_version = 0.9.102` |
| 패키지 설치 | 공식 PyPA `pip.pyz` (출처 `https://bootstrap.pypa.io/pip/pip.pyz`)를 활용해 프로젝트 `.venv`에만 설치; OS 전역 설치 없음 |
| 테스트 | `.venv/bin/python -m unittest discover -s tests -v` → **2 tests, OK** |
| 데이터 | 작성된 가상 한국어 문장만 사용; 실제 원고·비공개 분석자료 사용 없음 |

격리된 원본 소스와 별도 개인 실험 결과는 `/shared/NovelGraph-data/research/`에 두었고 공개 저장소에는 재현 테스트 코드와 결과 요약만 게시한다.

## 2. 통과한 실험

### A. 이미 구조화된 소설 노드·관계의 그래프 왕복

가상 문장: `에블린이 월요일에 오로라 회사의 지분 15% 계약에 서명했다.`

외부에서 자동 추출된 것처럼 **사전에 직접 지정한** 5개 노드(인물, 사건, 계약, 회사, 근거)와 4개 관계를 NetworkX 그래프로 만든 후 Graphify 공식 `to_json`으로 내보내고 `load_node_link_graph`로 다시 읽었다.

- 노드: 5개 / 관계: 4개
- 연결 방향과 관계명: 일치
- 출처 파일 `synthetic-001.txt`, 출처 위치 `L1`, 가상 원문 근거 문자열: 왕복 보존
- CLI `graphify path`: 에블린 → 계약 서명 → 계약 → 회사, **3홉 경로** 성공
- CLI `graphify explain`: 사건과 연결된 근거 위치 및 역방향 관계 표시 성공
- CLI `graphify query`: 가상 질문에 대해 **5개 노드 조회 성공**

이 시험은 Graphify **그래프 직렬화·로드·조회** 호환성만 검증한다. LLM 추출의 정확도나 실제 계약 상태의 자동 판단 능력을 증명하지 않는다.

### B. 원시 `.txt` 자동 의미 추출 (별도 검증)

가상 `001.txt` 한 파일만 입력하여 `graphify update <디렉터리> --no-cluster` 실행:

- 표준 출력: `No code files found - nothing to rebuild.`
- 종료 코드: `1` (현재 `0.9.102`의 처리 대상 없음 응답)
- 의미 노드나 그래프 산출물: 생성되지 않음

Graphify `update`는 **코드 AST 갱신 명령**이며, 일반 소설 문장에서 LLM 없이 인물/사건/자산을 해석하지 않는다. 실제 소설의 구조화는 ChatGPT가 별도로 수행해야 한다. 외부 LLM API를 연결하는 우회 방식은 요구사항상 사용하지 않았다.

## 3. 최소 연동 설계 결정

```text
ChatGPT (명시 사실과 추론 후보의 의미 추출; 근거 위치 포함)
    ↕  Moon MCP
NovelGraph CLI (근거 검증·중복 처리 방지·승인·상태 전이)
    ├─ SQLite: Event/Evidence/StateChange의 공식 이력
    └─ Graphify: 검증된 Entity/Event/Evidence로 graph.json 파생 뷰 생성
                    → graphify path/explain/query
```

**결정:** Graphify의 기존 그래프 JSON/CLI 기능을 재사용하며, 별도 서비스나 MCP 서버를 만들지 않는다. 아직 필요하지 않은 그래프 DB, Graphify 소스 포크, 벡터 인덱스는 보류한다.

그래프는 **파생 결과**이므로 원문 근거와 승인된 이벤트/상태 기록을 대신하지 않는다. 이후 [4/9]에서는 LLM 후보를 검증·격리하는 최소 CLI가 우선이고, 실제 그래프 자동 생성 어댑터와 상태 연동은 [7/9]에서 만든다.

## 4. 재현 방법

```bash
cd /shared/NovelGraph
.venv/bin/python -c 'import importlib.metadata as m; print(m.version("graphifyy"))'
.venv/bin/python -m unittest discover -s tests -v
git status --short
```

테스트 구현: [`tests/test_graphify_compatibility.py`](../tests/test_graphify_compatibility.py)

테스트는 `tempfile.TemporaryDirectory`로 격리되며, LLM/API 호출이나 실제 원고가 필요하지 않다.

패키지 설치가 필요한 신규 환경에서는 OS에 `pip`가 없어도 공식 PyPA pip zipapp으로 격리 가상환경에 `graphifyy==0.9.102`를 설치할 수 있다. zipapp을 전역 설치하지 않고 체크섬 및 출처를 확인하는 것을 권장한다.

## 5. 제한·남은 위험

1. **의미 정확도 미검증:** Graphify의 그래프 왕복 통과와 ChatGPT의 원고 의미 추출 성공은 별개이다.
2. **계약/금액 상태 미검증:** 지급·지분 이전·총자산 상태 전이는 아직 구현되지 않았다.
3. **동명이인/회상 시점 미검증:** 실제 원고를 이용한 동일성 검증과 서사 시점 복원은 후속 단계에서 해결해야 한다.
4. **Graphify 내부 포맷 의존:** Graphify 업그레이드 시 `schema_version`과 `graphify_version`을 확인하고 재시험한다.
5. **CLI 출력은 근거 검증의 대체가 아님:** 조회 결과를 상태에 반영하기 전 NovelGraph의 승인 단계가 필요하다.

## 6. 후속 단계

**다음: [4/9] 원고 분석 후보 왕복 MVP**

최소 기능: 가상 회차 입력 → ChatGPT가 근거/사건 후보 JSON 생성 → Moon MCP로 CLI 전달 → 필수 필드·원문 위치·해시 검증 → 후보 격리 저장 → 재입력 중복 검출 → 승인 전 세계 상태 불변 확인.

기존 원본 소스가 나중에 복구되면 현재 사양과 비교하여 기존 기능 재사용을 우선한다.
