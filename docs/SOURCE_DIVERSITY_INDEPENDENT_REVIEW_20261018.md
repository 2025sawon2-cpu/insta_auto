# 최소 검색·본문5원본 독립 검수 — 2026-10-18

상태: 2026-10-18 신규 패딩 영상의 검색·본문 원본·실파일·최종 QA·과거 자료 보존 독립 검수 완료. 실제 영어5·중국어5 검색과 본문6원본 MP4를 확인했다. production 코드는 변경하지 않았다. 브라우저 끝까지 재생·청감 확인·공개는 root 담당이며 이 문서의 기술/영수증 감사와 구분한다. 아래 진행 중/대기/실패 기록은 당시 관측을 보존한 시간별 이력이다.

## 최신 수용 기준

서로 다른 유효 영어 검색어5개 및 중국어 검색어5개로 실제 검색하고, 관련·검토·편집 가능한 서로 다른 부모 원본5개 이상을 확보한다. 최종 본문에도 실제 서로 다른 부모5개 이상을 사용한다. 검색어 생성·링크·미시도·표지 전용 사용·파생 파일/shot 개수로 수를 채우지 않는다. 반응/맥락과 정상속도 연장·재사용 허용은 유지한다. 모델의 passed가 정량 본문5원본 검사를 대체하지 않는다.

수집 준비와 의미 후보/실제 배치 가능성은 별도 결과다. 확보5개가 의미 후보5개 또는 최종 사용5개를 보장하지 않는다. 이때 부족 단계를 기록하고 현재 로컬 대안·이미 받은 미검토 자료·미사용 검색 범위를 먼저 평가해야 한다. 같은 확정 실패나 CAPTCHA/로그인 제한을 반복해 숫자를 채우지 않는다.

## 직접 확인한 경계와 반례

1. 이전 `source_goal`의 scene_duration 분기는 `minimum_total`로 만든 ready를 coverage 결과로 덮어썼다. 신규 최소5만 필드에 넣으면 우회될 수 있으므로 수집 agent가 최소 검색/원본 gate를 마지막 완료 결과까지 연결해야 한다.
2. `scene_analysis`의 최대6 options는 부모별6개가 아니다. 같은 부모의 shot6개만 남을 수 있으며 선택기에서 없는 부모를 만들어 사용할 수 없다. 관련성/직접 시연 보호를 유지하면서 부모별 대안을 보존하거나 제외 이유를 기록해야 한다.
3. renderer의 최초 minimum coverage는 충분히 긴 승인 window만 세어 diversity 실패를 기존 window-extension 요청보다 먼저 반환했다. 5번째 원본이 의미상 적합하고 0.9초→1초 정상 연장으로 사용 가능해도 그 기회를 놓칠 수 있다. 담당 renderer agent에게 전달했다.
4. main의 명시 unknown/완화 policy fail-closed와 renderer 최초 unknown version→unenforced가 달랐다. 같은 계약이 실행 경계에 따라 꺼지지 않도록 담당 agent에게 전달했다.
5. 단순 original_sha 우선 집계는 동일한 실제 file SHA5개에 서로 다른 original_sha 주장만 붙여5원본처럼 셀 수 있었다. 독립 반례로 재현했고 root가 동일 실제 SHA와 계보를 union하는 `parent_groups`로 수정했다. 이후 해당 반례도 통과했다.
6. `verified_quality_export`가 QA 비활성이면 바로 true를 반환하는 기존 경로를 지적했다. 현재 새 minimum 검사는 모델 검수 활성 여부와 별개로 적용된다. worker의 디코드/모델 전, 모델 결과 수용, 완료 검증에서 plan의 현재 계약 누락과 본문 수량 미달을 거절한다.
7. 현재 `handle_source_diversity_gap`는 no-render 증거와 진단을 보존하고 자동 진행을 끈다. 이는 반복 차단이며 로컬 재순위/미사용 검색을 실제로 실행했다는 뜻은 아니다. 이 연결이 추가되기 전 완료 보고에서 자동 복구까지 구현했다고 확대하지 않는다.
8. 최초 한 beat=한 shot 모델은 본문 beat슬롯이5개 미만이면 충분한 원본이 있어도5원본 배치가 불가능했다. 사용자 요구는 원본5개이지 자막5조각이 아니므로 root에 보고했다. 후속 renderer가 visual_cuts로 대사/자막을 보존한 분할을 구현하고, main의 수량·반복/진전·경계·QA 표본도 실제 visual_cuts를 읽도록 정렬 중이다. 아래 최신 반례는1대사/5실제컷을 검사한다.

