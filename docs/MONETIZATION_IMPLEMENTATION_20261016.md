# 영상 이후 자동화 구현과 검증 — 2026-10-16

기준: `MONETIZATION_PLAN_20261015.md`. 기존 영상·대본·개인 음성·완료/중지 상태를 보존한다. 계획의 과거 “기획만 수행” 범위는 이번 구현 요청으로 갱신됐으며, 실제 실행 결과는 아래처럼 분리한다.

## 제작·비교 전달

- 신규 1편 요구는 당시 미제작 레퍼런스로 생성된 손난로 `work-2d881e5afb2043ce / Dec5bcqyffk`가 충족한다. 재제작하지 않았다.
- 현재 MP4/계획 SHA와 통과 검수의 결속, 원본 존재, 생성 전후·기존 42개 작업 보존 근거를 감시 에이전트가 다시 확인했다.
- [원본 왼쪽·완성본 오른쪽 비교](https://navigate-penny-item-translated.trycloudflare.com/). 요청 미디어만 공개하는 별도 allowlist 서버이다. 제작 API·계정·키는 공개하지 않는다. PC·터널 프로세스 실행 중 유효하다.
- 실제 HTTPS range 206/1024 bytes·로컬 prefix 일치·다운로드 헤더, 브라우저 전체 16.8초 재생 종료/오류 없음 확인.
- 증거: `data/goal-continuation-20261016/{production-audit,public-verification,public-playback}.json`.

## 구현한 연결

- `monetization_store.py`: 영상 제작 큐와 별도 SQLite 기록. 계정명 정규화, 계정+레퍼런스+동작별 유일한 시도, 외부 제출 전 원자 기록, 실제 OS lease, 죽은 실행 소유자의 불명확 결과 오류 보존. job/task ID 변경으로 댓글 제한을 초기화하지 않는다.
- `monetization.py`: 검수된 실제 영상/계획/선택 대본 SHA에 결속해 상품 확인 → 링크 발급·연결 검사 → 본문 → 리틀리로 순차 진행한다. 오류는 이 흐름에만 남긴다. 기존 영상 큐를 재개하지 않는다.
- `coupang_partners.py`: 본인 파트너스 API 자격·계정 참조·키 저장, HMAC 요청, 원 상품 URL 응답 대응, 상품/옵션 ID 일치 검사. API 발급과 실제 landing 확인을 분리한다. 판매자 API/웹 발급으로 대체하지 않는다. 키는 GET/로그에 반환하지 않는다.
- `post_publish.py`: 선택 대본을 보존한 게시글 본문, 명시한 제휴 안내, ‘나도’ CTA, 정확한 DM 템플릿·개행·하트·아래방향8개, 실제 제품명/확인 특징의 버튼18자 제한.
- `monetization_browser.py`: 현재 승인된 Chrome 창/세션만 연결. 댓글1회, 기존/신규 DM 분리, 원작성자 수신 근거, 필요한 팔로우1회·새 메시지의 확인 버튼1회, 상품 확인, 리틀리13단계와 저장값 재확인 경로. 현재 UI가 계약과 다르면 오류로 멈춘다. 아직 실계정 DOM으로 검증하지 않았다.
- 오류 화면 기록(W26): 해당 실행이 마지막으로 접근한 탭만 연결 해제 전에 캡처한다. 정상·실패 화면 모두 별도 UUID 파일에 실제 화면·URL·시각과 같은 실행의 직전 동작 근거를 보존하고, 오류의 원래 예외 종류 및 effect/record·게시물/발송 읽기전용 오류에 경로를 연결한다. 스크린샷 실패도 새 영수증에 남기며 원래 오류를 바꾸지 않는다. 이전 실행의 `last-ui-step.json`을 새 오류 근거로 재사용하지 않고 실패 effect의 키워드·시도1회 정보를 유지한다. 같은 이름의 재검사로 과거 근거를 덮지 않으며, Playwright TimeoutError도 읽기전용 단계와 예약을 유지한 채 확인 실패로 기록한다.
- 첫 DM·팔로우 확인 후 DM 대기는 `Settings.monetization_dm_initial_wait_seconds` / `monetization_dm_followup_wait_seconds`로 각각 설정한다. 초기 구현 기본값은 각120초이며, 전체 제작시간 제한으로 전파하지 않는다. 실제 메시지 ID·수신 시각의 UI 표현도 실계정 검증에서 확인해야 한다.
- 수신 DM의 쿠팡 직링크와 관측된 상품 링크페이지를 지원한다. 공개 HTTPS 관측 링크만 열고, 표시된 후보의 레퍼런스 대응 문구를 확인한 경우에만 이동한다. 같은 페이지/fragment 반복·모호한 복수 링크·403/429·로그인/인증은 중지한다. 최종 쿠팡 상품/옵션 identity 확인은 그대로 유지한다. 로컬 route fixture에서 링크페이지→쿠팡2회 이동과 옵션 보존을 검증했으며 실제 서비스 실증은 아니다(`link-page-ui-fixture/verification.json`).
- 계정별 ‘다음 게시물’ 슬롯은1개만 유지한다. 불명확한 생성·실패로 슬롯을 자동 해제하지 않는다. 실제 게시물 연결 영수증을 확인해야 다음 상품으로 넘어간다.
- 첫 댓글 전 계정별 workflow도 원자 확보해, 앞선 상품이 처리 중이면 다른 레퍼런스의 댓글·API 호출부터 낭비하지 않는다. 생성 전 terminal 오류의 workflow만 해제하고 불확실 생성·등록 슬롯은 보존한다.
- `StudioStore.save` → `monetization_completion.py`: 새 `미완료 → 완료` 전환의 영상·계획·대본 SHA를 같은 DB transaction의 outbox에 남긴다. 과거 완료본은 backfill하지 않는다. 실제 task OS lease로 완료 handoff 중단을 구분하고 미시도만 재수용한다. 앞으로 새 완료 영상의 자동 후속 설정을 UI/API에 추가했다. 첫 실증 전 기본값은 꺼짐이며 이번 작업으로 운영 제작 worker를 시작하지 않았다.
- 게시 후 `inspect-post`는 저장된 자동화·우리 계정의 실제 게시물·본문·상품 링크를 읽어 결속하고, 확인 후에만 예약 슬롯을 해제한다. `inspect-delivery`는 해당 게시물·링크·자동화의 실제 상태 column이 성공인 발송 내역만 인정한다. 두 경로는 댓글·DM을 보내지 않는다.
- 늦게 로딩된 과거 DM·상대시각 변경, 성공0건/실패와 성공 단어 혼합, 타인댓글의 본문 복사를 성공 근거로 인정하지 않는다. 선택지 문구가 보이기만 해서는 ‘모든 댓글’로 판정하지 않고 실제 checked/selected/pressed 상태를 요구한다.
- `monetization_http.py`, 설정 연결 메뉴, 완성 영상 후속 링크, `web/monetization.*`: 연결 설정과 게시물별 상태·본문 표시.
- `tools/serve_monetization.py`: 제작 worker를 띄우지 않는 로컬 후속 설정 화면. 실제 손난로 작업은 `product/ready` 준비 상태만 저장했으며 외부 댓글은 보내지 않았다.

## 오류 목록과 회귀 검증

간단한 원인·수정·재검토 상태는 [감시 목록](GOAL_CONTINUATION_WATCH_20261016.md)에 기록한다. 이전 제작 중 D1~D7은 [기존 제작 감시](GOAL_LIVE_WATCH_20261015.md)에 보존했다.

- 새 수익화 테스트14개: 동시·재시작·새task 우회 금지, 실제 lease 생존/종료, 상품 옵션 불일치, 인증 서명, 키 비노출, 정확한 본문/DM, 순차 진행 및 실패 후 재댓글 금지. 외부 adapter는 fixture이며 실계정 성공으로 세지 않는다.
- 관련 수익화/검색어/병렬 수집 검사113개 통과: `monetization-query-tests.xml`.
- 별도 backend/서버 수명/과거 제작 보존 검사104개 통과: `backend-tests.xml`. 위 범위와 겹치므로 합산하지 않는다.
- 로컬 화면 렌더·스크립트 오류0·작업 ID 프리필·키 password 필드 확인. 실제 HTTP 다른 Origin403, 잘못된 Content-Type400, GET 키 비노출 확인.
- Python compile 및 새 JS 문법 검사 통과. 이번 변경 대상 `git diff --check` 통과. 전체 검사에는 건드리지 않은 기존 두 테스트 파일의 EOF 빈 줄 경고가 있어 임의 정리하지 않았다.
- 10/16 이어서 추가: 수익화/완료 outbox 검사34개 통과, 제작 workflow·검수·claim 등 관련 회귀149개 통과(중복 범위 합산 금지). `completion-store-regression.xml`, `followup-completion-tests.xml`, `followup-dom-contract.json`, `monetization-ui-extended-verification.json`에 증거를 남겼다. 실제 로컬 DOM으로 미선택 옵션·성공0건·실패 row를 거부했고, 상태 표시와 화면 스크립트 오류0을 확인했다. 실계정 DOM으로 확대하지 않는다.
- W26 후 수익화/완료 outbox 검사38개 통과(`failure-evidence-tests.xml`), 이번 관련 회귀149개 통과(`followup-r3-regression.xml`). 서로 다른 실행 목록이며 과거 수치와 합산하거나 단순 증감 비교하지 않는다. 새 반례4개는 실패 화면·촬영 실패·원예외/과거 근거 분리·effect 연결·이전 파일 불변·Playwright 시간초과의 읽기전용 재검사를 검사했다. 외부 계정 동작0회다.

## 미완료: 실계정 종단 검증

현재 수집용 Chrome의 실제 연결이 없고 쿠팡파트너스 API 키도 연결되지 않았다. 키 값을 채팅에 요구하지 않고 기존 저장 경로 또는 로컬 설정 화면을 요청했다. 이 상태에서 외부 댓글/팔로우/링크 발급/리틀리 생성을 시도하지 않았다.

남은 작업:

1. 기존 수집 Chrome의 Instagram·쿠팡·리틀리 탭 및 실제 로그인/연결 계정 확인. 실제 DOM으로 locator·DM 수신 방향·기본 답글·완료 상세 화면 보정.
2. 본인 파트너스 API 실제 발급 응답과 링크의 상품/옵션 일치 실증.
3. 이 영상 한 건으로 댓글1회부터 리틀리 저장 상세까지 실증. 실패 시 동일 레퍼런스에 자동 재댓글하지 않는다.
4. 구현한 읽기전용 게시물 연결·DM 발송 확인을 실제 리틀리 화면으로 검증한다. 수동 입력 boolean을 성공 근거로 쓰지 않는다. 해당 게시물을 실제 게시하기 전에는 연결/전달 완료를 주장하지 않는다.
5. 완료 outbox·자동 후속 연결 코드는 구현됐으며 첫 실계정 실증 후 새 제작의 실제 완료 전환에서 확인한다. 과거 완료/중지 작업을 일괄 재개하지 않는다.

따라서 전체 목표는 진행 중이며, 코드·fixture 통과를 실계정 완료로 보고하지 않는다.

## 3차 연결 재점검과 실행 한계

`continuation-r3.json`에서 기존 영상 revision188·원본/영상/계획 SHA 불변·제작 queued/running0, 수익화 product/ready·effects0·worker 비실행을 재확인했다. `public-range-r3.json`은 공유 영상의 HTTPS206·1024바이트·로컬 prefix 일치를 확인한다. 과거 전체 재생 근거와 구분한다.

기존 수집 Chrome과 본인 파트너스 API 연결 부재가 세 번째 목표 작업에서도 동일하게 확인됐다. 실제 댓글부터 리틀리 저장·게시물 연결·DM 전달까지의 검증은 연결 없이는 진행할 수 없다. 새 프로필이나 다른 계정으로 대체하지 않았고, 키 값은 출력하지 않았다.

로컬 후속 설정 helper의 재시작 명령은 자동 승인 검토에서 정책 차단으로 거부됐으며 구체적인 사유는 제공되지 않았다. 명령은 실행되지 않아 기존 helper는 유지했다. W26은 저장 코드·격리 회귀에서 검증됐고 실행 중 helper에 새 orchestration 코드가 적용됐다고 주장하지 않는다. 기존 설정 화면 주소는 유지된다: `http://127.0.0.1:3235/monetization.html?task=work-2d881e5afb2043ce`.
