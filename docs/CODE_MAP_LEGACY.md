> 과거 구현 탐색용 지도. 현재 실행/권한/정책은 WORKFLOW.md 및 CODE_MAP.md를 따른다. 이 문서의 과거 운영 상태는 재개 지시가 아니다.

# insta_auto 코드 탐색 지도

> 2026-10-22 사용자 방침: 기존 **제작실 코드는 outdated / 참고용 보존** 상태다. 아래 제작실 UI·API·Studio 실행기·자동 제작 관련 경로와 과거 구현·검증 기록은 역사적 참고 자료이며, 신규 작업의 기본 실행·개선·복구 대상으로 사용하지 않는다. 코드와 자료는 삭제하지 않는다. 재사용·활성화·수정에는 별도 명시 지시가 필요하다. 터진게시물 서비스와 독립 VoiceBench 전체를 outdated로 지정한 것은 아니다. 최신 우선순위는 AGENTS.md 최상단을 따른다.

먼저 바꿀 기능의 진입점과 해당 테스트만 읽는다. 운영 데이터는 data/에 있으며 모듈 재배치와 별개로 보존한다.

| 기능 | 진입점 / 구현 | 검증 |
|---|---|---|
| 첫 문장의 구체적 의문·점진적 해소·금지 질문형 | writing/RULES.md·hook_policy.py → variants.py/pipeline.py → studio_top_pick.py; script_style.question_ending_issues로 검사·수정안 수용·선정 fallback 경계 연결 | test_first_sentence_hook.py; 계약 v11/TopPick policy25, 정체 조기 공개와 후킹을 구분하고 실제 시청자 반응 측정으로 간주하지 않음 |
| PC→WireGuard→Android 폰 원격 릴스 게시(로컬 CLI) | mobile_reels_cli.py → mobile_device.py(ADB/장치·화면) / mobile_reels.py(패키지·호환 영상·폰 소유권·단일 공유) | test_mobile_reels.py; MOBILE_REELS_WIREGUARD.md; 실폰 IP/포트 미확보로 라이브 검증 미실행 |
| 메인 전체 보기·완성·제작 중 버튼과 검색/조건 결합 | web/index.html/style.css; app.js visiblePosts → 기존 productionState; 상태 갱신 시 선택 목록 동기화 | refactor_ui_regression.test.cjs/discovery_model.test.cjs; 모바일390px 확인 |
| 제작실 없는 게시용 서버·레퍼런스 계정 등록/현재 목록 갱신 | publication_server.py → account_registry_http.py → accounts.AccountRegistry; 게시물 준비는 post_preparation_http.py 재사용 | test_publication_accounts.py/test_account_git_sync.py/test_post_preparation.py; 신규 수집·제작은 시작하지 않음 |
| PC별 완성 영상·현재 적용 썸네일의 날짜별 저장 | publication_export.py → local/video-storage.json + local/VIDEO_STORAGE.md(Git 제외); PostPreparation.source의 검증 완료본 읽기 | test_publication_export.py; [로컬 저장 규칙](LOCAL_VIDEO_STORAGE.md); 완료 에이전트가 저장/해시 검증 후 전달 |
| 독립 게시용 광고·도입 감탄사 규칙 | post_media_rules.py → post_thumbnail.py/post_preparation.py; 광고 없는 본문 명시 반영/이후 body_final과 spoken_text/rules 유지 | test_post_media_rules.py/test_post_thumbnail.py; 실제 TTS271 적용·소스32 보존은 data/shelf-publication-rules-20261023/ |
| 사용자 클릭으로 현재 썸네일/영상 첫 프레임 교체·진행 피드백 | post_thumbnail.py → post_preparation.py/post_preparation_http.py; web/post-preparation.js/css; thumbnail_jobs + active.json | test_post_thumbnail.py/test_post_preparation.py/post_preparation.test.cjs; 본문 프레임/음성 해시 검증 후 원자 공개 |
| 게시물 준비: 다중 계정·썸네일 4문구·본문·고정댓글·제품 링크·고정 DM·20자 DM 버튼 초안과 개별 복사(업로드 없음) | web/app.js → web/post-preparation.js/css; post_preparation.py/post_preparation_http.py; post_preparation_content.py/json(확장 본문·해시태그5개·댓글2줄·DM 문구); 독립 post-preparation.sqlite3, 기존 완료 자료 읽기 전용 | test_post_preparation.py/test_post_preparation_content.py/post_preparation.test.cjs/refactor_ui_regression.test.cjs; [범위·검증](POST_PREPARATION_UI_20261022.md) |
| 영상 전체 순차 입장·무진전 영속 보류·검증된 동일 job 재개/후속 복원·검색어 MD | production_control.py → studio_store.claim/video_agents/video_agent_actions/commands; production_records.py → source_topic_queries/source_finder/studio_sources/lifecycle | test_production_control.py/test_production_records.py; [구현·한계](PRODUCTION_COMPLETION_CONTROL_20261022.md) |
| 상품 확인 댓글·DM 계정과 게시·리틀리 계정 분리 / 릴스 전용 댓글 dialog·permalink 확인 | monetization_store.py의 discovery_account/account·효과별 시도 키 → monetization.py/monetization_http.py; monetization_browser.py의 reference_comment_surface/own_comment_ids; web/monetization.* | test_monetization_account_roles.py/test_monetization_account_navigation.py/test_monetization_reel_comments.py; 실제 송신과 격리 fixture 검증은 구분 |
| 핵심 제품 우선 수집 v6·유한 탐색 부족 근거·분리된 보조 검색·본문 핵심 다양성 우선 | source_core_priority.py → source_policy.py/source_coverage.py/studio_sources.py/source_batches.py/source_functional.py; scene_analysis.py/studio_runtime/editing.py; 외부 studio_core_priority.py/studio_visual_cuts.py/studio_story_selection.py | test_core_product_priority.py(양쪽 저장소); [구현·검증](CORE_PRODUCT_PRIORITY_IMPLEMENTATION_20261019.md) |
| CAPTCHA 의심 화면 캡처→독립 이미지 재검토→SHA 결속 영수증 / 오탐·미확정 구분 | captcha_review.py → search_access.py/browser_search.py/source_access_preflight.py/platform_verification.py; source_attempts.py | test_captcha_screenshot_review.py/test_saved_captcha_recheck.py; [구현·검증](CAPTCHA_SCREENSHOT_REVIEW_20261019.md) |
| 주제별 핵심 제품·브랜드/모델/특징 유지 검색 / 보조 검색의 최소 횟수 제외 | source_query_identity.py → source_visual_queries.py → source_search/{planner,strategy,discovery}.py → browser_search.py/source_coverage.py | test_source_query_identity.py; docs/PADDING_QUERY_IDENTITY_20261018.md |
| 실제 영어5·중국어5 검색 / 관련 원본5 확보 / 본문 최소5 원본 사용·부족분 자동 복구 | source_coverage.py/source_policy.py/source_batches.py/source_diversity.py → scene_analysis.py/studio_runtime/editing.py/lifecycle.py; 외부 studio_visual_cuts.py/studio_source_diversity.py | test_source_diversity_acquisition_v5.py/test_minimum_source_diversity_independent_20261018.py/test_source_diversity_completion_recovery.py; [구현 결과](SOURCE_DIVERSITY_IMPLEMENTATION_RESULT_20261018.md) |
| 전체 제품 매력 몽타주·특장점 반복/맥락·정상 속도 원본 연장·수집 v4 권장량 | product_appeal_review.py/editorial_policy.py → scene_analysis.py → studio_runtime/editing.py/editorial_continuation.py; source_policy.py/source_coverage.py/source_batches.py; 외부 studio_editorial_policy.py/studio_story_selection.py/studio_render.py | test_editorial_semantics_20261018.py/test_editorial_inventory_policy.py/test_editorial_continuation.py/test_editorial_pipeline_20261018.py; [기준](editorial_montage_policy.md), [실제 원작 검증](EDITORIAL_REFERENCE_VALIDATION_20261018.md) |
| 기존 영상 보존한 명시 QA 재검토·입력 SHA/중지 토큰·같은 실패 방법 반복 차단 / 프레임 전송 예산 | studio_runtime/commands.py(recheck-quality) → daily_quality.py/daily_quality_scope.py → visual_media.py | test_quality_policy_recheck_20261018.py/test_quality_media_transport_20261018.py; [세 영상 최종 결과](EDITORIAL_MONTAGE_PRODUCTION_RESULT_20261018.md) |
| 제작실 요약 목록·선택 작업 상세 조회·응답 경합 방지 | studio_http.py → studio_runtime/media.py(brief); web/studio.js/app.js | test_studio_list_projection.py; STUDIO_EDITING_AUDIT_20261018.md |
| 연속 수동 표지·음성 수정 후 표지 유지·실제 QA 다운로드 경계 | studio_thumbnail.py → studio_runtime/editing.py; daily_quality.py → studio_workflow.py | test_studio_thumbnail.py/test_daily_quality.py; STUDIO_EDITING_AUDIT_20261018.md |
| 음성 설정만 바꾼 승인 장면 재사용·다음 모델 호출 중지 | studio_reviewed_scenes.py; studio_runtime/generation.py → script_rewriter.py → studio_pause.py | test_studio_reviewed_scenes.py/test_studio_pause_model.py |
| 영상 완료 후 상품 확인·파트너스 링크·본문·리틀리·인스타 게시 | monetization.py → monetization_store.py/coupang_partners.py/post_publish.py/instagram_publish.py/monetization_browser.py/instagram_publish_browser.py; monetization_http.py → server.py; web/monetization.* | test_monetization.py/test_instagram_publish.py; [최근 점검·운영 적용·남은 실증](INSTAGRAM_UPLOAD_IMPLEMENTATION_20261019.md); 실계정과 공개 영상·표지 비교 검증은 별도 |
| 몽벨 패딩 정수 PTS 마스크·실제 출력 경계 QA | quality_boundaries.py → daily_quality.py; 외부 studio_masks.py/studio_render.py | test_quality_boundaries.py; 외부 test_mask_integer_clock.py; [패딩 개선 결과](PADDING_VIDEO_QUALITY_RESULT_20261015.md) |
| 구간별 제품 등장·구도·새 정보·전역 선택 고정 | shot_presentation.py → scene_analysis.py/studio_runtime/editing.py/studio_workflow.py; 외부 studio_story_selection.py | test_shot_presentation.py/test_semantic_plan_cache.py; 외부 test_story_selection.py; data/padding-quality-implementation-20261015/ |
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
| 승인 대본·음성을 보존한 명시 자동 소스 재분석·수집 후 새 소스 선택 | studio_workflow.py의 source_selection_mode=automatic; studio_sources.py의 v5 실제 검색 우선 | test_source_reanalysis_selection.py/test_source_interval_recovery.py; TWO_VIDEO_CORE_IDENTITY_REPRODUCTION_20261018.md |
| 작은 수신 묶음→정식 검토→분량 충족 중단·SHA 복구 / 플랫폼 공통 정밀 후속 질의·전송 진단 | source_batches.py → source_finder.py/studio_sources.py; source_search/planner.py → source_queries.py, source_transfer_trace.py → tiktok_download.py/tikvideo_download.py/source_attempts.py | test_source_batch_recovery.py, test_source_probe_budget.py, test_remediation_contracts.py; VIDEO_PRODUCTION_REMEDIATION_RESULT_20261017.md |
| 유형별 TopPick·표지 문구 독립 보완 / 본문·음성 보존한 첫 프레임 교체 | studio_top_pick.py; thumbnail_copy.py → writing/pipeline.py/variants.py; daily_quality.py → cover_frame_copy.py → 별도 renderer portable-draft | test_remediation_contracts.py, test_studio_thumbnail.py; 실제 470프레임·오디오 동일성 검증 |
| claim별 시간·대기 event / 병행 구간 중복 합산 방지 | studio_store.py → studio_timing.py | test_studio_timing.py; 미계측 내부 대기는 claim wall time에 포함 |
| 신규 일별 자동 제작의 완성본 검토·재수집·재편집 | daily_quality.py → studio_runtime/{editing,lifecycle}.py; studio_automation.py의 시작 날짜 | test_daily_quality.py, test_studio_scene_selection.py; tools/test_daily_quality_live.py |
| 얼굴 없는 실제 썸네일·제품별 시청 동기 / 사용 구간을 확정한 뒤 선택 | thumbnail_copy.py → writing/variants.py·cover_selection.py·cover_product_crop.py·daily_quality.py → 별도 auto_capcut.studio_runner | test_thumbnail_copy.py, test_cover_selection.py; THUMBNAIL_VOICE_FEEDBACK_20261016.md; 실제 첫 프레임 검토 |
| 화면 문구 참고 영상의 실제 제품 프레임을 집필·안별 검토에 전달 | studio_automation.py → writing/reference_evidence.py → variants.py/pipeline.py → codex_writer.py의 이미지 사본·SHA 영수증 | test_writing_reference_visual.py; TODAY_TOP1_PRODUCTION_20261016.md; 원문·시각 관찰 분리 및 입력 무결성 실패 전파 |
| 완료된 내부 집필 3안의 썸네일·검토·출처 메타데이터를 후보 버전으로 가져오기 | script_candidate_versions.py의 completed_writing_candidate → 기존 add-script-candidate API | test_completed_writing_candidate_import.py; 원고·계약·원본 SHA 검증, 기존 선택 음성 보존 |
| 중지 상태의 명시 수동 소스 수집 / 다음 중지의 취소 권한 / 즉시 재claim 차단 | studio_pause.py → studio_runtime/commands.py·lifecycle.py → studio_store.py의 pause_claimed | test_paused_manual_source_request.py; 같은 pause 세대·현재 claim만 허용 |
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
| 사용자 승인 거울168 톤 기준·새 음성 비교 / 원본·설정 보존 | writing/RULES.md → tools/remake_approved_mirror_tone_20261016.py → voicebench_adapter.py; data/approved-mirror-tone-20261016/ | test_voicebench_adapter.py; THUMBNAIL_VOICE_FEEDBACK_20261016.md; 실제 run·개인 참조·선택 Seed 검사 |
| 사진 제작 실험(현재 비활성화, 사용자 재승인 필요) | config.py의 photo_production_enabled → studio.py/commands.py, photo_reference.py → tools/render_selected_photo_story.py → 별도 auto_capcut.photo_story_runner 프로세스 | test_photo_reference.py, test_photo_story_contract.py |
| 음성 없는·짧은 레퍼런스 | reference_narrative.py → studio_runtime/generation.py | test_reference_narrative.py, test_studio_workflow.py |
| 흐릿한 개별 화면 인용 생략·새 SHA 독립 재검증·같은 실패 호출 보존 | reference_narrative.py의 quote_decisions/READING_POLICY → reference-text-attempts | test_reference_narrative.py; NEXT_REFERENCE_VIDEO_20261017.md |
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

