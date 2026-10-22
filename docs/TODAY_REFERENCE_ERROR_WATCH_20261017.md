
## 2026-10-17 신규 선택 전 감시 시작

- 역할: 부모가 선택한 신규 제작의 실패·무관한 제품명/질의·접근 제한 오판·소유권·최종 QA 결속을 읽기 전용으로 감시한다. 신규 제작 시작, 외부 요청, DB 변경, 서비스 중지는 하지 않는다.
- 읽은 계약: `AGENTS.md`, `docs/CODE_MAP.md`, `docs/VIDEO_PRODUCTION_REMEDIATION_RESULT_20261017.md`. 기존 미커밋 변경을 확인하고 보존했다.
- 실제 운영 SQLite `data/studio/studio.sqlite3`를 mode=ro로 읽어 오늘 상위3의 completed 상태를 확인했다. rank1 `work-5e6ed8adf432404c`, rank2 `work-98ce7e341904464f`, rank3 `work-4f3fadbcab0f4df2`.
- 관측된 과거 메타데이터 결함: rank1의 product 값이 짧은 제품명 대신 ‘피아노 영상 속 카리나 착장 보자마자’라는 문장이다. 이 사실만으로 실제 검색이 그 문장으로 수행됐다고 단정하지 않는다. 해당 과거 manifest에는 4줄 스트라이프 스웻팬츠 관련 별도 질의와 원문 인용이 존재한다. 신규 대상이 rank1이면 현재 원문/시각 근거로 제품명과 실제 전송 질의를 별도로 검증해야 한다. 과거 완료 상태를 변경하지 않았다.
- 검사 도중 로컬 읽기 스크립트의 상대 URI와 cp949 콘솔 출력 오류를 수정했다. 이는 제작 파이프라인 오류나 외부 요청 실패가 아니다.

## 신규 선정과 준비 단계 통합 누락 검토

- 부모 선정: 오늘 1위 `work-5e6ed8adf432404c` / `DeiBMuLzPxV`. 기준선은 `data/today-reference-validation-20261017/`의 baseline.json, studio-before.sqlite3, target-before.json. 실제 계측 시작은 부모 관측 15:40:06.877 KST.
- 오늘 예약은 부모가 07:00:03 시작·07:23:52 종료·계정 성공39/실패0/게시물50으로 확인했다. 신규 제작은 이미 완료한 원작 하나의 별도 새 버전이며, 예약 누락 복구가 아니다.
- 기존 승인 소스 8개를 재사용하는 경로다. 신규 외부 수집 시간 단축의 실측과 구분한다.
- 확정 코드 원인 A: `studio_sources.py`의 수집 완료 product 정정은 None/빈값/‘원작 중심 대상 미확인’일 때만 실행된다. 초기 제목 fallback이 6단어 이하라 허용된 문장이 이후 실제 원문 근거 확보 후에도 stale로 남을 수 있다. 실제 원문·기존 manifest로 `identify_subject`가 ‘스웻팬츠’를 반환함은 부모가 확인했다. 수정 제안: product_override를 유지하며 fallback=''로 실제 근거에만 기반한 새 중심 명사가 확인될 때 갱신한다. 과거 task의 일괄 변경은 제안하지 않는다.
- 확정 코드 원인 B: `studio_runtime/generation.py`는 speech일 때 reference_text_evidence=None으로 저장하고, `studio_automation.py` 집필 제출은 오직 그 필드의 evidence만 전달한다. 따라서 음성형 원작은 실제 프레임이 writer에 전달되지 않는다. 수정 제안: OCR/발화 구분은 유지하고 별도 원작 visual evidence helper에서 같은 source SHA·명시 시각의6프레임을 준비, 기존 visual_context 검증후 전달한다. 기존 mixed/screen_text 근거는 유효할 때 재사용하며 소스 편집본은 입력하지 않는다.
- 두 최소 수정 제안을 부모에게 보고했다. 본 감시자는 코드·DB를 편집하지 않았다.

## 새 run 실행 감시와 렌더 전 stale 제약 오류

