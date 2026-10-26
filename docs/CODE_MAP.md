# 현재 코드 탐색 지도

작업별 규칙은 [WORKFLOW.md](WORKFLOW.md), 개발·검사는 [DEVELOPMENT.md](DEVELOPMENT.md)에서 확인한다. 필요한 모듈과 계약 테스트부터 읽는다.

| 기능 | 진입점 | 회귀 |
|---|---|---|
| 제작실 없는 게시용 서버 | hotpost/publication_server.py → account_registry_http.py, post_preparation_http.py | test_publication_accounts.py |
| 계정 목록 Git 동기화 | hotpost/accounts.py, influencer_list.txt | test_account_git_sync.py |
| 게시물 초안·현재 완료본 조회 | hotpost/post_preparation.py, web/post-preparation.js | test_post_preparation.py, post_preparation.test.cjs |
| 본문·댓글·DM 준비 문구 | hotpost/post_preparation_content.py/json | test_post_preparation_content.py |
| 명시 썸네일 반영·AVC 전달·서버 간 실행권 | hotpost/post_thumbnail.py, post_media_rules.py | test_post_thumbnail.py, test_thumbnail_admission.py, test_post_media_rules.py |
| 독립 계획 스타일·광고 전달·검토본 보관 | hotpost/production_delivery.py, publication_export.py | test_production_delivery.py, test_publication_export.py |
| 제작자 최종 QA 결속·완료 전환·현재 영상/표지 저장 | hotpost/final_qa.py → reference_registry.py, publication_export.py | test_reference_registry.py, test_publication_export.py |
| 로컬 폰 제어·명시 게시 | hotpost/mobile_reels_cli.py → mobile_device.py, mobile_reels.py | test_mobile_reels.py |
| 대본 계약·3안·후킹·금지 표현 | hotpost/writing/RULES.md → contract.py, variants.py, hook_policy.py, script_style.py, pipeline.py | test_first_sentence_hook.py, test_writing_variants.py, test_internal_writing.py |
| VoiceBench HTTP 연동 | hotpost/voicebench_adapter.py | test_voicebench_adapter.py |
| 수집·분석·리포트(별도 실행 승인) | hotpost/cli.py → collectors/, storage.py, analyze.py, report.py | test_collection_control.py, hot_detection.test.cjs |
| 레퍼런스 순위·게시물별 제작 상태 | hotpost/reference_registry.py, data/reference-status.json | test_reference_registry.py |
| 오전 7시 72시간 현재 수치 선정·축약 수치·완성본 건너뛰기 | hotpost/daily_ranking.py → reference_registry.py, web/discovery/model.js | test_daily_ranking.py, discovery_model.test.cjs |
| 설정 | hotpost/config.py, config.json, HOTPOST_* | 설정을 변경하는 기능의 계약 테스트 |
| 지침 파일·경로 | tools/check_guidance.py, docs/guidance.json | .github/workflows/guidance.yml |

모든 Python 테스트는 tests/, JS 테스트도 tests/에 있다. 파일명은 저장소 기준이다.

## 보존 경로

기존 제작실·자동 제작·복구·수동 제품 실험의 상세 파일 연결은 [과거 코드 지도](CODE_MAP_LEGACY.md)에 그대로 보존한다. 새 기본 실행 경로로 사용하지 않는다. production.py/Studio API는 저장된 작업과 호출자가 있어 단순 미사용 추정으로 지우지 않는다. 구형 script_auto 집필 경로는 사용하지 않는다.

계정·게시용 화면이 남아 있다는 이유로 제작실·수집·예약을 함께 켜지 않는다. 기존 자료·현재 중지·다른 작업은 보존한다.
