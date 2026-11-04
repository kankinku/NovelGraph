# [8/9] 실제 원고 1~3화 파일럿 — 평가 도구 및 실행 준비

> 상태: **정답표 평가 도구 개발·검증 중 / 실제 1~3화 의미 추출·품질 평가는 아직 미실행**. 기존 Moon `/shared/NovelGraph`에는 2026-11-04 기준 가상 테스트 원고만 확인됐고, 실제로 분석할 동일 작품의 1~3화 파일 세트는 확보하지 못했다. 실제 원고와 골드 라벨을 대신 만들어 품질 수치를 부풀리지 않는다.

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

## 4. 현재 준비 상태와 한계

- [x] Moon 연결 확인 및 GitHub 6·7단계 Fast-forward 동기화
- [ ] Moon 전체 56개 단위 테스트 완료 판정 — 느린 Graphify 투영 테스트를 별도 수행 중
- [ ] 정확도 평가 CLI 개발 검증
- [ ] 실제 같은 작품의 1·2·3화 원고 비공개 확보
- [ ] 독립 정답표 작성 및 검토
- [ ] 실제 ChatGPT 의미 추출·수입·검수·판정 실행
- [ ] 실제 품질 precision·recall·F1 산출

이번 단계에서는 **원고가 준비되지 않았다는 이유로 점수를 추측하거나 다른 작품의 원고를 혼합해 사용하지 않는다.** 원본 작품이 확정되고 비공개 원고 3화가 준비돼야 실제 파일럿을 완료할 수 있다.

## 5. 다음 실작업

1. 평가기 단위 테스트와 GitHub CI 실행, Moon 환경 재현 검증.
2. 대상 작품 선택과 해당 작품 원고 1~3화 Moon private 데이터 경로 확인.
3. 출처·판본을 고정한 후 사용자/독립 검수자가 평가할 수 있는 정답표 구성.
4. 승인 전 후보와 승인된 사실 구분, 1~3화 실전 평가·오탐 재분류.
5. 결과를 기준으로 [9/9] 1~43화 전체 확대 가능성 판단.
