# 2026-10-16 오늘 1위 제작 오류 관찰

대상은 오늘 오전 수집 급상승순 1위 `Defg3rTBA3M`, 제작 작업 `work-32b187bd4c1a405c` 하나다. 오류 감시 에이전트는 운영 DB·브라우저·코드를 수정하지 않고 관찰한다. 수정과 재개는 주 에이전트가 담당한다. 기존 이력을 보존하며 정상 서비스 대기와 미시도를 실패로 세지 않는다.

## 실제 관찰

| 관찰 시각(KST) | 상태·실제 근거 | 판단 |
|---|---|---|
| 2026-10-16 19:17 | `data/studio/studio.sqlite3`를 읽기 전용으로 조회. 대상 revision 8, `attention`, `prepare` 작업 `job-afa4eb57103842c0`는 `failed`. 최초 failed 이벤트는 2026-10-16 07:26:13 부근. | 원본 화면 인용문 검토 실패가 실제 중단 원인이다. 현재 검색/CAPTCHA 실패가 아니다. |
| 2026-10-16 19:17 | 오류 기록: 이미지 키 `52f4e430f6664ca59468a2af813b53e9`에서 `[광고]` 일부가 샤워기에 가려 전체 인용문을 판독할 수 없으며, 나머지 프레임 인용문은 보이는 문구와 일치. 발화는 빈 문자열. | 일부 문구 미확인이 전체 준비 단계 중단으로 이어졌다. 수정을 적용해 해결됐는지는 아직 확인하지 않았다. |
| 2026-10-16 19:18 | `data/transcripts/Defg3rTBA3M-1792103083303743600/transcript.json`의 duration 11.42초, speech 빈 배열. 화면 OCR은 `목욕 전쟁 도분 만에 끝`과 `목욕 전쟁 5분 만에 끝`으로 혼재. `reference.mp4`, `ocr_frames`, `reference-text-frames` 원본 자료 존재. | OCR 원시 결과를 확정 사실로 사용할 수 없다. 화면 문구와 발화 구분은 보존해야 한다. |
| 2026-10-16 19:18 | 같은 대상의 scripts/voices/edits/sources는 빈 배열, operation_progress 없음. TCP 127.0.0.1:8775는 PID 23080이 Listen 상태. | 서비스가 살아 있다는 증거와 이 제작 작업이 실행 중이라는 증거를 구분한다. 현재 이 제작 job은 실패한 준비 상태다. |
| 2026-10-16 19:19 | `reference-text-frames/mask-evidence-52f4e430f6664ca59468a2af813b53e9.png`를 직접 열어 확인. 큰 본문 `발버둥 치던 댕냥이들`과 `목욕 전쟁 5분 만에 끝`은 읽히고, 우측 상단 작은 `[광고]` 글자 일부에 샤워기가 겹친다. 고양이가 목욕 지지대에 서 있는 장면이다. | OCR의 `도분`은 이 이미지에서 실제 `5분`의 오인식으로 확인된다. 광고 표기의 가림과 큰 본문 판독 가능성을 분리해야 한다. 이 관찰만으로 시간 단축 효능을 사실로 입증하지는 않는다. |
| 2026-10-16 19:20 | DB revision 12, `preparing`, message `원본의 음성·화면 참고 내용을 구분하는 중`, error 빈 문자열. 같은 `job-afa4eb57103842c0`가 `running`, 새 claim `claim-34ca9f900b5344b9`, `auto_retries=0`. 8775 Listen PID는 39948. 이 PID의 자식 `codex.exe` PID 39188이 실제 생성됨. 참고 이미지 수는 9개에서 18개로 증가. | 동일 대상의 정상 준비 재개와 새 모델 검토 실행을 확인했다. 초기 오류를 또 실패했다고 세지 않는다. 실제 모델 결과는 아직 대기 중이다. |
| 2026-10-16 19:20 | `hotpost/source_search/library.py`와 `catalog.py`를 읽고 `data/source_jobs/*/manifest.json` 150개, candidate 683행의 제목·관찰 동작 및 실제 후보 파일 존재 여부를 조사했다. 파일이 존재하는 행은 422개(중복 원본 포함). 목욕/샤워/浴/bath/groom/반려/고양이/猫 및 pet·cat 지지대 확장 탐색의 3개 제목 일치는 난방텐트 2행(`浴霸灯`)과 싱크대 물막이 1행(실제 파일 없음)이었다. | 반려동물 목욕 지지대 관련 실제 로컬 후보를 확인하지 못했다. 제목·관찰 메타데이터 범위의 조사이며 전체 보관 파일을 시각 검토했다는 뜻이 아니다. 원본 reference.mp4는 신규 소스로 재사용하지 않는다. 네트워크 요청과 모델 실행은 하지 않았다. |
| 2026-10-16 19:20:57 | DB revision 25, `rewriting`, 오류 없음. 같은 prepare job은 `done`. 새 `rewrite` job `job-9fe2008536134fc2`, `collect_sources` job `job-083c251ee3b04660`가 running. original_text가 실제 읽히는 큰 문구 두 줄로 저장됐다. source_attempts는 실제 원본 SHA `1c2d609d0adeaa9d79997840d2705abfacd89d20ab81017e90e3e7bb98bb3208`와 새 manifest 경로에 결속됐으며 workers는 빈 배열. PID 39948과 그 자식 codex.exe 29784를 현재 확인. | 준비 오류는 실제 재개에서 해소되어 집필·소스 준비로 진전했다. 빈 workers 배열만으로 실제 외부 검색이 수행됐다고 보지 않는다. |
| 2026-10-16 19:23 | DB revision 42, 후보 비교 대기. 첫 collect_sources job은 done이지만 실제 manifest 후보는 0개. search_audit는 `google-vision/not_attempted/existing_browser_session_required`, `browser-worker/connection_failed`. 새 collect_sources job `job-ca25df7fcad14570`는 19:23:37 이후 실행 예약. source_acquisition.waiting에 동일 연결 상태가 보존됨. | 실제 검색·다운로드는 0회이며 CAPTCHA 근거는 없다. 연결 미확인 대기와 콘텐츠 품질 실패를 구분한다. 새 예약이 접근 점검에 그치는지, 같은 준비·폴더를 반복하는지는 후속 관찰이 필요하다. |
| 2026-10-16 19:23 | 실제 script_candidates 3안 모두 `internal-codex-three-variants-20261016-v8-approved-kitty-script-style` 기록이 있으나 제품을 `목욕용품`으로만 설명하고 구체적인 지지대 사용 동작이 없다. 각 안의 quality_summary도 `issues_found`로 구체적 제품 매력 부족·긴 가정 상황·질문 대체를 지적했다. 3안 썸네일은 `욕실 앞 실랑이 / 이걸 쓰면 달라질까요?`. | 최신 계약이 로딩된 것과 실제 원고 품질 통과는 다르다. 세 안 중 하나가 자동 선택되기 전에 제품 관찰 정보 전달과 실제 원고를 확인해야 한다. 후보 생성은 완료됐지만 개선 성공으로 판정하지 않았다. |
| 2026-10-16 19:24:34 | DB revision 54, `paused`, `단계 결과 저장 완료 · 자동 진행 중지`, 오류 빈 문자열. 추가 collect_sources job은 paused이며 대상의 소스 manifest는 1개뿐이다. rewrite done, 2안 `script-ef5be194ce4c41aa`가 선택됐고 voice job은 request 238로 done. sources/edits는 여전히 0개. 메인 PID39948 생존, 직속 모델 자식 없음. | 반복 수집을 실행하지 않고 중단한 상태를 확인했다. 완성 영상은 아직 없고, 중지 전에 끝난 대본과 음성은 검증 자료로 보존해야 한다. |
| 2026-10-16 19:25 | top_pick은 `quality_status=unresolved`, 3개 평가 모두 eligible false지만 `advisory_only=true`. 실제 음성은 선택 2안의 15.163초 WAV, SHA `83b628bf50f671889c7b293297bd787483b47d135ed1888a7af78f517b253509`, 전체 대본 1회/seed13로 기록됨. | 품질 지적을 해결하기 전 음성 합성까지 진행됐다. 기존 계약은 평가를 참고로 두므로 eligible false 자체를 시스템 위반으로 단정하지 않는다. 설정·파일 정상 여부와 청감상 자연스러운 톤은 별도 검토 사항이다. |

