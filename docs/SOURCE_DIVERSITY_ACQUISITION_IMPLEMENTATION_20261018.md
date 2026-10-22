# 2026-10-18 신규 v5 수집 최소 조건 구현

명시적인 새 외부소스 task/run은 영어 고유 검색 5개, 중국어 고유 검색 5개를 실제 수행하고 관련 검토 원본 5개와 핵심 제품 원본 1개를 확보해야 수집 준비가 된다. 본문 원본 5개 사용 검사는 별도 `source_diversity.py` 및 편집·렌더·QA 소유 변경과 연결한다. 저장된 v4/run/완성본은 읽기나 재시작으로 v5로 바꾸지 않는다. 기존 정상 속도 연장·관련 맥락·특장점 반복 기준은 유지한다.

## 수집 계약과 근거

- `hotpost/source_policy.py:17`: 새 montage policy v5, `source_diversity_policy.version=minimum-five-sources-v1`, 최소 부모 5, 핵심 부모 1, `search_minimums={en:5, zh:5}`. 저장 정책의 `run_policy`/`adopt_policy` 보존 동작 유지.
- `hotpost/source_coverage.py:38`: 실제 `results` 또는 `no_results`이며 명시적인 submitted·URL/input match·consumed 영수증이 있어야 산입한다. 예전 상태명만 있는 결과, 계획, 미시도, CAPTCHA, 로그인, 제한 쿼리는 충족 증거가 아니다. 0건 결과는 정상 수행으로 인정한다.
- `hotpost/source_coverage.py:57`: 현 run ID와 reference SHA·정규화 제품·원문 SHA가 모두 같은 검색 이력만 현 실적이다. 플랫폼 재제출·재시도·공백·index operator만 다른 입력은 새 고유 검색어가 아니다.
- `hotpost/source_coverage.py:15`: 실제 파일 SHA와 선언된 원본 SHA의 alias union으로 같은 파일의 여러 레코드·잘린 파생·잘못된 시간 매핑을 중복 부모로 세지 않는다. 같은 실제 SHA에 서로 다른 원본 SHA를 붙여도 하나다.
- `hotpost/source_coverage.py:87`: 실제 파일 SHA 일치, 편집 적합성, 검토된 양수 구간, 파일 SHA에 묶인 관찰·프레임 근거, 핵심 기능 일치 또는 용도 제한이 있는 관련 맥락 검토가 있어야 관련 소스로 인정한다. 단순 링크·미검토·거부·변조 파일은 제외한다.
- `hotpost/source_coverage.py:101`: 부모 5·핵심 1·en5·zh5를 독립 검사한다. 정상 속도 반복으로 고유 분량이 권장량보다 작아도 허용하지만, 새 최소 확보 수는 낮추지 않는다.

## 검색 실행 및 캐시

`source_planning.cached_enrich_plan(..., acquisition_policy=policy)`는 v5 계약을 별도 cache identity에 넣는다. 근거 있는 영어·중국어 각 5개를 생성하도록 요청하고 누락 언어는 같은 근거로 한 번만 보완한다. 근거 없는 색·소재·특징을 숫자 맞추기용으로 만들지 않는다. 근거가 부족하면 부족 상태를 기록하며 같은 증거의 검색어를 무한 재생성하지 않는다. 기존 준비 bundle과 query-policy 전역값은 보존한다.

`platform_queries`는 새 정책에서 영어·중국어를 우선 교차 배치한다. 중국어 전용 플랫폼에는 중국어만 전달한다. TikTok의 짧은 검토된 제품 명사구 제한은 유지하며, 다른 플랫폼은 동일하게 검증된 중심 제품 명사와 근거 있는 세부 범위를 사용한다. 필요한 수의 지원 쿼리가 없으면 부족으로 남는다.

