# Structural Hardening & SQLite De-bloating Plan (2026-10-15)

## 1. 목적 및 배경 (Purpose & Context)

`work-1672e441725d4445`(랭크 1), `work-8013247e50624ae6`(랭크 2, 사과 영상), `work-8b16890d03794af1`(랭크 3), `work-2d881e5afb2043ce`(랭크 4, 헬로키티 손난로 영상) 4건의 라이브 검증 완료 직후 수행한 비판적 엔지니어링 감사에서 다음 **4가지 구조적 한계·기술 부채**가 식별되었다.

본 계획서는 향후 다른 에이전트가 설계 의도, 불변성(Invariants), 수정 범위, 검증 절차를 독립적으로 재현·교차검증할 수 있도록 작성된 실행 계획서이다.

---

## 2. 보존 불변성 (Strict Preservation Invariants)

1. **기존 42개 베이스라인 작업 및 4개 검증 완료 작업 보존**:
   - `python -X utf8 -m tools.live_validation_preservation verify` 실행 시 `preserved: true` (`changed_old_tasks: []`, `changed_old_jobs: []`, `changed_old_files: []`)가 유지되어야 한다.
   - 완료된 4개 작업(`work-1672e441725d4445`, `work-8013247e50624ae6`, `work-8b16890d03794af1`, `work-2d881e5afb2043ce`)의 `status == 'completed'`, `daily_quality.status == 'passed'`, `export_verified == True` 상태가 변하지 않아야 한다.
2. **렌더 계약 서명(`render_contract_signature`) 불변성 유지**:
   - `hotpost/scene_requirements.py:212-232`의 `render_contract_signature()`는 `scene_analysis`, `scene_requirement_context`, `scene_requirements`, `cover_selection`, `cover_product_crop`의 특정 함수 바이트코드(`__code__`)와 프롬프트 상수를 해시하여 완료된 편집본의 `repair_input_signature` 및 `semantic-plan-*.json` 캐시 키에 바인딩한다.
   - 따라서 이미 검증 완료된 영상들의 서명 정합성을 깨뜨리지 않도록 `render_contract_signature()` 대상 함수/상수는 본 수정에서 변경하지 않는다.
3. **Writing Job ID(`jid`) 결정론적 해시 불변성**:
   - `hotpost/writing/jobs.py:88-90`에서 `jid = 'codex' + sha256(kind + '\n' + identity + '\n' + raw)[:32]` 계산식은 원본 `payload` 전체(`raw`)를 기준으로 계산되어야 기존 캐시 및 완료된 집필/검수 작업 ID와 100% 호환된다.

---

## 3. 항목별 상세 수정 계획 (Detailed Modification Plan)

### 항목 A (P14 근본 해결): `data/writing/jobs.sqlite3` 구조적 비대화 해소 (4.91 GB → <10 MB)

#### 1) 원인 분석 (실측 데이터)
- `data/writing/jobs.sqlite3` 전체 크기: **4,912.8 MB (~4.91 GB)**, `journal_mode = delete`, 인덱스 없음(`PRIMARY KEY(id)` 외 `state` 인덱스 부재).
- 테이블 용량 분포:
  - `editorial` / `completed` (2,053건): `payload` **4,864.9 MB**, `result` **4.6 MB**
  - `editorial` / `failed` (7건): `payload` **23.9 MB**, `result` **0.0 MB**
  - `editorial` / `interrupted` (2건): `payload` **0.0 MB**, `result` `None`
  - `script` / `completed` (50건): `payload` **0.4 MB**, `result` **0.6 MB**
- 즉, **DB 용량의 99.5%(4,888.8 MB)**가 `editorial` 작업의 `payload` 컬럼에 인라인 저장된 Base64 이미지(`media[].inlineData.data`) 문자열이다.
- 반면 `Jobs.execute`는 실행 시 이미 `data/writing/<jid>/image-{i}.jpg`로 이미지를 디스크에 풀어서 저장하고 있으므로, SQLite 내부에 수 메가바이트짜리 Base64 문자열을 중복 보관할 이유가 없다.
- 또한 `Jobs.work`가 `SELECT id FROM jobs WHERE state='running'` 및 `WHERE state='queued' ORDER BY created LIMIT 1`을 실행할 때 인덱스가 없어 4.91 GB의 오버플로우 페이지를 풀스캔하며 수십 초간 락을 유발했다.

