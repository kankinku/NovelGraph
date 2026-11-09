# 아키텍처

## 목표 처리 경로

```text
ChatGPT (의미 추출, 추론, 판단)
    ↕
Moon MCP (원고 제공, 명령 실행, 결과 전달)
    ↕
NovelGraph CLI / Python 엔진
    ↕
그래프 데이터 및 근거 저장소
```

Graphify는 승인된 후보의 **파생 관계 그래프**를 저장·검색하는 데 사용한다. 공식 상태 원장은 SQLite이며 Graphify가 상태를 변경하지 않는다. 2026-11-09 상태 확장안은 기능 브랜치의 테스트 단계다.

## 처리 단계

1. Moon을 통한 원고 로딩 및 회차 식별
2. 원문 범위/청크 식별자와 해시 부여
3. LLM의 사실·사건·상태 변화 후보 추출
4. 스키마·근거·동일성 검증
5. 후보 격리 저장, 검토 또는 승인 단계
6. 승인된 사건의 상태 전이 반영
7. 회차/시점 기준 세계 상태 재구성
8. 연속성 위반 및 불확실성 보고

## 운영 원칙

- 모든 상태 변화는 출처 회차와 원문 근거를 가져야 한다.
- 승인되지 않은 후보가 확정된 설정을 덮어쓰지 못한다.
- 동일 원고 반복 분석 시 중복 반영을 방지한다.
- 재분석과 이전 판정의 이력을 보존한다.
- 실제 MCP 명령명과 CLI 사용법은 소스 복구 후 문서화한다.

## 2026-11-09 확정: 집필 AI에 현재 상태 전달

~~~text
확정 원고 → LLM 의미 추출(JSON 근거 후보)
          → preflight-candidates (형식·원문 SHA 검증)
          → import-candidates (proposed로 격리)
          → assess-candidate (AI 평가, 공식 승인과 분리)
          → review-candidate (공식 검토 후 승인/반려)
          → apply-approved (승인된 사건만 상태에 반영)
          → query-state (요청 범위의 현재값/원문 근거만 전달)
          → graphify-export/trace (관계·인과 연결 그래프)
          → 집필 LLM 집필·검증 / 충돌 시 중단 및 반려
~~~

- 상태 사건(state_set)의 카테고리는 liquid, stock, bond, real_estate, liability, relationship, knowledge, thread, narrative, status, time.
- time은 작품 ID가 현재시간(current)을 관리하는 날짜 상태 노드. 미래 일정은 실제 발생 없이 현재로 승격하지 않는다.
- 관계는 active/ended, 지식은 known/not_known/unverified, 미해결 사건은 open/resolved/cancelled로 기록.
- 객관적 사실과 대사·소문·추측을 구별한다. 인물이 모른다고 명확히 쓰지 않았다면 not_known으로 확정하지 않는다.
- 요청 범위: assets, liquid_assets, cash, stock, bond, real_estate, liabilities, net_assets, relationships, knowledge, threads, narrative, status, time, ownership, contracts. 변경 내역은 명시적 --history 요청만 반환한다.
- 금액·주수·지분율은 단위가 다르면 합산하지 않는다. 같은 현금을 기존 cash 원장과 liquid 노드에 중복 넣지 말고, liquid를 현금 원장 외의 유동자산에만 사용한다.
- 공식 적용은 현행 리뷰 단계가 필요하다. 자동 승인과 전면적인 의미 충돌 판정은 미구현이다. 충돌 발견 시 작성 AI가 1차 판단하고 작가가 최종 결정하는 외부 워크플로우에서 원고를 반려해야 한다.
- 현재 Graphify 그래프는 SQLite에서 읽어 만든 최신 상태와 연결 경로의 복제본이며 원본 사실의 기준이 아니다.
