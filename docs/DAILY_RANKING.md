# 오전 7시의 최근 72시간 게시물 선정

사용자가 정한 현재 일일 경로다. 기존 제작실·자동 collector·성장 추적기는 보존하며 이 경로에서 호출하지 않는다. 수집과 제작은 승인된 예약 또는 명시 요청에서만 실행한다.

## 매일 현재 값으로 평가

- 수집 시작 시각을 한 번 고정하고 그 시각 이전 **72시간**에 실제 게시된 게시물을 확인한다. 고정 게시물·릴스 탭 순서와 원본 게시 시각을 구분한다. 시작 이후 게시물과 72시간 밖 게시물은 이번 대상에서 제외한다.
- 현재 로그인된 동일 Chrome 세션에서 계정별 최근 게시물과 **이미 수집했던 구간 안 게시물도 다시** 확인한다. 기존 DB에 있다는 이유로 건너뛰지 않는다. 과거 값으로 오늘의 미확인 조회수·팔로워 수를 채우지 않는다. 접근 제한·계정 간 간격은 [소스 규칙](SOURCE_WORKFLOW.md)을 따른다.
- **게시물 본문에 다이소가 있는 릴스는 제외한다**(사용자 결정 2026-10-27). 수집된 게시물 패널 텍스트에서 계정·음원 머리말과 댓글을 떼어 낸 본문(해시태그 포함)에 `다이소`/`daiso`(대소문자 무관)가 있으면 점수와 무관하게 랭킹·원장 후보에서 빠진다. 댓글에만 있는 언급은 제외 사유가 아니다. 패널 형식을 알아볼 수 없으면 전체 텍스트로 판단한다. 리포트에는 `assessment.status=excluded`, `reasons=["excluded_topic:daiso"]`로 남는다. 이미 원장에 있는 과거 후보는 다음 수집에서 `in_latest_report=false`가 된다.
- 현재 조회수 / 현재 팔로워 수로 점수를 산정한다. 기존 자료 선정 설정인 `acquisition_min_views_per_follower`(기본 1.8배), `acquisition_min_views`(기본 1,000회)를 모두 통과한 릴스만 랭킹에 포함한다. 새 최소치를 추가한 것이 아니며 PC 설정은 덮어쓰지 않는다. 좋아요·댓글·과거 평균·표본 수·게시 후 시간 보정·이전 관측은 선정 조건이 아니다.
- `1.7만`, `8만`, `팔로워 2.3만`은 표시 원문을 보존하고 각각 약 17,000·80,000·23,000으로 계산한다. 축약 표시만으로 제외하거나 정확값 확보를 기다리지 않는다. 실제로 값이 보이지 않거나 팔로워가 0이면 수치 미확인으로 남겨 이번 랭킹에서 제외한다.
- 조회수 증가량·속도·추격 점수·가속도·순위 변화·후속 관측 예약은 **사용하지 않는다**. 매일 현재 수치만으로 새로 평가한다. 실행 증거와 이전 자료 보존은 성장 추적과 구분한다.
- 최근 72시간 전체에서 점수 내림차순으로 정렬한다. 동점은 조회수, 게시 시각 내림차순, shortcode 순이다. 날짜별 우선 정렬이나 최초 발견일 우선은 적용하지 않는다. 1·2·3위 아래 후보도 보존하며, 통과 후보가 없으면 순위를 만들지 않는다.

## 현재 입력과 실행

브라우저 관측 폴더의 `profile-cards.json`, `post-details.json`, `reel-grid-views.json`은 같은 `started_at`을 가진다. 기존 수집 기록 형식을 유지하되 탐색·재확인 범위는 72시간이다. 프로필에는 `username`·보이는 `followers`·`observed_at`, 게시물에는 계정 경로가 포함된 `href`·`username`·실제 게시 시각 `last`·`observed_at`, 조회수에는 `href`·보이는 `raw`·`observed_at`을 저장한다. 반올림·누락과 접근 실패를 구분하며 수집 누락 계정/게시물은 실행 기록에 남긴다.

```text
python -m hotpost.daily_ranking --observations <이번 관측 폴더> --output <이번 폴더>/daily-report.json --publish
python -m hotpost.reference_registry --registry data/reference-status.json list --report data/report.json
python -m hotpost.reference_registry --registry data/reference-status.json next --report data/report.json
```