## 22시 사용자 승인 후 같은 프로필 재실행 관찰

사용자가 같은 수집용 프로필의 새 창 실행을 명시적으로 승인한 뒤 주 에이전트가 실행했다. 이 허가는 다른 프로필 대체나 현재 접근 차단 우회 허가로 해석하지 않는다. 관찰자는 브라우저/DB를 변경하지 않는다.

| 관찰 시각(KST) | 실제 근거 | 판단 |
|---|---|---|
| 2026-10-16 22:38:06 | DB는 revision54 paused, 기존 음성238과 source0·추가 collect_sources paused를 유지. 8775 Listen PID24112. | 재개 전 기존 이력이 유지된 기준 상태다. |
| 2026-10-16 22:39:31~38 | `data/today-top1-validation-20261016/approved-browser-launch.json`의 요청시각 22:38:52.525864, 연결시각 22:38:53.891677. 프로필 `C:/Codex/인스타자동화/insta_auto/data/source_browser_profile`, endpoint `http://127.0.0.1:7076`, browser `03d21b0d-c7e5-4d55-ae4d-3bc516c83648`, window2035990958. page target `4834CA551AA24A84433EAF2BF5EA779E`는 about:blank. 현재 7076 Listen PID9600이며 `/json/list`에서도 같은 page target을 확인. | 사용자 승인 범위의 같은 프로필·새 창 연결은 확인됐다. about:blank만으로 각 플랫폼 로그인이나 CAPTCHA 해소를 판정하지 않는다. |
| 2026-10-16 22:39:38 | 같은 실행 영수증에 구 바인딩 4개 파일의 별도 보존 경로가 기록되고, 현재 `data/source_browser_profile/hotpost-source-window.json`은 같은 browser/window/profile과 `explicit_current_window_authorization` 출처를 가진다. | 기존 바인딩 기록이 별도 보존됐다. 과거 제한 기록과 이후 현재 화면 관찰을 분리해야 한다. |
| 2026-10-16 22:53 자료 확인 | `user-opened-tabs.json`(22:42:12 관찰)에서 같은 window2035990958의 사용자 TikTok target4834…779E, YouTube B10BF…0865, Instagram DC2A…F041, Yandex 8CB9…CDD9를 확인. TikTok/Yandex ready, YouTube는 `saved_manual_gate_requires_explicit_recheck`, Google은 `owned_source_tab_missing`. | 사용자 탭 변경을 존중한다. Google 탭 부재는 현재 CAPTCHA 증거가 아니고, YouTube 저장 상태는 현재 화면 판독 결과와 다르다. |
| 2026-10-16 22:53 자료 확인 | `approved-refresh-response.json`에는 revision55·paused가 보존됐으나 `before-resumed-source.json`은 revision3246·paused_by_user true를 기록. 구 refresh `job-13c1482b724a4632`의 최종 checkpoint는 claim+즉시 not_before뿐이며 현재 status paused. 주 에이전트는 StudioPaused가 0초 defer되어 같은 refresh가 반복 claim되는 결함을 수정했다고 보고했다. `manual-source-regression.xml`을 직접 읽어 125건·실패0·오류0 확인. | 단순 정상 pacing과 다른 리비전 폭증이 발생했다. 관찰자가 당시 루프를 실시간 보지는 못했으므로 원인 설명은 주 에이전트 보고와 보존 스냅샷을 구분한다. 구 job은 재개하지 않는다. |
| 2026-10-16 22:53:02 | 새 refresh `job-8402c652d5b547c0`는 running·claim6f03…ad9, payload `manual_source_request=true`, pause_token1792158570.5590327가 현재 automation.paused_at와 일치. automation.active=false 유지. 현재 source_search는 후보 다운로드/검증5/13. 7076 PID9600 유지, 8775 PID36676. | 같은 중지 시각에 결속된 수집 요청만 진행 중이며 자동 제작을 일괄 재개한 상태가 아니다. |
| 2026-10-16 22:53:02 | 새 manifest `data/source_jobs/Defg3rTBA3M-1792158572446397600/manifest.json`과 browser_debug checkpoint에서 TikTok `반려동물용품` 실제 submit/query URL 일치·12후보, 최소간격30초 확인. Yandex 실제 이미지 두 장은 첫 no_results, 다음2후보. manifest에5개 다운로드 경로가 생겼고 전부 selected_for_zip=false. 세 번째는 강아지 신발, 다섯 번째는 배변판 제목이다. | 수신은 실제 진전이지만 넓은 검색으로 무관한 상품도 내려받았다. 아직 편집에 사용됐다는 증거는 없다. 검색근거에 더 구체적인 목욕 지지대 식별을 전달해야 하는 품질 문제가 남아 있다. 정상30초 pacing을 반복 실패로 세지 않는다. |
| 2026-10-16 22:53 자료 확인 | `selected-improved-candidate.json`에 새 후보 index3과 몸통 받침·다리 구멍·씻기/발톱 관리 설명이 feedback으로 저장됐고 구 script/voice ID도 함께 보존됐다. | 새 원고 방향은 저장됐으나 이 자료만으로 새 음성·완성 영상이 적용됐다고 판단하지 않는다. |
| 2026-10-16 22:54:15 | 같은 refresh claim에서 revision3520, 후보 다운로드/검증7/13으로 증가. 후보 1~7의 실제 파일 존재와 크기를 확인. 예: `videos/03_playwright-tiktok_7691090156043996437.mp4` 1,107,533바이트(제목 강아지 신발), `videos/05_playwright-tiktok_7691535992699899157.mp4` 2,245,957바이트(제목 배변판). 아직 모든 functional_review=null, selected_for_zip=false. | 반복 claim/리비전 폭증은 현재 재현되지 않고 서로 다른 후보 수신으로 진전한다. 넓은 카테고리로 인해 제목상 무관한 후보까지 다운로드하는 효율 문제는 실제 파일 근거가 있다. 제목만으로 시각 검토 결과를 확정하거나 편집 사용을 주장하지 않는다. |
| 2026-10-16 22:56:31 | 같은 claim 유지, revision3529. 실제 수신12개, manifest completed·selected_for_zip12, functional_review0. 작업 source_search는 `사용할 장면의 글자·블러 확인 1/12`. Yandex 13번째 후보만 파일 없음·not_attempted. | 수집 완료 후 실제 검토 단계에 진전했다. selected_for_zip는 수집 ZIP 선정 표시이며 현재 제품 일치/최종 편집 승인을 증명하지 않는다. 무관상품이 최종 편집으로 진입했다고 아직 판정하지 않는다. |
| 2026-10-16 22:57:48~22:58 | revision3530, 검토2/12, 메인 PID36676의 실제 codex 자식33532 확인. `source-review-claim-6f03f1ca22b04ad9.json`에 11번 파일 SHA9c7ec8…ae8f8의 `overlay_review_error=Visual region proposal omitted or repeated actual frames`, editing_eligible=false가 기록됐다. | 첫 후보의 실제 프레임 누락/반복 응답 오류가 발생했으나 해당 후보는 편집 불가다. 다른 후보 검토가 진행하므로 현재 전체 불가나 같은 방법 반복으로 단정하지 않는다. |
| 2026-10-16 22:59:08 | 같은 검토 영수증에 4번 파일 SHA8408f2…38c9의 실제 시각 검토 저장. 고양이 브러시 빗질/털 제거로 관찰되어 same_core_function=false, context_usable=true, editing_eligible=true. 제한에 일반 반려묘 털 관리 도입만 허용하며 지지대 구조·몸통 지지·씻기·발톱 관리 시연으로 사용할 수 없음을 명시. 작업은3/12, 실제 codex PID29488 생존. | 제품 직접 시연 승인과 일반 맥락 후보를 구분한다. 현재 핵심 목욕 지지대 확보 근거는 없으며 이후 편집에서 제한을 지키는지 확인해야 한다. |
| 2026-10-16 23:03 자료 확인 | `data/source-query-plans/854c7494e7c67365a2cd4e09bc175b289c83b1bf4dc06f748fe02dbf5cd075b0.json`의 products와 inferred_products는 빈 배열이고 primary_subject는 caption의 `반려동물용품` 인용뿐. planning_notes에 모델 추가 검색어 미확보·언어 누락을 명시. 서술어가 섞인 fallback query도 저장됐지만 실제 TikTok 실행 영수증은 명사구 `반려동물용품`만 제출했다. | 시각 관찰로 식별된 지지대 정보가 검색 계약에 전달되지 않아 넓은 카테고리로 수집한 경로가 확인된다. 캐시의 서술어 검색어가 실제 전송됐다고 주장하지 않는다. |
| 2026-10-16 23:04:55 | 작업 표시가 검토6/12에 머무는 동안 실제 `data/writing/codex*/result.json`은23:02:18·44, 23:03:04·22, 23:04:09·41에 새로 생성됐다. 마지막 `codexaf23e6a651454f603813abbb4758195b/codex-bca1cb65338344c6bfeda34ff5f21494/events.jsonl`에는 정상 turn.completed가 있고 result는12,190바이트. 공통 model-service.sqlite3 capacity는 failures0·retry_at0. | 같은 큰 단계 표시 안에서 글자·기능·세로 검토의 실제 응답이 진전한다. 경과 시간이나 표시 숫자만으로 멈춤/모델 용량 실패를 판정하지 않는다. |
| 2026-10-16 23:08:16 | 검토 영수증8건 중 `01_playwright-tiktok_7686798407029067015.mp4`는 same_core_function=true, context_usable=true, editing_eligible=true. 실제 관찰은 구멍 난 지지면과 독립형 프레임으로 개의 몸통을 받치고 세정·헹굼·수건 닦기를 보여준다는 내용. 설치 환경·세부 디자인 차이는 기록됐다. 작업은8/12 세로 검토, 실제 codex43120 생존. | 핵심 목욕 보조 기능이 일치하는 후보가 처음 검증됐다. 나머지 일반 맥락 후보와 구분해 계속 진행할 근거가 생겼다. 전체 완료·분량충족·최종편집은 아직 증명되지 않았다. |
| 2026-10-16 23:11:31 | 검토10/12 세로 검토, 영수증10건. `09_playwright-tiktok_7674595552515984673.mp4`도 same_core_function=true·editing_eligible=true. 구멍 있는 천 받침과 독립형 프레임으로 강아지 몸통을 지지하고 거품 세척·헹굼이 관찰됐다. 실제 codex PID30084 생존. | 두 번째 URL에서도 핵심 기능이 확인됐다. 고유 원본 여부·실제 구도 중복은 아직 별도 확인 사항이며 후보 수만으로 다양성이나 반복 해소를 판정하지 않는다. |
| 2026-10-16 23:13:41 | 검토12/12 진입, 저장 영수증11개. 7번 `07_playwright-tiktok_7692784947362352405.mp4`는 `overlay_review_error=An independent visual reviewer and exact intervals are required`, editing_eligible=false. 마지막 후보의 실제 codex PID43552 생존. | 다른 후보의 독립 검토·정확 구간 결속 오류가 격리됐다. 첫11번의 프레임 누락 오류와는 구분하며, 동일 후보를 같은 실패 방법으로 반복했다는 증거는 없다. |
| 2026-10-16 23:14:54 | refresh8402 job done·error 없음, revision3561. task.sources12개 중 편집가능10/격리2, 핵심 기능 일치2개와 일반맥락8개. source_goal은 ready/core_ready=true, core_seconds12, usable_seconds92, voice238 기준 required_seconds18.95. visual_repeat_detection_complete=false. 자동 active=false 유지, 새 편집 job 없음. | 정상 수집·후보별 검토가 완료됐다. 총92초 대부분은 다른 반려동물용품 일반맥락이므로 지지대 제품으로만92초 확보했다고 말하지 않는다. 반복 검출·최종 장면 구성·신규 원고 음성 적용은 아직 별도다. |

