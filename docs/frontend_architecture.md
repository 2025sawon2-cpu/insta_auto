# 프런트엔드 코드 찾기

빌드 도구 없이 정적 HTML이 기능별 JavaScript를 순서대로 불러온다. 아래 `submodule`은
기능별 파일·폴더를 뜻하며 Git submodule이나 별도 패키지 설치가 필요하지 않다.

## 화면별 진입점

| 작업 | 먼저 읽을 파일 | 기능 모듈 |
|---|---|---|
| 게시물 목록·검색·필터 | `web/app.js` | `web/discovery/model.js`, `web/hot-detection.js` |
| 오전 수집 후 열린 화면 갱신 | `web/discovery/report-refresh.js` | `app.js`의 `refreshDashboard()` |
| 원본 소스 ZIP·대사 추출 | `web/discovery/reference-jobs.js` | 제작실 상세 하단의 접힌 보조 도구; 제작 상태 렌더링과 별도 DOM 유지 |
| 게시물 상세의 4단계·완성본 비교 | `web/post-result.js` | `web/post-result.css` |
| 제작실 목록·작업 열기·탭 | `web/studio.js` | `web/studio-board.js`, `web/studio-intake.js` |
| 제작실 아이템 모달 시안 | `web/studio-modal.css` | `web/studio-detail.js`, `web/studio/source-view.js`, `web/studio-workspace.js` |
| 제작 요청·입력 보존·버전 선택 | `web/production-flow.js` | `web/studio-detail.js`, `web/studio-workspace.js` |
| 제작실 소스 현황·검색 기록·선택 | `web/studio/source-view.js` | `web/source-upload.js` |
| 자막·타이밍·장면 편집 | `web/caption-editor.js` | `web/caption-editor.css` |
| Remotion 자막·화살표·이모지 편집 | `remotion/editor.jsx` | `remotion/composition.jsx`, `web/remotion-editor.css`, `hotpost/remotion_editor.py` |
| 첫 프레임 썸네일 편집·새 버전 생성 | `remotion/thumbnail-editor.jsx` | `remotion/thumbnail-composition.jsx`, `hotpost/studio_thumbnail.py` |
| 제작실 수집 날짜·오늘·기간 검색 | `web/studio-browse.js` | `hotpost/collection_dates.py`, `studio_runtime/media.py`, `studio-intake.js` |
| 목소리 선택 | `web/voice-picker.js` | 자동 제작의 기본 목소리는 백엔드·VoiceBench 계약을 따른다 |
| 설정·로그인·알림 | `web/settings.js`, `web/platform-logins.js` | `web/display-settings.js`, `web/notices.js`, `web/collection-notifications.js` |

## 경계와 불변 조건

- **발견 시각:** `hot-detection.js`가 한국 날짜·최근 N시간·오늘 우선 정렬을 정의한다.
  `discovery/model.js`는 같은 규칙으로 필터·주제·상단 통계를 계산한다. 업로드 시각과 섞지 않는다.
- **제작실 수집 날짜:** `collection_date_at`은 터진게시물의 최초 핫 발견 시각과 같으며,
  기록이 없으면 최초 수집 시각, 내 촬영은 등록 시각을 사용한다. `collected_at`의 기존
  최초 수집 기록은 보존한다. 필터·카드 날짜·최근 수집순 정렬은 같은 기준을 사용한다.
  오늘은 한국 자정에 갱신하고 직접 선택한 기간은 유지한다. 최근 수집일은 별도 바로가기다.
  수집 연결 내역의 건수·후보는 마지막 수집 완료일을 기준으로 조회해 자정에 사라지지 않는다.
- **보고서 갱신:** 페이지 포커스·다시 표시·60초마다 `GET /api/report`를 확인한다.
  판정 기준 버전이 같아도 새 수집 시각이면 반영한다. 페이지 이동이나 상세 모달 재생성 없이
  목록과 통계만 갱신하므로 열린 영상·입력이 보존된다. 조회 실패 때는 마지막 확인 결과를 유지한다.
