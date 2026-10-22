# 영상 완성까지 이어가는 제작 제어 — 2026-10-22 구현·검증

## 현재 결과와 적용 범위

사용자가 보완한 계획에 ‘진행해’라고 지시하여 핵심 실행기 제어와 검색어 MD 기록을 구현했다. 구현·격리 검증·독립 코드 검토까지 완료했으며, 실제 운영 실행기 시작·중지 작업 재개·새 영상 제작 완료와는 구분한다. 운영 DB는 읽기 전용으로 확인했고 새 스키마는 복제 DB에서만 로드 검증했다. 예약 Disabled·자동 선정 false·자동화3 PAUSED는 유지한다. 첫 영상은 사용자에게 뉴발란스/향수/폭죽 중 선택을 요청한 상태다.

## 실제 변경

- `hotpost/production_control.py`: SQLite transaction 안에서 영상 전체의 순서를 보유하는 `production_slot`. 준비·대본·소스·미디어 worker claim 및 owner 후속 행동이 같은 입장을 사용한다. 현재 영상의 실패·보류·사용자 중지는 다음 영상으로 넘어가는 조건이 아니다. 실제 현재 최종 파일·plan·선택 대본/음성과 QA 결속 및 실행 대기열 종료를 확인한 뒤 다음 영상을 입장시킨다. 기존 개별 lane 수와 후보 선정 수는 유지한다.
- `hotpost/video_agents.py`: 기존 진단 예산/중복 거절과 기존 실패·무진전 확대 경계에서 동일 시도의 반복 재예약을 영속 보류로 전환한다. 정상 모델/서비스 대기는 실패로 세지 않는다. owner/run/job·원 오류·거절·실제 입력 지문·선택 산출물·다음 해결 행동·재개 조건을 보존한다. manager tick·일반 enroll 동기화·재시작은 보류를 해제하지 않는다. 새로운 단계별 시간/횟수 정책을 사용자 확정값처럼 만들지 않았다.
- `hotpost/video_agent_actions.py`와 `studio_runtime/commands.py`: `resume-held-attempt`가 정확한 `hold_id`와 `job_id`, 현재 revision/epoch 및 실제 변경된 자료 또는 검증된 수리 근거를 기존 정상 retry/retry_repaired/continue_repaired에 전달한다. 거짓 SHA·동일 바이트/이름 변경·근거 없는 resume은 보류를 해제하지 않는다. 사용자 resume-auto도 기술 보류를 자동 해제하지 않는다. 접근·소스·품질·서명/로드·현재 입력 보호는 기존 검증을 그대로 거친다.
- `hotpost/video_agent_runtime.py`: 현재 프로세스에 실제 로드된 검증 수리의 원job 재개 경로에 해당 시도 보류를 연결한다. 같은 영상의 후속 제작·최종 QA를 진행하며 이전 대본/음성/소스/실패 기록을 보존한다.
- `hotpost/production_records.py`: 수용된 검색/작업 상태와 MD outbox를 같은 transaction으로 저장한다. worker가 commit 후 per-task/run MD를 투영한다. 취소된 transaction은 기록으로 발행하지 않고, 파일 쓰기 실패는 pending으로 보존하며 재시작 후 복원한다. 오래된 투영이 새 상태를 덮어쓰지 않도록 digest를 다시 확인한다.
- `source_topic_queries.py`는 생성 원문을 검토/호스트 검증 통과와 구분해 기록한다. `source_finder.py`는 계획·검색 checkpoint·최종 manifest에서 검색 시도 MD를 기록한다. `studio_sources.py`는 각 수용 회차의 실제 검색 행을 따로 보존하여 재시도를 병합 이력과 구분한다. 누락된 제출 시각/과거 재시도 수를 만들어내지 않는다. 실제 편집 계획의 사용과 현재 최종 QA 완료도 분리한다.

## 독립 검토에서 발견한 재개 누락과 수정

첫 검토에서, 시도 보류가 함께 멈춘 후속 job들을 원job 재개 뒤에도 paused로 남겨놓는 결함을 발견했다. 원래 queued였고 아직 claim되지 않았으며 현재 run·대본/음성/edit·job 지문이 같은 후속 작업만 복원하도록 수정했다. 원래 failed/paused였거나 이미 실행된 방법은 자동 복원하지 않고 `held_method_incidents`에 개별 해결 근거와 정상 재개 경로를 유지한다. 추가 회귀는 두 개 이상의 작업이 함께 보류된 뒤 후속 작업의 실제 수용과 현재 최종 QA, 다음 영상 입장까지 연결한다.

