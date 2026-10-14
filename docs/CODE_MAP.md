# insta_auto 코드 탐색 지도

먼저 바꿀 기능의 진입점과 해당 테스트만 읽는다. 운영 데이터는 data/에 있으며 모듈 재배치와 별개로 보존한다.

| 기능 | 진입점 / 구현 | 검증 |
|---|---|---|
| 초기 no-render 표지 픽셀·문구 승인 결속 / 본문·음성 재실행 없이 렌더 | initial_prepared_render.py → studio_workflow.py/studio_runtime/editing.py; cover_selection.py/cover_product_crop.py; 외부 studio_cover.py | test_cover_mask_diagnostic.py/test_cover_product_crop.py; rank2-initial-preparation-cloned-db-independent.json, official20/copy9/worker guard |
| 최종 concat 실제 PTS와 승인 마스크 픽셀 결속 / 같은 실패 출력 반복 차단 | mask_application_evidence.py → quality_progress.py/daily_quality.py; 외부 auto_capcut/core/studio_masks.py/studio_render.py | mask-boundary-v2/typed-pending-receipt.json, official-first-frame-review.json, actual-render-job028b/actual-output-captions-proof.json; test_mask_application_evidence.py |
| 수신 소스의 명시 구간 별도 검토 / 기존 구간 캐시·기능·세로 검토 승계 방지 | source_mask_review.py/source_overlay_review.py; tools/review_rank2_bounded_cooking.py | test_source_overlay_explicit_scope.py; rank2-bounded-code-actual-clone-independent.json |
| 렌더 전 선택 실패·실제 QA 비교 기준 분리 / exact legacy 관측 append 정정 | daily_quality.py/quality_progress.py → scene_requirements.py; tools/correct_rank1_pre_render_observation.py, tools/review_rank1_repair_slot.py | test_pre_render_scene_gap.py, test_quality_progress_independent.py; rank1-correction-cloned-db-independent.json, 실제 native 필수 프레임 검증 |
| 중지·서비스 대기 중 실제 검색 이력/미검토 수신 보존·복구 | source_pause_receipts.py → studio_pause.py/source_browser_worker.py/source_finder.py → studio_sources.py/studio_runtime/generation.py; tools/restore_connected_apple_pause_history.py | test_source_pause_history.py, test_deferred_download_review.py; pause-resume-history-cross-review.md, 독립 복제DB·actual scope 영수증 |
| 승인한 기존 Chrome 동일 창 탭 생성·실제 제출/전송 여부·native Bili popup 방지 | source_browser_runtime.py/source_browser_worker.py → browser_search.py/source_attempts.py/source_outcomes.py → source_search/{readiness,strategy,triage}.py; tiktok_download.py/tikvideo_download.py | test_source_same_window_tabs.py, test_source_attempt_provenance.py, test_connected_search_input.py, test_bilibili_search_results.py, test_source_browser_worker.py |
| 상위3 실제 감시 결함 보정·중심 대상·계량/미공개 재료 검증 | source_queries.py → source_planning.py → source_search/planner.py → studio_automation.py; data/rework-top-three-20261014/ | test_query_rework_independent.py, test_daily_source_queries.py, test_studio_automation.py |
| 외부 접근 전 같은 job 대기·준비 영상/프레임/계획 SHA 재사용 | source_access_preflight.py/source_preparation.py → studio_sources.py/source_finder.py/studio_runtime/{generation,lifecycle}.py | test_source_access_preflight.py, test_source_preparation_reuse.py; data/rework-top-three-20261014/test_source_wait_independent.py |
| 전체 제작 흐름 독립 재점검·운영 반영 근거 | [2026-10-14 감사](workflow_reliability_audit.md); data/workflow-audit-20261014/ | 독립 A/B 반례, main 전체 회귀·실제 렌더/모델 검수, 운영 전후 감시 |
| 내구 큐 소유 세대·중복/늦은 완료·파일 부작용 방어 | studio_store.py → change_claimed/assert_owned → studio_runtime/; job_queue.py/storage.py/server.py | test_workflow_claim_generation.py, test_workflow_audit_acquisition.py, test_workflow_audit_independent_a.py |
| 원본 SHA별 영상/음성 전체 디코드·부분 수신 원자 저장 | source_finder.py의 _verify_reference/_download_reference; transcript.py/speech_worker.py | test_workflow_audit_reference.py; reference-integrity-local/verification.json |
| 검사 탈락과 네트워크 시도 분리·접근 대기 재개 | source_search/strategy.py/triage.py → studio_sources.py/studio_runtime/generation.py/lifecycle.py | test_workflow_audit_acquisition.py, test_workflow_audit_independent_a.py |
| 실제 요청/산출물/검수 SHA에 결속한 완료·공유·복구 | studio_runtime/editing.py → daily_quality.py → studio_workflow.py/comparison_share.py; tools/run_reserved_recovery_job.py | test_workflow_audit_independent_b.py; 별도 auto_capcut test_ffmpeg_progress/test_export_runner |
| 서버 시작 실패·종료의 owner/실행기 drain | server.py의 serve_many/ManagedHTTPServer → job_queue.py/Studio.close | test_workflow_audit_acquisition.py, test_workflow_audit_independent_b.py |
| VoiceBench 준비·전송 대기·수동 응답 불명의 요청 재사용 | studio_services.py → voicebench_adapter.py → studio_runtime/lifecycle.py; production.py | test_studio_services.py, test_voicebench_adapter.py, test_production.py, test_workflow_audit_independent_b.py |
| 사진 비활성 정상·복구 실행 경계 | photo_reference.py의 assert_creation_enabled → studio_runtime/lifecycle.py/tools/run_reserved_recovery_job.py | test_studio_runtime.py, test_workflow_audit_independent_b.py |
| 전체 제품 매력 중심 검수 / 원작 6개 보정·4개 검증 / 선택 개선과 재편집 사유 분리 | product_appeal_review.py → daily_quality.py/scene_analysis.py/scene_requirement_context.py/scene_requirements.py; tools/calibrate_reference_quality.py | test_product_appeal_review.py; data/reference-calibration-20261013-v2-native/ |
| 정상 대기·단계 무진전 감시 / 모델 공통 복구 대기 / 장면 확보 후 편집 | operation_progress.py, model_service.py, scene_requirements.py → source_finder.py/studio_sources.py/daily_quality.py/studio_runtime/ | test_reliability_progress.py, test_source_probe_budget.py, test_codex_writer.py, test_daily_quality.py |
| 품질 진전·결함 이력·같은 실패 방법/순환 차단·최선 결과·누적 사용량 | quality_progress.py → daily_quality.py/studio_runtime/lifecycle.py/studio_workflow.py/studio_store.py; [실행 계약](quality_progress_policy.md) | test_quality_progress_independent.py, test_quality_progress_policy_independent.py, test_render_contract_queue*, test_repair_render_accounting |
| 근거가 같은 검색어 묶음 고정·실제 페이지/커서 범위 이력 | source_planning.py → source_finder.py; source_search/strategy.py | test_search_scope_progress_independent.py |
| 전체 대본·제품/부품 관계를 반영한 필수 장면 증거 / 핵심 프레임의 실제 편집 노출 | scene_requirement_context.py → scene_requirements.py → source_frame_timing.py/studio_runtime/editing.py | test_scene_requirement_context.py, test_scene_requirement_preflight_context.py, test_scene_requirement_anchors.py, test_source_frame_timing.py |
| 대본 변경 후 비렌더 분석·시각 피드백 대응 / 불명확한 대응 보류 | scene_narration_prepare.py → studio_runtime/{generation,editing,lifecycle}.py | test_scene_narration_prepare.py |
| 수집·랭킹·일별 선정 | cli.py → collectors/ → storage.py → analyze.py/report.py → daily_hot.py/studio_automation.py | test_daily_hot.py, test_studio_automation.py |
| 제작실 조립·집필/미디어 분리 실행 | hotpost/studio.py, studio_runtime/, studio_store.py | test_studio_runtime.py, test_studio_worker_lanes.py, test_studio_workflow.py |
| 내 촬영 영상 신규 제작 | studio_self_shot.py, writing/product_research.py, web/studio-self-shot.js | test_studio_self_shot.py, test_studio_self_shot_browser.py |
| 제작 단계·버전 | studio_workflow.py, studio_store.py, studio_sources.py | test_studio_workflow.py, test_parallel_sources.py |
| 신규 일별 자동 제작의 완성본 검토·재수집·재편집 | daily_quality.py → studio_runtime/{editing,lifecycle}.py; studio_automation.py의 시작 날짜 | test_daily_quality.py, test_studio_scene_selection.py; tools/test_daily_quality_live.py |
| 얼굴 없는 실제 썸네일·문구의 제품 궁금증 / 사용 구간을 확정한 뒤 선택 | cover_selection.py → studio_workflow.py → 별도 auto_capcut.studio_runner | test_cover_selection.py; 실제 MP4 첫 프레임의 그룹별 daily_quality 검토 |
| 소스 후보 수집·전체 보관 소스 검색 | source_finder.py, source_search/{models,catalog,semantic,discovery,library,budget}.py | test_source_expansion.py, test_source_discovery.py, test_source_library.py, test_source_probe_budget.py |
| 소스 검증·마스크 증거·출력 결함 구간 제외 | source_quality.py, source_functional.py, source_mask_review.py, source_overlay_review.py, source_review_withdrawals.py | test_source_quality.py, test_source_mask_review.py, test_source_overlay_review.py, test_source_review_withdrawals.py, test_parallel_sources.py |
| 원본 해상도·비율 경고 / 실제 세로 크롭 화질·동작 보존 검토 | source_presentation.py → studio_sources.py | test_source_presentation.py |
| 긴 소스의 후보 구간 추출 | source_segments.py → source_finder.py의 일반 검증 | test_source_segments.py, test_source_video_track.py |
| 소스 수량 정책·플랫폼 실패 근거 | source_policy.py, source_outcomes.py, source_targets.py → studio_sources.py | test_source_quota_policy.py, test_tiktok_targets.py, test_parallel_sources.py |
| 검색어·접근 상태 / Bilibili 표시된 검색 카드 | source_queries.py, source_planning.py, browser_search.py, search_access.py | test_daily_source_queries.py, test_browser_auth_blocks.py, test_bilibili_search_results.py |
| 기존 TikTok 탭의 MP4 수신·바이트 조각 병합·blob 연결 | source_finder.py → tiktok_download.py; source_browser_runtime.py의 공유 간격·잠금 | test_tiktok_download.py, test_source_browser_runtime.py |
| 기존 YouTube 탭의 재생 응답·UMP 조립·영상 전체 디코드 | source_finder.py → youtube_download.py → youtube_ump.py | test_youtube_download.py, test_youtube_ump.py, tools/verify_youtube_browser_route.py |
| 기존 YouTube 탭 검색창·현재 응답과 표시 카드 대조 / 브라우저 모드 외부 검색 금지 | source_search/discovery.py → browser_search.py → youtube_search.py; source_browser_runtime.py의 existing_page | test_youtube_search.py, test_source_discovery.py, test_source_expansion.py, tools/verify_youtube_search_route.py |
| 대본 내부 연결·음성·편집 외부 연결 | studio_adapter.py, voicebench_adapter.py, editing_adapter.py | 각 adapter 테스트 |
| 사진 제작 실험(현재 비활성화, 사용자 재승인 필요) | config.py의 photo_production_enabled → studio.py/commands.py, photo_reference.py → tools/render_selected_photo_story.py → 별도 auto_capcut.photo_story_runner 프로세스 | test_photo_reference.py, test_photo_story_contract.py |
| 음성 없는·짧은 레퍼런스 | reference_narrative.py → studio_runtime/generation.py | test_reference_narrative.py, test_studio_workflow.py |
| Codex 참고 대본 3안·안별 검사·보완 / 직접 촬영 집필 | writing/RULES.md → contract.py → pipeline.py → variants.py/codex_writer.py | test_writing_variants.py, test_internal_writing.py |
| 내장 작업 큐·과거 기록 | studio_adapter.py → writing/jobs.py; data/writing/legacy | test_studio_adapter_identity.py, test_internal_writing.py |
| 의미·복사·수치·자연스러움 | writing/checks.py, script_integrity.py, benchmark_wording.py, script_quantities.py → studio_top_pick.py | test_studio_script_checks.py, test_top_pick_claims.py |
| 기존 후보의 최신 규칙 검사 | studio_script_checks.py → StudioAdapter.review 로컬 검사 → studio_top_pick.py | test_studio_script_checks.py |
| 장면 관찰·대본별 선택 | studio_ai.describe_shots → scene_analysis.py | test_scene_analysis.py, test_studio_scene_selection.py |
| 로컬 GPU 작업 조정 | local_compute.py → VoiceBench 유휴 자원 API | test_local_compute.py, test_voicebench_adapter.py |
| 화면 HTTP | server.py, studio_http.py | test_dashboard_settings.py |
| 메인 화면 | web/app.js, web/discovery/ | hot_detection.test.cjs, dashboard 관련 테스트 |
| 제작 화면 | web/production-flow.js, web/studio/, web/post-result.js | production_flow.test.cjs, post_result.test.cjs |
| 십대 폰트·첫 프레임 썸네일 재제작 / 비교 공유 | tools/build_typography_rework.py → 별도 auto_capcut.studio_runner; tools/share_typography_rework.py | docs/typography_cover_rework.md; Auto CapCut의 test_studio_cover.py, test_studio_typography.py |
| 썸네일 폰트 미지원 문자 / 대본·음성 보존한 표시 수정 | Auto CapCut studio_cover.missing_glyph_shapes/paint → tools/revise_jacket_cover_glyph.py | Auto CapCut test_studio_cover.py; 실제 cover/QA 및 clip·decoded-audio 해시 비교 |
| 과거 수동 패딩 실험 (새 제작에 사용 금지) | tools/refine_daily_jacket_value.py → tools/build_daily_jacket_value.py | 특정 표현 고정은 폐기. 현재 계약은 writing/RULES.md와 scene_analysis.py |
| 텐트 마지막 제품 장면 / 기존 원고·음성·썸네일 보존 | tools/revise_tent_product_cta.py → 별도 auto_capcut.studio_runner | 실제 CTA 프레임·전체 재생·원본 시간 범위·이전 run 및 공개 파일 해시 |
| 카트 도입 실제 적재 보행 / 기존 원고·음성·썸네일 보존 | tools/revise_cart_opening_motion.py; tools/sample_received_actions.py | 밀집 원본·세로 파생·12 QA 프레임·전체 공개 재생·이전 run/파일 해시 |
| 구 패딩의 조건부 가격·가족 매력 3안 및 새 개인 음성·편집 | tools/refine_old_jacket_value.py → 공식 Codex CLI; tools/build_old_jacket_value.py | 세 안 전후 검토·고유 TTS 요청·실제 파생/커버/12 QA·원본 구간 반복 검사·공개 전체 재생과 SHA·이전 run 보존 |
| 실물 폴더 썸네일 3안·저장 대사 장면 보완 | tools/refine_folder_thumbnail.py → 공식 Codex CLI; tools/revise_folder_transfer.py; tools/record_folder_transfer_review.py | 본문·음성 보존, 연결·PC 복사·파일 목록의 실제 파생 검토, 12 QA·공개 전체 재생·SHA, 미확인 사진 복사/폰 부착 표시 |
| 실물 폴더 USB 사용 설명 정정·신규 세로 소스 | tools/folder_phone_sources.py; tools/refine_folder_phone_quality.py → 공식 Codex CLI; tools/build_folder_phone_quality.py; tools/record_folder_phone_review.py | 기본 부착 추정 제거, 세 대본·새 개인 음성, 실제 USB 삽입/휴대폰 연결·12 QA·전체 공개 재생·SHA·이전 run 보존 |
| 거울 대본 3안·열기/닫기·메모·CTA 보완 | tools/refine_mirror_quality.py → 공식 Codex CLI; tools/review_mirror_actions.py; tools/revise_mirror_actions.py; tools/record_mirror_quality.py | 여는 대사의 닫기 컷·설치 전 바닥 컷 제거, 기존 음성 보존, 실제 파생·12 QA·공개 전체 재생·이전 run 보존 |
| A7 파일홀더 영수증 장면·썸네일 3안 보완 | tools/a7_receipt_sources.py; tools/refine_a7_receipt_thumbnail.py → 공식 Codex CLI; tools/revise_a7_receipt_scenes.py | 기존 TikTok 세션의 한 번 검색/한 편씩 수신, 실제 영수증 보관과 삽입 동작 구분, 12 파생·12 QA·전체 공개 재생·SHA·이전 run 보존 |

