# 영상 책임 에이전트 문제점 및 새 세션 인수인계

작성일: 2026-10-20, Asia/Seoul. 마지막 상태 조회 Unix 시각: 1792462928.

## 1. 결론부터

**3개 중 1개만 최종 완성 검증을 통과했다. “에이전트가 스스로 복구하여 3개 모두 끝까지 완성한다”는 사용자 요청은 미완료다.**

일부 복구 기능은 실제 운영에서 작동했다. 담당 에이전트가 직접 수정안을 작성하고 시험·독립 검토·적용·새 프로세스 로드·기존 작업 재개까지 진행했다. 그러나 공통 실행 구조를 root가 반복 수정해야 했으므로, root 개입 없이 완수하는 자율성은 입증하지 못했다. 시험 통과 수, 코드 변경 수, 호출 수, `active` 표시를 제작 성과로 보고하지 말 것.

최근 12시간 고정 감사 자료에는 행동 1,674건이 기록돼 있다. 코드 조회 742건과 이력 조회(`recall`) 177건으로 약 55%다. 조회가 모두 낭비라는 뜻은 아니지만 결과에 비해 진단 비중이 과도하다. 이 집계는 그 시점의 이동 시간창이며 새 조회에서는 숫자가 달라진다. 행동·적용 횟수는 고유한 수정 수와 다르다.

근거: `data/agent-progress-repair-20261019/twelve-hour-outcome-audit.json`.

## 2. 사용자의 요구와 작업 경계

- 영상마다 영속 담당 에이전트가 최종 영상 제작을 책임진다. 수동 요청과 예약 요청은 같은 실행 구조를 사용한다.
- 내부 오류, 잘못된 계획, 자막/블러/구간 검토 실패는 문제를 기록하고 해결해야 하며 사용자에게 해결책 제시를 요구하지 않는다.
- 사용자는 로그인 해제·CAPTCHA를 사용자 개입이 필요한 중지 사유로 지정했다. 실제 접근 제한·429의 대기 및 기존 검증 규칙은 우회하지 않는다. 기술 대기나 과거 로그인 표지만으로 영상 전체를 포기해서는 안 된다.
- **root가 소스를 대신 모으거나 렌더링·검수 승인·실패 이력 삭제·중복 제작 작업 생성으로 성공을 만들어 내면 안 된다.** 공통 실행 구조를 고치고, 담당 에이전트의 정상 복구와 실제 결과를 검증한다.
- v6 핵심 제품 원본 5개 우선 목표, 실제 영어5/중국어5 검색, 관련 원본 최소5개 및 최종 본문 활용 조건을 임의 완화하지 않는다. 정당한 부족 전환에는 현재 run의 실제 탐색·검토 근거가 필요하다.
- 기존 Chrome·VoiceBench·사용자 탭을 종료하거나 재시작하지 않는다. 기존 인증을 새 프로필·다른 계정으로 우회하지 않는다.
- 삭제한 완료 감시 자동화는 새로 만들지 않는다. 이번 인계 요청은 실행 중인 서버/담당 에이전트를 중지하라는 요청이 아니므로 그대로 두었다.

## 3. 정확한 대상 3개

| 대상 | task / shortcode | run | 마지막 확인 상태 |
|---|---|---|---|
| 에어텐트 | `work-33fa1ca3d69641b9` / `DeobnzrKCa1` | `run-94431a419d194f5e` | 완료 검증 통과 |
| 불꽃 | `work-ff0ee01205f2467e` / `Deogf81Se6b` | `run-ec85670c383e45fc` | 관련9·핵심3, EN5/ZH5. 검색 범위 대기 반복, 최종 영상 없음 |
| 향수 | `work-56d49cbfc5a64c1c` / `DenReaeTiaA` | `run-a202941b1cda4131` | 소스0, 내부 준비 실패 뒤 담당 에이전트 진단 중, 최종 영상 없음 |