`source_search/discovery.py:36`은 보관 후보가 12개 있어도 실제 en5·zh5가 부족하면 브라우저 수집을 건너뛰지 않는다. `browser_search.py`/`source_browser_worker.py`/`youtube_search.py`에 minima를 전달하고 후보 cap 또는 첫 언어 후보만으로 조기 종료하지 않는다. 실제 접근벽·판독 실패·cooldown 중지는 그대로 유지한다. 새 YouTube 입력은 Enter 직후 제출 기록과 실제 입력·URL 일치 확인을 분리해서 남긴다.

## 배치·새 원본 복구·중단 복구

`source_batches.state_with_search_audit`는 현재 소유권이 확인된 callback의 신규 manifest 또는 명시적으로 현재 run/scope에 묶인 manifest 검색을 임시 state에 합친다. 명시된 과거 run/scope·부분 태그는 덮어쓰지 않는다. manifest 자체가 현재 범위와 충돌하면 소유 callback이어도 과거 실적을 새 실행으로 승격하지 않는다.

본문 배치가 실패하고 root의 실제 inventory signature 검사가 새 원본을 요구하면, runtime policy 복사에만 `acquisition_parent_target=baseline_parent_count+1`을 넣는다. 수집 준비 목표는 `max(5, 본문 최소 부모 수, runtime 수집 목표)`다. BatchReviewer도 이 임시 목표를 사용한다. 저장된 본문 최소 5와 기존 run 정책은 바꾸지 않는다.

후속 독립 복구 검증에서 단순 signature 변경만으로 gap을 해제하면 미검토·무관 소스, 검토 이유/시각, 중복 레코드, 삭제/수동 거절도 새 편집을 만들 수 있음을 재현했다. 이를 보정하여 `source_diversity.inventory_material(state)`는 실제 SHA가 맞는 관련 승인 파일의 파일SHA/부모SHA/검토 구간/검증된 부모 구간만 정규화한다. lifecycle gap에는 `baseline_material`을 보존하며, 명시 `resolve_diversity_recovery`가 기준 대비 새 관련 부모 또는 실제 승인 구간 증가와 현 재고 준비를 모두 확인해야 해제한다. 같은 파일의 새 ID·같은 부모의 이미 포함된 파생 구간은 진전이 아니다. 삭제·축소·거절·변조·미검토·무관·메타 변경만으로 해제하지 않는다. 기준 material이 없는 과거 또는 불완전한 영수증은 증가를 추정하지 않는다. gap이 있는 동안 `source_goal.ready=False`와 runtime 추가 부모 목표는 서명 차이와 무관하게 유지된다.

`tests/test_source_diversity_completion_recovery.py` 16개는 임시 실제 StudioStore에서 최초 edit claim→no-render gap→자동 active 유지→정상 collect enqueue→신규 관련 승인 부모 수용→gap/history 해제→현재 source_ids 갱신→새 `source-diversity:1` edit key를 확인한다. 같은 입력 재시도와 12종 비진전 변경은 실제 workflow에 새 edit를 만들지 않는다. 같은 부모의 새 승인 프레임 증가, 이미 포함된 파생 구간, 옛/불완전 baseline도 분리 검증한다.

`source_search.strategy.merge_history`는 run ID와 search context를 보존하고 별도 ledger key로 유지한다. `restore_history`는 명시적인 round/manifest 결속이 있어야 untagged 행을 복구하며 두 결속이 충돌하면 현 실적으로 태그하지 않는다.

`studio_runtime/generation.py`의 refresh 경로는 현재 run 정책·scope 및 현재 범위의 previous_searches를 전달한다. v5의 저장된 재수집 결과 재개 key에도 run/scope/policy를 묶어 제품이나 실행이 바뀐 결과를 재사용하지 않는다. legacy resume key는 유지한다. 대기 후 이미 수신한 결과의 시각 검토를 재개하며 외부 요청을 자동 반복하지 않는다.

`source_finder.py`는 초기·중간·최종 manifest와 현재 query plan, 실제 search audit에 run/scope를 보존한다. `source_pause_receipts.py`는 v5 task/job/run/reference/policy/scope에 묶인 descriptor와 manifest·등록 worker checkpoint의 SHA를 확인한 뒤 신규 행만 태그한다. 명시된 옛 행은 보존하되 현 실적에서는 제외한다. manifest scope가 descriptor와 다르면 확인 대기로 멈춘다. 기존 영수증·원본 파일은 수정하지 않는다.

