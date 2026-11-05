# 1~11화 금액·서명 주체 정규화 설계 (2026-11-05)

목적: 모델 보류 37건을 원문과 재대조하고, 반복 오류의 원인을 근삿값과 계약 서명자 스키마에서 최소 수정한다.

1. continuity_fact:amount에는 선택적 amount_relation(exact 기본, approximate, greater_than, at_least)을 둔다. 정밀 수치와 근사·경계값을 동일한 값으로 침묵 비교하지 않는다. 금액 한정 관계가 있으면 관계가 다를 때 INSUFFICIENT_EVIDENCE만 내고 확정 충돌을 주장하지 않는다. change에서 amount_relation은 금지한다.
2. state_change:contract_signed에는 선택적 signer_id를 허용한다. actor_id=경제적 귀속 계좌, signer_id=법적 서명인. 서명인이 달라도 cash_payment/equity_transfer actor와 contract_id는 같은 경제적 주체로 유지. 없으면 기존 포맷 유지.
3. 실제 37개 보류 후보 각각을 원고 전체 문맥과 비교해 비공개 교정안을 만든다. 기존 118 공식 제안·원고·DB 불변, 별도 private per-episode candidate batches만 preflight, 임의 승인 불가.
4. 코카콜라 계약/금전/소급 공개 및 코디지 이익→이리 풋 프리미엄은 원문 근거와 새 qualified fact로 재검증한다.
5. 합성 TDD RED/GREEN + 전체 회귀 + 공개 Git에 원고/개인 JSON/DB 배제. 사람 독립 골드/정확 잔고는 여전히 미확정.

## 비공개 파일럿 교정 결과 (2026-11-05)

- 최신 모델 검수 보류 37건을 1~11화 원본·후보·이전 의견에 맞추어 모두 다시 대조.
- 기존 후보 유지/주의사항 보강 17건, 근거 또는 payload가 달라진 수정 초안 20건.
- 비공개 분류: 범위/해석 주의 14, 근거 확장 8, 근거+payload 변경 6, 회차 간 교차 근거 2, 정밀도 수정 검토 7. 이 분류는 분류별 전체 37건이고, 실제 교정 초안 20건과 일대일 대응하지는 않는다.
- 새 후보 20건은 7개 회차(1·3·4·5·8·10·11화)의 별도 JSON에서 원문 SHA·증거 위치·스키마 사전검사 통과.
- 코카콜라 3→5화 계약 ID는 동일. 이전 ID 불일치 의심은 오판으로 정정. 경제적 권리 주체(신탁)와 대리 서명자(조부)를 구분하는 교정안을 생성.
- 10화 실현 수익/최종 현금, 11화 이리 풋 비용 및 미완료 정산을 분리. 55만 달러 초과와 약 38만 달러에서 정확 현금잔액을 만들지 않음.
- 개인 교정안: /shared/NovelGraph-data/works/harrington-1883-pilot-20261105/reports/candidate-revision-proposals-20261105/ (0600, 공개 Git 제외).
- 공식 원고·118 후보·승인·적용 원장 변경 없음. 새 교정안 import/승인/적용 없음. 모델 자체 재검수는 사람 gold가 아님.
- 과거 needs_review 37건은 공식 원장의 모델 의견대로 유지. 정확도 precision/recall/F1은 미측정.