싱크대·오리·미역국 등 과거 대화의 작업과 혼동하지 말 것. 이번 검증 대상은 위 세 개다.

### 에어텐트 완료 근거

- 최종 edit: `job-efcdcf2542854bd4`.
- 파일: `data/studio/work-33fa1ca3d69641b9/job-efcdcf2542854bd4/preview.mp4`.
- SHA256: `212b053fa5339ac618ee5aac2af2a6a55e8199abc4ba26d1f05d3a9c58bc5547`.
- 입력 fingerprint: `9168921cf2df53fd21b3858789f8d39890a2ea4bb22978ff1bb754796135bc3b`.
- H264 1080×1920, AAC, 약15.033초. API ready, owner completion, 현재 파일/검수/입력 결속을 재확인했고 전체 디코딩도 성공했다.
- 근거: `completion-verification.json`, `final-three-media-verification.json`, `media-decode-work-33fa1ca3d69641b9.json` (모두 아래 감사 디렉터리).
- 보기: <http://127.0.0.1:8775/studio.html?work=work-33fa1ca3d69641b9>.

## 4. 미해결 문제와 원인

### P0 — 동일한 검색 전 점검을 새 진전으로 오인한다

불꽃의 현재 작업은 `job-f0a99c40533f423f`다. 같은 작업에서 claim → 접근/검색 범위 점검 → 대기를 반복했다. TikTok/Yandex는 `query_exhausted`, 여러 다른 플랫폼은 `not_attempted`, YouTube는 과거 수동 로그인 재확인 대기다. 저장된 `source_acquisition.waiting`, `receipt_wait`, `hold`는 해당 감사 시점에 없고 `no_progress_rounds=1`이었다.

확인한 원인:

1. `hotpost/video_agent_context.py::job_method_fingerprint`가 `source_access_preflight.at`와 observation의 `observed_at`를 일반적인 범위 소진 대기에서는 진전 지문에 포함한다. 기존 정규화는 `parser_repair_context`가 있을 때만 적용된다.
2. 따라서 검색어·범위·수신 영상·검토 결과가 그대로인데도 점검 시각 변경으로 지문이 바뀐다. `VideoAgentManager.step`의 무진전 관찰 시작 시간이 다시 잡힌다.
3. `recovery_target`은 `deferred_wait`와 미래 `not_before`를 일반 서비스/접근 대기로 취급한다. 범위 소진에 따른 내부 계획 문제를 담당 에이전트 진단으로 넘기는 분기가 부족하다.

**현황: 원인은 확인했지만 수정 코드는 아직 구현·시험·배포하지 않았다.**

- 신규 파일 `tests/test_video_agent_scope_wait.py`는 작성만 한 **미실행 회귀 시험 초안**이다. 통과한 시험으로 보고하지 말 것.
- `captured-scope-preflight-wait.json`은 원본 queued job과 최소 상태의 읽기 전용 캡처다. 유휴 배포를 위해 일시 예약 시각을 미룬 기간에 캡처했으므로 `not_before`를 실제 실패 본질로 그대로 고정하지 말 것.
- 수정 방향: 점검 시각과 claim 변경을 진전에서 제외하되, 실제 상태·사유·검색 범위·미디어·검토 내용 변화는 유지한다. 작업/run에 결속된 내부 범위 소진만 진단 대상으로 예약하고, 정상 서비스 대기·실제 접근 차단·명시 사용자 중지는 보존한다.
- 이 수정은 부족 근거를 임의 승인하거나 더 낮은 품질로 완료시키는 수정이 아니다. 담당 에이전트가 수집/검토/부족 판정의 실제 원인을 고치도록 연결하는 공통 구조 수정이다.

### P0 — 향수는 빈 검색어 풀을 만들고 준비 단계에서 멈춘다

현재 동일 child job: `job-7acdf5827d1d4127`, parent `job-485595b8bd9e412d`. child round7, `planning_recovery_from` 유지.