## 독립 격리 검사

합의 main API: `policy_for_state`, `parent_identity`, `body_usage_report`, `require_body_minimum`, `SourceDiversityRequired.diagnostics`.

`.venv/Scripts/python.exe -m pytest tests/test_minimum_source_diversity_independent_20261018.py -q`: **35 passed (0.17s)**. 검사는 합성 plan과 임시 파일만 사용하며 외부 검색/모델/디코드/렌더 성공을 주장하지 않는다.

- 실제 선택 부모5개 통과 및 입력 불변, 확보5/options5인데 선택1개이면 shortfall4.
- 파생5개·같은 실제 SHA5개·상충 계보 태그가 있어도 동일 file SHA는 중복.
- 표지 전용5번째, 첫1프레임 cover beat, 양수 시간이지만 출력 tick이0개인 구간, 음수/0 source/output window, SHA 누락 제외.
- 관련 리액션/맥락의 실제5번째 부모 허용. 새 정보·제품 전 컷 노출 조건을 추가하지 않음.
- unknown/완화/누락/잘못된 타입의 명시 policy fail-closed. 현재 expected policy를 plan에서 지워 우회할 수 없음.
- run 동결 policy 우선, legacy run이 새 state policy를 소급 상속하지 않음, 과거1원본 통과 표시 보존.
- 실제 `DailyQualityMixin`에서 디코드·모델 전에 미달/계약 누락 거절. controlled model passed라도 수용 불가 및 상태 불변.
- QA 기능이 꺼져 있어도 export 완료 불가. 정상5원본의 새 계약 완료 경로는 통과.

## 문서 정렬 이력

최초 읽기에서 AGENTS 최신 수집 항목과 개선 계획에 “최종5개 사용은 필수 아님”이 남았다. 계획의 수용조건7, 사용자 기준, 단계2/3 완료 조건, 최종 보고 기준, 새 세션 인계 prompt까지 같은 과거 기준이 반복됐다. root에게 최신 “최종 본문5개 필수”와 충돌함을 전달했다. 단지 맨 위 한 문장만 바꾸고 단계별 수용 조건을 그대로 두면 구현/검수의 서로 다른 목표가 남는다.

과거 v3/v4·이미 완료된3개 결과는 당시 계약의 이력으로 보존한다. 새 정책은 `source_diversity_policy.version=minimum-five-sources-v1` 명시 run/plan에 적용하며, 구현된 gate와 새 실제5+5검색·본문5원본 실행 검증은 분리한다.


## 후속 검수와 추가 위임

renderer 담당 후속 코드에서 짧은5번째 부모의 적합 window가5원본 구성을 가능하게 하면 `reviewed_window_required`로 기존 실제 정상속도 연장을 먼저 요청하는 분기를 직접 읽었다. unknown policy fail-closed 및 동일 실제 SHA/원본 alias union도 반영됐다. `<5 body slots`에는 `requires_cut_split`과 추가 슬롯 수를 기록하며, 이후 사용자 목표가 실제 새 영상 완성으로 명확해져 renderer 담당이 컷 분할 연결을 계속 구현한다.

root는 즉시 hold만 하는 최초 gap handler를 실제 로컬 대안/근거 결속 재순위/받은 미검토 자료/미사용 검색 보완으로 교체한다고 알렸다. 본 검수자는 이 완료 경로가 실제 연결되기 전 자동 복구 완료라고 표시하지 않는다.

