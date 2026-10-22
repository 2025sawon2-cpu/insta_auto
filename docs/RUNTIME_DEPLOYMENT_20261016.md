# 최신 코드 운영 반영·오전 7시 실행 확인 — 2026-10-16

사용자 요청에 따라 최신 저장 코드를 운영 프로세스에 반영했다. Git 커밋·푸시는 하지 않았다. 기존 영상 제작을 새로 시작하거나 중단 작업을 재개한 배포가 아니다.

## 오늘 오전 7시 작업

- Windows `HotpostDailyCollect`: 2026-10-16 07:00:01 실행, 종료 코드 0.
- 실제 로그: 07:00:02.108 시작 → 07:24:42.656 종료. `data/daily_collect.log`.
- 수집 DB run 9: 성공 39계정 / 실패 0 / 생략 0 / 게시물 55개. 제작 작업 3개 신규 등록.
- 수집 완료와 영상 제작 완료를 구분한다. 확인 시점에 오늘 선정 3개 영상의 완성본은 없다.

| 순위 | 대상 | 실제 제작 상태 |
|---|---|---|
| 1 | 반려동물 목욕 관련 `Defg3rTBA3M` / `work-32b187bd4c1a405c` | 원본 화면 문구 검토 오류로 `attention`. 이번 서버 반영에서 재개하지 않음. |
| 2 | 에르베 샤플리에 가방 `DegiqugP5pn` / `work-f06ccbf05b3b42f4` | 대본·음성 이후 `source_wait`. 기존 수집용 Chrome 연결을 확인할 수 없어 소스 대기. CAPTCHA 발생으로 판단한 것이 아님. |
| 3 | 지퍼 수선 관련 `Dege8mKBaUR` / `work-2cefe2e1f11f46fc` | 희미한 화면 문구 판독과 관련 없는 짧은 발화 검토 오류로 `attention`. 이번 서버 반영에서 재개하지 않음. |

예약은 변경하지 않았다. 다음 실행은 2026-10-17 07:00 KST다.

## 운영 반영

반영 전 메인 웹 서버 8775는 미실행이었다. 오전에 실행된 제작 워커(실제 PID 25872)와 구형 후속 자동화 helper(실제 PID 23104)가 남아 있었다.

1. 수집·제작·집필·후속 자동화 DB 4개를 SQLite backup으로 별도 보관했다. 작업 상태, 소스 코드 SHA, 설정 SHA, 주요 완성 영상 SHA를 저장했다.
2. 실행 중 제작·집필 작업이 없는 것을 확인하고, 대기 job 1개의 체크포인트만 임시 보류했다. 제작 DB transaction으로 새 claim과의 경쟁을 막은 상태에서 확인한 두 유휴 프로세스만 종료했다.
3. 첫 종료 점검은 VoiceBench 서비스 자식 프로세스를 발견해 아무 프로세스도 종료하지 않고 DB transaction을 rollback했다. 서비스 정체를 확인한 다음 VoiceBench를 보존하는 조건으로 진행했다. 실패한 점검 기록도 남겼다.
4. 19:01:53에 새 메인 프로세스(PID 23080)를 시작해 `http://127.0.0.1:8775/`에 바인드했다. 보조 UI도 같은 최신 소스로 3235에서 재시작했다. 둘 다 숨김 실행이다.
5. 로딩 확인용 `boot.py`가 실제 import한 17개 핵심 모듈의 경로·SHA·정책을 기록한 뒤 기존 공식 CLI `hotpost serve` 또는 기존 helper 진입점을 실행했다. 서버 기능을 별도 구현으로 대체하지 않았다.
6. 체크포인트를 원래 값으로 복원했다. 가방 소스 job은 같은 ID로 기존 대기를 이어가며, 별도 제작 워커 대신 메인 서버가 실제 OS worker lease를 소유한다.