마지막 실제 재실행은 claim `claim-8901a467db0e484d`, 시작1792461259.220828, 실패1792461434.0676787. `PreparationEvidenceWaiting`: 계획 복구의 독립 검토 검색 근거 부족. job은 paused이고 담당 owner는 recovering이다. 로그인/CAPTCHA로 확인된 실패가 아니다.

새 실제 제안은 `queries=[]`, EN0/ZH0이었다. 화면은 인물/인터뷰/리액션 위주이고 제품 설명은 캡션에 있다. 생성 측은 “화면에 상품이 안 보인다”를 “검색어를 만들 수 없다”로 처리했다. 독립 검토는 제공된 텍스트를 근거로 검색할 수 있는데 빈 풀을 만든 점을 지적했다.

검토할 방향은 캡션의 실제 문구에 결속된 **검색 가설**과 픽셀로 검증한 제품 정체성을 구분하는 것이다. 텍스트를 근거 없는 시각적 제품 승인으로 승격하거나 모델명을 지어내지 않는다. 기존 관찰/프레임 링크 필수 조건과 독립 검토 계약의 충돌도 함께 점검해야 한다. **이 방향은 해결 완료된 구현이 아니다. 담당 에이전트가 실제 원문 근거로 수정·시험·독립 검토해야 한다.**

실제 자료:

- manifest: `data/source_jobs/DenReaeTiaA-1792461259899671100/manifest.json`.
- visual input SHA: `204b7a08603a82a67ecb4c21c0b0cfee06cbd54d33e5eba9358e125ae60a9b08`.
- 새 diagnostics: `data/source-visual-pool-recoveries/c84f72f3b0e72c0cdb4e72209c0610d53408956fe745aee1e24cad6b75336ea7/`의 `proposal.json`, `review.json`, `receipt.json`.
- receipt SHA: `b32e45bae5f0646a2d9e1b33872098774b1669855a2a7a41d68bb43734a5ba66`.

### P1 — 진단·수리의 반복 비용이 제작 성과보다 크다

- 검사/조회/재제안/시험/검토가 많아도 소스나 영상이 늘지 않을 수 있다. 단계별 새로운 증거와 실제 결과를 기준으로 진전 판단이 필요하다.
- 작업/수정 ID·시각·코드 SHA만 달라지는 것을 미디어 진전으로 인정하지 않는다.
- 이미 읽은 증거를 반복 조회하거나 동일 실패 가설을 재포장하는지, 단계 전환 조건이 다시 확인을 요구하는지 점검해야 한다.
- 불꽃의 재개 수집 라운드는 약79분 소요됐다. 무관한 분무기/페인트 후보도 서로 다른 짧은 구간으로 여러 번 검토했다. 다른 구간의 거절은 새 검토 기록이지 유효 재고 증가가 아니다. 시간만 보고 정상 검토를 중단하거나 무관 영상을 승인해서는 안 된다.
- 처리량 향상이나 “어떤 상황에서도 완수”는 측정·입증되지 않았다.

### P1 — 수정안 적용과 증거 전달의 공통 구조가 반복적으로 막혔다

아래 항목은 이번 과정에서 고쳐 실제 적용했으나, 전체 자율 완수를 의미하지 않는다.

- 격리 시험에 원래 준비 자료/이전 원인 영수증이 빠져 실제 사건을 재현하지 못함.
- 담당 에이전트가 자신의 중첩/평탄화 진단 파일을 읽을 권한 경로를 받지 못함.
- 내부 준비 대기로 paused된 정확한 job에 독립 승인된 수정을 적용하기 위한 정상 주차 경로가 없음.
- 새 공통 코드가 과거 승인 코드 SHA를 대체하면 서비스 시작 자체가 실패함. 인증된 과거 영수증과 현재 로드 권한을 구분하도록 보완.
- 새 증거가 생겨도 과거 진단/시험 컨텍스트만 반복 제공되는 문제.

## 5. 실제 작동한 자율 복구와 최신 배포

### 불꽃

