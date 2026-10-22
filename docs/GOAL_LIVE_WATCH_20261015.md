# Live Production & Watcher Defect Log (2026-10-15)

## 1. Selected Reference Video (`최근 터진게시물` Unproduced Candidate)
- **Shortcode**: `Dec5bcqyffk`
- **Task ID**: `work-2d881e5afb2043ce`
- **Hot Post Rank**: Rank 4 in `all_today` (Ranks 1–3 `DebVFJ8vOCY`, `Deb2jkPxQ43`, `DebLqa-T1kq` already have completed & verified target videos)
- **Kind**: `reel` (`rank_score = 5.93`, `views = 2337`, `likes = 39`)
- **Subject / Caption Summary**: 헬로키티 핑크 손난로 (거울 + 조명 + 대용량 보조배터리 + 내장 충전 케이블 일체형)
- **Preservation Check**: Not in the 42 frozen historical baseline tasks; existing top-3 tasks (`work-1672e441725d4445`, `work-8013247e50624ae6`, `work-8b16890d03794af1`) and all 42 historical baseline tasks verified untouched (`preserved: true`).

## 2. Watcher Architecture
- **Subprocess Watcher (`tools/live_task_watcher.py`)**:
  - Polls `data/studio/studio.sqlite3`, `data/studio/<task_id>/*/operation_progress.json`, `data/source_jobs/<shortcode>-*/manifest.json`, and `data/writing/jobs.sqlite3` every 10 seconds.
  - Appends continuous telemetry to `data/live-validation-20261014/goal-watch-Dec5bcqyffk.jsonl` and structured defect records to `data/live-validation-20261014/goal-defects-Dec5bcqyffk.json`.
  - Automatically detects and alerts (`exit code 2`) on:
    - `no_progress_stall`: No revision, job, or `operation_progress` change for $\ge 240$ seconds.
    - `job_failed` / `job_auto_retry`: Any failed job or retry loop.
    - `writing_job_error`: Any CLI or `database is locked` failure in `data/writing/jobs.sqlite3`.
    - `quality_loop_hold` / `source_acquisition_hold` / `task_stopped_or_attention`: Any hold (`scene_wait`, `exhausted`, `failed`, `source_hold`, `editorial_hold`).
    - `duplicate_search_query` / `overlong_search_query`: Search query defects in source manifests.

## 3. Discovered Defects & Real-Time Code Fixes

### D1. TikTok Skipped with `no_supported_queries` on Hand Warmer / Power Bank (`hotpost/source_queries.py`)
- **Observed At**: `2026-10-15T03:49:23+09:00` (`job-958f2aa8695f4621`, `collect_sources`)
- **Evidence Path**: `data/source_jobs/Dec5bcqyffk-1792003763470579400/manifest.json` (`tiktok_query_details: []`, `search_audit[1]: {"provider": "tiktok", "status": "no_supported_queries"}`)
- **Root Cause**: `'손난로'`/`'hand warmer'`/`'暖手宝'`, `'보조배터리'`/`'power bank'`/`'充电宝'`, `'핑크'`, and `'헬로키티'`/`'키티'`/`'Hello Kitty'` were absent from `PRODUCTS`, `BRANDS`, `REVIEWED_OBJECT_GROUPS`, `TIKTOK_MODIFIERS`, and `TIKTOK_EQUIVALENTS` in `hotpost/source_queries.py`. Consequently, `grounded_tiktok_noun_phrase` rejected all 3 primary product queries (`'헬로키티 핑크 손난로'`, `'Hello Kitty pink hand warmer'`, `'Hello Kitty 粉色暖手宝'`).
- **Code Fix**: Added `'손난로'`/`'hand warmer'`/`'暖手宝'`, `'보조배터리'`/`'power bank'`/`'充电宝'`, `'Hello Kitty'`/`'헬로키티'`/`'키티'`, `'Sanrio'`/`'산리오'`, `'핑크'`, and related product groups to `hotpost/source_queries.py`. Verified `grounded_tiktok_noun_phrase` approves all 3 queries.

### D2. Bare Generic Action Queries Without Central Subject Noun (`hotpost/source_planning.py`)
- **Observed At**: `2026-10-15T03:51:40+09:00` (`job-958f2aa8695f4621`, `collect_sources`)
- **Evidence Path**: `data/source_jobs/Dec5bcqyffk-1792003763470579400/manifest.json` (`queries: ["button activated light", "按键开启照明", "버튼으로 조명 켜기"]`)
- **Root Cause**: `enrich_plan` in `hotpost/source_planning.py` accepted model-generated `technique`/`action` queries without requiring the central product head noun, which caused YouTube search to download unrelated adhesive wall tap lights (`07_playwright-youtube_O2KTzES08VI.mp4`, `08_playwright-youtube_loIaJCBGFuo.mp4`).
- **Code Fix**: Updated `enrich_plan` prompt and `accept()` in `hotpost/source_planning.py` so that when `primary_subject.category == 'product'`, any `technique`/`action`/`demonstrated_action`/`close_up_footage` query that omits the central product head noun is rejected.