#### 2) 코드 수정 (`hotpost/writing/jobs.py`)
1. **WAL 모드 및 복합 인덱스 추가 (`Jobs.__init__`)**:
   - `CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created)` 추가.
   - 기존 DB 파일이 이미 대용량(`>100MB`)이고 `DELETE` 저널 모드인 경우 `VACUUM` 전 거대 `-wal` 파일 생성을 방지하기 위해, `Jobs.__init__`에서는 DB 파일이 경량(`<100MB`)일 때만 즉시 `PRAGMA journal_mode=WAL`을 켜고, 대용량 DB는 마이그레이션 스크립트에서 `UPDATE` + `VACUUM` 완료 직후 `WAL`로 전환한다.
2. **Payload 외부 파일 오프로딩 및 이미지 중복 제거 (`_save_payload`, `_compact_payload_media`, `_load_payload`)**:
   - `Jobs.create(self, kind, payload, identity='')`:
     - `jid`는 기존과 동일하게 `raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)`로 해시.
     - **[교차검증 보완 1 — 레이스 컨디션 방지]**: 백그라운드 `codex-writer` 워커 스레드가 `state='queued'` 행을 가져가는 즉시 `payload.json`을 읽을 수 있도록, **반드시 SQLite `INSERT OR IGNORE` 실행 전에** `self.root / jid / 'payload.json'`을 먼저 기록한다.
     - SQLite `INSERT OR IGNORE INTO jobs(...)`에는 `payload` 컬럼 값으로 `None`(`NULL`)을 저장하여 DB 페이지 비대화를 원천 차단.
     - 반환 시 `job = self.get(jid, include_payload=False); job['payload'] = copy.deepcopy(payload); return job`으로 불필요한 디스크 재읽기/재인코딩 방지.
   - `_compact_payload_media(self, jid, payload=None)`:
     - **[교차검증 보완 2 — 인메모리 불변성]**: 호출자의 인메모리 `payload` 딕셔너리를 변경하지 않도록 `copy.deepcopy(payload)` 사본에서 작업한다.
     - `self.root / jid / f'image-{i}.jpg'` 파일이 이미 디스크에 존재하고 크기가 `> 0`인 경우에만, `payload.json` 내 `media[i]['inlineData']`에서 대용량 `'data'`(Base64 문자열)를 제거하고 `{'_external_file': f'image-{i}.jpg', 'mimeType': mime}` 참조로 치환하여 디스크에서도 Base64 중복 저장을 제거한다.
     - `Jobs.execute`에서 `image-{i}.jpg` 추출 및 검증이 끝난 직후 `_compact_payload_media(job['id'], payload)`를 호출한다.
   - `_load_payload(self, jid, sql_payload)`:
     - `Jobs.get(self, jid, *, include_payload=True)`에서 호출(`include_payload=False`일 때는 기존 계약대로 반환 딕셔너리에 `'payload'` 키를 포함하지 않음).
     - `sql_payload`가 있으면 파싱하고, 없으면 `self.root / jid / 'payload.json'`을 읽는다.
     - 만약 `media` 항목 중 `inlineData`에 `'_external_file'`이 있으면 `self.root / jid / _external_file`의 바이트를 읽어 Base64 문자열(`'data'`)로 즉시 복원(Re-hydrate)하여 반환한다. 이로써 외부 호출자(`StudioAdapter`, `execute`, 기존 단위 테스트)는 이전과 100% 동일한 `job['payload']` 구조를 받는다.

#### 3) 기존 4.91 GB DB 무손실 마이그레이션 도구 (`tools/migrate_writing_jobs_sqlite.py`)
- **[교차검증 보완 3 — 워커 락·스트리밍·VACUUM 순서]**:
  1. `file_lock(root / 'worker.lock')`을 획득하여 마이그레이션 중 워커 스레드 개입을 차단한다.
  2. 메모리 스파이크 방지를 위해 `SELECT id FROM jobs WHERE payload IS NOT NULL`로 ID 목록만 먼저 조회한 뒤, 한 행씩 `SELECT payload, state FROM jobs WHERE id=?`로 스트리밍 처리한다.
  3. 모든 행에 대해 `data/writing/<jid>/payload.json`을 생성(이미 `image-{i}.jpg`가 존재하면 `_external_file` 참조로 압축 저장)하고 디스크 기록을 검증한다.
  4. 아직 `journal_mode=delete`인 상태에서 `UPDATE jobs SET payload = NULL WHERE payload IS NOT NULL` 및 `CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created)`를 커밋한다(WAL 전환 전에 수행해야 4.9GB `-wal` 파일이 생기지 않음).
  5. `isolation_level=None`(autocommit) 연결로 `VACUUM`을 실행하여 4.91 GB 파일을 즉시 축소한다.
  6. `VACUUM` 완료 후 `PRAGMA journal_mode=WAL;` 및 `PRAGMA wal_checkpoint(TRUNCATE);`를 실행한다.
  7. 마이그레이션 전후 행 수(`2,112`), 상태별 카운트, 샘플 `Jobs.get(jid, include_payload=True)` 복원 정합성 및 파일 크기(`4,912.8 MB` → `<10 MB`)를 JSON 리포트(`data/live-validation-20261014/sqlite-migration-report.json`)로 기록한다.