렌더러는 요청마다 별도 JSON subprocess로 최신 파일을 읽는 구조다. 별도의 상주 렌더러 재시작은 필요하지 않다. VoiceBench 엔진·참조 음성·Seed는 변경하지 않았다. 원본 Chrome과 공유 영상 서버·터널도 종료하지 않았다.

## 검증 결과

- Hotpost 관련 회귀 **313개 통과**, 렌더러 관련 회귀 **72개 통과**. 서로 다른 저장소의 이번 실행 기록이며 과거 테스트 횟수를 누적하지 않는다.
- Hotpost Python 전체 문법 파싱, `monetization.js`·`post-result.js`·`app.js` 구문 검사 통과.
- 실제 운영 HTTP 8개 경로 200: 메인 페이지, 후속 자동화 HTML/JS, 수집 상태, 선정 결과, 기존 작업 조회, 연결 상태, 제작 준비 점검.
- 새 프로세스에서 집필 계약 `internal-codex-three-variants-20261016-v8-approved-kitty-script-style`과 썸네일 정책 `subject-specific-viewer-interest-20261016-v1` 로딩 확인. 로딩 모듈 SHA는 저장 소스와 일치.
- 후속 자동화 HTML/JS 실제 응답이 작업 공간 파일과 바이트 단위로 일치.
- 실제 `/api/production-health`: Codex 집필·VoiceBench·auto_capcut 모두 ready.
- 기존 완성 영상 API는 Range 206, 1024바이트 및 실제 파일 prefix 일치 확인. 새 영상을 만들거나 영상 내용을 교체하지 않았다.
- DB 4개 모두 `quick_check=ok`. 기존 52개 작업의 추가·삭제 없음. 51개 작업의 저장 상태가 그대로이고, 가방 1개만 기존 `source_wait`를 유지하며 대기 관찰을 갱신했다.
- 과거 job 875개의 상태·체크포인트·오류 보존. 기존 손난로 완성본 및 패딩 별도 개선본 SHA 불변. 수익화 외부 effect 추가 없음. 설정·예약 및 배포 대상 소스 파일 불변.

## 남은 검증

운영 반영과 기본 동작 검증을 완료했다. 새 영상 한 편의 전체 제작을 이번 배포 검증으로 실행한 것은 아니다.

- Chrome 연결 상태는 여전히 false다. 소스 확보는 대기하며 다른 프로필·브라우저로 대체하지 않았다.
- 본인 쿠팡파트너스 API는 미설정이다. 후속 자동화 설정은 기존대로 disabled이며 메인 서버의 완료 감시 스레드만 정상 동작한다. 보조 UI에는 제작·완료 감시 worker가 없다.
- 따라서 실제 댓글·DM·링크 발급·리틀리 등록·발송의 전체 실계정 검증은 남아 있다.
- 오늘 1위·3위의 원본 문구 검토 오류 원인을 수정·재검증하는 작업은 이번 재시작 범위에서 수행하지 않았다.

## 근거 파일

`data/runtime-deployment-20261016/`에 다음을 보존했다.

- `*-before.sqlite3`, `before.json`, `after.json`: DB 백업·전후 상태·코드/영상 SHA.
- `main-boot.json`, `helper-boot.json`: 실제 새 프로세스와 로딩 모듈.
- `maintenance.json`, `maintenance-v2.json`, `stopped.json`, `restored.json`: 최초 보류와 실제 종료·복원 기록.
- `http-verification.json`, `ownership-verification.json`, `preservation-detail.json`: HTTP·OS lease·예약·작업 보존 확인.
- `schedule-before.json`, `schedule-after.json`, `listeners-after.json`, `processes-after.json`: 실제 예약·리스너·프로세스 확인.
- `hotpost-regression.xml`, `renderer-regression.xml` 및 대응 로그: 이번 회귀 결과.

기존 보고서에 있는 ‘운영 서버 미반영’은 그 보고 시점의 사실로 보존하며, 최신 운영 반영 상태는 이 문서를 따른다.