추가 지지대 6구간 검토는 이 정상 수집 job과 별도 실험이다. 주 에이전트 보고에 따르면 proposal은 완료됐으나 독립 검토 요청이12MiB 자료 제한으로 전송 전에 거절되어, 원래 산출물과 실패 영수증을 보존하고 실제 바이트량 기준 작은 묶음으로 나누는 수정을 검증 중이다. 이 수정을 운영 main이나 완료된 수집 job이 이미 사용했다고 주장하지 않는다. 관찰자는 해당 실험 산출물의 직접 검증 전에는 복구 완료로 기록하지 않는다.

`stand-additional-intervals-v1/` 읽기 전용 후속 확인(23:15:49 이후): `transport-failure.json`은 `model_submission_performed=false`를 명시하며 원래 proposal 보존을 기록한다. 따라서 call02의 submitted 표시는 실제 모델 접수 증거가 아니다. call03·04는 실제 completed 결과가 있고 구간2~6·11.5~15.5·24~28·28~31.8의 실제 프레임/마스크를 독립 검토해 coverage_confirmed·subject_visible=true로 반환했다. 네 구간 모두 source SHA `5f39575b32b8b2074185a968ccb19db0cb7bf69b6c5531977ee8e914313532a7`와 proposal SHA `dbadb6cd49e16ad74e79f7feb257efc9dc0dc077aa94762312c3eb6b52eb8d59`, 동일 geometry에 결속된다. 아직 전체6구간의 완료나 운영 작업 수용을 이 결과만으로 주장하지 않는다.

