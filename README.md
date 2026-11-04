# NovelGraph

장편 웹소설 원고에서 서사 세계의 사실과 사건을 자동 구조화하고, 회차별 상태 변화와 연속성 충돌을 검증하는 도구의 **개발 코드와 복구·설계 문서 저장소**.

> **증거 수준:** 이 문서는 2026-11-04 대화에 정리된 이전 작업 회고를 바탕으로 재구성했다. 기존 NovelGraph 원본 코드·Git 커밋·테스트 로그는 현 Moon 서버에서 검증되지 않았다. 재구성 내용은 검증 완료한 코드 사양으로 간주하지 않는다.

## 핵심 목표

1. LLM이 원고의 인물·조직·장소·사건·시간·자산·계약·관계·복선을 의미 기반으로 추출한다.
2. 사건과 근거를 그래프로 연결하고, 화별 상태 전이를 관리한다.
3. 특정 화 시점의 현금·총자산·지분·계약·관계 상태를 복원한다.
4. 시간·행동·위치·수치·계약 관련 모순과 근거 부족을 검출한다.
5. ChatGPT와 Moon MCP를 통해 원고 입력부터 결과 조회까지 수행한다.

## 범위에서 제외

- 자동 집필 및 다음 화 생성
- 원고 자동 퇴고·수정
- 유료 외부 LLM API 호출을 기본 전제로 하는 분석
- 추론 후보를 사람 검증 없이 확정 설정으로 승격

## 문서 구성

- [목표와 범위](docs/01-goals-and-scope.md)
- [아키텍처 및 처리 흐름](docs/02-architecture.md)
- [데이터·상태 추적 설계](docs/03-world-state.md)
- [연속성 검증 규칙](docs/04-continuity-validation.md)
- [과거 작업 이력 및 증거 수준](docs/05-history-and-evidence.md)
- [복구 및 개발 계획](docs/06-recovery-roadmap.md)
- [Karpathy·Ponytail 적용 개발 계획 (2026-11-04)](docs/07-implementation-plan-2026-11-04.md)
- [기존 소스 복구 조사 및 차단 요인 (2026-11-04)](docs/08-source-recovery-audit-2026-11-04.md)
- [[2/9] 개발환경 기준 고정 (2026-11-04)](docs/09-environment-baseline-2026-11-04.md)
- [[3/9] Graphify 적용성 실증 (2026-11-04)](docs/10-graphify-feasibility-2026-11-04.md)
- [[4/9] 분석 후보 격리 저장 MVP (2026-11-04)](docs/11-candidate-intake-mvp-2026-11-04.md)
- [[5/9] 동적 세계 상태 엔진 (2026-11-04)](docs/12-world-state-step5-2026-11-04.md)
- [[6/9] 연속성 충돌 검출기 (2026-11-04)](docs/13-continuity-step6-2026-11-04.md)
- [[7/9] Graphify 실제 연동 및 근거 역추적 (2026-11-04)](docs/14-graphify-step7-2026-11-04.md)
- [[8/9] 실제 원고 파일럿 평가 기준 및 CLI 준비 (2026-11-04)](docs/15-pilot-evaluation-step8-2026-11-04.md)
- [[9/9] 전체 43화 처리 준비 및 체크리스트](docs/16-full-manuscript-step9-plan-2026-11-04.md)
- [[8/9] 비공개 실제 1~5화 파일럿 실측 보고](docs/17-real-private-corpus-pilot-2026-11-04.md)
- [[실사용 전환 01/12] 기준선·안전 감사](docs/18-production-baseline-2026-11-05.md)
- [실사용 전환 Superpowers 실행 계획](docs/superpowers/plans/2026-11-05-novelgraph-production-plan.md)
- [[실사용 전환 02/12] 실제 원고 정보 누락 예비 대조](docs/19-fact-gap-preaudit-2026-11-05.md)
- [[실사용 전환 02/12] 독립 검수 준비도·원문 근거 확인](docs/20-review-readiness-phase2-2026-11-05.md)
- [[실사용 전환 02/12] 1차 독립 판독·2차 후보 대조 문서 분리](docs/21-blind-review-packets-phase2-2026-11-05.md)
- [[실사용 전환 02/12] 71개 후보의 모델 예비 의미 검토](docs/22-model-71-semantic-triage-2026-11-05.md)
- [[실사용 전환 03/12] 의미 추출 기준과 후보 저장 전 검증](docs/23-extraction-contract-and-preflight-2026-11-05.md)
- [[실사용 전환 04/12] 인물 ID 충돌 사전 검사](docs/24-identity-audit-phase4-2026-11-05.md)
- [[실사용 전환 05/12] 모델 평가와 공식 승인 로그 분리·무결성 점검](docs/25-model-review-and-approval-boundary-2026-11-05.md)
- [[실사용 전환 06/12] 계약 제안·거절 상태와 실제 지급·지분 분리](docs/26-contract-lifecycle-phase6-2026-11-05.md)
- [[실사용 전환 07/12] 원고 판본 변경 및 승인 근거 영향 검사](docs/27-source-version-audit-phase7-2026-11-05.md)
- [[실사용 전환 08/12] 연속성 판정 및 뒤늦게 공개된 과거 사실 보정](docs/28-continuity-accuracy-phase8-2026-11-05.md)
- [[실사용 전환 09/12] 작가용 읽기 전용 Markdown 검토 보고서](docs/29-writer-continuity-report-phase9-2026-11-05.md)

## 현재 상태

- **Moon 실제 검증:** 전체 **156개 테스트가 Moon 격리 작업 트리에서 통과**했다 (2026-11-05, 377.942초, 9단계 보고서 포함). 후보 검증, 승인 원장, 회차별 세계 상태, 연속성, Graphify 투영, 파일럿 평가, batch-readiness 및 비공개 검수 준비도 검사를 포함한다.
- **실제 1~5화 원고 파일럿:** 사용자 제공 원고 5건을 원본 바이트 해시와 대조하여 비공개 경로에 보존했다. ChatGPT가 근거 기반 후보 26건을 작성해 SQLite에 등록했고 **모두 proposed 상태**로 남아 있다. 모델 검토만 거친 25건의 승인 형식 실험은 **별도 shadow DB**에서 실행했으며 사람의 승인으로 간주하지 않는다. 그 실험에서 Graphify 55개 노드·58개 관계가 생성됐고 출처 추적이 동작했다.
- **독립 품질 검증:** 인간이 검토한 골드 라벨이 없어 precision/recall/F1은 **미측정(null)**. 선택된 주장에 경고가 없었다는 사실을 소설 전체 무오류로 해석하지 않는다.
- **[9/9] 43화 확장:** 읽기 전용 원고 해시/누락 회차/등록 및 미검수 건수 점검기 PR #5가 `main`에 병합됐다. **전체 43화 수집·분석은 미완료**다. 현재 받은 1~5화와 과거 43화 대상 작품이 동일하다고 가정하지 않는다.
- **기존 구형 원본 복구:** 별도의 Moon 인스턴스에 있던 909e00d 원본은 미복구 상태다. 새 구현과 병행하되 원본 확보 시 비교한다.

자세한 실측과 한계: [비공개 1~5화 파일럿 보고](docs/17-real-private-corpus-pilot-2026-11-04.md), [개발 계획](docs/07-implementation-plan-2026-11-04.md).

Graphify: https://github.com/Graphify-Labs/graphify — 승인된 후보의 파생 그래프 구축과 근거 역추적에 사용하며, 공식 세계 상태의 기준 원장은 SQLite이다.