독립 재검토 결과는 `approved=true`, findings=[]다. 도구 실행 없는 별도 공식 Codex 코드 검토 호출 두 번을 격리된 review 디렉터리에서 수행했다. 기존 운영 영상 owner/model 큐를 재개한 것이 아니다. 검토는 공급한 정확한 변경 범위의 코드 검토이며 운영·미디어 승인으로 사용하지 않는다.

## 검증 증거

증거 루트: `data/production-control-20261022/`.

- `targeted-tests.xml`: 341 passed, 2 skipped, 2 deselected. 기존 두 cover fixture 실패는 아래 별도 기록으로 제외했다. Source/QA/claim/epoch/접근 보호 관련 대상 검사와 새 제어/기록 회귀를 함께 실행했다. 겹치는 이전 실행 수를 합산하지 않는다.
- 실제 중복 조회 예산 거절 분기 → owner 영속 보류 → 가상 시간/tick 반복 후 새 모델 접수0·source claim0 → 같은 저장소 재구성 후 유지 확인.
- 실제 retry budget/자료 SHA 검증 → 정확한 실패 job 재개 → 정상 worker claim → 동일 영상의 후속 register 수용 → 현재 최종 QA 수용·완료 → 다음 영상 입장 확인. 내부 승인/완료 검증기는 교체하지 않았다. 미디어 바이트와 외부 생성 결과는 격리 fixture이며 새 실제 영상 제작을 입증하지 않는다.
- `independent-review-1.json`, `review-input-1.json`, `review-call-receipts-1.json`: 최초 지적과 당시 코드/검토 호출. `independent-review.json`, `review-input.json`, `review-call-receipts.json`: 수정 후 독립 코드 검토와 코드 SHA.
- `isolated-load-check.json`: 실제 운영 DB를 read-only backup한 복제 DB에서 새 스키마 생성 및 13개 모듈의 실제 SourceLoader 실행 SHA를 확인했다. 운영 DB와 복제 DB의 task/state/revision·owner/epoch·job/checkpoint 보존을 확인했다. 첫 비교는 sqlite3.Row/tuple 표현 차이로 false였으며 `isolated-load-check-initial.json`을 보존하고 동일 튜플 표현으로 재확인했다. 운영 실행기 로드 증거가 아니다.
- Chrome 전용 보존 프로필 endpoint는 현재 read-only 확인에서 응답했다. config 및 현재 shell의 Ego binding은 비활성이고 자동 선정은 false다. 현재 로그인·플랫폼 접근·실제 운영 프로세스의 Chrome 설정 로드는 아직 미확인이다. 새 Chrome/Ego 창이나 검색을 실행하지 않았다.

## 기존 실패 두 건 — 새 코드 수정으로 숨기지 않음

`test_daily_quality.py::test_cover_only_repairs_without_external_recollection`, `::test_new_approved_source_does_not_reuse_paused_reedit_queue_key`는 기대한 quality_reedit 대신 refresh_sources/보류가 발생했다. 새 claim 제어와 MD outbox 수용을 격리 프로세스에서 제거한 조건에서도 같은 두 실패가 재현됐다(`preexisting-cover-tests.xml`). 현재 cover routing은 `quality_progress.valid_cover_evidence`를 요구하며 해당 fixture에는 그 근거가 없다. fixture/현재 계약의 정합과 실제 제작 결함 여부는 후속 확인 대상이다. 보호 검증을 대체하거나 운영 코드를 완화하지 않았다.

## 남은 실행 작업

1. 첫 영상 선택 후 해당 작업의 최신 오류·현재 run·산출물을 확인하고, 사용자 중지를 해제할 대상은 그 한 영상으로 한정한다. 다른 중지 작업·예약·일괄 자동화는 재개하지 않는다.
2. 필요한 Chrome 로그인·현재 접근 상태를 실제 확인한다. 실제 첫 영상에 사용되지 않는 옛 Ego 오류를 고치기 위한 재접속/재시험은 하지 않는다.
3. 실제 운영 프로세스의 새 코드/정책 로드와 현재 상태를 확인한 뒤 해당 영상의 중단 단계부터 제작을 이어 최종 파일·현재 QA까지 확인한다. 격리 통과만으로 이 단계를 완료 처리하지 않는다.
4. 첫 영상의 실제 차단에 필요한 코드/입력 수정만 우선 처리하고 기존 감사의 나머지 개선과 미확정 정책은 보존한다. 별도 광범위 회귀 시험을 위해 처음부터 제작을 반복하지 않는다.