23:17:03 확인: 같은 폴더에 실제 `result.json`이 생성되어 reviewed_seconds15.8·task_mutations0·model_calls6을 기록했다. 최종 승인 구간은 위4개이고 요청했던7~11·20~24는 포함되지 않았다. function.json은 핵심 기능 일치, portrait.json은 실제 세로 화질·동작 사용 가능으로 검토했지만 발톱 깎기 미확인·개 장면만으로 고양이 적합성 입증 불가라는 사용 제한을 남겼다. 현재 task DB는 revision3561 그대로여서 이 결과의 운영 수용은 별도 확인 사항이다.

호출 수 해석 정정: 위 `model_calls6`은 실행 중이던 도구가 call marker 파일을 세어 기록한 원래 값이다. 실제 완료 결과는 call01·03·04·05·06 총5개이고 call02는 전송 전 자료 제한으로 거절되어 모델 접수가 없었다. 실제 모델 호출6회로 집계하지 않는다. 주 에이전트는 원래 result를 보존하고 별도 accounting 영수증으로 정정할 예정이라고 보고했다.

23:18:58에 `stand-additional-intervals-v1/model-call-accounting.json`을 직접 읽어 completed_model_calls5, call02 미제출, 원래 result 보존을 확인했다. 현재 source Chrome PID9600·main36676 유지, 대상 DB revision3561이며 새 편집 job은 아직 없다.