---

### 항목 B (D1·D2 일반화): 동적 중심 대상 명사구 허용 및 다국어 액션 쿼리 주어 보강 (`hotpost/source_queries.py`, `hotpost/source_planning.py`, `hotpost/browser_search.py`)

#### 1) 원인 분석
- **D1 (`hotpost/source_queries.py`)**:
  - `tiktok_product_queries(plan)`이 오직 정적 사전(`TIKTOK_NOUN_HEADS`)에 등록된 명사로 끝나는 쿼리만 통과시켜, 원문 캡션/음성에 문자 그대로 등장하고 `primary_subject(row, evidence)` 검증까지 통과한 미등록 한국어 상품 명사구(예: `'접이식 독서대'`, `'전동 네일케어'` 등)도 TikTok에서 `no_supported_queries`로 전량 탈락함.
  - **[교차검증 보완 4 — 하위 필터링(`tiktok_noun_phrase`, `platform_queries`, IPC 워커) 호환성]**:
    - `tiktok_product_queries` 마지막 줄(line 323)과 모든 호출부(`discovery.py`, `planner.py`, `browser_search.py`)의 `platform_queries(queries, 'tiktok', ...)`가 다시 `tiktok_noun_phrase(raw)`를 호출하므로, 검증된 동적 `primary_subject` 명사구를 `register_tiktok_noun_head()`를 통해 런타임 `TIKTOK_NOUN_HEADS[lang]`에 등록하고, 서브프로세스(`browser_search.py:_run_route`)에서도 부모가 전달한 `provider_queries['tiktok']`에 대해 동일하게 등록해야 하위 필터에서 탈락하지 않는다.
- **D2 (`hotpost/source_planning.py`)**:
  - `enrich_plan`에서 `subject_heads`를 구성할 때 정적 `PRODUCTS`와 `TIKTOK_NOUN_HEADS`만 참조하여, 미등록 상품의 경우 `subject_heads['en']`이나 `subject_heads['zh']`가 비어 있게 됨.
  - 또한 `subject_heads[lang][0]` 하나만 시도하여, 첫 번째 후보에 미검증 수식어가 포함된 경우 `grounded_named_terms`를 통과할 수 있는 두 번째 후보(`subject_heads[lang][1]`)를 시도하지 못함.