## 격리 검증

외부 검색·브라우저·모델·운영 DB·운영 프로세스 실행은 하지 않았다. pytest 임시 파일, 가짜 입력·provider·모델 응답을 사용했다.

- 최초 관련 acquisition 170개 통과.
- 추가 준비 재사용·probe·worker·접근 중지 회귀 97개 통과.
- 최신 scope·중단 복구·refresh·배치·query cache·strategy 관련 88개 통과(2.82초).
- 확장 회귀 297개 중 290개 통과, 7개 실패(25.51초). 7개는 모두 `tests/test_deferred_download_review.py`의 기존 overlay fixture가 새 `accepted_interval_frames`의 source SHA/interval 영수증 계약을 충족하지 않아 `source_overlay_review.py:214`에서 실패했다. 수집 quota/scope 검사의 실패가 아니며 root에 별도로 전달했다. 이 보고서에서 전체 회귀 통과로 주장하지 않는다.
- 변경 acquisition 모듈 `py_compile` 통과.
- 후속 복구 보강 후 독립 completion-recovery/acquisition/최소본문/inventory/quota/batch/refresh-commit/pause/resume 관련 166개 통과(4.40초).

새 `tests/test_source_diversity_acquisition_v5.py`는 실제/no-result 영수증, 옛 결과명 배제, 플랫폼/공백 중복, run·제품·원문 변경, 5개 독립 부모와 1개 핵심, 같은 실제 SHA 위장 부모, 변조/미검토/사용 거부, v4 보존, runtime 추가 부모 목표, 보관 후보 조기종료 방지, en/zh 실행 우선, 별도 query cache, 중단 scope 복구, refresh scope 전달, manifest 초기 결속, merge/restore 충돌을 검사한다.

실제 현재 플랫폼 세션에서 영어5·중국어5 수행과 관련 원본5 확보에 성공했다는 주장은 이 코드 검증에 포함되지 않는다. 접근 가능 경로와 근거 있는 쿼리 풀이 부족하면 준비가 아닌 부족·대기 상태로 남아야 한다.

## 실제 신규 패딩 run 읽기 전용 감시

root가 운영 적용 및 신규 실행을 승인한 뒤 감시 범위만 추가했다. 서버 PID 40312, task `work-d82634dd9a064151`, run `run-e6c381d094f841e5`, 시작 `2026-10-18 15:32:17.768 KST`; 원본 시작 영수증 `data/source-diversity-20261018/production-start.json`과 baseline 자료를 보존했다. 이 감시자는 코드·DB·프로세스·브라우저를 수정하지 않으며 SQLite URI `mode=ro`와 `PRAGMA query_only=ON`으로 관찰한다.