`repair-e9ce6eb513324db4aade818515caa66c`: 114개 시험, 독립 승인 후 담당 owner가 정상 park/apply 수행. 적용1792456439.5505, 새 프로세스 로드1792456450.131519. **원래 job `job-ad8c5c4b516b448c`를 재개**하여 실제 검색/수집이 진행됐다. 이후 정상 후속 작업으로 관련9/핵심3까지 증가했다.

증거: `spark-same-job-autonomous-recovery.json`. 현재는 위 P0 범위 점검 반복에 다시 걸려 있다.

### 향수

`repair-cfd15d91c83c485aa7185c25773736b1`: 160개 시험/3skip, 독립 승인 후 실행 중인 소스 작업이 끝나자 자동 적용1792461204.7516205. 새 프로세스가 `source_visual_queries.py` SHA `b8259644dd5d98171a314bf791613cc5385fc2317a555b2f421ec3877dc5b528`를 로드하고 같은 child job을 재개했다. 원래 경로 실패는 넘었지만 새 빈 검색어 문제로 실패했다.

증거: `perfume-paused-child-autonomous-recovery.json`. 오래된 applied 기록만으로 현재 로드됐다고 판단하지 않는다.

### 최신 공통 변경: deployment53

- 파일: `hotpost/video_agent_context.py`, `tests/test_video_agent_pool_diagnostics.py`.
- 담당 job/run/input SHA에 묶인 원래 중첩 receipt에서 정확한 평탄화 진단 디렉터리를 계산한다. 고정된 JSON3개만 제한된 크기로 제공한다. 미디어 승인 권한을 부여하지 않는다.
- 독립 review101: 영수증 없는 폴더가 읽기 한도를 소진하는 문제 발견 → 수정.
- review102: 무관한 폴더 열거 오류가 기존 직접 파일 조회도 막는 문제 발견 → 수정.
- review103 승인. 최종 관련 시험 **432 passed / 8 skipped**. 전체 저장소 green을 뜻하지 않는다.
- 배포 시각1792462473.587456. 당시 실제 서버PID25708. **PID는 재사용/변경될 수 있으므로 새 세션에서 다시 확인한다.**
- 임시 스케줄 예약은 finally에서 복원했고 Chrome/VoiceBench는 재시작하지 않았다.
- `state_rows_preserved=false`: 시작 중 향수 task revision 등이 변했다. 후속 조회에서는 기존 task/job ID 누락과 신규 ID가 없었다. **모든 행이 동일하게 보존됐다고 보고하면 안 된다.**
- 배포 후 향수 owner가 새 receipt 경로를 받아 `inspect_artifact`로 실제 조회한 것을 확인했다. 따라서 증거 접근 수정은 실제 효과가 확인됐다.
- 소스 범위 무진전 수정은 이 배포에 **포함되지 않는다**.

## 6. 새 세션 시작 순서

1. `AGENTS.md`, 이 문서, `docs/CODE_MAP.md`, 필요한 관련 모듈만 읽는다. 대규모 dirty tree와 다른 세션의 수익화 변경을 보존한다. reset/clean/일괄 덮어쓰기 금지.
2. 현재 listener/서버 명령/담당 owner/진행 중 시험·적용 프로세스를 확인한다. 이전 배포/모델 명령을 중복 실행하지 않는다. 문서 snapshot이 현재 상태라고 가정하지 않는다.
3. 아래 경량 조회로 정확한 세 작업만 확인한다. 완료된 에어텐트를 다시 제작하지 않는다.
4. P0 불꽃 무진전 감시부터 실제 캡처와 회귀 시험으로 고친다. 미실행 초안 시험의 API/가정부터 검증한다. 실제 상태/접근 제한 변화가 지문에 남는 음성 사례, 동일 job의 반복 claim/defer 뒤 owner 예약과 정상 worker 차단, 다른 작업 불간섭을 확인한다.
5. 공통 수정은 독립 검토 및 유휴 적용·실제 로드 확인 후 효과를 확인한다. 실행 중 작업을 강제 종료해서 유휴로 만들지 않는다. 기존 배포 스크립트의 PID·입력 SHA·startup 실패·row 비교 한계를 검토한 뒤 사용한다.
6. 향수 owner가 새 증거를 읽고 도메인 수정→시험→독립 검토→적용→같은 job 재개로 진행하는지 확인한다. root가 검색어/소스/미디어 승인을 대신 작성하지 않는다.
7. 불꽃도 범위 소진/미완료 검토/부족 전환의 정확한 원인을 담당 owner가 해결해야 한다. 소스9개가 있다는 이유로 핵심 제품 정책을 무시하지 않는다.
8. 세 작업 모두 실제 최종 완료 조건을 만족할 때만 성공이라고 보고한다. 그렇지 않으면 완료 수, 실제 진전, 미해결 원인, 적용/미적용을 구분한다.