- **소스 선택:** `studio/source-view.js`의 `selection()`이 체크박스와 변경 여부 비교의 공통 기준이다.
  현재 완성본의 사용 소스와 다음 제작에 저장한 선택을 구분하며, 빈 선택도 유효한 선택으로 보존한다.
- **API 쓰기:** 소스 뷰는 화면·선택 기준만 담당한다. 실제 제작 요청과 저장은
  `production-flow.js`에서 수행한다. `discovery/reference-jobs.js`는 원본 추출 전용 API만 사용한다.
- **기존 작업:** `production.html` 및 `studio.js`의 이전 프로토콜 처리는 저장된 과거 작업의
  호환 경로다. 최신 화면에서 쓰지 않는다는 이유만으로 삭제하지 않는다. 일반 설정의 제작실 링크는 `studio.html`이다.
- **재생·표시:** 상세 4단계, 원본 왼쪽/완성본 오른쪽, 이전 완성본, 실제 실행 작업만 스피너 표시,
  완료 녹색·대기 회색·실패 빨간색 계약을 유지한다. 명시적 테마 선택이 OS 테마보다 우선한다.

## 로딩 순서

`index.html`과 `studio.html`은 `studio/source-view.js`를 `production-flow.js`보다 먼저 불러온다.
`index.html`은 `hot-detection.js`, `discovery/model.js`, `discovery/report-refresh.js`를
`app.js`보다 먼저 불러온다. `studio.html`은 `discovery/reference-jobs.js`를 `studio.js`보다
먼저 불러온다. 독립 VM 테스트도 같은 의존 순서를 지켜야 한다.
기존 최상위 파일 URL·공개 `window.ProductionFlow`, `window.PostResult` 인터페이스는 유지한다.
`studio.html`의 Remotion 번들은 `caption-editor.js`보다 먼저 로드한다. 편집 영역만 React를
사용하며, 설치와 렌더링 경계는 [remotion_editor.md](remotion_editor.md)를 따른다.
`studio-modal.css`는 제작실의 마지막 스타일 계층이다. 영상소스·내 대본·편집·완성영상의
네 탭을 제공하고 목소리 듣기·설정은 내 대본 도우미에서 연다. 기존 `voice` 링크는
`script`로 연결한다. 제작 단계 상태와 저장 API는 유지하고, 완료 안내만 제목 옆으로
모은다. 진행·오류·재시도 안내는 본문에 표시한다.

## 검증

제작실 탐색은 `studio-browse.js`와 `studio-browse.css`가 담당한다. 기본 화면은
제작 중·완성 영상 두 영역이며 확인 필요한 영상은 별도 화면으로 전환한다.
날짜 범위는 한국 시간의 최초 수집일(`collected_at`, posts.first_seen) 기준이고
재제작·수정 시간으로 바뀌지 않는다. 직접 촬영 작업은 최초 등록일을 사용한다.
수집 날짜가 없는 이전 작업은 전체 기간에서 접근할 수 있다. 화면 전환 시
검색어·날짜 범위·각 화면의 페이지와 스크롤 위치를 보존한다.
`test_studio_browse_browser.py`와 `test_studio_collection_dates.py`가 이 계약을 검증한다.

```powershell
node --test tests/*.test.cjs
Get-ChildItem web -Recurse -Filter *.js | Where-Object Name -ne data.js |
  ForEach-Object { node --check $_.FullName }
.\.venv\Scripts\python.exe -m pytest -q tests/test_dashboard_browser.py tests/test_production_flow_browser.py tests/test_studio_board_browser.py
```

DOM 회귀 테스트는 `linkedom`을 사용한다. 설치된 경로를 `HOTPOST_TEST_DOM`에 지정할 수 있으며,
미설치 상태에서 건너뛴 DOM 테스트를 화면 검증 성공으로 보고하지 않는다.
브라우저 테스트는 격리된 fixture API를 사용하며 실제 수집·영상 제작을 요청하지 않는다.
`web/data.js`는 생성 결과이므로 수동으로 수정하지 않는다.