추가 명시 위임으로 `test_daily_quality.py::ready`와 `test_studio_workflow.py`의 기존 module-scope small_inventory_contract만 legacy v4로 명시 고정했다. 기존 guard/assertion은 변경하지 않았고 전역 conftest는 수정하지 않았다. 앞선 단일 소스 큐/캐시/복구 테스트의 계약을 보존하는 변경이며 신규 최소5 계약을 약화하지 않는다. 실제 신규 기본값 v5가 새 store/run에 영어5·중국어5·본문5 정책을 동결하는 별도 unmocked 반례를 독립 테스트에 추가했다.

독립 반례를 확장한 합동 실행에서는 두 legacy 파일117개가 전부 통과했고, 당시 독립39개 중38개가 통과했다. 남은1개는 **plan에 source_diversity_policy=None을 명시하면 main helper가 legacy 미명시와 동일 취급하는 경계**다. renderer는 명시 null을 거절하므로 root에게 main에서도 필드 누락과 명시 null을 구별하도록 전달했다. 최신 테스트 파일은 unmocked 신규 기본값 반례를 추가하여40개이며, 이 문단 시점에는 root null 수정 후 재실행을 기다린다. 이전35pass를 최신40전체 통과로 바꾸어 쓰지 않는다.


## 최신 독립 실행: 43 passed

root의 명시 null fail-closed 보완 후 독립43개가 전부 통과했다(0.15초). unmocked 신규 store 기본값 검사는 `automation.protocol=2`의 실제 init_run 진입점을 사용하도록 고쳤다. prepare=False만으로는 자동 run이 생기지 않는 기존 동작을 테스트가 잘못 가정했던1건이며 production 수정 사유가 아니었다.

추가 visual_cuts 반례는 원래1대사 beat를 유지한 채5원본 실제컷이면5원본/150본문프레임으로 통과하고, 반대로 자막 beat5개에 다른 부모 라벨이 있어도 실제 visual_cuts가1원본이면1/5로 실패함을 확인한다. caption/beat 개수로 본문 원본 수를 대신할 수 없다. 이 실행에도 실제 모델·외부 검색·디코드·렌더는 없다.

수집 agent의 새 `current_search_rows`가 current run+reference SHA+normalized product+원문 text SHA에 결속하고, 실제 submitted/matched results 또는 no_results만 count하며 플랫폼/공백 중복을 합치는 것을 직접 읽었다. 추가 지적했던 state_with_search_audit의 old scope 덮기는 소유권이 검증된 현재 manifest/명시 현재 binding에서만 신규 태그를 붙이도록 담당 agent가 수정했다. 과거에 명시된 다른 run/scope와 부분 태그는 보존한다는 후속 보고를 받았다. 완성 목표를 위해 root의 실제 recovery/새 제작 검증은 계속 진행 중이다.

## 15:31 KST 실제 화면 컷 후속 경계

실제 child visual cut의 철회 구간을 `source_review_withdrawals.validate_plan`이 차단하는 반례가 통과했다. 자동 세로 크롭 보호도 child 자신의 소스에 적용한다. 원 자막/SFX의 `emphasis=2`는 유지하고 화면 확대만 `visual_emphasis=0`으로 분리하며, 명시 사용자 crop override는 유지하는 반례를 확인했다.

native proof는 모든 보조 컷에 같은 직접 증거를 강제하지 않는다. 두 번째 실제 컷이 검토한 product_support 프레임을 유지하면 전체 해당 대사 요구를 충족한다. 첫 구현에서는 anchor가 첫 번째 비증거 컷을 불필요하게 그 구간으로 이동해 추가 원본 재사용 충돌로 실패했다. 독립 테스트로 재현했고 root가 이미 증거를 가진 실제 컷을 먼저 선택하도록 수정한 뒤 통과했다. 반대로 parent beat의 mirror 선택만 증거를 갖고 실제 child들이 잃으면 validator는 거절한다. 승인된 범위 안에서 실제 컷을 이동해 증거를 복원하는 정상 anchor 경로는 허용한다.