## 7. 경량 확인 명령과 완료 기준

작업 폴더: `C:\Codex\인스타자동화\insta_auto`. Python: `.\.venv\Scripts\python.exe -X utf8`.

```powershell
.\.venv\Scripts\python.exe -X utf8 data/agent-progress-repair-20261019/live_three.py
.\.venv\Scripts\python.exe -X utf8 data/agent-progress-repair-20261019/watch_short.py
.\.venv\Scripts\python.exe -X utf8 data/agent-progress-repair-20261019/owner_detail.py
.\.venv\Scripts\python.exe -X utf8 data/agent-progress-repair-20261019/verify_completion.py
```

`live_three.py`는 완료된 에어텐트를 생략하고 나머지 둘을 출력한다. 실행 중 batch의 partial 값은 아직 task에 확정 수용된 최종 재고와 구분한다.

API는 `http://127.0.0.1:8775/api/studio?view=list`에서 정확한 task3개만 필터링한다. 전체 상세 목록, 거대한 DB payload/base64, 전체 acquisition 이력을 출력하지 않는다. 특히 이전 감사에서 전체 acquisition 출력이 매우 커졌으므로 금지.

완료 판정은 `completed_video_ready=true`, `video_agent.completion.completion_verified=true`, 현재 edit/대본/음성/입력 fingerprint와 실제 결과 파일 SHA·QA·export 결속을 모두 확인한다. 최종 파일은 `verify_completed_media.py`로 전체 디코딩도 확인한다. 이 도구는 제작하지 않고 검증 결과만 저장한다.

## 8. 증거와 미완성 파일 색인

공통 증거 루트: `data/agent-progress-repair-20261019/`.

| 파일/폴더 | 용도/주의 |
|---|---|
| `twelve-hour-outcome-audit.json` | 12시간 실측, 1/3완료, 행동 집계 |
| `completion-verification.json` | 가장 최근 API·owner·파일/QA 결속 |
| `final-three-media-verification.json` | 최종 디코딩, 당시 decoded1/all_three=false |
| `spark-same-job-autonomous-recovery.json` | 불꽃의 실제 적용·로드·원래 job 재개 |
| `perfume-paused-child-autonomous-recovery.json` | 향수의 실제 적용·로드·같은 child 재개 |
| `captured-scope-preflight-wait.json` | 무진전 점검 사건, 일시 스케줄 lease 시각 주의 |
| `pool-diagnostics-live-proof.json` | 새 진단3개 경로/해시의 읽기 전용 증명 |
| `pool-diagnostics-reviewed-final.xml` | 432pass/8skip |
| `independent-review-101..103/result.json` | 지적2회와 수정 후 승인 |
| `deployment-53/receipt.json`, `deployment-53/loaded.json` | 배포/모듈 로드, row 동일성false 주의 |
| `deployment-schedule-drain-53-all.json` | 일시 예약 변경과 finally 복원 |
| `implementation-audit.json`, `refresh_audit.py` | **최신53을 반영하지 않은 부분이 있음. 이 문서 및 실제 receipt 우선** |
| `autonomous-applied-repairs.json` | 역사적 적용 목록. 전부 이번 세션 수정이나 현재 유효 로드가 아님 |
| `tests/test_video_agent_scope_wait.py` | **미실행·미완성 시험 초안. 대응 production 수정 없음** |