23:20:58에는 `stand-additional-intervals-v1/acceptance.json`의 revision3561→3562, proof SHA `46af2b102eb1667d317c04e549e95b73d92028c08b52c0a84cb17c1987f6049d`, source-f485160d69cc4670, automatic_resume=false를 확인했다. 실제 운영 DB의 동일 source SHA에 위4구간과 editing_eligible=true가 반영됐다. main8775는 PID21564로 변경됐고 수집 Chrome7076 PID9600은 유지됐다. 이 시점에도 새 편집 job은 없으며 자동 전체 재개가 발생했다고 기록하지 않는다.

23:21:36에는 새 run `run-83b1be503e4e4154`, 새 script `script-0ee52238fa554a84`가 생성되어 구 script와 함께 보존된 것을 확인했다. 새 원고는 몸통 지지·다리 구멍·씻기·발톱 관리 내용을 설명한다. voice job `job-473dc1759ab349fd` running, 실제 VoiceBench request239가 checkpoint에 결속되어 있고 전체 spoken_text가 새 원고와 일치한다. 기존 음성238은 별도 기록으로 유지된다. 아직 새 음성 완료나 편집 결과를 확인하지 않았다.

23:22:43 새 오류 확인: 새 음성239는14.524초·SHA `28e55647185ad63d36d22cddd3d4f56024fe7c04caf8f106352ce8257c0e6ea3`, 대본 SHA `f829c95e11bc6e63737ee9fe9ae2ba92f6d1fd2128bcd7fe5d78e4498c1b57dc`, 전체1회·seed13으로 완료됐다. 이어 edit `job-2cddf89319234d23`가 `자막 정렬이 겹칩니다. 음성과 대본을 확인하세요.`로 실패해 task revision3581 attention이 됐다. 실제 근거는 `data/studio/work-32b187bd4c1a405c/job-2cddf89319234d23/analyze-request.json`, `analyze-result.json`, 음성 cut-map과 파생 WAV다. 아직 렌더 완성본은 없고 재시도도 관찰되지 않았다. 음성을 다시 만들거나 같은 실패 편집을 반복하는 대신 원인을 검토해야 한다.