#### 2) 코드 수정
1. **`hotpost/source_queries.py` 및 `hotpost/browser_search.py`**:
   - `REVIEWED_OBJECT_GROUPS`에 빈출 라이프스타일·가전·리빙·주방 카테고리 다국어 그룹 추가(`독서대`/`book stand`/`阅读架`, `가습기`/`humidifier`/`加湿器`, `마사지기`/`massager`/`按摩器`, `캠핑 랜턴`/`랜턴`/`camping lantern`/`露营灯`, `거품기`/`milk frother`/`奶泡机`, `밀봉기`/`bag sealer`/`封口机`, `보풀 제거기`/`lint remover`/`毛球修剪器`, `주방 저울`/`kitchen scale`/`厨房秤`, `에어프라이어`/`air fryer`/`空气炸锅`, `계란찜기`/`egg steamer`/`煮蛋器`, `무드등`/`night light`/`小夜灯`, `충전기`/`charger`/`充电器`, `파우치`/`pouch`/`收纳包`, `텀블러`/`tumbler`/`保温杯`).
   - `_clean_tiktok_syntax(query)`와 `register_tiktok_noun_head(phrase)` 추가:
     - `tiktok_product_queries(plan, fallback=None)`에서 `plan.get('primary_subject')`가 `primary_subject(ps, evidence_dict)` 검증과 `grounded_named_terms`를 통과하고 동작 어미/조사가 없는 순수 명사구이면 `register_tiktok_noun_head(validated['name'])`를 호출해 `TIKTOK_NOUN_HEADS`에 등록하고(비-operator 요청 시 `rows`에도 포함), `tiktok_noun_phrase` 및 `platform_queries(..., 'tiktok', ...)`를 일관되게 통과시킨다.
     - `hotpost/browser_search.py:_run_route`에서도 `provider == 'tiktok'`이고 `provider_queries`에 `'tiktok'` 풀이 명시적으로 전달된 경우 `register_tiktok_noun_head`를 적용해 서브프로세스 경계를 넘어서도 동적 명사구가 유지되게 한다.
     - 단, 번역된 영/중 쿼리나 임의의 모델 생성 쿼리는 기존과 동일하게 `grounded_tiktok_noun_phrase`의 엄격한 사전 등가성 검사를 거치므로 `tests/test_query_rework_independent.py`의 오역·미관측 수식어·은닉 재료 차단 테스트를 100% 그대로 통과한다.
2. **`hotpost/source_planning.py`**:
   - `enrich_plan`에서 `subject_heads` 수집 시:
     - 기존 `plan['products']` 및 `TIKTOK_NOUN_HEADS` 매칭 외에, `result.get('tiktok_queries', [])` 및 `result.get('queries', [])`(`intent in {'subject', 'product', 'unbranded'}`) 중 `language(rq) == rlang`, `len(quote) >= 2 and quote in evidence.get(source, '')`, `not unidentified_measurement(quote)`, `grounded_named_terms(rq, evidence)`를 만족하는 짧은 명사구(4단어 이하, `_clean_tiktok_syntax` 통과)를 해당 언어(`ko`/`en`/`zh`)의 `subject_heads` 후보로 추가한다.
   - `accept()`에서 `action`/`technique`/`demonstrated_action`/`close_up_footage` 쿼리에 주어 명사를 보강할 때 `for head in subject_heads[lang]:`를 순회하며 `len(candidate_q) <= 120 and grounded_named_terms(candidate_q, evidence)`를 만족하는 첫 번째 `candidate_q`를 채택하고 즉시 `break`한다.

---

### 항목 C (D5 타이밍 한계 해결): 초기 `prepare` 및 `rewrite` 시점의 중심 대상(`product`) 조기 식별 (`hotpost/studio_automation.py`, `hotpost/studio_runtime/generation.py`)

#### 1) 원인 분석
- `prepare` 완료 직후 `rewrite`와 `collect_sources`가 병렬로 실행된다.
- 기존에는:
  1. `identify_subject(manifest, speech, fallback)`(`hotpost/studio_automation.py:242`)가 `product_query_plan(caption, [], [], {'speech': speech}, [])`를 호출할 때 `screen_text`를 전달하지 않았다.
  2. `_prepare`(`hotpost/studio_runtime/generation.py:86`)가 생성하는 초기 reference manifest에 `screen_text`가 누락되어 있었다.
  3. 정적 `PRODUCTS` 사전에 없는 상품의 경우 `collect_sources`가 `cached_enrich_plan`으로 추출한 `primary_subject`가 `data/source-query-plans/<identity>.json`에 캐시되는데도, 초기 `rewrite`는 `source_search_manifest_path` 파일이 완성될 때(15~20분 후)까지 이를 참조하지 못해 첫 대본 생성 시 `product='원작 중심 대상 미확인'` 상태로 시작되었다.

#### 2) 코드 수정
1. **`hotpost/studio_automation.py`**:
   - `identify_subject(manifest, speech, fallback)` 내부의 `product_query_plan` 호출 시 정규화된 문자열 `{'speech': speech, 'screen_text': screen_text}`를 전달하여 화면 자막(`screen_text`)에만 상품명이 있는 경우에도 즉시 식별되도록 수정.
   - `_resolve_rewrite_manifest(studio, state, manifest)` 헬퍼 추가:
     - `rewrite()` 시작 시 `manifest`에 `screen_text`가 없으면 `state.get('transcript_path')`에서 `screen_text`(`list[dict]` -> `str` 정규화)를 읽어 보강.
     - `identify_subject(manifest, ...)`가 `'원작 중심 대상 미확인'`이고 `not manifest.get('product_evidence')`인 경우:
       1. `studio.settings.source_dir.glob(f"{state['shortcode']}-*/manifest.json")`의 최신 `product_evidence`(수집 초기 32% 시점에 이미 기록됨) 확인.
       2. `studio.settings.data_dir / 'source-preparations' / state['shortcode']` 내 준비 번들 확인.
       3. `data/source-query-plans/<identity>.json` 캐시 파일을 조회(또는 `cached_enrich_plan` 호출)하여 `manifest['product_evidence']`로 연결 후 `identify_subject`를 재평가.
