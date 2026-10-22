
## 2026-10-17 구현 전 읽기 전용 오류 감시

검토 대상: AGENTS.md의 소스·가림·claim·반복 차단 계약, `SOURCE_VALIDATION_STRICTNESS_AUDIT_20261017.md`, source_overlay_review/source_mask_review/studio_sources/source_batches/quality_progress 및 인접 source_presentation/source_functional/scene_requirements 경계. 운영 코드·DB·브라우저·모델은 변경하지 않았다. 신규 제작 대상은 부모가 별도 선정한다.

### 확인한 안전 조건과 반례

1. **시간별 가림의 실제 활성 범위 일치**: 현재 propose_masks는 같은 window에서 표본별로 발견한 모든 서로 다른 박스를 window 전체에 놓고, _coverage_media도 interval_index만 확인하여 모두 칠한다. 이를 짧은 시간별 가림으로 바꾸면 독립검토 미리보기와 실제 renderer가 모두 source_start <= 실제 decoded timestamp < source_end인 마스크만 사용해야 한다. 문자 위치가 바뀌는 경계 직전·직후 실제 픽셀을 보지 않고 희소 표본 사이를 낙관해 보간하면 미검토 문자가 노출될 수 있다.
2. **짧은 구간은 새로운 독립 승인**: explicit_review_scope는 source SHA·정확한 시간·기하·표본 수·정책으로 결속된다. 새 scope는 기존 영수증의 시간만 줄여 만들 수 없다. _fresh_explicit_reviews가 이전 기능·세로 검토를 이력으로 남기고 현재 기능/세로를 required 및 editing_eligible=false로 되돌리는 안전 장치를 유지해야 한다. 새 구간의 실제 프레임으로 정상 기능·세로 검토를 마친 뒤에만 분량에 포함한다.
3. **복구 방법의 동일성**: 현재 overlay 실패 캐시의 기본 키는 policy+sourceSHA여서 새 짧은 scope까지 막을 수 있다. 복구는 실제 실패 근거에 결속된 scope/마스크/샘플의 새 방법키로 구분하고, 같은 짧은 scope의 확정 실패는 자동 재요청하지 않아야 한다. 폴더·UUID·코드해시·이유 문장·아주 미세한 경계값 변화는 새로운 시각 근거가 아니다. quality_progress의 parent원본 시간·실제 native 노출 비교를 유지한다.
4. **희소 표본 수와 실제 새 프레임 구분**: 5표본을 요청해도 극단적으로 짧은 구간은 같은 native프레임이 여러 ID로 생성될 수 있다. 자동 분할의 최소 폭과 새 근거 판단은 5라는 개수가 아니라 실제 decodedPTS/노출 범위로 판단해야 한다. 이전 구간 전체 거절이 그 안의 모든 짧은 범위 불가를 증명하지는 않지만, 단일 정지 표본의 반복은 동작 승인 근거가 아니다.
5. **거절·형식 오류·서비스 대기 분리**: 현재 정상 독립 reviewer가 intervals=[]를 반환한 경우와 reviewer 미수신을 approve_masks에서 같은 일반 오류로 표시한다. 검토 완료/승인0, 응답 형식 오류, 서비스 대기, 무결성 불일치, 미검토를 구분해야 한다. 거절 각 구간의 이유를 source/proposal/scope에 결속하여 보존한다. unknown 응답은 승인하지 않는다.
6. **문자열 서비스 오류 분류의 한계**: is_service_review_error는 database lock/OperationalError/429/timed out 등의 regex를 쓴다. 실제 내용 거절 reason에 그런 문자열이 있어도 서비스 재시도로 오인할 수 있다. 새 typed category가 있으면 이를 우선하고 원래 예외 타입·HTTP status·stage를 기록한다. 서비스 대기를 콘텐츠 실패·품질 회차 소진으로 세지 않는다.
7. **묶음 검토의 기존 경계 유지**: source_batches는 현재 claim/pause를 모델 전후 확인하고 task/run/product/reference SHA를 결속하며 최신 수동 제외를 보존한다. 짧은 복구 결과를 캐시·병합할 때도 이 범위를 유지해야 한다. 동일 sourceSHA의 새 구간 영수증으로 이전 승인/수동 제외를 덮거나 미검토 구간을 같이 합격시키면 안 된다.
8. **실제 사용량 합집합**: 새 짧은 승인 구간이 기존 승인 구간과 겹치면 길이를 중복 합산하지 않는다. 같은 parent·파생 시간/retiming도 현재 원본 좌표 기준 중복 차단을 통과해야 한다. 분량 충족 후 추가 다운로드가 없어야 한다.

위 조건·반례를 부모에게 즉시 보고했다. 감시 문서는 구현 완료 주장이나 신규 제작시간 절약 실측이 아니다.

### 구현 계획 응답과 병합 추가 반례

부모 계획은 움직이는 마스크를 보간하지 않고 새 명시 subinterval 각각5native프레임과 독립 가림 승인을 수행하는 방식이다. 이전 영수증·실패를 보존하며 신규 요청에만 새 정책을 적용한다. 이 방향 자체의 기준 완화는 없다.