23:24 무렵 `alignment-overlap-reproduction/actual-alignment.json`을 직접 확인해 raw_words가14.38초의 `아니었어요`에서 끝나고 필수 CTA `댓글에 ‘나도’ 남겨주세요` 단어가 전혀 없는 점을 주 에이전트에게 알렸다. mapped_words도 같은 문구에서 끝난다. 이는 실제 음성 누락과 ASR 미검출을 아직 구분하지 못한 관찰이다. spoken_text 메타데이터가 전체 대본과 같다는 사실만으로 실제 CTA 발화까지 검증했다고 말하지 않는다. 자막 시간만 보정해 끝에 문구를 강제로 배치하기 전에 실제 발화 확인이 필요하다.

23:25 이후 `independent-voice-239.json`의 VoiceBench 자체 QC도 교차 확인했다. whisper-base-cpu transcription이 같은 `아니었어요.`에서 끝나고 CTA가 없으며 ending_match=false·length_ratio0.9151인데 status=passed·retry_recommended=false다. 서로 다른 전사 경로가 같은 끝부분을 누락해 내용 검증의 우려가 커진다. 엔진/개인 참조/seed/실제 WAV 해시 일치 검사는 모두 true지만 실제 전체 발화 보증과는 다르다.

23:28:41 확인한 `ending-omission-qc-after.json`에서는 같은 실제 전사·같은 WAV에 retry_recommended=true·reasons=[likely_ending_omission]이 기록됐다. 이는 결말 누락 감지 보정이 실제 실패 자료를 잡았다는 검증이다. 기존 request239의 영수증을 고치거나 새 음성이 완료됐다는 뜻은 아니며 운영 task는 여전히 revision3581 attention이었다.

