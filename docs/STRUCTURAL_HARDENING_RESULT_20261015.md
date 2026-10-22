# Structural Hardening & SQLite De-bloating Result Report (2026-10-15)

## 1. 개요 (Executive Summary)

본 문서는 [`docs/STRUCTURAL_HARDENING_PLAN_20261015.md`](file:///c:/Codex/인스타자동화/insta_auto/docs/STRUCTURAL_HARDENING_PLAN_20261015.md)에 정의된 4대 구조적 개선 과제를 서브에이전트(`Plan Cross-Validator`) 교차검증을 거쳐 구현·마이그레이션·검증한 최종 결과 보고서이다.

- **계획서 경로**: [`docs/STRUCTURAL_HARDENING_PLAN_20261015.md`](file:///c:/Codex/인스타자동화/insta_auto/docs/STRUCTURAL_HARDENING_PLAN_20261015.md)
- **결과 보고서 경로**: [`docs/STRUCTURAL_HARDENING_RESULT_20261015.md`](file:///c:/Codex/인스타자동화/insta_auto/docs/STRUCTURAL_HARDENING_RESULT_20261015.md)
- **마이그레이션 실측 JSON 리포트**: [`data/live-validation-20261014/sqlite-migration-report.json`](file:///c:/Codex/인스타자동화/insta_auto/data/live-validation-20261014/sqlite-migration-report.json)
- **신규 회귀 테스트 스위트**: [`tests/test_structural_hardening_20261015.py`](file:///c:/Codex/인스타자동화/insta_auto/tests/test_structural_hardening_20261015.py)

---

## 2. 항목별 구현 및 검증 결과 (Implementation & Verification Results)

### 항목 A (P14 근본 해결): `data/writing/jobs.sqlite3` 구조적 비대화 해소

#### 1) 변경 파일 및 핵심 로직
- [`hotpost/writing/jobs.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/writing/jobs.py#L17-L150):
  - `Jobs.__init__`: `CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created)` 인덱스 생성 및 `PRAGMA journal_mode=WAL` 활성화.
  - `Jobs.create`: 작업 ID(`jid`) 해시는 원본 `payload` 전체 JSON 문자열을 기준으로 동일하게 계산하되, 워커 스레드 레이스 컨디션 방지를 위해 SQLite `INSERT OR IGNORE` 전에 `data/writing/<jid>/payload.json`을 먼저 기록하고 SQLite `payload` 컬럼에는 `NULL`(`None`)을 저장.
  - `Jobs._compact_payload_media`: `data/writing/<jid>/image-{i}.jpg`가 디스크에 추출·검증된 직후, 인메모리 원본을 변경하지 않고(`copy.deepcopy`) `payload.json` 내 `media[i]['inlineData']['data']`(수 MB의 Base64 문자열)를 `{'_external_file': f'image-{i}.jpg', 'mimeType': ...}` 참조로 치환하여 디스크 중복 저장까지 제거.
  - `Jobs._load_payload`: `Jobs.get(jid, include_payload=True)` 호출 시 `payload.json`을 읽고 `_external_file` 참조가 있으면 `image-{i}.jpg`로부터 Base64 문자열을 즉시 복원(Re-hydrate)하여 기존 호출자 계약을 100% 유지(`include_payload=False`일 때는 `'payload'` 키 생략 유지).
- [`tools/migrate_writing_jobs_sqlite.py`](file:///c:/Codex/인스타자동화/insta_auto/tools/migrate_writing_jobs_sqlite.py):
  - `worker.lock` 획득 후 스트리밍 방식으로 2,112개 행의 `payload`를 `payload.json`으로 무손실 분리, `DELETE` 모드에서 `UPDATE jobs SET payload = NULL` 및 `VACUUM` 수행 후 `WAL` 모드로 전환.

#### 2) 마이그레이션 전후 실측 비교 (`sqlite-migration-report.json`)

| 지표 (Metric) | 마이그레이션 전 (Before) | 마이그레이션 후 (After) | 변화율 / 비고 |
| :--- | ---: | ---: | :--- |
| **`jobs.sqlite3` 파일 크기** | **4,912.85 MB** (`5,151,494,144` B) | **8.69 MB** (`9,113,600` B) | **-99.82% (4.90 GB 감소)** |
| **SQLite `payload` 컬럼 총합** | **4,889.21 MB** | **0.00 MB** (`NULL`) | `payload.json` + `_external_file`로 분리 |
| **SQLite `result` 컬럼 총합** | **5.11 MB** | **5.11 MB** | **100% 보존** |
| **총 행 수 (`jobs` 테이블)** | **2,112건** | **2,112건** | `editorial` 2,062건 + `script` 50건 보존 |
| **미디어 Base64 중복 압축 행 수** | 0건 | **1,879건** | 기존 `image-{i}.jpg` 참조로 치환 |
| **저널 모드 (`journal_mode`)** | `delete` | **`wal`** | 읽기/쓰기 블로킹 해소 |
| **인덱스 (`PRAGMA index_list`)** | PK 단일 | **`idx_jobs_state_created` 추가** | `(state, created)` 복합 인덱스 |
| **워커 큐 폴링 지연시간** | **~40,000 – 96,000 ms** (풀스캔) | **1.624 ms** | **약 25,000배 이상 단축** |
| **샘플 `editorial` 복원 검증** | - | **`rehydrated_ok: true`** | 9개 이미지(`251,288` B) Base64 무손실 복원 확인 |

---

### 항목 B (D1·D2 일반화): 동적 중심 대상 명사구 승인 및 다국어 액션 쿼리 주어 보강

- [`hotpost/source_queries.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/source_queries.py#L113-L375):
  - `REVIEWED_OBJECT_GROUPS`에 빈출 라이프스타일·가전·리빙·주방 품목 14개 다국어 그룹 추가.
  - `_clean_tiktok_syntax` 및 `register_tiktok_noun_head` 도입: `tiktok_product_queries(plan)` 실행 시 `primary_subject`가 원문 인용(`primary_subject(ps, ev)`), 문자 그대로의 출현(`_literal_term`), 명사구 문법 검사(`_clean_tiktok_syntax`), 재료/브랜드 근거 검사(`grounded_named_terms`)를 모두 통과하면 `register_tiktok_noun_head`를 통해 런타임 `TIKTOK_NOUN_HEADS`에 등록하여 하위 `tiktok_noun_phrase` 및 `platform_queries(..., 'tiktok', ...)` 필터에서도 탈락하지 않도록 일반화.
  - 반면 번역된 영/중 쿼리나 임의 모델 생성 쿼리에 대해서는 기존의 엄격한 사전 등가성 검사(`grounded_tiktok_noun_phrase`)를 그대로 유지하여 오역(`vacuum cleaner`), 미관측 수식어(`silver steam cleaner`), 은닉 재료(`cinnamon`) 차단 불변성을 보존.
- [`hotpost/browser_search.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/browser_search.py#L372-L380):
  - `_run_route`에서 서브프로세스 워커가 부모로부터 전달받은 `provider_queries['tiktok']` 풀에 대해 `register_tiktok_noun_head`를 호출하여 프로세스 경계 너머에서도 동적 명사구가 유지되도록 보강.
- [`hotpost/source_planning.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/source_planning.py#L181-L230):
  - `enrich_plan`의 `subject_heads` 수집 대상을 정적 사전 외에 원문 근거와 `grounded_named_terms`가 확인된 모델의 짧은 `subject`/`product`/`unbranded` 쿼리 및 `tiktok_queries`(4단어 이하)까지 확장.
  - `accept()`에서 액션/기법 쿼리에 주어 명사를 붙일 때 `for head in subject_heads[lang]:` 전체 후보를 순회하며 `grounded_named_terms`를 통과하는 첫 번째 후보를 채택하고 즉시 `break`하도록 개선.

---

### 항목 C (D5 타이밍 한계 해결): 초기 `prepare` 및 `rewrite` 단계의 중심 대상(`product`) 조기 식별

- [`hotpost/studio_automation.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/studio_automation.py#L129-L136) ([`_resolve_rewrite_manifest`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/studio_automation.py#L228-L278), [`identify_subject`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/studio_automation.py#L281-L311)):
  - `_normalize_screen_text`를 통해 `transcript.json`의 리스트형 `screen_text`를 문자열로 정규화하고, `identify_subject` 내부의 `product_query_plan` 호출에 `screen_text`를 전달.
  - `rewrite` 시작 시 `source_search_manifest_path`가 아직 없더라도 (1) `transcript_path`의 `screen_text`, (2) `data/sources/<shortcode>-*/manifest.json`의 초기 `product_evidence`, (3) `data/source-query-plans/<identity>.json` 캐시된 검색 계획을 순서대로 조회하여 첫 번째 대본 생성 시점부터 검증된 `primary_subject`가 `state['product']`에 반영되도록 개선.
- [`hotpost/studio_runtime/generation.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/studio_runtime/generation.py#L85-L103):
  - `_prepare`가 생성하는 초기 reference manifest에 정규화된 `screen_text`와 전체 캡션을 기록하고, 초기 `product`가 식별되면 즉시 상태에 반영.

---

### 항목 D (D7b 일반화): `edit_id` 생성 이후 발생한 기술 실패(`pending='failed'`) 복구 및 큐 재등록

- [`hotpost/daily_quality.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/daily_quality.py#L285-L295) 및 [L609-L616](file:///c:/Codex/인스타자동화/insta_auto/hotpost/daily_quality.py#L609-L616):
  - `fail_daily_quality`에서 `failed_job_kind`와 `failed_job_id`를 기록.
  - `advance_daily_quality`에서 `stage == 'quality_review'` 큐 등록 시 `resume_retry_count > 0`이면 `queue_key`에 `:retry:{resume_retry_count}`를 추가하여 기존 `status='failed'` 잡과의 `INSERT OR IGNORE` 키 충돌 방지.
- [`hotpost/studio_workflow.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/studio_workflow.py#L535-L539):
  - 초기 `stage == 'edit'` 큐 등록 시에도 `resume_retry_count > 0`이면 `:retry:{resume_retry_count}`를 접미사로 부여.
- [`hotpost/quality_progress.py`](file:///c:/Codex/인스타자동화/insta_auto/hotpost/quality_progress.py#L535-L580):
  - `resume_assessment(state)`에서 초기 편집 실패뿐 아니라, `edit_id`가 생성되었으나 아직 해당 편집본의 검수가 완료되지 않은 상태(`reviewed_edit_id != edit_id`)에서 `quality_review`나 `edit`이 기술 오류로 실패한 경우 `resume_retry_count`를 증가시키며 즉시 `pending='pending'`으로 복구.
  - `refresh_sources` 실행 중 기술 오류(`failed_job_kind == 'refresh_sources'`)로 실패한 경우에도 `local_review_resume_count`를 증가시키고 `pending='recollect'`로 복구.
  - 반면 이미 검수가 완료된 편집본에서 확정 실패한 `reedit` 시도를 새 증거 없이 재개하려는 요청은 기존 정책대로 차단(`test_explicit_resume_cannot_reopen_failed_method_by_adding_known_source_url` 통과).

---

## 3. 향후 다른 에이전트를 위한 재검증 명령어 (Reproducibility & Verification Commands)

다른 에이전트가 본 작업의 결과를 독립적으로 검증할 때 아래 명령어를 순서대로 실행하면 된다.

### 1) 신규 및 기존 정책 회귀 테스트 실행 (143개 테스트)
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_structural_hardening_20261015.py tests/test_tiktok_query_policy.py tests/test_query_rework_independent.py tests/test_internal_writing.py tests/test_studio_adapter_identity.py tests/test_studio_editorial.py tests/test_quality_progress_independent.py tests/test_quality_progress_policy_independent.py -q
```
- **실행 결과**: `143 passed in 3.09s`

### 2) `data/writing/jobs.sqlite3` 상태·크기·인덱스·지연시간 확인
```powershell
.\.venv\Scripts\python.exe -c "import sqlite3, os, time, json; p='data/writing/jobs.sqlite3'; t0=time.perf_counter(); db=sqlite3.connect(p); db.execute('SELECT id FROM jobs WHERE state=?', ('running',)).fetchall(); db.execute('SELECT id FROM jobs WHERE state=? ORDER BY created LIMIT 1', ('queued',)).fetchone(); dt=round((time.perf_counter()-t0)*1000, 3); print(json.dumps({'size_mb': round(os.path.getsize(p)/1048576, 2), 'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0], 'indexes': [r[1] for r in db.execute(\"PRAGMA index_list('jobs')\").fetchall()], 'total_rows': db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 'non_null_payloads': db.execute('SELECT COUNT(*) FROM jobs WHERE payload IS NOT NULL').fetchone()[0], 'poll_ms': dt}, ensure_ascii=False))"
```
- **기대 결과**:
  - `size_mb`: `8.69` (`< 10.0`)
  - `journal_mode`: `"wal"`
  - `indexes`: `["idx_jobs_state_created", "sqlite_autoindex_jobs_1"]`
  - `total_rows`: `2112` (또는 이후 추가된 작업 수 이상)
  - `non_null_payloads`: `0`
  - `poll_ms`: `< 5.0` ms

### 3) 기존 42개 베이스라인 작업 및 4개 검증 완료 영상 보존 확인
```powershell
.\.venv\Scripts\python.exe -X utf8 -m tools.live_validation_preservation verify
```
- **실행 결과**:
  - `changed_old_tasks: []`
  - `changed_old_jobs: []`
  - `changed_old_files: []`
  - `preserved: true`
  - 4개 검증 대상 작업(`work-1672e441725d4445`, `work-8013247e50624ae6`, `work-8b16890d03794af1`, `work-2d881e5afb2043ce`) 모두 `status: "completed"`, `daily_quality.status: "passed"` 유지 확인.
