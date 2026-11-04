# NovelGraph

장편 웹소설 원고에서 서사 세계의 사실과 사건을 자동 구조화하고, 회차별 상태 변화와 연속성 충돌을 검증하는 도구의 **복구·설계 문서 저장소 초안**.

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

## 현재 상태

이 저장소(`kankinku/NovelGraph`)는 GitHub `main` 브랜치에 게시되었으며 Moon `/shared/NovelGraph`에 복제되어 있다. 현재는 **설계 문서만 존재**하고, 이전 Moon에 있었던 NovelGraph 원본 코드·과거 테스트 로그·커밋 복구는 **미완료**이다. 상세 실행 계획은 [07 문서](docs/07-implementation-plan-2026-11-04.md)를 따른다.

관련 참조: [Graphify](https://github.com/Graphify-Labs/graphify) — 실제 적용 여부는 소스 복구 후 재검증 필요.