QA 입력의 visual_cuts별 사용 제한 전달과 cuts 시 부모/group cache 우회 방지도 직접 읽었다. `approved_voice_scenes`의 기존 한 shot 빠른 재사용은 과거 visual_cuts를 첫 mirror로 축소할 수 있어 지적했고, 현재 old.visual_cuts가 있으면 정상 분석 경로로 보내는 코드와 독립 반례가 반영됐다.

추가 재순위 실패 후 실제 보완은 `handle_source_diversity_gap` → active 유지/수집 → 실제 관련 승인 소재 증가 확인 → run source_ids 갱신/새 generation 편집 키로 연결 중이다. 첫 inventory_signature는 검토 reason/reviewed_at만 바뀌어도 새 시도로 인정할 수 있어 독립 반례가 실패했다. root/수집 agent가 실제 원본·승인 사용 구간 증가만 인정하도록 보완 중이다. 이 수정 완료 전의 50/51 결과를 최종 전체 통과로 표시하지 않는다. 새 구간 반례는 실제 source duration4초 안에서 승인 끝2→3초로 확장하는 유효 증가를 사용한다.

본 검수자가 실행한 main 회귀: `test_daily_quality.py`, `test_studio_workflow.py`, `test_quality_progress_independent.py`, `test_scene_requirement_proof_modes_independent.py`, `test_scene_requirement_intervals.py` 합동 **177 passed (12.19s)**. duplicate review/source completion 테스트는 해당 함수의 state/source_state에만 explicit v4를 넣어 저장 legacy 작업의 idempotency 검증 의도를 보존했다. assertion과 production 완료 조건은 완화하지 않았다. 독립 최소5 테스트는 현재52개이며 signature 수정 중 세대가 섞인 중간 실행은 최종 결과에서 제외한다.

AGENTS와 단계별 개선 계획의 최종 본문5원본 의무를 최신 파일에서 재확인했다. 새 `SOURCE_DIVERSITY_IMPLEMENTATION_RESULT_20261018.md`도 코드 반영과 아직 미적용 운영/실제 신규 완성 검증을 구분하고 있다. 현재 격리 테스트 통과는 영어5·중국어5 실제 신규 검색, 새 원본 수신·검토, 최종 MP4의 실제5원본/최종 QA/GUI 재생 증거를 대신하지 않는다.

## 15:33 KST 수정 후 재확인

`inventory_material`/`new_inventory_material` 실제 코드가 hash 검증된 관련 소스의 사용 가능한 승인 구간을 정규화하고 reason/reviewed_at/ID/중복 record를 진전에서 제외하는 것을 읽었다. 단순 감소는 새 소재로 보지 않으며, 이미 알려진 부모의 파생 파일은 실제 원본 좌표상의 승인 구간 증가가 있어야 한다. resolve는 실제 증가와 수집 준비를 모두 확인한 뒤 gap을 해제한다.

최신 실행: 독립 최소5 테스트 **52 passed**, 기존 approved/reviewed scene 테스트18개와 합동 **70 passed (0.67s)**. 이전 signature 실패는 수정 후 통과했으며 중간 세대 실행의 ImportError는 최종 결과에 남아 있지 않다. 위의 별도177개 회귀와 겹치는 검사를 전체 고유 검사 수로 합산하지 않는다. 현 코드의 공통 최소5 경계에서 추가 치명적 blocker를 확인하지 못했지만, 실제 외부 검색·새 원본 확보·새 완성본 검증은 아직 수행되지 않았으므로 제작 성공 판정은 보류한다.

## 15:32 KST 실제 신규 패딩 run 감시 시작