- 15:33:20.922 KST: 새 run에 v5/minimum-five 계약이 저장되어 있고, 현재 코드로 계산한 수집 목표는 관련 승인 원본 12/5·core=True·영어 실제0/5·중국어 실제0/5·ready=False였다. 과거 검색 이력11개는 새 scope 실적으로 승격되지 않았다. 제품 scope는 `몽벨 패딩`, reference SHA `29dbac492f15ebc3e092f89f0aaf27af694ae8b2c8a6d0174d96551ab45f80e4`, 원문 SHA `176fc6ed9d33d65688d58fbcc2b0329dc4acf68fa34da3f6d7c6759b52a9627f`다.
- 동일 시점: 신규 collect/queued/running job이 없고 과거 `collect:run-f40858ef18e84c0d:0` done만 있었다. state는 active=True/source_wait지만 저장된 `source_goal`·`source_search`는 과거 v3 ready/done 값이었다. 시작 약63초의 이 관측을 즉시 root에 전달했다. 기존 completed state에서 첫 ensure_source_collection이 완료 guard에 걸린 뒤 workflow가 source_wait로 바뀌었을 가능성은 **추정**이며, 수집 실패나 모델 실패로 단정하지 않았다. 이 시점 실제 검색 제출·새 파일 수신·동일 모델 반복의 증거는 없다.
- root가 원인을 확인하여 `ensure_source_collection`의 완료 guard를 “task completed이며 선택 run도 없거나 completed인 경우”로 한정했다. 따라서 새 running run은 첫 tick의 옛 task.status가 completed여도 정상 수집 큐를 만든다. root가 새 서버 세대 적용 후 같은 run을 정상 `resume-auto`로 재개하기로 했으며 이 감시자는 운영 조작을 하지 않았다.
- 독립 경계 회귀 `test_completed_task_new_running_v5_run_queues_collection_before_workflow_updates_task_status`를 추가했다. 임시 실제 StudioStore에서 완료 task/완료 v4run→새 running v5run→collector enqueue, en/zh0 ready=False, 기존 관련 재고 재사용, 옛 run·sources 불변을 확인했다. 해당 신규파일은 이제 17개이며 관련 집중 회귀 121개 통과(2.67초). 이 후속 단계는 테스트·문서만 수정했다.
- 같은 run 정상 재개 후 collect job `job-b6ccc154408a4e54`가 생성되었다(15:34:45.342 KST). 15:35:39.798 KST 읽기 관측에서 running, en0/zh0, `source_attempts` 없음, `interval_recovery` checkpoint만 있었다. 기존 source `693d0f20521ca7793fca4ef10ca790f5991150cc47b83a0b763d423ab70b8be2`에 대한 proposal은 15:34:51.199에 시작해 결과 JSON이 생겼고, `scope-dc8d0c9f9067bf9b8a64.json`은 15:35:07.442에 started 상태였다. 관련 원본12·핵심 충분이고 실제 검색 영수증만 부족한 상태에서 local interval 추가 검토가 실행된 **불필요 검토 경계**다. 동일 입력의 모델 재호출이 반복되었다고 단정한 것은 아니며 첫 local rescue 경로 자체가 검색 최소치를 해결하지 못한다는 의미다.
- root가 local recovery 진입에서 `source_diversity_ready && core_ready && !source_diversity_gap`이면 건너뛰는 조건을 추가했다. 독립 테스트는 검색만 부족할 때 recovery 모델/체크포인트를 만들지 않는지, 실제 재고 부족과 검증된 배치 gap은 기존 local review 경로를 유지하는지 분리 검증했다. recovery 신규파일 총20개 통과(2.16초). 운영 조작과 소스 수정은 root가 담당하며 이 감시자는 테스트·기록만 변경했다.
- deployment-4 정상 재개 뒤 같은 collector가 `Dec8wlLhu9N-1792305405533948000/manifest.json`을 생성했다. 15:38:21.952 KST 관측에서 preparation을 지나 planned와 browser checkpoint가 있었다. 새 v5 준비 bundle `source-preparations/Dec8wlLhu9N/237a8c13ea91f70f7f154560-c460461d-acq-7e3f49da98.json`은 옛 `Dec8wlLhu9N-1792016655218112400/reference.mp4`, 12개 프레임, sheet를 재사용하며 14/14 파일 SHA가 맞았다. 정규화 전사 SHA `150fcd0fa72df3a69868e403ed6c20bc4ddc96e1c2072437362d4558d37958d7`도 옛v2/media-only bundle과 같고, 신규 source-job 폴더에 reference.mp4/reference_frames가 없었다. **v5 쿼리 재계획이 기준 영상·프레임·전사를 전체 재생성했다는 증거는 없다.**
- 같은 관측의 실제 worker 영수증은 TikTok `Montbell stand collar puffer jacket` results 1건(submitted/matched=True, 입력값 일치), 중국어 `Montbell 横向绗缝 夹克`는 started/submitted=False였다. 따라서 관찰된 실제 실적은 영어1·중국어0이고, started 행을 완료 실적으로 세지 않는다. state acquisition은 아직 batch 수용 전이므로 en0/zh0였으며 worker의 실제 진전과 분리한다.
- 새로운 의미/효율 경계: v5 enriched plan의 `minimum_query_plan`은 en11/zh11이지만 최종 `round_queries`는 영어2·중국어1·한국어2뿐이었다. 검증된 시각 query 전체 문자열을 필수 head로 쓰는 substring 필터가 `Montbell padded jacket colors/fit/with sportswear` 등 근거 있는 다른 제품 명칭 행을 제거했다. 시각 제안 자체도 언어별2개이고 중국어 `Montbell 立领 棉服`는 충전재 추정이라는 정당한 독립 거절로 빠져 중국어1개만 남았다. 필터 전 숫자를 최종 수행 가능 pool 숫자로 오인하면5+5를 달성할 수 없으므로 root에 즉시 보고했다. 기존 거절을 강제로 승인하거나 같은 쿼리의 플랫폼·공백·조건만 바꿔 숫자를 채우지 않고, 실제 중심 제품·관찰 특징의 충분한 영어/중국어 계획을 검토하거나 부족 상태를 명시해야 한다. 이 단계에서 감시자는 소스·캐시·DB를 수정하지 않았다.