### D3. Candidate Ranking Inversion Ignoring `similarity_warnings` (`hotpost/source_finder.py`, `hotpost/studio_sources.py`)
- **Observed At**: `2026-10-15T03:56:10+09:00` (`job-958f2aa8695f4621`, `collect_sources`)
- **Evidence Path**: `data/source_jobs/Dec5bcqyffk-1792003763470579400/manifest.json` (candidates `#5..#13` with `similarity_warnings=['low_product_or_scene_similarity']` sorted ahead of `#14..#18` with `similarity_warnings=[]` and higher similarity `0.691..0.719`)
- **Root Cause**: `candidates.sort` in `hotpost/source_finder.py:1266` ordered by `(c.downloaded_file != "", c.source_score or 0, c.similarity or 0)` without checking `not bool(c.similarity_warnings)`. Because `clean_score * 0.55` dominated `source_score`, unrelated `light-overlay` videos with `low_product_or_scene_similarity` ranked above actual Hello Kitty hand warmer videos (`edited-with-text`, `similarity=0.691..0.719`, `similarity_warnings=[]`).
- **Code Fix**: Updated `hotpost/source_finder.py:1266` to include `not bool(c.similarity_warnings)` in the candidate sort key, and sorted `incoming` in `hotpost/studio_sources.py:_collect_source_attempt` by `not bool(s.get('similarity_warnings'))` before visual review.

### D4. Missing `source_visual_review` Checkpoint in `_collect_source_attempt` (`hotpost/studio_sources.py`)
- **Observed At**: `2026-10-15T04:01:00+09:00` (`job-958f2aa8695f4621`, `collect_sources`)
- **Evidence Path**: `data/studio/studio.sqlite3` (`jobs.id = 'job-958f2aa8695f4621'`, `checkpoint` keys `['_claim_token', 'source_attempts', 'manifest']`)
- **Root Cause**: Unlike `_refresh_source_attempt` (`hotpost/studio_runtime/generation.py:252-265`), `_collect_source_attempt` (`hotpost/studio_sources.py:371-378`) never initialized `job['checkpoint']['source_visual_review']`, causing `_checkpoint_deferred_review(job, source)` to return early without persisting per-source visual review progress during initial collection.
- **Code Fix**: Initialized and restored `job['checkpoint']['source_visual_review']` in `_collect_source_attempt` in `hotpost/studio_sources.py`.

### D5. Unresolved `state['product'] == '원작 중심 대상 미확인'` When `rewrite` Runs in Parallel with `collect_sources` (`hotpost/studio_automation.py`, `hotpost/studio_sources.py`, `hotpost/studio_runtime/commands.py`)
- **Observed At**: `2026-10-15T03:54:40+09:00` (`job-86bf7d37b5864a24`, `rewrite`)
- **Evidence Path**: `data/studio/studio.sqlite3` (`tasks.id = 'work-2d881e5afb2043ce'`, `state.product = '원작 중심 대상 미확인'`)
- **Root Cause**: `rewrite()` only checked `state.get('manifest_path')` (the lightweight preparation manifest without `product_evidence`), and neither `accept_source_round` nor `resume-auto` backfilled `state['product']` from `source_search_manifest_path` once `collect_sources` finished.
- **Code Fix**: Updated `rewrite()` in `hotpost/studio_automation.py` to prefer `state.get('source_search_manifest_path') or state.get('manifest_path')`, and added `identify_subject` backfill in `accept_source_round` (`hotpost/studio_sources.py`) and `resume-auto` (`hotpost/studio_runtime/commands.py`).

### D6. Bilibili Controlled Search `bili_header` Selector False Positive on `/search` URLs (`hotpost/browser_search.py`)
- **Observed At**: `2026-10-15T04:05:10+09:00` (`pytest tests/test_platform_search_verification.py`)
- **Evidence Path**: `hotpost/browser_search.py:502`
- **Root Cause**: `bili_header` matched `host == 'www.bilibili.com'` without excluding `/search` paths, causing `/search` URLs on `www.bilibili.com` to use `input.nav-search-input` before `.search-input-el`.
- **Code Fix**: Added `and not (parsed_url.path or '').startswith('/search')` to `bili_header` in `hotpost/browser_search.py:502`.