- 새 run `run-bb8a041be35a4891`, 접수 15:43:53.492 KST. 집필 job `codex86b13685dccff0e2026298295ef622ae`, 선택 1안, 새 script `script-f323475bd7734ec2`. 실제 모델4호출 모두 같은 원작 SHA와6프레임 ID/SHA를 받았고 입력 파일 실제 SHA도 일치했다.
- 새 VoiceBench request245는 external_api / long_form_hq / Seed13으로 15:43:54~15:45:06 KST 성공했다. 새 voice는21.490068초, script SHA329a7b1b…에 결속, QC1회/선택Seed13/경고0. 이전 script/voice는 보존되어 있다.
- 새 edit `job-6ae474cde5564e7e`는 렌더 전에 no_render selection hold를 남겼다. 무의미한 반복 실행은 없으며 부모가 재개를 멈추고 원인을 확인했다.
- 확정 원인: 현재 `daily_quality.feedback=[]`인데 `anchor_selected_scenes`가 활성 요구 대신 과거 `scene_requirements.requirements`를 직접 읽는다. `constrain_plan`, `validate_selected_scenes`는 활성 required_scenes가 비면 정상 반환하지만 anchor만 과거 네이티브 프레임 강제를 수행한다. coverage_current도 활성 요구가 없을 때 True이므로 과거 receipt가 검증된 것처럼 넘어갔다.
- 과거 receipt는 구 script-cfca… SHA d3da…의 beat15 ‘조이면 조거 모양으로’에 결속되어 있다. 새 semantic plan의 beat15는 ‘상의에도 차려입은’이다. 새 원고의 다른 구간에 과거 상의 지퍼 오인 결함을 강제 이식해 생긴 통합 결함으로, 신규 후보의 실제 검토 실패나 콘텐츠 품질 실패와 구분한다.
- 최소 수정 제안: `anchor_selected_scenes`에 `if not required_scenes(state): return`을 추가해 다른 제약 진입점과 동일한 활성 범위를 사용한다. 활성 요구가 있으면 기존 coverage_current/원고/실제프레임 검증은 그대로 유지한다. 과거 review/receipt/완성본은 삭제할 필요 없다. 부모에게 즉시 보고했고 감시자는 운영 변경을 하지 않았다.

## 기술 복구와 최종 QA 결속 확인

- 부모가 inactive 요구 진입 guard를 수정하고 관련147개 검사 통과를 보고했다. `selection-recovery-proof.json`은 같은 실제 선택 계획 복제본에 보존 전 anchor AST를 실행해 원래 실패를 재현하고, 수정 함수에서는 plan 무변경 통과를 기록한다. 모델/렌더 추가0회다.
- `resume_verified_selection.py`를 읽기 검토했다. 정확한 task/run/state SHA, 새 script/voice, empty feedback/unresolved0, 모든 owned job 유휴, no_render selection failure, MP4미생성, 코드/계획/증거 SHA를 확인한 뒤 동일 edit job 하나만 새 claim으로 복구한다. 구 실패와 QA·claim을 stop_history/technical_recoveries/event로 보존한다. 품질 permit이나 활성 장면증명 검사를 우회하는 복구가 아니다.
- 실제 최종 QA `job-95392bb171174029/review.json`: passed=true, issues=[], full_decode_passed=true. 실제 preview SHA `5244263fad5ff6dcf60005fcae49920ab3444f642df8ebf8418120ce91c9b523`, timeline SHA `554a00b3818db4c3219d90e44da32d9a0e4669ac0f844732d750e54b5c274fea`와 일치했다.
- 음성 및 자막: timeline은 새 script SHA329a7b1b…와 원 voice_source SHA77d1e5a5…에 결속된다. 승인 WAV의 조용한 구간만 샘플 단위로 제거한17.456735초 음성을 사용하며 발화 속도는 바꾸지 않았다. 최종영상17.466667초, CTA 마지막 자막은16.466667~17.416667초다. decoded audio audit6지점 offset0/상관0.99997이상/길이차0을 확인했다.
- VoiceBench 실제 run269 metrics/manifest에도 fixed_primary_v1, base/selected/worker Seed13, 1회 시도, 다른 Seed fallback=false, 끝문장 match=true가 저장됐다. 자동 전사에 일부 오기가 있으나 그 자체만으로 청감 발음 오류를 확정하지 않는다.
- 한계: 자동 QA의 audio_listened=false, auditory_naturalness_reviewed=false, full_motion_review_complete=false다. 이 감시에서 청감 자연스러움이나 전체 영상 재생을 완료했다고 주장하지 않는다. 부모가 배정한 별도 실제 프레임 검토와 공개 비교 페이지 재생 검증을 진행한다.