기존 baseline 실패도 남아 있다. 전체 green으로 주장하지 말 것:

- `test_source_pause_history.py::test_app_death_active_pointer_is_hold_not_new_attempt`: 이전 코드에서도 `SourceReceiptWaiting` 기대 불충족 재현.
- `test_source_visual_query_minima_v5::test_zero_received_review_gates_search_only_and_avoids_unneeded_downloads[missing_inventory]`: 기존 테스트 lambda가 새 `inventory_only` 키워드를 받지 못함. 이전 단계 코드에서도 재현.
- 각각 `preexisting-source-pause-baseline.xml`, `preexisting-minima-fixture-baseline.xml` 참조.

## 9. 다른 세션 작업과 분리

인스타 업로드·리틀리·상품 확인 계정/연결 인계는 `docs/INSTAGRAM_UPLOAD_REVIEW_HANDOFF_20261019.md`와 기존 `docs/HANDOFF.md`의 최신 수익화 절에 있다. 이번 문서는 영상 책임 에이전트 문제 인계이며 수익화 변경을 취소하거나 재실행하라는 지시가 아니다. 계정 비밀값은 출력하지 않는다.

이번 문서화에서 추가 제작 트리거·렌더·승인·배포·서버 중지·커밋은 하지 않았다. 정상 실행 중인 담당 에이전트의 상태는 문서 작성 후 바뀔 수 있다.

## 10. 2026-10-20 후속: 범위 점검 무진전 수정과 검색 조건 충돌 확인

아래는 위 최초 인계 이후의 별도 작업 결과다. 최초 인계의 미구현·미실행 표시는 당시 상태로 보존한다.

### 공통 P0 수정·검증·운영 반영

- `job_method_fingerprint`는 일반 범위 대기에서도 `source_access_preflight.at`와 관측 `observed_at`를 진전에서 제외한다. 실제 상태·사유·검색어·페이지 범위·재시도 시각·소스·검토 내용은 유지한다. 저장된 증거 자체는 바꾸지 않는다.
- `scope_repair_context`는 현재 task/run과 결속된 미시도 범위 소진만 내부 진단 대상으로 인정한다. 준비된 경로·미완료 수신·hold·실제 접근 실패·미래 retry·사용자 중지는 기존 게이트를 유지한다. 이 예외는 진단 예약용이며 검색 요청·소스 채택·부족 전환을 승인하지 않는다.
- `VideoAgentManager`의 실제 DB 조회에도 task_id를 유지하고, 내부 범위 대기 작업을 담당자의 수정 대상에 포함했다. 정상 worker의 재claim은 해당 예약 작업만 차단한다.
- 인계의 초안 시험에는 pulse 미설정, `defer(seconds)`에 절대 시각 전달, `waiting=True` 누락이 있었다. 실제 API 계약에 맞춰 고쳤으며 시험을 통과시키려고 production API를 바꾸지 않았다.
- 별도 독립 검토 승인, 관련 전체 실행 **577 passed / 10 skipped**. 독립 검토자는 핵심 세 시험 파일을 별도로 실행해 **103 passed**를 확인했다. 전체 저장소 green을 뜻하지 않는다.
- 진행 중 모델이 자연 종료한 뒤 Studio·writing·별도 collection DB를 모두 잠그고 유휴 상태를 확인해 반영했다. 기존 배포 helper에 빠졌던 collection 큐 확인도 추가·독립 검토했다.
- 새 실제 listener PID **21668**, API `/api/criteria` 200. PID는 이후 담당자의 정상 배포에서 바뀔 수 있다. 실제 source loader가 실행한 두 모듈 SHA가 독립 검토 대상과 일치한다.
- 일시 스케줄 필드는 finally에서 복원했다. Chrome/VoiceBench는 재시작하지 않았다. 기존 task/job ID 누락·신규 ID는 없고 job 상태도 당시 비교에서 동일했다. **향수 task revision/state는 시작 중 달라졌으므로 모든 행 불변이라고 보고하지 않는다.**
- 배포 뒤 불꽃은 기존 같은 job에서 자신의 parser 복구 초안을 실제 시험했다. 이는 이번 범위 지문 수정으로 새 소스가 늘었다는 증거가 아니다. 현재는 별도의 parser 복구 경로를 담당자가 수정 중이며, 일반 범위 소진 재발에 대한 운영 효과는 이후 관측해야 한다.