## 상세 지도

- 전체 7건 품질 감사·공동 비교: `tools/audit_current_quality_scope.py`, `tools/finalize_quality_scope_audit.py`, `tools/share_audited_seven.py`, `tools/verify_audited_seven_public.py`. 실제 21개 대본·현재 원고/음성/파일 SHA·커버/QA·전체 디코드·공개 파일 검증은 `data/quality-scope-audit-20261011-v1/completion-audit.json`에 모은다.
- A7 실제 미니 봉투 장면: `tools/revise_a7_envelope_alignment.py`; 추가 생선 소스 연구: `tools/recheck_fish_source.py`. 동일 SKU를 별도 필수 조건으로 추가하지 않고 실제 기능 증거와 미확인 사항을 구분한다.
- 공유 페이지의 선택 재생 및 버전별 스냅샷: `tools/share_daily_rework.py`의 `lazy_media`, `hotpost/comparison_share.py`의 `snapshot_suffix`. 기본 호출은 유지하고 원본 metadata/완성본 none·같은 출처 JPEG poster를 사용한다. CSP는 유지한다.

- [제작 실행 모듈](studio_runtime_architecture.md)
- [프런트엔드 모듈](frontend_architecture.md)

## 안정적인 경계

`hotpost.studio.Studio`, `hotpost.source_finder.Candidate/OpenClipVerifier`는 기존 호출자를 위한 진입점을 유지한다. Git submodule이나 별도 저장소로 쪼개지 않고 저장소 내부 Python 패키지·브라우저 모듈로 책임을 나눈다. `production.py` 및 기존 제작 페이지는 저장된 작업과 실제 호출자가 있어 단순히 오래됐다는 이유로 제거하지 않는다.

기존 완성 영상·대본·음성·세션·작업 ID는 보존한다. CAPTCHA 차단과 사용자 정지 상태를 리팩토링 중 변경하지 않는다. 자동 제작의 내용 평가는 참고 의견이며 사용자 승인 대기를 새로 만들지 않는다.

장면 분석은 최대 6개 장면·24개 이미지씩 관찰한 뒤 텍스트만으로 대본별 순위를 정한다.
현재 묶음에 실제 전달된 프레임의 설명만 다음 단계에 넘기며, 설명 누락·순위 실패는
미확인 임시 배치로 표시한다. `context_only`는 핵심 동작의 증거로 승격하지 않는다.