대상 task `work-d82634dd9a064151`, run `run-e6c381d094f841e5`. root의 정상 make-video API 요청과 deployment-2 적재 영수증을 읽었고, 본 검수자는 DB를 `mode=ro`로만 열었다. production 코드·DB·프로세스·브라우저 조작은 없다. 독립 raw는 `data/source-diversity-20261018/independent-watch/latest.json`에 저장했다.

첫 관측: 새 run/state 정책은 v5이며 기존 승인 대본·음성 ID를 유지한다. 실제 검토된 관련 부모는 기존12개지만 현재 run의 영어/중국어 검색은 각각0/5다. 새 기준 검색이 끝났다고 표시하지 않았다. baseline-hashes의 기존23개 파일은 실제 SHA가 전부 일치했다.

발견한 운영 진입 오류: make-video event 이후 새 job이0개이고, source_wait message만0/5로 바뀐 반면 저장 source_goal은 옛 policy3/readytrue였다. active=true/paused=false/hold없음/failed collect없음을 읽어 확인했다. 정적으로 advance_workflow가 새 source_wait를 쓰기 전에 ensure_source_collection을 호출하고, ensure는 옛 status completed이면 반환하므로 과거 완성 task의 첫 새 run에서 수집 큐가 빠질 수 있음을 root에 즉시 전달했다. 아직 모델·브라우저 서비스 대기나 실제 검색 실패가 아니라 수집 job이 등록되기 전의 경계다. root의 정상 경로 보완 전 이 상태를 실제 제작 진전으로 세지 않는다.

15:35 KST 후속 관측: `collect_sources/job-b6ccc154408a4e54`가 신규 등록·claim되어 local interval recovery 영수증을 생성하기 시작했고 source_goal도 v5로 갱신됐다. 초기 queue0 상태는 이후 정상 경로에서 해소됐다. 아직 현재 run 검색 영수증이0이므로 로컬 실제 구간 검토를 외부 검색 완료로 세지 않는다.

15:36 KST 보존 확인: task와 새 collect job은 root의 agent 배포를 위한 일시 pause 상태로 바뀌었다. 사용자가 제작을 중지한 것이 아니며, 이 배포 pause를 콘텐츠 실패나 새 검색 시도로 세지 않는다. 읽기 전용 `independent-watch/audit.py`로 기존23파일의 실제 SHA 및 baseline scripts/voices/edits/runs 모든 필드를 대조했으며 전부 동일했다. actual current 영어0·중국어0, 신규 edit0이다. 이후15:36:41 정상 resume 영수증을 확인했고 같은 job의 감사를 이어갔다.

## 15:38 KST 준비 재사용 및 실제 검색 진전

root의 deployment-4/PID38212와15:36:41 resume 영수증 후 같은 collect job이 진행 중이다. 새 preparation bundle은10/15의 reference.mp4·12frame·contact sheet를 그대로 참조한다.14파일 SHA가 모두 영수증과 일치하고 mtime도10/15 그대로다. 기존 전사 speech/screen_text를 재사용하며 query plan만 새로 만든 증거를 확인했다. `independent-watch/preparation-reuse.json`에 기록했다.

새 query_details에 caption의 “저장해 두고”(게시물 북마크)를 제품 보관 동작으로 오해한 storage/保存方法 후보2개가 있어 root에 알렸다. 실제 worker는 우선 관련 제품 명사구를 검색했고, 현재 영어1·중국어1에 submitted+input/URLmatching+results 영수증을 관측했다. 두 번째 영어 검색 started는 아직 완료로 세지 않는다. manifest/state 수용 전0과 worker 실제 관측1+1을 구분한다.30초 요청 pacing은 정상 대기이며 콘텐츠 실패가 아니다.

## 15:40 KST 실제 실행에서 확인한 검색 풀 축소

새 준비 query_plan에는 search_minimums en5/zh5와 다수 관련 후보가 있지만, 실제 `round_queries(query_plan,strategy)` 후 planned manifest의 queries는 ko2/en2/zh1 총5개뿐이었다. TikTok 전용 pool도 같은5개다. 실제 worker는 영어2·중국어1을 끝낸 뒤 yandex-images로 이동했다. Browser minimums 전달 자체가 누락된 것은 아니며, 상위 visual_product 전략이 실행 후보를 줄이는 경계다.

