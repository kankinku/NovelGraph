# NovelGraph 원본 복구 조사 — 2026-11-04

> 조사 상태: **현재 접근 가능한 환경 조사 완료 / 기존 소스 확보는 미완료(이전 Moon 인스턴스 접근 필요)**.
> 이 보고서는 현 연결의 부재를 기록할 뿐 과거 원본이 삭제되었다거나 영구 유실되었다고 단정하지 않는다.
> 검토 원칙: 기존 데이터 보존, 파괴적 작업 금지, 추정과 실측 분리, 최소 변경(Karpathy/Ponytail).

## 1. 조사 목적과 범위

`docs/07-implementation-plan-2026-11-04.md`의 [1/9] 단계: 기존 NovelGraph 원본, 테스트 및 상태 데이터를 복구할 수 있는지 확인하고, 불가할 경우 접근 범위·근거·복구 인계사항을 문서화한다.

**직접 확인한 범위**

- 현재 연결된 Moon의 영구 경로 `/shared` 및 그 하위(경로명 검색, Git 저장소 검사).
- `/shared/NovelGraph` 로컬 클론의 브랜치, 원격 및 Git 객체.
- GitHub `kankinku/NovelGraph`의 `main` 및 검색 가능한 파일/커밋.
- 연결된 `kankinku` GitHub 소스 검색에서 `novelgraph.sqlite`, `graphify-data` 항목.

**조사 범위 밖**

- **예전** Moon 인스턴스 `project-moon-local`의 현재 디스크: 이 연결로 접근할 수 없음.
- 예전 서버의 미커밋 파일·Git reflog·별도 백업 장치 및 스냅샷.
- 과거 작업 결과의 실행 검증.

## 2. 회고 기록으로 확인된 복구 단서 (현재 직접 검증 불가)

| 항목 | 과거 작업 기록 |
| --- | --- |
| 예전 Moon 인스턴스 | `project-moon-local` |
| 예전 영구 작업공간 | `/shared/moon-workspace` |
| NovelGraph 저장소 | `/shared/moon-workspace/작가/_tools/novelgraph` |
| 최신 기록 커밋 | `909e00d` (`master`) |
| 진행 문서 | `NOVELGRAPH_CURRENT_STATUS_20261104.md`, `PROGRESS.md` |
| 또 다른 상태 추적 | 2026-11-03 이후 미커밋 코드/문서 변경 가능성 |
| 기존 작품 분석 DB (예시) | `작가/두 번째 인생은 1883년이었다/graphify-data/novelgraph.sqlite` |
| 검수 원장 (예시) | `graphify-data/review/sequential.sqlite` |
| 인덱스·후보 결과 | 각 작품의 `graphify-data/`, `.s/` 이하 (작품별 분리) |
| 기록된 테스트 | 690/690 성공 회고. 현재 테스트 로그/코드 미복구 |

**주의:** `909e00d`는 7자리 약식 해시다. 다른 Git 저장소의 동일 접두어 커밋을 원본으로 오인하지 않는다. 기존 저장소에서 전체 SHA와 트리를 확인해야 한다.

## 3. 2026-11-04 직접 조사 결과

| 항목 | 관측 | 판단 |
| --- | --- | --- |
| 현재 Moon `/shared/moon-workspace` | 디렉터리 없음 | 이전 워크스페이스가 현재 연결에 없음 |
| 현재 Moon의 예전 소스 경로 | 없음 | 소스 복구 불가 |
| 예전 작품 SQLite 경로 | 없음 | 데이터 복구 불가 |
| 현재 Moon의 Git 저장소 | `/shared/NovelGraph`, `/shared/NovelGraph-documentation`, `/shared/github-recovery/story-maker-agent` | 셋 모두 `909e00d` 객체 없음 |
| GitHub 현재 NovelGraph | `main` 한 브랜치, 문서만 존재 | 이전 코드가 업로드된 저장소가 아님 |
| GitHub 코드 검색 | `novelgraph.sqlite`, `graphify-data` 검색 결과 없음 | 검색된 범위에서 기존 데이터/코드의 증거 없음 |
| GitHub 커밋 검색 | 과거 NovelGraph 기능 구현 커밋 확인 실패 | 계정 내 숨은/검색 비포함 저장소까지 부재 증명은 아님 |
| 새 문서 저장소 | `/shared/NovelGraph`, `main` 클린 | 이후 계획 문서·구현 작업 기준 위치로 사용 가능 |

## 4. 원본 복구 실행 지침 (이전 Moon 접근이 가능해질 때)

**원본 경로에 대해 `git reset --hard`, `git clean`, `git checkout`, 삭제·덮어쓰기를 먼저 수행하지 말 것.**

1. 이전 Moon의 실제 작업공간 및 `AGENTS.md`를 확인하고 소스 경로가 존재하는지 검증한다.
2. **미커밋 변경과 Git 메타데이터를 포함한 저장소 디렉터리 전체**를 독립된 사본으로 보존한다.
3. 작품별 `graphify-data`, SQLite 원장, 원고/근거 위치 매핑과 후보 격리 저장소를 **공개 GitHub가 아닌 별도 비공개 공간**에 보존한다.
4. 기존 저장소에서 `git status`, `git log`, `git remote -v` 및 `git show 909e00d`를 확인한다. 로그/원격 URL에는 인증정보가 있을 수 있으므로 공개 문서에 그대로 게시하지 않는다.
5. 테스트 명령, lockfile, CLI 엔트리포인트, 모델 추출 계약·상태 스키마를 확인한다.
6. 복구한 코드와 본 저장소의 문서를 비교한 뒤, 이미 구현된 기능은 재사용하고 현재 계획의 중복 개발을 취소한다.

**원고/DB 보안:** 현 GitHub는 public이므로 사본 전체나 DB, 사용자 원고를 직접 업로드하지 않는다. 공개 코드에 들어갈 수 있는 항목만 별도 검토해 반영한다.

## 5. 판정 및 다음 단계

- **[1/9] 현 환경 조사:** 완료.
- **[1/9] 실제 기존 소스 복구:** 접근 차단으로 **미완료**.
- **진행 가능:** [2/9] 기준 환경 고정(개인 데이터 Git 제외 정책, 개발 경로 및 실행 명령의 기반 마련). 이는 기존 원본을 대체하거나 유실로 확정하는 행위가 아니다.
- **새 구현 보류:** 구형 소스를 복구할 수 있는지 먼저 확인하는 것이 바람직하다. 원본 접근이 불가능한 동안 새 코드를 시작하면 중복 구현 위험을 명시하고 제한된 MVP만 추진해야 한다.
- **최우선 외부 의존성:** 이전 `project-moon-local` 연결 또는 그 저장소의 안전한 비공개 사본 확보.

## 6. 확인되지 않은 사항

실제 이전 Moon의 생존 여부, 오래된 Git 작업 트리 상태, `909e00d`의 전체 SHA, 690개 테스트의 실제 내용과 재현 가능성, Graphify 실질 통합 상태, 실제 원고 분석 정확도는 **미확인**이다.