## 실제 관측 이후 승인된 effective-pool 보정

root가 위 경계를 확인해 서버를 정상 배포 pause하고 구현 권한을 다시 부여했다. **변경 전의 실제 영어2·중국어1 성공 기록과 옛 query/visual/preparation 영수증은 보존**한다. 이 단계의 코드·격리 테스트를 마친 뒤 production source 고정을 선언했으며, 배포·같은 job 재개는 root가 수행한다.

- `source_visual_queries.py`: 새 v5 시각 계약은 `sampled-product-search-v3-approved-language-minima`와 최소 언어 수를 실제 reference/frame/text evidence key에 결속한다. 기존 v2 캐시는 수정하지 않는다. 실제 관찰된 중심 제품의 서로 다른 짧은 명사를 영어·중국어 각5개 이상 제안하되 근거가 충분할 때만 각7개까지, 한국어는1~2개 보조로 제안한다. 기존9개 검토 상한은 legacy에 그대로 남고 새 계약은 총16개를 수용한다. 원문·실제 프레임을 받는 같은 독립 검토가 모든 문구를 검사한다. generic 패딩으로 棉服·羽绒服 충전재를 복원하지 않으며 관련 문자 근거도 요구한다. 거절로5개 미만이면 부족으로 남는다.
- `apply_visual_queries`와 v5 `round_queries`: 필터 전 모델 숫자는 `generated_query_pool`, 실제 독립 승인 명사 수·지문은 `effective_query_pool`로 구분한다. 최종 `minimum_query_plan_ready`는 승인된 고유 영어/중국어 명사 수로만 계산한다. v5는 이 명사 풀을 직접 전송하여 action 우선 분기나 raw/close-up suffix로 다시 줄이거나 숫자를 채우지 않는다. TikTok의 짧은 명사 규칙과 언어 우선순위는 유지한다.
- `source_finder.py`: 언어 최소 계약이 다른 옛 v5 준비 계획은 재사용하지 않고, 새 visual contract를 포함한 별도 bundle 경로를 만든다. 그 정확한 bundle이 있으면 우선 SHA 검증·재사용하여 generic legacy current 경로 때문에 새 계획을 다시 조립하지 않는다. 원본 영상·프레임·전사는 기존 검증 자료를 재사용한다.
- `source_search/planner.py`: caption의 “저장해두고/저장해두세요” 북마크 CTA가 물리 제품 보관 행동으로 바뀌지 않도록 한다. “용기에 넣어 저장” 등 실제 물리 저장 동작은 보존한다.
- search-only는 일반 자동 `collect_sources`의 검색 실적 부족에만 허용한다. 현재 run/scope, 정상 `TaskBatchReviewer`, 원본 SHA·관련성·편집 적합성을 계산한 실제 source goal, 초기0received callback을 요구한다. caller boolean·임의 callback만으로는 작동하지 않는다. 수동 추가 요청·품질 보완·미해결 scene requirements·레이아웃 gap·재고 부족은 이 경로에서 제외한다.
- `browser_search`/`youtube_search`/worker/strategy는 현재 run의 실제 성공 이력을 합쳐 언어별 부족분만 수행한다. 영어2·중국어1이면 추가 영어3·중국어4가 성공한 순간 후보 cap과 무관하게 멈추고 이미지 검색으로 숫자를 채우지 않는다. 같은 쿼리의 다른 플랫폼 제출·공백 변형도 새 쿼리로 쓰지 않는다. 완료0received callback이 현재 관련 재고·핵심 조건을 다시 확인하면 이미 충분한 재고를 위해 새 파일을 받지 않는다.