이 한 round만으로5+5를 충족할 수 없고, 후속 넓은 전략까지 기다리며 불필요 이미지 검색/다회 수집이 생길 수 있어 root와 수집 담당에게 즉시 전달했다. 격리 단위 테스트의 minimums 우선 선택 통과가 실제 query_plan→round전략→provider 경로의 충분한 후보 전달을 보장하지 않는 사례다. 현재 확보된 원본 수12개나 일부 실제 검색 결과를5+5 완료로 바꾸어 보고하지 않는다.

15:40 KST root 배포 일시 pause 확인: 위 실행 풀 축소 보완을 위해 root가 정상 pause 후 담당 agent의 visual/finder/planner 수정·검증을 진행한다. 사용자가 제작을 취소한 것이 아니다. 이미 실행된 영어2·중국어1 valid 영수증은 `independent-watch/before-effective-query-pool-fix.json`으로 보존했다. 별도 브라우저·모델·소스 조작은 하지 않았으며 재개 신호 전 DB 반복 조회를 멈췄다.

## 15:46 KST 보류 다운로드 회귀 fixture 보강

root의 명시 위임으로 `tests/test_deferred_download_review.py`의7실패를 재현했다. 모두 정상 overlay mock에 exact intervals/frame_ids/frame_id/실제 sample-file SHA가 없어 실제 accepted_interval_frames의 binding 검사를 통과하지 못했다. production 결함으로 보이는 실패는 없었으며 해당 positive mock에만 source_sha256·0–4초 interval·frame ID·실제 임시 이미지 SHA를 결속했다. accepted_interval_frames 자체는 mock하지 않았고 기존 assertion·실패/사용자 제외/대기 재개 검증은 그대로다. legacy 계약 변경은 필요하지 않았다.

해당 파일13개 통과(0.93초), source_overlay_explicit_scope의 실제 범위/중복 frame/변조 거절 반례를 포함해 합동30개 통과(5.09초). production 코드·runtime DB·브라우저·모델을 조작하지 않았으며 배포 대기 중 운영 반복 조회도 재개하지 않았다.


## 15:51 KST effective approved pool 보완 후 독립 검수

실제 새 테스트 파일명은 `tests/test_source_visual_query_minima_v5.py`다. 이 파일과 legacy visual/preparation reuse/acquisition v5/deferred download를 합동 실행해 **75 passed (2.94s)**를 확인했다. production 소스는 변경하지 않았다.

직접 읽은 새 계약은 v5 별도 visual cache와 독립 승인, legacy9개 상한/영수증 불변, 독립 승인된 최종 영어·중국어 명사의 실제 개수, 전략/플랫폼 전송에서 같은 명사 pool 보존이다. 게시물 북마크 CTA를 제품 보관 동작으로 바꾸는 경로도 반례가 통과했다. 승인 반려 소재를 수량 채우기로 되살리지 않는다.

search-only는 caller boolean만으로 켤 수 없다. 실제 TaskBatchReviewer와 현재 run/scope, 일반 collect, 수동 요청/quality repair/필수 scene/unresolved scene/diversity gap 없음, 실제0received batch의 기존 관련원본·핵심 goal 근거가 필요하다. 반례는 부족 재고·caller boolean·수동 요청·quality repair·다른 scope·미해결 scene에서 정상 다운로드 경로가 유지됨을 확인했다. 실제 worker 함수 격리 반례는 기존 영어2·중국어1 영수증을 바꾸지 않고 부족 영어3·중국어4만 추가한다. 이 검사는 외부 검색 성공을 모사한 unit test이며 실제 재개 후 영수증 감사를 대신하지 않는다. 재개 신호 전 운영 DB 반복 조회는 수행하지 않았다.