- 현재 source의 functional_review와 presentation_review는 각각 단일 값이다. presentation.scope.intervals는 source.reviewed_intervals와 정확히 같아야 한다. A승인구간과 새B구간을 합친 뒤 B전용 영수증을 A∪B 전체의 증거로 붙이면 안 된다. A∪B 전체에 대한 정상 새 검토 또는 각 구간별 receipt를 재검증하는 명시 합성 규약이 필요하다. 기존 A/B 영수증은 보존한다.
- joint 기능 검토는 현재 candidate 전체에서 최대6프레임만 전달한다. 분할 후 구간이 많아지면 어떤 짧은 구간은 모델에 한 장도 전달되지 않을 수 있다. 각 새 구간의 실제 기능 프레임이 검토됐음을 확인하고, 파일 전체 same_core_function 하나로 미전달 구간을 승인하지 않아야 한다.
- 두 반례를 부모에게 보고했다. 실제 구현 파일의 검토는 부모 완료 통보 후 진행하며 독자적으로 변경하지 않는다.

### 작성 중 구현의 읽기 검토에서 전달한 수정 요청

`source_interval_recovery.py` 초안에 대해 다음을 부모에게 전달했다. 구현 중 파일을 읽은 시점의 반례이며 이후 수정 여부는 별도로 확인한다.

- accepted 복구 캐시를 원본 영상 SHA만 확인해 수용하면 마스크 proposal/receipt와 기능/세로 프레임 변조를 확인하지 못한다. 정상 가림 승인 재검증과 기능·세로 증거 파일 SHA 또는 불변 영수증 묶음 SHA를 확인한 뒤에만 재사용해야 한다.
- status=started인 중단 기록을 다음 claim에서 무조건 재시도하면 원인 미확인 동일 입력 호출을 반복할 수 있다. service_wait와 구분하고 실제 owned child/정상 adapter 결과가 없으면 보류해야 한다.
- 복구 방법 identity에는 현재 제품·원본 텍스트 등 검토 context도 결속해야 한다. source/reference SHA와 native 범위가 같아도 새 중심 대상 맥락에 과거 기능 승인을 재사용하면 안 된다.
- normalized_scope가 요청 구간을 완전히 포함된 native프레임으로 축소한 뒤 인용 evidence ID의 최종 범위 포함을 재확인해야 한다. 예를 들어 요청 end=.65, 인용 nativePTS=.633333인 경우 그 프레임의 끝이.666667이면 정규화한 범위에서 제외되어 새 end=.633333이 된다. 요청 범위 내부라는 첫 검사만으로 최종 [start,end) 내부 인용을 보증하지 못한다.

### 통합 초안 2차 검토

확인한 보완:

- accepted 캐시는 checkpoint가 가리킨 불변 receipt SHA를 확인하고 _restore_review/accepted_interval_frames/세로 프레임 SHA를 재검증한다.
- 시작만 남은 중단 기록은 PreparationEvidenceWaiting으로 보류하고 자동 반복하지 않는다. service_wait만 별도 복구한다.
- proposal과 물리 scope identity에 제품·원본·본문 등 context_key가 추가됐다. 정규화 후 실제 인용PTS가 최종 범위 내부에 없으면 거절한다. 실제 함수 AST를 파일쓰기 없이 추출 실행해0~.65/인용PTS19/30 경계 반례가 None으로 거부됨을 확인했다.
- joint 승인 구간마다 review_interval 태그를 부여하고 기능 모델에 각 구간 최대3프레임을 전달하도록 보강됐다. 이전 승인 구간을 모두 유지한 joint 가림 승인과 정상 기능·세로 검토가 있어야 사용 분량이 증가한다.
- 충분 분량 확인 시 다음 복구 scope를 멈춘다. 관계 내 선명도 우선은 실제 프레임SHA와 구간 결속이 맞는 옵션의 순서만 바꾸며 삭제·승격하지 않는다.
- runtime callback은 checkpoint context에서 제거 후 별도 runtime dict에만 유지된다. receipts dict는 공유되며 record는 claim/pause check→원자receipt→ledgerSHA→checkpoint 순서다. 포인터 없는 타 작업의 보존 receipt는 자동 승인하지 않는다.

부모에게 추가 요청한 미해결 반례(이 검토 시점):

1. 모델 전후 check는 pause/claim만 확인한다. 같은 claim에서 제품·원작 본문·run이 바뀌면 처음 binding이 현재task와 일치하는지 재검증해야 한다. source_batches의 현재 context 비교와 같은 수용 경계가 필요하다.
2. 외부 catch가 원본/영수증/프레임 변조·소실 ValueError/OSError까지 매번 checked_at이 새 diagnostic으로 바꾸면 candidate!=source가 계속 참이 되어 local 결과만 반환하는 회전이 가능하다. 무결성 실패는 PreparationEvidenceWaiting으로 보류하고 확정 형식 실패는 영수증을 고정해 동일 입력을 반복하지 않아야 한다.