`--publish` 없이 실행하면 새 스냅샷 파일만 만든다. `--publish`는 이전 report를 관측 폴더에 보존한 뒤 현재 수치·실행 기록·리포트·원장을 갱신한다. 성장 추적 등록·후속 조회·모델·제작·게시를 실행하지 않는다. 입력/출력 폴더를 새로 준비하고 이미 쓴 스냅샷이나 동일 조건을 무진전 재호출하지 않는다. `ranking_mode=views_per_follower_72h`인 리포트가 현재 계약이며 과거 리포트와 완료본은 보존한다.

## 수집 후 신규 적격 게시물의 상품·내 원링크

사용자 결정 2026-10-27: 매 수집에서 **새로 수집한 게시물 중 위 기준을 통과한 릴스만** 댓글→수신 DM→상품 버튼→정확한 상품·옵션→내 쿠팡 인플루언서 원링크 확인을 진행한다. 영상 완성을 기다리지 않는다. 기존 수집 계정과 로그인된 동일 Chrome을 사용한다. 실제 계정·스토어·컬렉션·Chrome 연결은 Git 제외 `data/monetization/state.sqlite3`의 `collection_products` 설정을 사용한다. [설치별 초기 설정](POST_PREPARATION_UI_20261022.md#설치별-초기-설정)이 저장되어 있으면 계정·스토어·컬렉션은 `installation` 설정을 우선하고, 기존 활성화 여부와 Chrome 연결은 유지한다. 설정 저장은 실행 재개가 아니다. 초기 설정은 과거 수집 게시물을 기준선으로 보존하며 과거 전체를 소급 처리하지 않는다.

`daily_ranking --publish`는 posts upsert **전에** `collection_product_seen`/`collection_product_queue`에 새 게시물과 대기열을 한 트랜잭션으로 보존한다. 이 코드 자체는 댓글·DM·링크 발급을 실행하지 않는다. 현재 수집을 맡은 에이전트는 publish 뒤 아래 절차를 이어서 실행해야 상품 확인까지 완료한 것이다. 대기열 생성만으로 수익화 완료라고 보고하지 않는다. 새 작업은 한 건씩 처리하며 기존 영상 제작·리틀리 등록·실제 게시를 이 단계에 연결하지 않는다.

1. `python -m hotpost.collection_products list`로 `pending`을 읽고, 현재 게시 리포트에서 여전히 적격인 대상만 확인한다. `comment_reserved` 이후 중단된 시도는 다시 댓글을 달지 말고 기록·실제 화면을 확인해 실패 또는 읽기 전용 복구로 남긴다. 완료된 결과는 재사용하고 실패는 다음 수집·재시작으로 풀지 않는다.
2. 기존 Chrome의 실제 로그인 계정, 원작성자·shortcode·현재 본문, 기존 DM 메시지 identity 기준선과 기존 자기 댓글을 관측한다. 키워드는 본문이 요청한 실제 단어를 사용한다(`keyword_from_caption`). 고정 `나도`를 다른 원작 키워드 대신 쓰지 않는다. 아무 댓글 조건일 때만 기본 `나도`를 사용한다. 불명확하면 보내지 않고 사유를 남긴다.
3. Git 제외 data 작업 폴더에 preflight JSON을 저장한다. `observed_at`(Unix초), `account`, `browser_extension`, `storefront_url`, `shortcode`, `author`, `caption`, `keyword`, `dm_baseline`(기존 수신 메시지 identity 배열), 화면 근거를 포함한다. `begin --code <id> --evidence <JSON>`이 `comment_reserved`와 반환한 `token`을 내구 저장한 **후** 댓글 한 번만 제출한다. 기존 수익화 `effects`와 원링크 시도가 있으면 자동 재진입하지 않는다. 실제 자기 댓글의 ID·키워드·계정을 확인한 JSON으로 `record --stage comment_confirmed`를 실행한다.
4. 댓글 이후의 새 수신 DM만 사용한다. `sender`, `incoming=true`, 새 `message_id`와 관측 시각·화면 근거로 `record --stage dm_received`를 실행한다. 팔로우 확인형이면 첫 안내 DM을 보존하고 확인 뒤 도착한 상품 DM을 새 message_id로 같은 dm_received 단계에 한 번 추가 기록한다(별도 followup 근거로 보존). 필요한 팔로우·팔로우 확인·상품 버튼은 클릭 **전에** `reserve-action --action follow|follow_check|product_button --code <id> --token <token>`으로 각각 한 번만 예약한다. 이미 팔로우 중이면 새 팔로우를 하지 않는다. 첫 DM 및 확인 후 DM은 기존 설정 `monetization_dm_initial_wait_seconds`/`monetization_dm_followup_wait_seconds`(기본 각각120초)까지만 기다린다. 미수신·결과 불명·접근 제한이면 `fail --reason <실제 사유>`로 종료하고 댓글/버튼을 재실행하지 않는다. 여러 상품 중 대상이 불명확하면 임의로 고르지 않는다.
5. 실제 버튼의 URL과 도착 상품명·원 상품 URL의 productId/itemId/vendorItemId를 확인해 `record --stage product_verified`에 `dm_button_url`, `product_name`, `product_url`과 최종 상품 DM의 `message_id`를 연결한다. 원작성자 제휴 링크를 우리 수익화 링크로 사용하지 않는다.
6. 로그인된 내 스토어·설정 컬렉션을 확인한 JSON(`storefront_url`, `collection`)으로 `record --stage link_reserved`를 먼저 남긴다. 기존 원링크는 정확한 상품·옵션으로 찾아 재사용한다. 없으면 기존 Chrome에서 본인 파트너스 링크를 발급하고 **확인된 내 컬렉션**에 한 번 등록한다. 기존 `coupang_onelink`의 원링크·상품 식별자 검증을 재사용한다. 로그인/인증/상품·옵션 확인이 안 되면 중지하며 API나 다른 상품으로 대체하지 않는다.
7. 내 스토어의 실제 상품 레코드에서 얻은 CREATOR 원링크와 그 링크의 실제 도착 상품·옵션을 대조한다. `record --stage completed` JSON에는 `one_link`, `product_name`, `product_url`, `storefront_url`, `final_url`, `landing_verified=true` 및 `store_record_evidence` 객체(스토어 주소·원링크·세 식별자), 실제 화면 근거를 포함한다. 모든 record에는 같은 `--code`, `--token`, `--evidence`를 전달한다. 완료 원링크는 정상 게시물 준비 화면의 빈 제품 링크에 읽기 전용으로 연결되며 기존 사용자의 비어 있지 않은 링크는 덮어쓰지 않는다.

상품 확인 실패는 수집 수치·순위·완성 영상을 되돌리지 않는다. 그 게시물의 실패 근거를 남기고 다른 **신규 대기열 항목만** 순서대로 확인할 수 있다. 접근 제한이 계정 전체에 적용되면 남은 항목을 실행하지 않는다. 실제 관측·시도·완료를 구분해 이번 수집 결과와 함께 보고한다. 초기 실증은 사용자가 명시한 한 건만 `add-test --code <id> --authorization <사용자 실제 지시>`로 등록하며 이 예외로 과거 전체를 처리하지 않는다.

## 성과 순위와 제작 대상

목록 카드는 기존 사진 썸네일·조회수·5단계 작업현황 패널을 유지한다. 현재 조회수/팔로워 수는 선정 입력이며 카드의 작업현황 영역을 수치 표시로 바꾸지 않는다. `thumb`이 비어 있으면 같은 shortcode의 로컬 `web/thumbs` 캐시를 사용하고, 실제 사진이 없을 때만 대체 아이콘을 표시한다. 썸네일 캐시 복구는 순위 수집·영상 소스 채택·제작 재개와 별도로 기록한다. 공통 원장의 제작 상태는 `AgentStatus.referenceModel`을 통해 기존 패널로 표시하며, `in_progress`나 담당자 결속만으로 실제 실행 애니메이션·단계별 완료를 추정하지 않는다. 순위·축약 수치 허용·완성본 필터는 그대로 유지한다.

완성 여부는 성과 순위에 영향을 주지 않는다. 완성 영상도 랭킹에 남기고 완성 영상 보기/필터로 구분한다. [공통 원장](REFERENCE_STATUS.md)의 고정 video_id에 task/run·제작자/감시자·현재 최종 파일·QA를 연결한다.

- 다른 영상이 제작 중·중지·보류라면 기존 작업을 먼저 확인한다. 원래 중지를 자동 해제하거나 새 영상으로 건너뛰지 않는다.
- 위에서부터 **완성된 영상만** 자동으로 건너뛴다. 완료 처리된 영상은 이미 검토가 끝났으므로 다시 검사하지 않는다. 상위 3개가 전부 완성이어도 그 아래를 확인한다.
- `unknown`이면 기존 작업·DB·완료본을 감사한다. 미제작으로 확인되면 근거를 남겨 `not_started`로 바꾸고 같은 후보를 다시 확인한다. 미확인을 미제작으로 추정하거나 다음 후보로 건너뛰지 않는다.
- 첫 적격 `not_started` **한 편만** 시작한다. 전담 제작자·읽기 전용 감시자, 최종 QA·저장·완료 후 독립 검증은 [WORKFLOW](WORKFLOW.md)를 따른다. 실제 게시와 다음 영상 자동 시작은 포함하지 않는다.