새 `tests/test_source_visual_query_minima_v5.py` 23개는 각7개 영어·중국어와 한국어2개 총16개 수용/실제 전송 limit10에서5+5 보존, legacy9·옛 영수증 불변, 새 bundle 우선 재사용과 미디어 재생성 없음, 거절·충전재 추정 복원 금지, 필터 후 부족 보고, 기존3쿼리 보존과 정확 추가3+4, 실제 임시 StudioStore/정상 TaskBatchReviewer0received, 수동/품질/미해결scene/scope불일치/임의callback 우회 차단을 검사한다. 모델·브라우저·다운로드는 격리 fake다.

**최종 넓힌 회귀: 425개 모두 통과(29.49초).** 앞서 실패했던 deferred-download overlay fixture7개는 담당 독립 검수자가 실제 SHA·프레임ID·구간 영수증을 테스트에 보강하여 이 최종 실행에 포함해 통과했다. 이 코드 검증은 실제 새 v3 시각 계획과 남은3+4 검색의 운영 성공을 대신하지 않는다. 해당 실제 결과는 같은 run 재개 후 별도로 기록한다.

### deployment-5 이후 읽기 관측

root가 서버 PID31296/68개 모듈을 확인하고 `effective-query-pool-resume.json`에 같은 run·collector 재개를 기록했다. 15:52:14.765 KST의 현재 run 실적은 기존 성공 영어2·중국어1 그대로였다. 새 attempt `Dec8wlLhu9N-1792306299763546500`은 구 계약 attempt를 덮어쓰지 않았다.

15:53:33~44 KST: 새 독립 검토에서 최종 전송 가능 명사가 영어6·중국어6으로 확보되었다. 이것은 **계획의 승인된 후보 수이며 실제 수행6/6이 아니다.** 예: 영어 `Montbell puffer jacket`, `Stand collar puffer jacket`, `Horizontal quilted jacket`, `Full zip puffer jacket`, `Zipper pocket puffer jacket`, `Hip length puffer jacket`; 중국어는 `Montbell 绗缝外套`, `立领 绗缝夹克`, `横向绗缝 夹克`, `全开襟拉链 绗缝夹克`, `拉链口袋 绗缝夹克`, `及胯 绗缝夹克`다. 棉服/羽绒服을 복원하지 않았다.

이 attempt의 `search_only=True`, batch0000/0001 모두0received, 현재 관련 부모12/5·핵심 부모8을 정상 goal로 확인했다. 새 원본 수신 파일은0개다. 다만 첫 attempt는 **새 계획 전 old preflight가 산출한 ready_routes**를 받아 텍스트 경로를 모두 “미사용 범위 없음”으로 건너뛰고 yandex-images만 남았다. search-only는 이미지가 영어·중국어 실제 검색을 대신할 수 없어 업로드하지 않았다. 결과적으로 해당 job은 추가 검색0·ready=False·실제2/1을 유지해 완료되었다. root에 추가 회차 비용을 보고했다.

정상 다음 collector `job-2c8f6c2c8ec84dbb`는 새 준비 계획을 읽고 TikTok `Montbell puffer jacket` 검색 입력으로 진입했다. 이 시점은 새 회차의 입력 관측이며 submitted/matched 성공 또는 남은3+4 완료로 아직 세지 않는다. 새로운 쿼리 계획·실제 검색·수신 파일을 분리하여 감시한다.

