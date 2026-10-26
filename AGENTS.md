# Hotpost 작업 안내

이 파일은 작업 진입점이다. 일회성 작업 기록이나 규칙 전문을 추가하지 않는다.

## 시작·재개 시

1. [협업 원본](docs/COLLABORATION.md)을 작업 시작, 세션 재개·컨텍스트 압축 후, 범위 확장, 사용자가 요청한 Git 변경 작업 직전에 실제로 다시 읽는다. 협업 절차의 단일 원본이며 최신 사용자 명시 지시가 우선한다.
2. `git status --short`와 관련 브랜치를 확인하고 기존 변경을 보존한다. [현재 작업 경계](docs/WORKFLOW.md)를 읽는다. 운영 이력이 필요하면 원래 clone의 Git 제외 `docs/HANDOFF.md`에서 해당 작업의 최신 절만 확인한다.
3. 아래 표로 필요한 규칙을 읽고 수정할 모듈·계약 테스트를 [코드 지도](docs/CODE_MAP.md)에서 찾는다. 파일이 없으면 원본 clone/최신 Git에서 확보하며 기억으로 대신하지 않는다.
4. 작업 범위·읽은 문서 SHA·기준 커밋·현재 단계·검증·미해결 사항을 Git 제외 `local/SESSION.md`에 남긴다. 재개 시 문서가 바뀌었으면 다시 읽는다.

## 항상 유지할 경계

- 제작·수집·예약·복구·모델·폰 제어·실제 게시 중지는 새 명시 지시 없이 해제하지 않는다. 문서/코드 정리는 운영 재개 승인이 아니다.
- 기존 제작실 UI/API/Studio 실행기는 **outdated / 참고용 보존**이다. 신규 기본 경로로 쓰거나 정리 목적으로 코드·데이터를 삭제/이동하지 않는다. 현재 게시용 경로는 `hotpost.publication_server`다.
- 영상은 한 편씩 준비부터 현재 파일에 결속한 최종 QA까지 완료한다. 실패/보류/중지는 완료가 아니며 다음 영상으로 자동 건너뛰지 않는다.
- 영상 시작·재개 시 [현재 작업 경계](docs/WORKFLOW.md)의 전담 제작자·별도 읽기 전용 감시자 결속과 완료 후 감시 Markdown 독립 검증을 확인한다.
- 신규 제작·중단 재개·레퍼런스 현황은 각각 저장소 `skills/hotpost-new-production`, `skills/hotpost-resume-production`, `skills/hotpost-reference-status`를 진입점으로 사용한다. 실제 규칙과 상태 계약은 WORKFLOW·REFERENCE_STATUS가 원본이다.
- `data/`, `local/`, `.runtime/`, 세션·쿠키·음성·모델·미디어·로컬 인계는 보존하고 커밋하지 않는다. 비밀값을 출력하지 않는다.
- 브라우저·수집은 기존 로그인 Chrome 세션을 사용한다. 사용자에게 링크를 줄 때는 [WORKFLOW](docs/WORKFLOW.md)의 검증된 Cloudflare HTTPS 전달 규칙을 따른다. 접근 차단을 우회하지 않는다.
- VoiceBench는 HTTP API, Auto CapCut은 버전 JSON·별도 프로세스 경계를 유지한다. 개인 목소리·참조·Seed·사용자 선택 대본을 임의 대체하지 않는다.

## 작업별 원본

| 작업 | 먼저 읽을 문서 |
|---|---|
| 집필·수정·대본 검사 | [writing/RULES.md](hotpost/writing/RULES.md) |
| 소스 검색·검토·검색 기록 | [SOURCE_WORKFLOW.md](docs/SOURCE_WORKFLOW.md), [SOURCE_SEARCH_LOG.md](docs/SOURCE_SEARCH_LOG.md) |
| 음성·잘림·확인된 발음 이상 복구 | [TTS_TRUNCATION_RECOVERY.md](docs/TTS_TRUNCATION_RECOVERY.md) |
| 편집·최종 QA·전달 | [WORKFLOW.md](docs/WORKFLOW.md), [editorial_montage_policy.md](docs/editorial_montage_policy.md) |
| 영상 시작·완료·썸네일 완료 | [LOCAL_VIDEO_STORAGE.md](docs/LOCAL_VIDEO_STORAGE.md) + 원래 clone의 `local/VIDEO_STORAGE.md`, `local/video-storage.json` |
| 신규 제작 선정·중단 재개·레퍼런스 현황 | [REFERENCE_STATUS.md](docs/REFERENCE_STATUS.md), [WORKFLOW.md](docs/WORKFLOW.md) |
| 오전 7시 최근 72시간 수집·선정 | [DAILY_RANKING.md](docs/DAILY_RANKING.md) |
| 게시물 문구·썸네일 반영 | [POST_COPY_RULES.md](docs/POST_COPY_RULES.md), [게시물 준비 계약](docs/POST_PREPARATION_UI_20261022.md) |
| 폰 제어·게시 | [MOBILE_REELS_WIREGUARD.md](docs/MOBILE_REELS_WIREGUARD.md) |
| 개발 검증·지침 유지보수 | [DEVELOPMENT.md](docs/DEVELOPMENT.md) |

작업 기록은 규칙에 누적하지 않는다. 과거 AGENTS는 Git 이력에서만 조회하며 당시 실행 지시를 현재 승인으로 해석하지 않는다. 규칙 변경은 담당 원본을 수정하고 이 표의 연결과 검사를 함께 확인한다.