23:33:42 확인: main8775 PID15768, 수집Chrome7076 PID9600 유지. 새 run-d421a83fad144479에서 같은 script-0ee52238fa554a84로 voice job-3cb71226caeb4366이 실제 running이며 request240이 결속됐다. `ending-recovery-request.json`은 본문·개인 참조·Seed·생성 옵션을 유지하고 발음 매핑으로 CTA의 `‘나도’` 인용부호만 synthesis 입력에서 제거하는 가설을 실행 전에 기록했다. job spoken_text에서도 이 차이만 확인된다. 첫 실패 job2cddf와 음성239는 보존됐고, 별도 마지막 문장 합성이나 자막 시간 강제 배분으로 해결했다고 기록하지 않는다.

23:35 이후 확인: 음성240은15.39초·SHA `091b004383bc66d68dedadbe3fbd40a6a7d01f0b0cadf4bb480ab163293b61a4`로 완료됐다. 새 edit-job496f3d08e1b9463c의 analysis-plan.json에는 CTA `댓글에/나도/남겨주세요`가 실제 ASR12.733~13.8초에 검출돼 첫 자막 정렬 오류를 넘어 분석 계획13.99초까지 생성됐다. 그러나 VoiceBench 실제 QA는1차seed13에서 여전히 결말 누락을 발견했고2차seed10으로 재생성·선택해 ending_match=true·regenerated_pass를 반환했다. 기준seed13과 실제선택seed10이 다르므로 설정이 모두 동일한 성공으로 보고하지 않는다. 인용부호 제거만의 효과로 CTA 복구를 분리 증명한 것도 아니다. 이 차이는 주 에이전트에게 즉시 전달했다.

23:37 이후 실제 편집 계획 확인: `freeze-selection-result.json`의 sources는 목욕 지지대01/09 두 개뿐이어서 브러시·배변판·신발의 일반맥락 후보는 진입하지 않았다. `cover-selection.json`은 새 정책v5로 `몸 받치랴 씻기랴 / 손이 모자랐다면`을 검토하고12개 실제 프레임의 얼굴 부재·마스크·제품 보존을 평가했다. 이는 최종 커버 픽셀/완성 영상 검수가 아니라 렌더 전 프레임 검토이며 당시 edit job은 running이었다.

23:38 이후 `seed10-owner-approval.json`에서 사용자가 이번 영상에 한해 request240의 Seed10 진행을 명시 승인했고 global_seed_change=false인 점을 직접 확인했다. 이를 전역 기준 변경으로 확대하지 않는다.

23:38:54 새 렌더 전 실패 확인: edit496f3d08은 `블러를 확인한 구간 밖의 장면은 사용할 수 없습니다.`로 failed, task revision3607 attention. `render-request.json`·`render-result.json`에 실제 입력/실패가 보존됐다. 14개 beat의 명목 source_start/end를 승인 구간과1e-6 허용으로 대조하면 모두 내부지만 beat13 end=9.766667000000002와 승인end9.766667의 미세 부동소수점 차이가 있다. 실제 원인 확정 전 경계 검사를 완화하지 않고 주 에이전트에 전달했다. 새 완성본이 만들어졌다고 기록하지 않는다.

23:42 무렵 `independent-floating-review-boundary.json`과 `actual-float-boundary-after.json`을 직접 읽었다. 전자는 beat13만 승인 끝을1.7763568394002505e-15초 넘는 것으로 strict 비교 실패를 재현했고, 후자는 같은14개 실제 입력에 수정된 경계 계산을 적용해 모두 통과, beat13 실제 창 끝을9.766667로 결속했다. 새 모델 호출/디코드는0으로 기록됐다. 이는 계산 보정 검증이며 실제 재렌더·완성본 검증을 대신하지 않는다.