### 실제 영어5·중국어5 완료 및 기존 재고 편집 진입

15:56:49.655 KST: 기존 성공2/1에 아래 **정확7개 추가 검색**을 합쳐 고유 actual 영어5/5·중국어5/5를 확인했다. 모두 같은 현재 run/reference/product/text scope이고, 실제 TikTok 입력값·결과 URL 일치와 `query_submitted=True`, `query_url_matched=True`, `status=results` 영수증이 있다. 기존3쿼리 재전송은0, 추가8번째 쿼리도0이었다. 새7요청의 첫 제출부터 마지막 제출까지178.735초이며 약30초 정상 pacing을 지켰다.

| 추가 언어 | 실제 입력 | 제출 시각 KST |
|---|---|---|
| en | Montbell puffer jacket | 15:53:45.968 |
| zh | Montbell 绗缝外套 | 15:54:15.015 |
| en | Stand collar puffer jacket | 15:54:46.385 |
| zh | 立领 绗缝夹克 | 15:55:14.352 |
| en | Horizontal quilted jacket | 15:55:46.303 |
| zh | 横向绗缝 夹克 | 15:56:14.335 |
| zh | 全开襟拉链 绗缝夹克 | 15:56:44.703 |

실제 영수증은 `data/source_jobs/Dec8wlLhu9N-1792306411979802900/browser_debug/search-checkpoint-f9c38dd55ab448548bad4f3b6e390630.json`, 최종 manifest는 같은 폴더의 `manifest.json`이다. 문자열 지문은 공백/NFKC/대소문자·플랫폼 index operator 정규화 후 계수하며, 브랜드 범위가 다른 실제 검색을 단순 공백 변경과 구분한다. 이전 승인3개와 새7개 모두 실행 근거를 보존한다.

15:57:20.255 KST: 최종 manifest `completed`, `search_only=True`, `batch_review.ready=True`, `probe_attempts=0`, `probed_downloads=0`, `downloaded=0`, 중지 사유는 `search_receipts_only_existing_reviewed_inventory`였다. 정상0received 검토가 기존 관련 승인 부모12·핵심8을 재확인했고 run의 `source_ids`는 production-start와 동일한12개였다. collector는15:56:58.324에 done, edit `job-3c491c9dc5184905`는15:56:58.846에 running으로 진입했다. 수집 준비 완료는 최종 영상5부모 사용·품질 통과와 구분한다.

15:58:13.902 KST 추가 보존 확인: 선택12개 모두 baseline record SHA가 같고 현재 실제 파일 SHA도12/12 일치했다. 전체 source record ID 집합도 변하지 않았다. 선택 script `script-112f53277b5c466e`, voice `voice-run-f40858ef18e84c0d`는 그대로이며 신규 voice job은0이다. 15:59:44 관측까지 단일 edit job이 유지되고 새 collect/voice job은 없었다. analyze 요청 지문은 `963ee3a77804b4cd6fcdeabd2bbb86407895ed1f4e94fcfac7bc2b4973f7fc5b`, analyze 결과 파일은15:57:16에 생성되어 초기 분석은약17초였다. 이후 의미 분석/모델 대기는 별도 단계로 관찰하며 파일 하나의 mtime만으로 반복·정체를 단정하지 않는다.

16:02:25.802 KST 모델 효율 점검은 `data/writing/jobs.sqlite3`도 URI mode=ro/query_only로 읽었다. 편집 시작 후 editorial7건 중 관찰6건은 서로 겹치지 않는 shot_ids 묶음6+6+6+6+6+2, 총32개 shot에 대한 completed였다. 관찰 instruction SHA는 같지만 evidence SHA는 모두 다르며 각 CLI attempt는1개였다. 7번째는 instruction/evidence가 다른 ranking job `codex1e8103b6bbc0d9049598ca0d6b925275` running1회였다. 동일 입력 모델 반복이나 실패 재시도 증거는0이며 정상 관찰6batch→ranking 진전으로 구분했다.