근거 루트: `data/agent-progress-repair-20261020/`.

| 근거 | 내용 |
|---|---|
| `scope-wait-tests.xml` | 577통과/10skip |
| `scope-wait-independent-review.json` | 검토 범위·승인·정확한 소스 SHA |
| `scope-wait-deployment/{before,expected,loaded,receipt}.json` | 유휴 반영·실제 로드·listener·행 비교 |
| `scope-wait-deployment/schedule-leases.json` | 일시 예약과 finally 복원 |
| `completion-after-deployment.json` | 기존 에어텐트 완료 결속 유지·나머지 미완료 |

### 검색어 기준이 과도한 구체적 근거

1. 향수 제안은 실제 캡션의 브랜드·농도·제품 설명이 있어도 관련 제품 픽셀이 없다는 이유로 `queries=[]`를 반환한다. `source_visual_queries.validate`는 모든 검색어에 제품 관련 observation/frame 링크를 요구한다. **원문에 근거한 검색 가설**과 **픽셀로 확인한 후보 제품 채택**을 분리할 필요가 있다. 제품 모델을 추측하거나 원문을 픽셀 승인으로 바꾸는 것은 해결책이 아니다.
2. 동일 사건의 `proposal.json`은 최상위 `proposal` 아래에 subject_identity를 저장한다. 그 영문 필수어는 `Dior` + `perfume` + `eau de toilette` + `floral` + `bottle-neck jacquard ribbon`이다. 최소9단어인데 `_clean_tiktok_syntax`는6단어 초과를 거절한다. **정정: 이 충돌은 TikTok 영문 전송의 구문 조건이다. 모든 provider의 영문 검색이 불가능한 것으로 일반화하지 않는다.**
3. 모든 부가 특징을 필수어로 고정하지 않고 제품을 구별하는 최소 조건과 검색 변형을 구분해야 한다. 정체성 변경도 실제 원문에 결속된 새 독립 검토를 거쳐야 하며, 이전 승인·검색 실적·실패 이력을 덮지 않는다. EN5/ZH5·핵심 원본5 우선 및 본문 관련 원본5의 기존 사용자 정책은 이번 공통 수정으로 변경하지 않았다.

향수 담당자는 별도 텍스트 영수증과 준비→실제 전송 연결을 스테이징하고 있으며9단어/6단어 충돌도 인지하고 있다. **초안은 미적용이며 실제 검색·소스 확보 성공은 아니다.** root가 담당자의 검색어·소스·미디어 승인을 대신 작성하지 않았다.

### 배포 직후 실제 제작 상태

- 에어텐트: 완료 검증 유지. 결과 SHA `212b053fa5339ac618ee5aac2af2a6a55e8199abc4ba26d1f05d3a9c58bc5547` 그대로.
- 불꽃: 관련9/핵심3, EN5/ZH5. 같은 `job-f0a99c40533f423f`. 담당 parser 복구 초안의 첫 시험은119통과/1실패로 보류됐다. 실패를 승인·운영 적용으로 보고하지 않는다.
- 향수: 관련0/핵심0, EN0/ZH0. 같은 `job-7acdf5827d1d4127` paused, 담당자는 새 검색 경로를 수정 중.
- 실제 완료는 여전히 **1/3**이다. 공통 P0 코드 반영과 두 영상의 완성을 구분한다.

