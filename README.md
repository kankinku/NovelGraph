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

## 현재 상태

이 저장소(`kankinku/NovelGraph`)는 GitHub `main` 브랜치에 게시되었으며 Moon `/shared/NovelGraph`에 복제되어 있다. 현재는 **후보 수집·원문 근거 검증·중복 방지용 최소 CLI와 테스트**가 구현되어 있다. Graphify 저장·조회 테스트 2개, 후보 격리 테스트 10개가 개별 검증에서 통과했다. 현재 승인 로그·동적 세계 상태 엔진은 구현되어 가상 테스트 23개가 GitHub와 Moon에서 통과했다. 연속성 검출기는 GitHub `main`에 병합됐다. Graphify 실제 투영·근거 역추적까지 GitHub `main`에 병합했고, 가상 시나리오 **56개가 GitHub Actions에서 통과했다**. Moon `/shared/NovelGraph`에 GitHub 최신 코드를 Fast-forward로 동기화했다. 기능별 재시험에서 후보 수집 10개, 연속성 18개, Graphify 기본 2개, 상태 엔진 11개가 통과했고 Graphify 실제 투영 15개는 별도 검증 중이다. [8/9] 정답표 평가 CLI의 합성 테스트 12개는 Moon 별도 작업 트리에서 통과했다. 실제 원고 1~3화 평가와 이전 Moon 원본 복구는 **미완료**이다. 상세 실행 계획은 [07 문서](docs/07-implementation-plan-2026-11-04.md)를 따른다.

관련 참조: [Graphify](https://github.com/Graphify-Labs/graphify) — 승인 사실·사건의 파생 그래프 연동 및 원문 SHA·회차·위치 역추적이 [7/9]에서 구현되어 CI 검증되었다. 실제 원고 파일의 자동 복원과 Moon 검증은 아직 미완료.