16:04:03 KST: ranking completed 후 select-shots/freeze-selection/cover-candidates 결과가 생성되었다. 실제 동결 plan의 `body_usage_report`는 enforced=True/minimum5/used6/shortfall0, 최대 한 부모 점유율24.29%였다. 부모별 본문 분량은2.30·0.667·3.933·3.467·4.00·2.10초다. `source_diversity_gap` 없이 단일 edit가 이어지고 있다. 이는 **동결 배치 계획의 노출 프레임 계수**이며 실제 MP4의 디코드·최종 품질 통과를 대신하지 않는다.

16:05:08.834 KST edit가 done으로 저장되고 새 `quality_review` job `job-2fa5c459872f4449`가 시작되었다. 16:06:08.462 KST 실제 `job-3c491c9dc5184905/preview.mp4` 존재·크기10,269,552bytes·SHA `6035e89e0be6cbdcfad5cfc0d99ffd987d05416526f648bacb9e5fcec51ed453`를 읽기 확인했다. export_verified=True, duration16.5초이며 같은 폴더 `timeline.json`의 최종 본문 원본6/min5/shortfall0·최대24.29%가 유지됐다. 선택 대본·음성 ID도 그대로다. 직전16:05:53.893 QA 스냅샷에서 새 QA는 running이고 `daily_quality.status=passed`는 과거 edit `job-93795039313a43ff`에 묶여 있었으므로, 그 초기 스냅샷을 **신규 완성본 통과로 산입하지 않았다**.

최종 정정/완료 확인: 이후 독립 read-only DB 관측에서 task와 선택 run 모두 completed, 현재 edit `job-3c491c9dc5184905`의 `quality_verified=True`, `daily_quality.status=passed`와 `reviewed_edit_id`가 **현재 edit에 정확히 결속**됨을 확인했다. 새 QA 영수증은 `job-2fa5c459872f4449/review.json`이다. DB의 완료 시각은16:05:56.310 KST이며 root의 실제 결과 검증 영수증 `data/source-diversity-20261018/actual-production-result.json`은16:06:16.144 KST에 기록됐다. 요청 시작→결과 검증은2038.376초, 즉 **33분58.376초(중간 구현·배포 pause 포함)**다. 실제 검색5/5, 기존 관련 재고12, 새 다운로드0, 기존 대본·음성, 실제 본문6부모와 새 완성 QA 통과가 모두 같은 run에 묶였다. 공개·브라우저 검증은 root가 별도로 담당한다.

최종 모델 이력도 편집 시작→결과 검증 구간으로 다시 계산했다. editorial job14개가 모두 completed이고, instruction+evidence 지문14개가 서로 달랐다. 각 job의 실제 CLI attempt는1개, 총14개로 동일 입력 재시도는 없었다. 앞의32shot 관찰6묶음, 순위 및 이후 표지/검수 작업을 완료한 이력이며, 7번째 모델의 대기 시간을 실패나 반복으로 잘못 세지 않았다.

처음 시작15:32:17.768부터 편집 생성까지는24분40.478초로, 중간 코드 보정·정상 배포 pause/resume 시간이 포함된다. deployment-5 재개15:51:36.721부터 편집 생성까지는약5분21.526초다. 최초 전환 회차는 claim15:51:39.973→done15:52:59.784, 총79.811초(새 정책의 필수 계획·독립 검토도 포함)였고, old scope 소진 판정이 새 querypool 생성 후 갱신되지 않아 검색0으로 끝났다. 다음 preflight15:53:31.478에서 TikTok이 ready로 자동 회복했다. 이 최초1회 비용과 이후 실제 검색 pacing을 분리하며 무한 반복이나 플랫폼 콘텐츠 실패로 세지 않는다. 향후 개선 후보는 scope 소진 판정을 querypool 지문에 묶어 지문이 바뀔 때만 `fresh_queries`를 재평가하는 것이다. 실제 인증·로그인·CAPTCHA·탭 누락 중지는 유지해야 한다. 현재 코드는 동결 유지했다.