## 15:54 KST 새 명사 풀 실제 생성·다음 회차 검색

deployment-5/PID31296의 정상 resume 뒤 같은 run/job이 진행했다. 새 독립 visual receipt `2cfe3f46db4acba7ed6905450cd06171dceca9671d095f86545211b53ee2a56e`는 영어6·중국어6을 승인했다. planned dispatch는 이12개와ko2 총14개이며 생성 수와 실제 검색 수를 분리한다.

새 계약 첫 회차의 access preflight는 옛 풀로 TikTok을 scope소진 판정한 ready_routes를 새 풀에도 적용해 추가 검색0으로 끝났다. batch.ready=false/검색2·1을 유지했고 다운로드0이었다. 즉시 root에 보고한 후 다음 collect job `job-2c8f6c2c8ec84dbb`의 preflight가 새 풀을 읽어 TikTokready로 복구됐음을 추가 확인했다. 이 시점 무한 반복 증거는 없으며 첫1회 불필요 회차와 후속 자동 회복을 구분한다.

다음 manifest `Dec8wlLhu9N-1792306411979802900`에서 실제 새로운 영어1·중국어1 submitted/matching/results가 관측됐고 다음 영어는 started다. 기존 수용2·1과 합치면 관측3·2이나 새 회차 manifest/state 수용 전이므로 최종5·5 완료로 표시하지 않는다. 기존23파일 및 과거 scripts/voices/edits/runs 전필드는 최신 snapshot에서 모두 보존됐다.


## 15:58 KST 실제5+5 수용 및 편집 진입

현재 run에 결속된 actual_search_coverage가 영어5·중국어5 모두 ready다. 각10건은 submitted+matching input/URL+results 영수증으로 확인했다. 기존2·1을 보존하고 새로운3·4를 추가했다. 관련 검토 부모12·핵심8개를 유지했고 새 manifest의 batch.ready=true, probe_attempts=0, downloaded_file 없음, budget_stop=search_receipts_only_existing_reviewed_inventory를 확인했다. 새 소스12개를 다시 다운로드했다는 뜻이 아니라 기존 검토 재고를 활용한 검색 보완 성공이다.

collect job2개가 끝나고 새 edit `job-3c491c9dc5184905`가 실행됐다. 같은 승인 script-112f53277b5c466e/voice-run-f40858ef18e84c0d를 쓰며 신규 TTS는0이다. 기존23파일 실제SHA와 scripts/voices/edits/runs 모든 과거필드는 계속 동일하다. analyze-request/result와 analysis-plan이 생성됐으며 아직 최종 MP4·본문5·최종 QA 통과는 별도 대기다.


## 16:05 KST 실제 동결 선택6원본

`freeze-selection-result.json`의 min5 정책과 selection_frozen을 확인했다. 원래 대사16개를 유지하며 visual_cuts 추가 없이6부모 원본이 선택됐고 표지 첫 프레임을 뺀494본문프레임이다. 부모별 본문 분량은2.30/0.667/3.933/3.467/4.00/2.10초, 최대 점유율24.29%다. 선택된 실제6파일 SHA가 모두 source 기록과 일치하고 retiming 필드도 모두 없다. `independent-watch/selection-audit.json`에 보존했다. 이것은 동결 선택 증거이며 아직 최종 actualclip/MP4/QA 통과 선언은 아니다.

표지 후보27개가 생성되고 별도 cover-selection 기록이 생겼다. 장면 분석은 서로 다른 payload SHA의 actual-frame 묶음6건과 배치 판단1건으로 진행됐으며 동일 입력 반복 증거를 찾지 못했다. 정상 모델·표지 준비 시간을 콘텐츠 실패로 세지 않는다.


## 16:08 KST 최종 독립 감사: 통과

대상 `work-d82634dd9a064151/run-e6c381d094f841e5`, 새 edit `job-3c491c9dc5184905`, 새 QA `job-2fa5c459872f4449`가 정상 완료됐다. DB는 mode=ro로만 읽었고 이 감사의 ffprobe/ffmpeg는 기존 파일 검사·null decode만 수행했다.

