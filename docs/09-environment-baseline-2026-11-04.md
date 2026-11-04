# [2/9] NovelGraph 개발환경 기준 고정 — 2026-11-04

> 상태: **기준 경로·격리 Python·데이터 보호 정책 확인됨**. Graphify 및 타사 패키지 설치는 미진행; `pip` 부재는 다음 단계 선행 작업이다.

## 1. 기준 경로와 플랫폼

| 자원 | 현재 실측값 |
| --- | --- |
| Moon 영구 코드 작업공간 | `/shared/NovelGraph` |
| GitHub 연결 | `https://github.com/kankinku/NovelGraph`, 공개 저장소, `main` |
| private 실행/분석 데이터 | `/shared/NovelGraph-data` (현재 빈 디렉터리, 모드 `700`) |
| Python 가상환경 | `/shared/NovelGraph/.venv` |
| OS | Ubuntu 24.04.5 LTS (WSL2) |
| Python | `3.12.3` |
| SQLite | `sqlite3` 표준 라이브러리, `3.45.1` |
| Git | `2.43.0` |
| CPU / RAM | 12 논리 CPU / 30 GiB (환경 표시, 전용 보장 아님) |
| 저장소 여유 | 점검 시 약 818GB |
| GitHub CLI | 실행 가능하나 미로그인 |
| Graphify | 미설치 |

현재 `/shared/NovelGraph`의 소스는 README 및 설계 문서와 프로젝트 규칙뿐이며, 기존 NovelGraph 구현체는 미복구이다.

## 2. 직접 수행한 환경 구성

- 가상환경: `python3 -m venv --without-pip /shared/NovelGraph/.venv`
- private 데이터 공간: `mkdir -p /shared/NovelGraph-data && chmod 700 /shared/NovelGraph-data`
- 검증: 가상환경 Python이 Python 3.12.3 / SQLite 3.45.1을 로드했고, `sys.prefix != sys.base_prefix`를 만족했다.
- 패키지 관리: 시스템 Python에 `pip`, `ensurepip` 없음. 일반 `python3 -m venv`는 실패했고, `--without-pip`로 표준 라이브러리만 사용 가능한 격리 환경을 만들었다.

**남은 환경 의존성:** [3/9] Graphify 적용 시험 전 가상환경용 Python 패키지 설치 경로를 확보해야 한다. 사용 가능한 공식 배포판의 `python3.12-venv` 또는 신뢰 가능한 패키지 도구를 검증 후 최소한으로 도입한다. 현재 환경에 설치되어 있다고 가정하지 않는다.

## 3. 실행·검증 기본 명령

```bash
cd /shared/NovelGraph
.venv/bin/python --version
.venv/bin/python -c 'import sqlite3, decimal, json; print(sqlite3.sqlite_version)'
git status --short
git ls-files
git check-ignore -v .venv/ data/ manuscript.sqlite .env graphify-data/  # 예측 경로 검증
```

아직 실행 가능한 NovelGraph CLI/테스트 엔트리포인트는 없다. 다음 단계 검증 시 반드시 실제 설치·테스트 결과를 기록한다.

## 4. 데이터 보안·공개 Git 규칙

- **실제 소설 원고·개인 메모·승인 후보·분석 결과 및 DB는 공개 Git 저장소 외부**에 둔다. 프로그램은 장래에 데이터 루트를 옵션으로 받을 수 있지만 필요해지기 전에는 범용 설정 프레임워크를 만들지 않는다.
- `.gitignore`는 일반적인 실수 방지 장치다. Git에서 강제 추가 가능한 만큼 안전을 보증하지 않는다. 매 커밋 전 `git diff --cached --name-status` 및 `git diff --cached`를 확인한다.
- GitHub 연결을 통한 쓰기 권한과 Moon 자체 GitHub CLI 인증은 별개다. Moon에서 직접 `git push`할 수 있다고 가정하지 않는다.
- 새 서비스·수신 포트·독립 MCP는 만들지 않는다. `/shared/AGENTS.md`에 정의된 Moon 운영 경계를 침범하지 않는다.
- 이전 Moon 원본 소스가 발견되면 새 구현보다 복구·차이 비교를 우선한다.

## 5. 기준 확인 완료 조건

- [x] 현재 GitHub `main`에서 문서와 작업 목표 확인
- [x] Moon에 `/shared/NovelGraph` 복제 및 기본 브랜치 확인
- [x] Python 격리 실행 및 SQLite 표준 라이브러리 검증
- [x] private 분석 데이터 디렉터리 구성 및 모드 확인
- [x] 공개 저장소의 무시 규칙·프로젝트별 보안 가이드 문서화
- [ ] 가상환경의 패키지 설치 능력 확보 — [3/9] 시작 전 필수
- [ ] 기존 NovelGraph 원본 확보 — 이전 Moon 접근 필요

**최종 Git 동기화·ignore 검증 및 작업 트리 상태는 이 문서 게시 뒤 재검사해 보고한다.**