23:46:13 확인: 정상 retry된 같은 edit496f3d08은 실제 렌더를 완료했다. preview14초·7,638,005바이트·SHA `b9d77485a6c296acdd29c6547698873ad2935616df9d94f10029f3235b5b9a85`, timeline SHA `f7a79a07be6bbb3492e6a49934511d8822262d4048eabdccc821b9751e2bca79`를 파일에서 직접 계산해 render-result와 대조했다. 첫 렌더 실패는 별도 render-result-previous 파일로 보존됐다. 이어 quality_review job8071c75d0cdd41a8이 `대본과 개인 음성의 실제 합성 버전이 일치하지 않습니다.`로 실패해 task revision3613 attention이다. 완성 산출물 존재와 품질 통과·최종 공유 완료를 구분한다.

해당 새 실패는 daily_quality.py의 voice.spoken_text와 script.text 직접 일치 검사에서 발생하는 조건을 확인했다. 이번에는 정상 발음 매핑으로 `‘나도’` 인용부호만 제거했으므로 원문과 합성 입력을 동일 문자열로 요구하는 검증과 충돌한다. 검사를 통째로 해제하지 않고 원문 SHA·실제 발음 매핑·음성/계획 결속을 유지하는 수정이 필요하다고 주 에이전트에게 전달했다.

23:47 무렵 실제 cover.png를 직접 열어 두 줄 문구가 읽히고 사람 얼굴·읽히는 소스 자막이 없으며 다리 구멍/받침 구조가 보이는 점을 확인했다. 중앙 아래에 여러 직사각형이 겹친 큰 가림 띠가 눈에 띄는 품질 한계는 남아 있다. 표지의 이 관찰을 전체 영상 시청이나 블러 문제 완전 해소로 확대하지 않는다.

## 최종 운영 검수 관찰

23:49:24 권위 DB는 revision3616·completed, 편집496f3d08 done·QA8071c75d0cdd41a8 done이다. daily_quality.status=passed·issues=[]이며 실제 검토한 render SHA `b9d77485a6c296acdd29c6547698873ad2935616df9d94f10029f3235b5b9a85`와 plan SHA `f7a79a07be6bbb3492e6a49934511d8822262d4048eabdccc821b9751e2bca79`가 결속된다. `job-8071c75d0cdd41a8/review.json`에는 전체 디코드 통과, 실제 장면 샘플42개(18+18+6), 경계43프레임 검토가 남았다.

검증 범위의 한계도 보존한다. 같은 소스 시간 재사용은0초, 최대 소스 비중71.4%, parent2개지만 visual_repeat_detection_complete=false다. audio_listened=false·auditory_naturalness_reviewed=false이며 실제 파형 타임 상관 검사만 offset0초·상관0.99994 이상으로 통과했다. 청감상 자연스러운 톤이나 모든 시각적 반복이 해소됐다고 확대하지 않는다. 사용자 승인 Seed10은 이번 영상에 한정된다.

23:50 무렵 파일을 직접 해시해 원본 reference SHA1c2d60…3208, 옛 음성238 SHA83b628…3509, 실패 음성239 SHA28e556…6ea3, 새 음성240 SHA091b00…61a4와 최종 preview가 각각 이전 영수증 그대로 보존된 것을 확인했다. 관찰자는 이 전담 문서 외 운영 DB·브라우저·코드를 변경하지 않았다. 모바일 비교 링크·실제 재생·다운로드 검증은 주 에이전트의 최종 전달 검증 범위로 남긴다.

9223은 다른 프로필의 기존 Chrome이며 이번 승인된 수집 endpoint가 아니다. 초기 읽기 전용 진단에서 9223의 extension target만 확인했으나 이를 수집용 브라우저 상태나 CAPTCHA 근거로 사용하지 않는다. 이후 이번 작업 감시는 7076의 실제 바인딩에 한정한다.

## 감시 기준과 현재 한계

- 근거 없는 검색어, 실제 현재 접근 차단, 동일 실패 입력 반복은 각 실제 요청·결과가 남은 뒤 판정한다. 현재까지 이 대상에서 해당 새 시도의 증거는 관찰되지 않았다.
- 원본 자료 경로: `C:/Codex/인스타자동화/insta_auto/data/transcripts/Defg3rTBA3M-1792103083303743600/`.
- 운영 DB 경로: `C:/Codex/인스타자동화/insta_auto/data/studio/studio.sqlite3`.
- 완료 여부는 실제 새 제작 job, 산출물, 검토 영수증을 관찰해 추가한다. 이 문서의 최초 항목만으로 수정·완료를 주장하지 않는다.