- 실제 검색: 현재 run/reference/product/text scope의 영어5·중국어5, 전부 submitted/matching/results 영수증. 재시도나 플랫폼 중복으로 채우지 않았다.
- 최종 본문: 서로 다른 실제 원본6개, 표지 첫1프레임을 뺀494본문프레임. 입력 수·shot 수·표지 전용 사용으로 수를 채우지 않았다. 실제6원본파일 SHA가 plan/선택/clip 영수증과 일치한다.
- 완성 MP4:1080×1920,30fps,495프레임,16.5초. 전체 video/audio decode 통과.16개 actualclip 모두 원본 구간 길이=출력 프레임수/30, 실제 clip count 일치, 선택 shot/SHA/window 결속. 감속·freeze/tpad 충당 증거 없이 정상 속도 span이다.
- 승인 대본·음성: 기존 script/voice ID·대본 본문·원본 음성 SHA·voice_source/pause_processing 원본 결속·처리 음성 SHA 일치. 신규 TTS0·신규 edit1·신규 QA1이다.
- 최종 QA:3groups passed, issues/advisories 없음.48실제 검수 프레임 SHA가 모두 일치하고 QA의 render/plan SHA와 원본6개 집계가 최종 파일에 결속됐다. export quality_verified=true이며 전체 active jobs0이다.
- 기존 자료: baseline23개 실제 파일 SHA와 과거 scripts/voices/edits/runs의 모든 필드가 그대로다. 새 run/편집/검수 이력만 추가됐다.

독립 출력 감사85개 검사 모두 통과, 실패0. `independent-watch/job-3c491c9dc5184905-output-audit.json`과 `latest.json`에 원시 증거를 보존했다. 첫 scratch 검사는 실제 clip 계약의 selected_source_window를 source_start/end 필드로 잘못 가정해 경고했으나 실제 renderer 코드/영수증과 대조해 감사 스크립트만 바로잡았다. production/영수증·검사 목표를 바꾼 것은 아니다.

최종 preview SHA는 `6035e89e0be6cbdcfad5cfc0d99ffd987d05416526f648bacb9e5fcec51ed453`, plan SHA는 `13246d342274c0a1066b00952f6ce9af0b44fddc0777266866b2f6dd01d31e9c`다. whole-video-overview의 실제 표본을 직접 확인해 제품/착용/관련 맥락 흐름을 확인했다. 이는 전체 재생/음성 청감을 대신하지 않는다. QA는 audio_listened=false, auditory_naturalness_reviewed=false, full_motion_review_complete=false를 명시하므로 파형/해시 일치만으로 청감·모든 움직임 검토 완료를 주장하지 않는다. root의 GUI 재생은 별도 근거다.

시각은 모두KST, created→updated 큐 포함 wall이다. 첫 collect15:34:45→15:52:59는18분14.442초(배포 일시 pause/새 모델 준비/no-op 포함), 후속 search-only15:52:59→15:56:58는3분59.069초, edit15:56:58→16:05:08는8분10.588초, QA16:05:08→16:05:56는47.628초다. edit 큐 생성→QA 끝은8분58.155초이며, 최초 요청→root 검증은33분58.376초로 수정·배포 중지를 포함한다. 이를 순수 모델/검색 처리시간으로 해석하지 않는다.


18:18 KST 호출 수 정정: 앞선32shot 제작의 OBSERVE5건 표기는 조회 cutoff1792306650보다 먼저 생성된 첫 job codex7b45524775adde215f36ea86e5536eec를 놓친 집계였다. 실제32shot은6개 OBSERVE batch다. 이후 제외 재제작에서 현재 payload를 오프라인으로 재구성하고 전체 writing job을 대조해 확인했으며, 위 문구를6으로 바로잡았다. 이 정정은 영상/정책/QA 결과 변경이 아니다.