2. **`hotpost/studio_runtime/generation.py`**:
   - `_prepare()`가 `enabled(state)` 경로에서 초기 `manifest` 저장 시 정규화된 `screen_text`를 함께 기록하고, 전체 캡션(`post_caption(self.settings, state) or state['title']`) 기반 `identify_subject`로 초기 `product`를 계산해 유효한 경우 반환값 및 상태에 즉시 반영한다.

---

### 항목 D (D7b 일반화): `edit_id` 생성 이후 발생한 런타임/기술 실패(`pending='failed'`)에 대한 `resume-auto` 복구 (`hotpost/daily_quality.py`, `hotpost/quality_progress.py`, `hotpost/studio_workflow.py`)

#### 1) 원인 분석
- 현재 `resume_assessment(state)`(`hotpost/quality_progress.py:538`)는 `quality.get('pending') == 'failed' and not state.get('edit_id') and not unresolved(state)`일 때만 `pending='failed'`를 해제한다.
- 만약 (1) 1차 또는 2차 편집본(`edit_id`)이 이미 생성된 상태에서 아직 해당 편집본의 `quality_review`가 완료되기 전(`quality.get('reviewed_edit_id') != state.get('edit_id')`) `quality_review`가 기술적 오류로 실패했거나, (2) `refresh_sources` 도중 기술적 오류(`failed_job_kind == 'refresh_sources'`)로 `pending='failed'`가 된 경우, `state.get('edit_id')`가 존재한다는 이유로 초기 복구 분기를 타지 못하고 `reedit` 가설 검사에서 막혔다.
- **[교차검증 보완 5 — `studio.sqlite3` `jobs` 테이블 중복 키(`INSERT OR IGNORE`) 블로킹 해소]**:
  - `store.enqueue`는 `INSERT OR IGNORE INTO jobs(..., key=queue_key)`를 사용하므로, 이전에 실패한 `quality_review`, `refresh_sources`, 또는 초기 `edit` 작업이 동일한 `queue_key`로 `status='failed'` 상태에 남아 있으면 `pending`만 해제해도 새 잡이 큐에 등록되지 않는다.
  - 따라서 `resume_assessment`가 기술 실패를 복구할 때 `quality['resume_retry_count']`(또는 `refresh_sources`의 경우 `local_review_resume_count`)를 증가시키고, `advance_daily_quality`(`daily_quality.py`)와 `advance_workflow`(`studio_workflow.py`)가 `queue_key`에 `:retry:{resume_retry_count}`를 부여하여 새로운 잡이 정상 등록되게 해야 한다.
- 단, `tests/test_quality_progress_policy_independent.py:192-206`(`test_explicit_resume_cannot_reopen_failed_method_by_adding_known_source_url`)이 검증하듯, 이미 검수가 끝난 편집본에서 확정 실패한 `reedit` 방법(`ledger['attempts']`에 `status='failed'`로 기록된 방법)을 새 근거 없이 재실행하는 것은 계속 차단해야 한다.

#### 2) 코드 수정
1. **`hotpost/daily_quality.py`**:
   - `fail_daily_quality(self, job, error)`에서 `quality['failed_job_kind'] = str(job.get('kind') or '')` 및 `quality['failed_job_id'] = str(job.get('id') or '')`를 함께 기록.
   - `advance_daily_quality`에서 `stage == 'quality_review'`의 `queue_key` 생성 시 `quality.get('resume_retry_count')`가 있으면 `:retry:{int(quality['resume_retry_count'])}`를 접미사로 추가.
2. **`hotpost/studio_workflow.py`**:
   - `advance_workflow`에서 초기 `stage == 'edit'`의 `queue_key` 생성 시 `quality.get('resume_retry_count')`가 있으면 `:retry:{int(quality['resume_retry_count'])}`를 추가하고, `existing['status'] == 'failed'`로 인한 조기 반환을 피한다.
