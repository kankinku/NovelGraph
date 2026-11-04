# [4/9] 원고 분석 후보 수집·격리 MVP 검증 (2026-11-04)

**판정: 구현 및 후보 테스트 10/10 통과.** 원고 의미 자동 추출, 승인, 세계 상태 반영은 아직 미구현.

## 구현 범위

- `novelgraph/__main__.py`: Python 표준 라이브러리 CLI
- `tests/test_candidate_intake.py`: 가상 원고 수입·오류 검증
- `source-info`: 원본의 SHA-256과 Unicode 길이를 조회
- `import-candidates`: ChatGPT가 작성한 후보 JSON의 원본 일치 여부 확인 및 SQLite 격리 저장
- `status`: 화별 `proposed/approved/rejected` 건수 출력 (원문·인용 공개하지 않음)

**데이터 보안:** 소설 원고, 후보, DB는 GitHub가 아닌 `/shared/NovelGraph-data`에 보관한다. 데이터 루트 접근권한 0700, 신규 DB 0600; 외부 심볼릭 링크, 잘못된 DB 권한, 공개 소스 안쪽 경로는 거부한다.

## JSON 입력 계약

```json
{
  "schema_version": 1,
  "work_id": "synthetic_demo",
  "episode": 1,
  "source_sha256": "<source-info에서 확인한 64자리 SHA-256>",
  "candidates": [
    {
      "kind": "event",
      "payload": {"actor": "가상 인물", "action": "계약 서명"},
      "evidence": {"start": 0, "end": 4, "text": "<원본의 일치하는 문구>"}
    }
  ]
}
```

위 해시와 위치·인용은 **자리표시자**다. 실제로는 `start/end`가 원고 Unicode 문자열의 0부터 시작하는 **끝 제외** 범위이고, `원고[start:end]`가 `text`와 일치해야 한다. `kind`는 `entity`, `event`, `relation`, `state_change` 중 하나다. `payload`는 비어 있지 않은 JSON 객체여야 하지만 내용의 서사적 사실 여부는 아직 검사하지 않는다.

## Moon MCP 명령 예시

```bash
cd /shared/NovelGraph
.venv/bin/python -m novelgraph source-info \
  --source /shared/NovelGraph-data/works/demo/001.txt
.venv/bin/python -m novelgraph import-candidates \
  --source /shared/NovelGraph-data/works/demo/001.txt \
  --input /shared/NovelGraph-data/works/demo/001.candidates.json
.venv/bin/python -m novelgraph status --work-id demo --episode 1
```

다른 비공개 루트는 서브명령 **앞에** `--data-root /절대경로`를 붙인다.

## 실제 가상 데이터 검증

| 항목 | 관측값 |
| --- | --- |
| 입력 가상 원고 | 63 Unicode 문자 / 139바이트 |
| 최초 후보 수입 | 2 신규 / 0 중복 |
| 동일 원고·후보 재수입 | 0 신규 / 2 중복 |
| 후보 상태 | proposed 2 / approved 0 / rejected 0 |
| SQLite 테이블 | episodes / candidates |
| 공식 세계 상태 변경 | 0 (아직 상태 엔진 없음) |
| DB 파일 권한 | 0600 |
| 단위 테스트 | 10/10 통과 |

가상 실험 파일은 `/shared/NovelGraph-data/research/mvp4-demo/`에 있으며 공개 Git에는 올리지 않았다.

## 인수 기준 및 미구현

근거 문구 위조, 잘못된 Unicode 오프셋, 원본 해시 불일치, 동일 화 원고 버전 변경, 잘못된 종류, 누락 근거, 중복 수입, 비공개 경로 이탈을 거부한다. 원고나 후보가 잘못되면 DB에 일부 후보만 등록하지 않는다.

**아직 구현하지 않은 것:** LLM 자동 분석 기능 자체, 의미·인물 동일성 심사, 승인 워크플로, 자산·계약 상태 변경, Graphify 연동, 기존 Moon의 과거 원본 복구.

**다음 [5/9]:** 근거가 확인된 승인 사건을 기준으로 계약 서명·대금 지급·지분 이전을 별개 사건으로 기록하고 회차별 상태 재생과 중복 지급 방지를 검증한다.