추가 관측: 시작 경로의 `resume_loaded_repairs`가 이미 수용된 `loaded-repair-resume` 결정을 다시 조회해 과거 queued 결과를 owner에 재기록한다. 실제 향수 job은 paused와 이전 updated를 유지했지만 task revision 및 owner의 last_action/pending은 바뀌었다. 실행 재시도의 중복 방지는 유지되지만 과거 행동이 새 진전처럼 표시될 수 있다. 이는 이번 수정에 포함하지 않았고, 향후 공통 진전/시작 멱등성 점검 대상으로 남긴다.

## 11. 실패 영상 감시·연속 수정 후속 — 13:34 KST

최신 상세 기록은 `docs/FAILED_VIDEO_CONTINUATION_20261020.md`, 영상별 읽기 전용 감시는 `FAILED_SPARK_WATCH_20261020.md` / `FAILED_PERFUME_WATCH_20261020.md`다. 기존 영상 담당자가 정상 제작·복구를 계속 맡고 별도 감시·독립 검토를 두었다.

공통 host는 다음을 시험·독립 검토·유휴 적용하고 실제 source loader SHA 및 효과를 확인했다.

- 시작 시 이미 수용한 loaded resume 영수증을 다시 owner에 재기록하지 않는 멱등성.
- 실제 등록 원본 프레임 bytes/SHA/signature를 immutable isolated fixture에 전달. 모델 입력/incident navigation에는 raw bytes를 제외. 불꽃12개 원본과 복원본이 실제 `fresh_frames=[]` 소진 관계를 유지함.
- 앞선 지문 정규화로 과거 parent 영수증 검증이 깨진 회귀 보완. legacy fingerprint는 기존 parent durable continuation 검증에만 허용. 현재 retry영수증·정확한 action·후속 실행/중지/park 부재·supervision hold 부재를 검증한 후 정상 queue가 같은 향수 child를 새token50573로 claim. parent행과6개 과거영수증 보존.
- 유효한 text 계획을 owner식별자 누락으로 false표시하던 읽기 전용 진단 보완. 실제 persisted 준비 선택에서만 owner를 가져오고 real validator를 유지. e6c077 번들의 `current_query_contract=true`가 실제 owner 모델 payload까지 전달됨. 최신 해당 배포 PID45132/contextSHA c1e3a6c3…(이후 정상 적용으로 PID변경 가능).

향수 도메인 수정93fe…는169통과/3skip·독립 승인·적용·로드 후 실제 원문 제안과 검토에 도달했다. cff9f065… 영수증에는 EN5/ZH5의 유효한 **계획**이 있고 e6c077… 번들이 저장됐다. 실제 검색횟수는 여전히0이다. 이후 과거 다른주제 TikTok page_unresolved와 parser 응답 unavailable로 보류되었다. 옛 checkpoint의 FileNotFoundError/PreparationEvidenceWaiting을 이번 새 실패로 오인하지 않는다. 담당자가 유효한 준비 계약을 인정하고 실제 접근 분기를 진단 중이다.

불꽃은 원본 픽셀·기존 소진 이력과 동시 parser single-scroll 변경을 보존하는95eb6d… 초안에서 외부 제안·독립 검토·새번들 저장·동일job선택·후속 접근 gate까지 긍정 통합시험이 통과했다. 독립 검토·적용·실제 수집은 아직 별도다. 관련9/핵심3, EN5/ZH5 그대로다.

실제 완료는 **1/3(에어텐트만)**. 공통 코드 수정·담당 도메인 시험·검색 계획·실제 검색·소스 확보·최종 완료를 분리한다. 삭제한 완료 자동화를 재생성하지 않았고, Chrome/VoiceBench를 재시작하거나 생산 보류를 운영 SQL로 강제해제하지 않았다.