- 최종 음성/대본 버전 결속: `hotpost/daily_quality.py::verify_narration_version`은 canonical script/음성SHA/voice_source를 검증하고, 차이가 있는 spoken_text는 같은 script+voice+canonical에 유일 결속된 저장run의 명시 pronunciations만 적용한다. 회귀는 `tests/test_daily_quality.py`.
- 별도 renderer 승인 구간 산술: `../auto_capcut/auto_capcut/core/studio_diversity.py::render_window`는 승인 범위 경계의8ULP 이내 부동소수 오차만 정확한 경계값으로 정규화하며 strict mask 검증과 최종 프레임 가림을 유지한다.

- 실제 제품 특징→검색 명사: `hotpost/source_visual_queries.py`의 원본·프레임 SHA 결속 제안/독립검토 → `source_finder.py`의 기존 준비자료 재사용 → `source_queries.tiktok_product_queries`의 현재 근거 재검증·우선 전송. 확정 products/브랜드/재질로 자동승격하지 않는다. `tests/test_source_visual_queries.py`, `PRODUCT_QUERY_NEXT_VIDEO_20261016.md` 참조.

- 음성 레퍼런스의 실제 그림: `studio_adapter.py::submit` → `writing/visual_reference.py`는 speech 입력에 원본 SHA·시각·6프레임 SHA를 결속하고 캐시 변조/소실을 제출 전에 거부한다. 화면문구 OCR 계약은 유지한다. `tests/test_spoken_reference_visual.py`.
- 근거 있는 중심 명사 갱신: `studio_sources.py::accept_source_round` → `studio_automation.py::refresh_resolved_subject`는 실제 원문에서 해결된 명사만 갱신하며 사용자 override와 이전 metadata 이력을 보존한다.
- 새 대본의 과거 장면 영수증: `scene_requirements.py::anchor_selected_scenes`는 현재 활성 요구가 있을 때만 anchoring한다. 해결된 과거 요구의 이력은 보존하고 활성 영수증 SHA 검사는 유지한다. 실제 실패·복구·운영 로딩 및 영상 검증은 `TODAY_REFERENCE_VALIDATION_20261017.md`.
- 실제 최근5개 원작 대비 소스 검증 엄격도: `tools/audit_source_strictness_20261017.py`의 동결 선정·기능 양성 대조·실제 세로 크롭·독립 전체 매력·가림 승인 구간 비교. `docs/SOURCE_VALIDATION_STRICTNESS_AUDIT_20261017.md`; 운영 task/승인/정책을 변경하지 않는 별도 audit이며 source duration readiness와 콘텐츠 탈락을 구분한다.
- 받은 소스의 짧은 구간 복구: `source_interval_recovery.py` → `studio_sources.py`/`source_batches.py`는 새 수집 전에 실제 native 구간을 제안하고 A∪B 정상 가림·기능·세로 재검토 및 충분 분량 조기 종료를 수행한다. `source_review_status.py`는 형식 오류·승인0·내용 거절·대기를 분리하고 `shot_presentation.prefer_clear_options`는 같은 관련성에서 실제 선명도/가림 면적을 우선한다. `SOURCE_INTERVAL_IMPROVEMENT_20261017.md`, `tests/test_source_interval_recovery.py` 참조.