### D7. Cover Candidate Sampling Near Window End Crossing Native Frame Boundary & Initial Edit Failure Resume (`auto_capcut/core/studio_cover.py`, `hotpost/quality_progress.py`)
- **Observed At**: `2026-10-15T04:11:25+09:00` (`job-88a87b8da8cc4cc3`, `edit`)
- **Evidence Path**: `data/studio/work-2d881e5afb2043ce/job-88a87b8da8cc4cc3/cover-candidates-result.json` (`{"status": "failed", "error": "표지 실제 프레임이 선택된 소스 구간 밖입니다."}`)
- **Root Cause**:
  1. In `auto_capcut/core/studio_cover.py:candidates()`, `timestamp = min(end - 1/1000, start + offset)` sampled `10.444444s` inside a used window ending at `10.4499998s` (`5.5ms` before `end`). Because 30fps native frames are `33.3ms` long, the last full native frame inside `[10.07, 10.45]` starts at `10.400000s` (`[10.40, 10.433333]`), so `_native_frame(rows, 10.444444)` selected ordinal `314` (`[10.466667, 10.50]`), which exceeded `end = 10.45` and raised `ValueError('표지 실제 프레임이 선택된 소스 구간 밖입니다.')`.
  2. In `hotpost/quality_progress.py:resume_assessment()`, when the initial `edit` job failed before any `edit_id` or quality defect existed (`pending == 'failed'`, `edit_id is None`, `unresolved(state) == []`), `resume_assessment` required `hypothesis(state, 'reedit')['grounded']` and returned `False`, preventing `resume-auto` from retrying the failed initial `edit` job.
- **Code Fix**:
  1. Updated `auto_capcut/core/studio_cover.py:candidates()` to clamp sampled timestamps to valid native frame exposures `[f_start, f_end]` within each used window (and clean up partial `candidate-*` files if `candidates.json` was not yet written). Added unit test `test_candidates_clamps_near_window_end_to_valid_native_frame`.
  2. Updated `hotpost/quality_progress.py:resume_assessment()` to allow resuming when `quality.get('pending') == 'failed' and not state.get('edit_id') and not unresolved(state)`.

## 4. End-to-End Production Progression & Final Verification (`work-2d881e5afb2043ce`)
1. **`prepare` (`job-c154a7a4c3fb402f`)**: Extracted reference video (`reference.mp4`) and spoken/screen-text transcript (`transcript.json`).
2. **`rewrite` (`job-86bf7d37b5864a24`, `codex51ed4469eb6750c527869f75d2cbf419`)**: Generated 3 candidate scripts (`A/B/C`) and selected Top Pick (`"어, 키티 손난로 꺼내니까 옆에서 뭐냐고 물어요. 공연장 줄이 추워서 주머니에서 꺼냈거든요. 귀여운 손난로인 줄 알았는데 뚜껑 안엔 거울이 있고, 버튼을 누르면 조명도 켜져요. 입장 전에 화장 고치고 닫으려는데, 내장 케이블로 폰 충전까지 되는 대용량 보조배터리예요. 공연 기다릴 때 챙기고 싶은 키티네요. 댓글에 ‘나도’ 남겨주세요."`).
3. **`voice` (`job-12e673af612a496b`, VoiceBench `230`)**: Synthesized `19.25s` personal voice WAV (`required_seconds = 24.06s`).
4. **`collect_sources` (`job-958f2aa8695f4621`) & `refresh_sources` (`job-cb5b9ce648a642de`, `job-fb6756a4bdcc42f3`)**: Collected 19 candidate videos and reviewed 16 editing-ready sources (`sources=19, editing_ready=16`).
5. **Edit & Quality Review Loop**:
   - **Edit 1 (`job-88a87b8da8cc4cc3`)** $\rightarrow$ **QA 1 (`job-31c7fa45662e4593`)**: Flagged `repetition` on `beat-16` (`same_source_time_replay_seconds: 5.376`, `maximum_source_share: 0.657`, `parent_files: 2`).
   - **Edit 2 (`job-5302d87d7ab54d05`)** $\rightarrow$ **QA 2 (`job-7a196873229d4393`)**: Reduced replay after expanding to 16 ready sources (`same_source_time_replay_seconds: 4.863`, `maximum_source_share: 0.626`, `parent_files: 3`), flagged `repetition` on `beat-15`.
   - **Edit 3 (`job-f9e8a4de00d545a9`)** $\rightarrow$ **QA 3 (`job-f986b909d2244ef1`)**: **PASSED** (`passed: True`, `issues: []`, `same_source_time_replay_seconds: 3.663`, `maximum_source_share: 0.555`, `parent_files: 3`, `audio_timing_audit.passed: True`).
6. **Final Verified Output**:
   - **Status**: `completed` (`revision = 188`, `daily_quality.status = 'passed'`, `export_verified = True`, `quality_verified = True`)
   - **MP4 Path**: `data/studio/work-2d881e5afb2043ce/job-f9e8a4de00d545a9/preview.mp4` (`10,686,246` bytes)