검사 환경 메모: 기본 Python310 및 시스템312에는 PIL이 없어 전체 모듈 import 읽기 검사가 실패했다. 모델·운영 실패가 아니며, 실제 함수 AST를 표준 라이브러리로 추출한 순수 함수 검토로 대체했다. 부모의 정식 회귀 환경 시험과 구분한다.

### 통합 초안 3차 검토

부모가 현재 context 비교와 무결성 오류 보류, 부족한 수신 묶음에서 외부 다음 전송 전에 로컬 복구하는 경계를 보강했다. 코드에서 실제 연결을 확인했다. batch는 새 복구를 체크포인트에 저장하고 최신 voice/state로 goal을 다시 계산한다. 부모가 새 묶음 복구 관련17개 검사 통과를 보고했다(본 감시자의 별도 실행 수가 아님).

추가로 내부 예외 경계를 보고했다. recover의 내부 try가 review_source_overlays/정상 기능·세로 검토 ValueError/OSError까지 unconfirmed로 정착시키면, service_wait 재개 중 보존된 bounded proposal/receipt/evidence가 변조된 오류가 외부 PreparationEvidenceWaiting 변환에 도달하지 못할 수 있다. 정상 승인0/응답형식 오류와 무결성 오류를 내부에서도 구분해야 한다. proposal 캐시 windows를 수정하고 binding을 그대로 두는 경우에도 재정규화 또는 불변 전체SHA 결속이 필요함을 전달했다.

### 첫 운영 제작의 checkpoint·필요 분량 관측

부모가 r2 운영 적용 후 실제 선반 재제작을 시작했다. 대상 `work-98ce7e341904464f` / 새 run `run-244b49520a454a18`, collect `job-69e3330ea7f14da3`와 edit `job-c48b4d6cf9f5420f`.

- SQLite의 실제 interval_recovery checkpoint에 proposals dict와 receipts dict가 모두 JSON으로 지속됨을 확인했다. proposal 전체SHA b599f860…와 scope receipt SHA b3750b22…가 실제 파일과 일치했다. 앞서 지적한 runtime-only 신규 proposals dict 누락은 현재 운영 r2에서 발생하지 않았다.
- 해당 시점 scope는5.5~6.5초, 원본 d9315472… native165~194, 전원부/USB포트 실제 표본에 근거한 제안이며 status=started다. 이는 제안/검토 중이지 승인 증가로 세지 않는다.
- 음성 완료 후 source_goal은 voice18.76초·필요23.45초·기존 승인24초로 ready=true다. 기존2소스의 승인구간은 아직 그대로다. 편집과 소스 작업이 병행 중이며 에러는 없다.
- 따라서 이 실행이 신규 검색/다운로드0회로 종료하면 ‘신규 수집이 필요한 영상’의 비용 실측 완료로 보고할 수 없다. 원작 길이 기준 초기 부족과 실제 음성 기준 충족을 분리해야 한다고 부모에게 보고했다. 부모는 최신 voice를 읽는 sufficient 보강의 후속 검사를 완료했고 현재 실행 종료 후 유휴 배포할 계획이라고 알려왔다.

### 선반 첫 운영 결과의 실제 수용·완성본 범위

- scope5.5~6.5초는165.66초,8.5~9.5초는164.50초에 각각 accepted로 끝났으며 checkpoint가 가리킨 각 영수증 실제SHA가 일치했다. sourceID `source-69ca904c1bb04fe1`과 이전3개 승인구간은 유지됐다. 기능 candidate_review_intervals와 세로 scope가 새2구간을 포함한5구간에 정확히 결속됐다. 합집합 재고는24→26초다.
- 첫 복구 도중 실제 음성이 완료되어 이미 기존24초/필요23.45초로 충분해졌지만, r2는 원작 길이 기준 충분 판단을 계속 사용해 두 번째 복구에 진입했다. 서로 다른 물리 범위이며 확정 실패 반복은 아니다. 다만 불필요한 추가 검토 비용으로 기록한다. 부모가 최신 voice 충분 조건을 보강하고18개 관련 검사 통과, 현재 실행 종료 후 유휴 반영 예정이라고 보고했다.
- 최종 QA `job-bf1cc84c4f0d45ac`는 passed=true/issues0/full_decode_passed=true. previewSHA942573d5…와 planSHAcb80b64a…가 실제 파일과 같고 음성 audit6지점 offset0/상관0.99998이상이다. 청감 검토 audio_listened=false는 그대로다.
- **실제 완성본 경계:** 편집은 첫 복구 승인보다 먼저 병행 시작했다. 최종 timeline.sources에는 기존3구간씩만 있고 interval_recovery_history가 없으며 새5.5~6.5/8.5~9.5 구간은 실제 선택0개다. 따라서 새2초가 이 완성본 픽셀에 반영됐다고 주장하지 않는다. 이 실행은 정상 재고 구간 복구의 실증과 별도 완성본 생성이며, 새 검색/다운로드가 필요한 영상의 시간 단축 검증은 별도다. 이 구분을 부모에게 보고했다.
