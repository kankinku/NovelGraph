# [8/9] 실제 원고 1~3화 파일럿 — 평가 도구 및 실행 준비

> 상태 (2026-11-04 갱신): **평가기 구현·main 병합 / Moon 73/73 전체 자동 테스트 통과 / 동일 작품 1~5화 비공개 원고 확보·26건 근거 후보 proposed 저장 및 모델 검토 shadow 그래프 검증 완료 / 독립 인간 골드 정답표 부재로 실제 정밀도·재현율·F1 미측정**. 기존 PR #4의 구현 근거는 유지하되 최신 실측은 [17 문서](17-real-private-corpus-pilot-2026-11-04.md)를 따른다.

## 1. 목적

소설 본문을 ChatGPT가 추출한 `entity`, `event`, `relation`, `continuity_fact`, `state_change` 후보의 **정확도와 누락**을 사람이 검토한 정답과 비교한다. 프로그램의 단위 테스트 수와 소설 의미 추출 품질을 분리한다.

### 단계별 파일럿

1. 같은 작품 1·2·3화 원고를 비공개 디렉터리에 보관한다. 각각 원본 SHA-256 및 글자 수 기록.
2. 별도의 검토자가 인물 동일성·시간·계약·금액·자산·관계의 정답표를 작성한다. 소설 본문 구절을 GitHub에 올리지 않는다.
3. ChatGPT가 Moon을 통해 원고를 읽고 원본의 Unicode `[start,end)` 위치가 들어 있는 후보 JSON을 만든다.
4. 후보는 먼저 `proposed`로 저장한다. **원고 근거와 진술을 직접 확인한 후** 승인한다. 자동 무인 승인 금지.
5. `check-continuity`, `world-state`, `graphify-export`, `graphify-trace`를 실행한다.
6. `pilot-evaluate`로 정답표와 시스템이 검출한 연속성 사례를 비교한다. 사실 추출의 정밀도·재현율은 추가 정답 항목을 만들어 별도 평가해야 한다.

## 2. 비공개 평가 파일 계약

원고·평가 자료는 `/shared/NovelGraph-data` 아래에 보관해야 한다.

### manifest.json

```json
{
  "work_id": "sample_novel",
  "episodes": {
    "1": {"source": "pilot/001.txt", "source_sha256": "64자리 실제 SHA-256"},
    "2": {"source": "pilot/002.txt", "source_sha256": "64자리 실제 SHA-256"},
    "3": {"source": "pilot/003.txt", "source_sha256": "64자리 실제 SHA-256"}
  }
}
```

위의 SHA는 설명용 텍스트다. 실제 파일 내용의 UTF-8 바이트 해시를 넣는다. 프로그램은 해당 원고가 private 루트 내부에 있는지, 해시가 정확한지 확인한다.

### gold.json

```json
{
  "work_id": "sample_novel",
  "as_of_episode": 3,
  "findings": [
    {
      "category": "NEEDS_REVIEW",
      "subject_id": "contract:warehouse",
      "field": "amount",
      "evidence": [
        {"episode": 1, "start": 0, "end": 16, "source_sha256": "1화 실제 SHA-256"},
        {"episode": 3, "start": 18, "end": 38, "source_sha256": "3화 실제 SHA-256"}
      ]
    }
  ]
}
```

골드 항목은 독립적인 인간 검토가 필요하다. `source_sha256`, 오프셋은 실제 원문과 일치해야 하며, 원고에 없는 오류를 예시 값 그대로 골드 데이터로 입력해서는 안 된다.

### predictions.json

`novelgraph check-continuity --work-id sample_novel --episode 3`의 JSON 결과를 비공개 파일로 저장한다. 검사 결과의 `findings`에 동일한 판정명, 대상, 필드, 근거 회차·위치·SHA가 담긴다.

## 3. 평가 CLI

```bash
cd /shared/NovelGraph
.venv/bin/python -m novelgraph --data-root /shared/NovelGraph-data \
  pilot-evaluate \
  --manifest /shared/NovelGraph-data/pilot/manifest.json \
  --gold /shared/NovelGraph-data/pilot/gold.json \
  --predictions /shared/NovelGraph-data/pilot/predictions.json
```

**비교 키:** `(판정, subject_id, field, 원문 근거 위치·해시 집합)` 정확히 일치. 판정이 다르거나 근거가 틀리면 참양성으로 계산하지 않는다.

**지표:** TP, FP, FN, precision, recall, F1, 카테고리별 수치, 미검증 근거 수, 거짓 경고 목록, 놓친 정답 목록(인용문 제외). 분모가 0이면 지표를 임의로 100%로 표시하지 않고 `null`을 반환한다. 동일 결과를 중복 반환하면 중복을 FP로 계산한다.

`pilot-evaluate`는 평가 및 보고용이다. **LLM 의미 추출을 스스로 수행하거나, 후보를 자동 승인하지 않는다**. 결과의 정답표가 실제 사람이 검증한 것인지는 프로그램이 자동 보증할 수 없다.

## 4. 2026-11-04 현재 준비 상태와 한계

- [x] Moon 연결 및 GitHub 최신 코드 동기화
- [x] 기존 56개 및 전체 73개 자동화 테스트 Moon 실행 통과
- [x] 정답표 비교 평가기 코드와 합성 테스트
- [x] 실제 같은 작품 1~5화의 원본 보존, SHA-256·회차 매핑, 26건 출처 후보 검증
- [x] 모델이 검토한 주장 25건을 **별도 일회용 shadow DB**에서 승인 형식 실험 및 그래프 근거 추적
- [ ] 사람/독립 검수자의 누락·모순·시간·계약·자산 정답표 검토
- [ ] 실제 오류 검출 precision/recall/F1 및 누락률 측정

**주의:** ChatGPT가 승인 형식으로 처리한 shadow 후보는 사용자 승인이 아니다. 실제 corpus DB의 후보는 26건 모두 `proposed`이며, 자산·현금 확정 상태가 변경된 적 없다. 빈 예시 정답표로 산출된 `null`은 평가 완료나 오류 0건 보증이 아니다.

## 5. 다음 실작업

1. [비공개 파일럿 실측](17-real-private-corpus-pilot-2026-11-04.md)의 후보 목록과 전체 원고를 독립 검토자가 대조하여 놓친 사실·잘못된 판정의 정답표를 만든다.
2. 실제로 정답표가 확정되면 평가기에서 TP/FP/FN, precision/recall/F1을 계산하고 오탐·누락의 재현 구간을 개선한다.
3. 다른 작품의 원고·설정을 합치지 않고 동일 작품 1~43화가 확보되었을 때에만 전체 적용으로 확장한다.