3. **`hotpost/quality_progress.py`**:
   - `resume_assessment(state)`에서:
     - **미검수 편집본 또는 초기 편집의 기술 실패 복구**: `quality.get('pending') == 'failed'`이고 `quality.get('failed_job_kind') in {None, '', 'edit', 'quality_review'}`이면서 `(not state.get('edit_id') and not unresolved(state))`이거나 `(state.get('edit_id') and quality.get('reviewed_edit_id') != state.get('edit_id'))`이면, `pending`과 `error`, `failed_job_kind`, `failed_job_id`를 정리하고 `quality['resume_retry_count'] = int(quality.get('resume_retry_count', 0) or 0) + 1`, `status='pending'`으로 복구한다.
     - **`refresh_sources` 기술 실패 복구**: `quality.get('pending') == 'failed' and quality.get('failed_job_kind') == 'refresh_sources'`이거나 `quality.get('pending') == 'scene_wait'`일 때, 로컬 미검수 소스(`pending_local`)·기술 오류 초기화(`cleared`)·입력 서명 변경(`sig != saved_sig`) 또는 `failed_job_kind == 'refresh_sources'`가 확인되면 `local_review_resume_count`를 증가시키고 `pending='recollect', status='repair'`로 전이한다.

---

## 4. 검증 계획 (Verification Plan for Current & Future Agents)

1. **서브에이전트 교차검증 (완료)**:
   - `Plan Cross-Validator` 서브에이전트가 교차검증한 5가지 핵심 보완 사항(위 `[교차검증 보완 1~5]`)을 계획 및 코드에 모두 반영함.
2. **단위 및 정책 회귀 테스트 실행**:
   - 신규 단위 테스트(`tests/test_structural_hardening_20261015.py`) 작성:
     - `Jobs` SQLite `payload` NULL 저장, `payload.json` 선기록 및 외부 분리, `_external_file` 이미지 중복 제거(인메모리 원본 보존 포함) 및 `get(jid, include_payload=True/False)` 무손실 복원/계약 검증, `idx_jobs_state_created` 인덱스 생성 검증.
     - 미등록 한국어 `primary_subject`(예: `'전동 네일케어'`)의 동적 TikTok 명사구 승인(`tiktok_product_queries`, `platform_queries(..., 'tiktok', ...)` 통과 포함) 및 오역/미관측 수식어 차단 유지 검증.
     - 미등록 상품의 다국어(`en`/`zh`) `subject_heads` 추출 및 다중 후보 `grounded_named_terms` 폴백 검증.
     - `identify_subject`의 `screen_text` 반영 및 `rewrite` 시점의 캐시된 `product_evidence` 조기 결합 검증.
     - `edit_id` 존재 후 미검수 상태(`reviewed_edit_id != edit_id`)에서 발생한 `quality_review` 기술 실패 및 `refresh_sources` 기술 실패의 `resume_assessment` + `advance_daily_quality` 큐 재등록 검증.
   - 기존 전체 관련 테스트 스위트 실행:
     - `pytest tests/test_structural_hardening_20261015.py tests/test_goal_live_defects.py tests/test_tiktok_query_policy.py tests/test_query_rework_independent.py tests/test_internal_writing.py tests/test_studio_adapter_identity.py tests/test_studio_editorial.py tests/test_quality_progress_independent.py tests/test_quality_progress_policy_independent.py`
3. **`data/writing/jobs.sqlite3` 실전 마이그레이션 및 검증**:
   - `python -X utf8 -m tools.migrate_writing_jobs_sqlite` 실행.
   - 마이그레이션 전후 DB 파일 크기(`4,912.8 MB` → `<10 MB`), `journal_mode == 'wal'`, 인덱스 존재 여부, 2,112개 전체 작업 행 수 일치 및 샘플 `get(jid, include_payload=True)` 복원 검증.
4. **보존 검증 (Preservation Check)**:
   - `python -X utf8 -m tools.live_validation_preservation verify` 실행하여 `preserved: true` 확인.
5. **결과 문서 작성**:
   - 모든 실행 결과, 실측 수치(Before/After), 생성/수정된 파일 목록, 재검증 명령어를 `docs/STRUCTURAL_HARDENING_RESULT_20261015.md`에 기록한다.
