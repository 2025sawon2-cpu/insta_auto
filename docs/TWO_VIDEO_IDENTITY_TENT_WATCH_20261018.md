# 텐트 핵심 제품 정체성 재실행 감시 — 2026-10-18

## 범위와 관측 방식

- 대상: `work-17bb4524ce3a4217`, shortcode `DeZbgOAKTjP`, 제목 “친구네 따라 캠핑 갔다가 바로 따라 산 텐트 🏕”.
- 19:30–19:33 KST 기준선 조사. 이 문서의 시각은 KST다. 루트가 정상 API로 새 run/job을 시작하기 전의 상태이며, 재실행·실제 검색 성공을 주장하지 않는다.
- SQLite는 `mode=ro` URI와 `PRAGMA query_only=ON`으로 직접 읽었다. 모델·외부 검색·브라우저·프로세스·운영 DB·소스 코드를 변경하지 않았다. 기존 이미지와 파일만 읽고 SHA256을 계산했다.
- 전달받은 운영 세대 PID는 33468. 적용 예정 검색 계약은 `sampled-product-search-v4-core-identity`, 프롬프트 리비전 `minimal-core-natural-terms-v2`다. PID·계약 전달 사실과 해당 작업의 실제 새 영수증 적용 여부는 구분한다.

## 제품 정체성 기준선

원문 caption은 “차에 달고 다니다 도착하면 쓱 펼치면 설치 끝”, “땅에서 떠 있어”라고 설명한다. 원문 speech와 승인 대본도 차량 뒤에서 펼치는 텐트를 중심으로 삼는다. 기존 `state.product='텐트'`만으로 새 검색의 충분한 핵심 정체성을 판정하면 이 차이가 사라질 수 있다.

직접 본 기존 contact sheet와 `reference_frames/frame_1792275897704670100_scene_002.jpg`에는 검정·주황 텐트, 지면과 떨어진 바닥과 지지 다리, 차량 후면의 접힌 수납체가 있다. 정지 프레임은 정확한 3초 설치, 부착 호환성, 주행 안전성, 습기·냉기 차단 성능을 독립 입증하지 않는다. 시간 순서가 다른 보충 프레임을 붙인 contact sheet 순서도 동작 증명으로 쓰지 않는다.

천의 로고는 `TEPLER`로 읽힌다. 그러나 caption/speech는 브랜드·모델을 중심 주제로 명시하지 않고, 기존 준비 번들의 `brands/models`도 비어 있다. 화면 로고 존재만으로 필수 브랜드나 정확한 모델을 새로 확정하지 않는다. 현 단계 감시 가설은 **차량 후면에 운반·거치하는 펼침형 텐트**라는 핵심 구조가 일반 독립형 다리 텐트로 희석되지 않는지 보는 것이다. 최종 필수 조건은 새 정상 생성과 독립 검토의 실제 근거로 확인해야 한다. 모든 편의·색상·용량을 필수 조건으로 묶어 과도하게 좁히지도 않는다.

관련 구현: `hotpost/source_query_identity.py:55`의 원문·시각 근거 검사, `:92`의 실제 검색어 정체성 일치, `:107`의 동의어·어순 중복 지문; `hotpost/source_visual_queries.py:19`의 새 계약, `:262` 부근 독립 검토 조건. 과거 영수증을 새 계약 검토 완료로 간주하지 않는다.

## 보존할 승인 자료·이력

- 현재 run: `run-a36d83dc38df402e`(2번), `completed`. 저장 정책 v4다. 1번 `run-d0eb58f9f1404ab0`은 `superseded`이며 과거 v3 이력을 보존한다.
- 승인 대본 `script-a4fad68969c3449c`:

  > 같이 도착했는데, 저쪽은 벌써 텐트 안에서 쉬면 부럽잖아요. 이건 차 뒤에 달고 와서 삼 초 만에 펼치는 텐트예요. 짐 풀기도 전에 쉴 자리가 생기는 거예요! 바닥이 땅에 닿지 않아 습기랑 냉기가 덜하고, 네 식구가 함께 들어갈 만큼 넉넉해요. 댓글에 ‘나도’ 남겨주세요.

- 승인 음성 `voice-run-d0eb58f9f1404ab0`, 위 대본 연결, `data/studio/work-17bb4524ce3a4217/voice-run-d0eb58f9f1404ab0/original.wav`. 실제 SHA와 저장 SHA 일치: `76e59f18728f587a4bdd40a8ba29c60cbdb618ed18f44f38717cde5666d9f421`.
- 기존 edit `job-558f0a1bf2084148`, 14.066667초, `quality_verified=true`. 최종 검수 영수증 `job-fdebcc884aa84bcd/review.json`. 이는 과거 기준 완료 사실이며 새 계약의 소스 수량·검색 기준 충족을 뜻하지 않는다.
- 최초 편집 `job-b9719e6d67ad402b`은 “No reviewed complete global plan; insufficient candidates or required evidence” 실패를 보존한다. 과거 QA의 프레임 크기 실패 `job-3670ecae905e4be8`도 콘텐츠 부적합으로 합산하지 않는다.

| 보존 파일 | 직접 계산한 SHA256 |
| --- | --- |
| `data/transcripts/DeZbgOAKTjP-1792275842134339200/reference.mp4` 및 기존 source job의 `reference.mp4` | `a301284d4b72b3ea60c0410dddaf859e7b6d7bde7d1e014dff9d0ace43fd153f` |
| 기존 source job `reference_contact_sheet.jpg` | `8eec0d1839d54acb466f6e754d0f003328644207d60a09765a1f22c967a7f937` |
| 기존 source job `reference_frames/frame_1792275897704670100_scene_002.jpg` | `d4016013bc07894f65e7acd48558a5e10c43383583ca265dad3ad7de6fb8778b` |
| `data/studio/work-17bb4524ce3a4217/job-558f0a1bf2084148/preview.mp4` | `5d6806d7614e9841017f7416beea7fcf2002b50581bbe5cbe1ec05b4ab0e97a3` |

## 준비 번들과 실제 기존 검색

기존 수집 폴더는 `data/source_jobs/DeZbgOAKTjP-1792275897166605000/`다. 준비 캐시 `data/source-preparations/DeZbgOAKTjP/bfe40bfcc09aa09dbd465116.media.json`은 미디어 전용이며, `bfe40bfcc09aa09dbd465116-c460461d.json`의 검색 정책은 `central-subject-grounding-v4-visual-short-nouns`, 실제 시각 영수증은 구형 `sampled-product-search-v2-short-nouns`다. 새 v4 core-identity 영수증은 아직 없다. 정상 미디어 SHA 재사용과 새 쿼리 근거 재평가를 분리해 관찰한다.

구형 독립 검토는 `raised platform tent legs`를 텐트 전체가 아니라 다리 부품을 찾는 표현이라 거절했다. 이 거절은 유지하며 정당한 부족을 임의 번역·브랜드 추가로 메우지 않는다. 승인된 구형 명사구는 한국어2·영어1·중국어2였다.

기존 manifest와 `source_acquisition.queries`에는 아래 **제출 및 URL 일치가 명시된 실제 TikTok 검색 5건**이 있다. 별도 이미지 검색2건을 더해 이력은7행이다. 이미지·로그인/미시도 행은 en/zh 최소 횟수로 세지 않는다. 과거 검색은 새 run의 실제 검색 실적으로 자동 승격하지 않는다.

| 언어 | 실제 제출 검색어 | 구형 결과 | 새 핵심 정체성 관측 |
| --- | --- | --- | --- |
| en | `rear vehicle mounted tent` | results, 후보3 | 차량 후면형 핵심을 포함 |
| ko | `차량 후면 거치 텐트` | results, 후보3 | 차량 후면형 핵심을 포함 |
| zh | `车尾 支架 帐篷` | results, 후보3 | 차량 후면 지지 구조 포함 |
| ko | `다리형 고상 텐트` | results, 후보3 | 차량 후면형과 일반 독립형을 구별하지 못할 가능성 |
| zh | `离地 支腿 帐篷` | results, 후보3 | 위와 같은 범위 희석 가능성 |

중국어 `车尾 支架 帐篷`의 search_input 요청2개는 실제 서로 다른 검색2개를 뜻하지 않는다. 최종 제출·일치 영수증1개로 보존한다. 기존 en1/zh2라는 기술적 이력과 새 계약에 적합한 실제 최소 카운트는 별개다.

## 기존 승인 소스 3개와 주의할 구조 차이

아래 세 파일은 실제 SHA와 저장 SHA가 모두 일치했다. 기존 `functional_review`는 모두 reviewed/same_core_function/context_usable=true, 정책 `visual-product-presentation-v4-full-reference-features`다. 이는 새 identity 계약의 재판정 결과가 아니다. 현재 승인·이력을 수정하지 않았다.

| source id / TikTok video | 실제 파일 SHA256 | 기존 검토된 구간 | 이미 기록된 관찰·한계 |
| --- | --- | --- | --- |
| `source-6903471bd5994852` / `7688121219501051156` | `7adee945ea590d18590f410d7708943a5b367e5ff92dea5a99cb348e5bd373b8` | 4.1–5.1, 6.85–10.85, 10.9–11.9, 13.7–17.7 | 높은 입구 바닥의 아이들, 차량 뒤로 바닥·프레임을 접는 모습, 접힌 수납체와 프레임. 차량 뒤 위치는 보이나 부착 하드웨어·주행 중 운반·정확 모델은 미확인. |
| `source-ae80f2fd9c594602` / `7671905895634308372` | `c1958d5f2b64fa24083b163ef4d2fe75e438bc01e592e60c62d9ccf90501ed28` | 1.9–2.7, 7.4–8.1, 8.1666665–12.1666665 | 독립 다리형 텐트를 들어 옮김, 프레임 조작·출입구. 검토 한계에 차량 후면 장착 운반·차량에서 펼침은 아니라는 점을 명시. |
| `source-4f55add3c5564729` / `7671844919215918344` | `67404fa92a43f7491bae78eb6b86b71906fb2179f94cb6ce463d8c2fbd3deedd` | 0–4, 8.1666665–12.1666665, 16.333333–20.333333 | 독립 다리형 텐트 이동·설치, 보관 가방·프레임·지퍼. 차량 후면 운반·차량에서 펼침 미입증, 색/프레임/구조 차이와 모델 미확인을 명시. |

뒤 두 소스는 관련 보조 몽타주로 쓸 수 있는지와 차량 후면형 주제품의 직접 시연으로 오인되는지를 구분해야 한다. 일반 텐트라는 이유만으로 새로운 핵심 제품 검색 실적이나 주제품 직접 시연 근거에 자동 산입하면 안 된다. 반대로 대사마다 정확히 같은 장면이어야 한다는 구형 엄격 기준을 복원하지 않는다.

## 새 실행 감시 원장

| 관측 시각 | 확인 사실 | 판정·다음 관측 |
| --- | --- | --- |
| 19:30:51 | 기준선 task는 기존2번 run completed; 새 run/job 통지 없음. | 과거 완료본 보존. 새 실행 성공/실패로 세지 않음. |
| 19:31–19:33 | 구형 준비 캐시·원작 실제 프레임·3개 소스 SHA·승인 대본/음성 확인. | 차량 후면형 핵심 유지 여부와 독립 다리형 보조컷 구분을 루트에 보고. |
| 19:38:35 | 루트의 정상 API 요청으로 `run-5b8af824e2e243bc` 시작. 대상은 텐트+키티로 확정되었으며 몽벨 더플백은 제외. 시작 영수증 `data/two-video-core-identity-20261018/work-17bb4524ce3a4217-start.json`. | 기존 승인 `script-a4fad68969c3449c`·`voice-run-d0eb58f9f1404ab0` 유지, 새 edit 선택은 비움. |
| 19:38:39 | deployment-1의 `verification.json`: PID27468, 로드69모듈, 요청 전 task58개·보호파일66개 보존 확인. | 앞서 전달된 PID33468과 구분하여 새 실제 운영 세대로 기록. |
| 19:38:57 | 새 수집 `job-16889b96fc384072` queued. source_goal 관련 부모3/5·en0/5·zh0/5, ready=false. 체크포인트에 interval_recovery 문맥과 `not_before=19:39:09.752626`. | 아직 새 실제 검색/준비 번들 없음. 정상 예약·대기 구간으로 보며 실패·반복으로 단정하지 않음. |
| 19:40:45 | 텐트 automation.active=true/paused_by_user=false. 동시에 키티 수집 job running이나 텐트는 queued. | 이 스냅샷만으로 lane 점유가 원인이라고 확정할 수 없음. 이후 원인 영수증과 구분. |
| 19:42:03 | events에 새 `pause-auto` 기록. 19:42:20 읽기에서 텐트 active=false/paused_by_user=true, job16889 paused. source_search.message는 “짧은 구간 제안의 체크포인트 SHA 확인 대기”. | 루트가 이번 배포를 위해 정상 중지한 결과. 새 run 이전 중지가 남아 있던 것이 아님. 새 검색·다운로드0. |
| 19:43:35–19:43:51 | deployment-2 검증 영수증과 main-loaded 직접 확인: PID41340, 로드69모듈의 현재 파일 SHA 불일치0. v4-core-identity/minimal-core-natural-terms-v2/en5zh5 일치. 같은 run/job가 running이며 새 manifest `data/source_jobs/DeZbgOAKTjP-1792320202503497600/manifest.json`의 preparation 진입. | 원작 SHA/제품 힌트/원문SHA/run_id 결속 확인. search_audit·후보는 아직 비어 있음. “음성·화면·캡션에서 검색 주제와 행동을 분석하는 중”은 정상 분석 진전. |
| 19:44:52.532 | 새 visual 영수증 `data/source-visual-queries/375f93197dbccf41028460aa1e6f48acf3153eb453336ca6f0970e303bf87147/review.json` 생성. identity 지원/완전성 모두 false. | 모델이 돌아온 실제 평가 결과이며 서비스 대기와 구분. |
| 19:44:53.021 / 19:45:03 관측 | job16889 failed: “핵심 제품 정체성의 독립 검토를 통과하지 못했습니다.” manifest failed/preparation, 실제 search_audit/후보0. | 새 run 시작 후 약6분17.67초, 실제 재개 후 약1분30초에 검색 전 실패. 실제 쿼리 전송·다운로드·편집 성공을 주장하지 않음. |
| 19:48:29.932 | 루트의 별도 v3 분석 proposal 생성. 동일 `subject_hint='텐트'`, 새 cache `4e61aa1b149bac2e3dc29c3c18e1cfe733f7c7900bc445e0410aead39db9d855`. | 차량 후면형·접이식·지면 이격형 세 필수 조건을 복원, 재질/브랜드를 추정하지 않음. 독립 검토 전에는 성공 미확정. |
| 19:49:03.277 / 19:49:45 검증 | v3 review 전체 identity true,12제안 모두 개별pass. 최종 receipt의 영어5·중국어5 approved_query_pool ready=true. result의 분석 경과77.0496초. | 원작실제SHA·입력12프레임SHA 전부 일치. 공유 지문 함수로도 en5/zh5 고유·정체성 보존 확인. **별도 분석 성공이며 실제 검색0**. live v2 실패 기록은 보존. |
| 19:55:41.937 재claim / 19:56:08 관측 | deployment-3 PID39568/로드70모듈의 SHA 불일치0. 동일 job16889/run5b8에 새 claim-d4ec5e...로 재시도. 새 manifest `DeZbgOAKTjP-1792320944574830500`에서 4e61 검증캐시와 기존 실제 프레임 경로를 재사용, 새 미디어 재추출 없음. | 운영 v3 계약 적용과 승인 en5/zh5 풀 정상 승계. 새 모델 입력을 무의미하게 반복한 증거 없음. |
| 19:55:43 preflight / 19:56:30 확인 | preflight가 TikTok을 query_exhausted/no_unused_supported_scope로 판정하고 ready_routes를 yandex-images로 제한. 이후 새 en5/zh5 풀을 만들었어도 strategy.routes는 yandex만이며 TikTok은 strategy_skipped. | 새풀 이전 판단을 유지한 stale-route 경계 가능성을 즉시 보고. 새 TikTok CAPTCHA 관찰과는 다른 근거다. 현재 이미지 검색은 정상10초 간격으로 진행 중이며 en/zh실검색0. |
| 19:56:39 / 19:57:08 / 19:57:38 | deferred 후보 `7281086194551688491`, `7169189336179543342`, `7634989235702943006`의 실제 MP4 3개 수신. transfer 영수증은 selected_existing_target/existing_browser_playback/blob/complete=true. | 새 검색 결과라고 세지 않음. 기존 TikTok 연결을 사용했고 새 프로필·대체 다운로드 경로 사용 증거 없음. |
| 19:57:47→20:00:54 | 사용구간 글자·블러 검토4/6→5/6→6/6으로 진전. 첫 두 새 후보의 functional v5는 same_core_function=false/context_only=true, 캠핑/휴식 맥락만 승인. | 지면형 차량 쉘터를 후면 접이식/고상 바닥의 직접 시연으로 승격하지 않음. state goal은 아직3부모/en0/zh0, batch callback 수용 전. |
| 20:01:23.205→20:01:35.332 | 루트 normal pause-auto 후 job16889가12.13초 뒤 정상 모델 경계에서 paused. manifest paused/discovered, 새 수신3개 모두 v5 context_only, 기존 state3개는 v4 core 유지. | 실제검색0/편집0. 저장된 과거 완료본을 변경하거나 새 후보를 수동 승인한 것이 아님. |
| 20:03:03 완료 / 20:03:44 관측 | deployment-4 PID4312/로드70모듈 SHA 불일치0. 동일job16889 done. 새 claim-3e73... review 영수증6개 중 기존3개는 여전히 v4/core=true, 신3개만 v5/context_only. state 관련부모6/en0zh0, 다음job252249c27ff64899 queued. | helper 반영만으로 실제 재평가 완료를 주장할 수 없음. 구판3개 재검토 연결 누락 가능성을 루트에 즉시 보고. |
| 20:08:47 | deployment-5 PID45048/로드70모듈 SHA 불일치0, protected82/task58 보존. 같은 run/job252249 running, 기존3개 재검토1/3. | 구판정3개가 source_goal에서 제외되어 관련3/core0/en0zh0/readyfalse. 새v5 3개의 불필요 재검토 증거 없음. |
| 20:09:59 | 재검토 진행3/3. state는 아직 구판정 수용 전. | 모델 결과 수용을 기다리는 정상 진행으로 기록. |
| 20:10:25.229 실패 / 20:11:05 관측 | job252249 failed error=`'round'`. source_search failed, state 구3개v4 유지, goal 관련3/core0/en0zh0. | 콘텐츠 거절·접근 대기가 아닌 반환 계약 코드 오류. 새v5판정 수용 완료로 보고하지 않음. 루트에즉시보고. |
| 20:19:25 | deployment-6 PID15576/70모듈 SHA 불일치0. job252249 done, 기존3개 v5 판정 수용, identity_source_review 등록 확인. 관련6/core2/en0zh0. 다음job e10eeb0173c9497b running. | 기존 writer 결과 재사용으로 실제 구판정 재분석 수용 완료. core2의 용도 제한은 아래 별도 기록. |
| 20:19:17 preflight / 20:19:32 종료 / 20:20:56 관측 | 다음 collector도 TikTok=query_exhausted, ready_routes=yandex뿐. manifest `DeZbgOAKTjP-1792322357895684000` completed, budget_stop=search_receipts_only_existing_reviewed_inventory, actualsearch_audit=[]로 끝남. 새job916f3c1966624a59 queued. | 새10쿼리 미사용인데 text검색0인 회차가 반복됨. 첫 pool 교체1회만의 no-op으로 볼 수 없어 루트에 즉시 정정 보고. |
| 20:29:57 | deployment-7 PID44568/70모듈 SHA 불일치0, task/protected/package 동일보존=true. 같은job916f/run5b8 running. preflight20:29:44에 TikTok ready/current_existing_page_observed, ready_routes=tiktok+yandex. | 구풀소진오판이 해소되어 새실제text경로 진입. 과거 CAPTCHA 기록만으로 현재차단을단정하지않음. |
| 20:30:04 제출 / 20:31:16 결과확인 | 새manifest `DeZbgOAKTjP-1792322984855301700`의 browser checkpoint에 en2/zh1이 submitted=true/URLmatched=true/results. 다음zhawning은started/submitted=false. | 확인된실적2/1만집계, 미완료행제외. 각행 search_identity 보존. state0/0는 batchcallback전이라별도표기. 정상약30초pacing, 현재CAPTCHA행없음. |
| 20:32:10 | 새결과5쿼리=en3/zh2, 후보10URL 모두서로다름. 다음zhzip은started. | 매번후보2개라고같은추천영상반복으로단정할수없음. 기존승인URL2건이결과에재등장했으나재다운로드증거없음. |
| 20:33:41 | en4/zh4 제출·URL일치/results, 누적후보15URL unique. | 정상pacing, 마지막en/zh각1개진행중. |
| 20:34:32.024 마지막제출 / 20:34:54 검증 | 10개 actual검색행 모두 submitted+URLmatched/results, 공유 coverage en5/zh5 확인. state ledger에도 current run/context/search_identity 보존, source_goal ready=true/related6/core2. collector916f20:34:39.836 done→edit2b4390998dbe4df4 20:34:40 running. | 이번수집은준비완료. finalmanifest search_receipts_only_existing_reviewed_inventory, 새수신MP4=0. **영상완료/본문5개검증/최종QA완료는아직아님.** |
| 20:36:46–20:38:07 | edit2b439는running. analyze-result.json은20:34:53에status=completed, analysis-plan은14.0337초. 부모job에는아직analyze단계체크포인트만있음. | 정상장면선정작업/대기를실패로세지않음. 최종timeline/render/QA결과는아직없음. 수집완료후추가검색·다운로드반복증거없음. |
| 20:40경 | select-shots/freeze-selection 완료. 공유 body_usage_report=5부모/shortfall0, 선택된실파일SHA모두일치. 승인script/voice ID와원본voiceSHA유지. | 실제렌더전계획검증이며최종영상완료는아님. 특정쉘터맥락컷이주제품직접시연으로오인되는지완성QA확인대상을루트에전달. |
| 20:41:00→20:41:19.792 | render 시작 후 edit2b439 done, 새14.066667초 preview 생성. | 이번새출력은1회렌더. source검색·TTS전체재생성반복증거없음. |
| 20:42:07.340 완료 / 20:42:17 검증 | quality_review job-fe439f6fbd774f40 done, passed=true/issues=[]/full_decode_passed=true. 현재run5b8 completed, edit2b439·승인script/voice결속, export_verified=true/web_render. | 실제본문5부모와QA/video/plan SHA일치확인. 청감/전체연속동작검토완료로과장하지않음. |

새 run/job가 확정되면 이 표에 실제 시각, 준비 캐시 재사용/새 identity 영수증, 승인된 en/zh 풀과 실제 제출·일치 영수증, 같은 scope/query 지문 중복, 관련 부모 수·본문 사용, 대기/접근 제한, 최종 실제 QA를 추가한다. 생성된 쿼리 수와 실제 검색 수를 혼동하지 않는다. 모델 서비스 대기·정상 요청 간격·미시도는 실패나 무한반복으로 단정하지 않고, 같은 입력의 반복과 새 근거의 재평가를 분리한다.

### 실행 전 별도 분석과 런타임 분석의 구분

루트 전달에 따르면 별도 detached 분석은 더 구체적인 제품 힌트를 사용했으며 금속 소재 근거가 없는 쿼리를 거절한 결과 en4/zh4였다. 이는 실제 검색도, 새 런타임 번들의 평가 결과도 아니다. 런타임은 기존 `product='텐트'`를 힌트로 별도 새 캐시를 정상 생성할 예정이다. 따라서 동일 입력 모델 반복으로 자동 분류하지 않되, 힌트가 넓다는 이유로 차량 후면형 핵심을 잃은 일반 텐트 쿼리를 최소 실적으로 승인하는지는 실제 런타임의 `subject_identity`·관찰·독립 review로 확인한다. 금속 근거 거절을 임의 복구하지 않는다.

### 첫 실행의 검색 전 구간 확장 대기

events의 실제 claim은 19:38:38.4638336, source_wait defer는 19:38:39.752626이며 실행 구간은1.288792초다. 그 뒤 해당 job은 재claim되지 않은 채 19:42:03의 정상 배포 중지에 도달했다. API 요청19:38:35.349부터 중지까지 약3분27.75초이며 이 시간의 대부분은 실제 외부 검색이 아니다. 체크포인트의 interval_recovery는 기존3소스/동일 원문·reference SHA의 문맥이고 proposals/receipts는 비어 있었다. 새 쿼리 준비 번들·외부 제출은 아직 생성되지 않았다.

이는 “검색어가 부적합하여 검색 실패”라는 증거가 아니다. 기존 승인 핵심 구간이 이미 있는데 실제 검색 최소치가 부족한 상태에서도 먼저 로컬 구간 확장 단계로 간 뒤 체크포인트 SHA 대기에 머문 경계다. 루트는 core_ready=true/search_ready=false인 v5 상태에서 로컬 구간 확장을 생략하고 정상 find_sources로 진행하는 보정을57테스트로 확인했다고 전달했다. 19:42:20 시점에는 아직 live 적용 전이며, 본 감시 에이전트는 운영이나 코드를 변경하지 않았다. 부족한 부모 수는 새 실제 원본 확보가 필요하므로 같은 부모의 구간 확장만으로3/5를5/5로 올릴 수 없다.

### 런타임의 정체성 축소와 실제 독립 검토의 한계

`375f93197.../proposal.json`의 `subject_identity`는 product=tent/帐篷/텐트, 필수 feature=elevated/离地/지상형만 설정했다. `o6`에는 차량 뒤쪽 옆에 놓인 텐트가 관찰되지만 차량 후면 거치/운반 정체성이 필수 조건에 없고, 전송 제안도 `elevated tent wide entrance`, `rectangular elevated tent`, `宽门 离地帐篷`, `长方形 离地帐篷` 등이다. 원문 중심 구조를 넓은 `subject_hint='텐트'`보다 우선했는지는 검토가 필요하다.

독립 review는 **rear 누락을 사유로 막지 않았다.** en2–5와 zh1–5에 supported/central_product/core_identity_preserved=true를 주었다. identity 전체를 false로 한 구체적 설명은 한국어 ‘지상형’이 지면에서 떨어졌다는 뜻을 보존하지 않는다는 번역 오류다. en1 `elevated tent support legs`는 부품이 검색의 중심이 된다는 이유로 별도 거절됐다. 따라서 “독립 검토가 차량 후면형 핵심 누락을 차단했다”라는 결론은 근거가 없다. 한국어 번역만 고쳐 같은 좁은 정체성을 재승인하면 핵심 누락이 남을 가능성을 루트에 즉시 보고했다. 수동 승인·영수증 수정·반복 실행은 하지 않았다.

별도 구체 힌트 영수증 `3ff4ed83ca737f80152019bd8a11f59610a11744caefef40e555f8e75aaf57dc/review.json`은 “차량 후면에 장착해 운반하고 펼치는 지면 이격형 접이식 텐트”라는 정체성을 명시적으로 인정했다. 이쪽은 금속 소재를 독립 입증하지 못해 en4/zh4에 그쳤다. 서로 다른 hint의 두 관측을 대조할 수 있으나, 더 잘 나온 옛 결과를 새 런타임의 실제 성공으로 치환해서는 안 된다. 원시 파일은 모두 보존한다.

### v3 원작 중심 정체성 우선 규칙의 실제 별도 검증

루트는 짧은 category label보다 원작의 중심 설명·제품을 구별하는 구조를 우선하고, core-only 명사구도 하나 허용하며 관찰된 추가 변형을 제안하는 규칙을 별도 분석했다. 입력 힌트는 넓은 ‘텐트’를 유지했으며 캐시 리비전은 `reference-topic-before-short-label-v3`다. 이로써 힌트만 더 구체적으로 바꿔 결과를 낸 실험과 구분한다. 실행 스크립트는 `data/two-video-core-identity-20261018/analyze_tent_v3.py`, 출력은 같은 폴더 `tent-reference-v3/{baseline,result,receipt}.json`이다. 감시 에이전트는 모델을 실행하지 않았다.

원시 영수증 폴더는 `data/source-visual-queries/4e61aa1b149bac2e3dc29c3c18e1cfe733f7c7900bc445e0410aead39db9d855/`이며 `receipt.json` SHA256은 `aba50dcfb7b5dc3de3864136f840bbbc99a8b0a9343d356ba3ac8a73c71ab38e`다. 독립 review는 차량 후방 연결/접이식/지면 이격 정체성을 원문과 실제 프레임으로 지지하며, 보이는 로고를 특정 모델 필수 조건으로 올리지 않았다. 최종 전송 후보10개는 아래와 같다. 표는 **아직 실제 제출 내역이 아니다.** 한국어2개 제안도 개별 검토됐지만 최종 minimum pool에는 en/zh10개만 남았다.

| 변형 | 영어 승인 후보 | 중국어 승인 후보 |
| --- | --- | --- |
| 핵심 구조 | `rear-mounted folding elevated tent` | `车尾折叠离地帐篷` |
| 돌출 덮개 | `rear-mounted folding elevated tent with awning` | `带遮阳篷的车尾折叠离地帐篷` |
| 지퍼 출입구 | `rear-mounted folding elevated tent zippered entrance` | `拉链门车尾折叠离地帐篷` |
| 직사각 구조 | `rear-mounted folding elevated rectangular tent` | `长方形车尾折叠离地帐篷` |
| 지지 다리 | `rear-mounted folding elevated tent with legs` | `带支腿的车尾折叠离地帐篷` |

실제 파일을 다시 읽어 원작 SHA 일치·12개 프레임 SHA 불일치0을 확인했다. `source_query_identity.query_identity`로 각 언어의 고유 지문5개를 계산하고 `matches_identity`가10개 모두 true임을 확인했다. 영어 최장6단어이며 구형 부품 중심 `support legs` 대신 제품 전체가 중심인 `tent with legs`를 사용했다. 금속 소재 탈락을 수동 복구하지 않고 관찰된 구조만으로 수량을 충족했다. 향후 운영 반영/정상 새 collector 시작 및 실제 제출 여부는 별도 영수증으로 추가 확인한다.

### 운영 v3의 캐시 재사용과 경로 판단

새 준비 번들 `data/source-preparations/DeZbgOAKTjP/bfe40bfcc09aa09dbd465116-c460461d-acq-84702c45f1.json`은 기존 원작 경로·12프레임을 유지하면서 visual_query_evidence.input_sha256=4e61...를 사용한다. 새 수집 폴더에는 reference 재추출 파일이 없으며 이 자체는 정상 결속 재사용이다. 캐시의 생성·독립 검토 시각은19:48–19:49로 유지되어 운영에서 다시 같은 모델을 호출한 증거는 없다.

반면 source_access_preflight는19:55:43 시점에 TikTok의 미사용 scope가 없다고 판단했다. 새 승인 풀의10개 명사구가 생긴 뒤 strategy.routes의 ready 제한을 갱신했는지는 확인이 필요하다. 당시 checkpoint는 yandex 이미지 frame_001 재검색 no_results와 보충 scene_003 업로드 시작을 기록했다. 이는 image 검색이며 en/zh필수 검색으로 세지 않는다. 과거 다른 run과 이미지 SHA가 같다는 사실만으로 이번 명시 재제작의 동일 실패 무한반복을 확정하지 않되, 새 text pool을 만들고도 이전 소진 판단 때문에 text 경로를 건너뛰는 낭비와 후속 회차 자동 회복 여부를 따로 감시한다.

### 새 실제 후보의 관련성 검토

19:57의 manifest는 deferred9개+library4개+Yandex1개로 후보14개를 나열했다. 일반 지퍼 수선 도구, 침대 모기장, DIY 트럭 침대 텐트 등의 제목도 후보에는 들어 있으나 이 자체를 승인으로 간주하지 않는다. 20:00:54까지 검토 영수증으로 확인한 새 승인2개는 모두 `visual-product-presentation-v5-related-context`, `same_core_function=false`, `source_role=context_only`다. 차량 후면형 핵심과 차이가 있다는 제한을 지웠다는 증거는 없다.

- `7281086194551688491` 실제SHA `8b8877c8a93110b0644c06e37943f63c3131c20b69f6b66b248128507a52bf84`: 지면에 설치한 차량 연결 쉘터와 차량 안 침구를 둘러보는 장면. 후보 바닥은 지면이며 차량 밖 고상 접이식 바닥이 아니다. 캠핑 도착/쉴 자리 맥락으로만 허용하며 차량 뒤 장착 운반·3초 전개·지면 이격·습기/냉기 성능·4인 수용은 근거로 쓰지 못한다고 명시했다.
- `7169189336179543342`: 차량 후면에 연결한 공간을 둘러보지만 후면 장착 접이식 전개와 고상 바닥이 확인되지 않아 같은 핵심 기능으로 인정하지 않았다. 일반 캠핑 휴식 맥락만 허용했다.

기존3개는 v4 functional 영수증과 사용 제한을 유지한 채 batch review에 포함됐다. 새 쿼리의 엄격한 핵심 정체성 유지와 소스의 실제 제작 대본 관련 맥락 허용은 목적이 다르므로, 모든 보조 후보에 원작 핵심 시연을 강제하거나 반대로 일반 쉘터를 핵심 시연으로 자동 승격하지 않도록 최종 사용을 함께 확인해야 한다. 이 시점의 실제 en/zh 제출은0/0이며 관련 부모 추가는 state에 아직 수용되지 않았다.

20:02:11에 세 번째 새 후보 `7634989235702943006`도 v5 same_core_function=false/context_only=true로 확인했다. 루트는 명시 automatic source reselection 새 run에서 구판 core/context를 `needs_identity_reanalysis`로 정상 기능 재검토하도록 보정했다고 전달했다(143테스트 통과, live 적용 전). 과거 run이나 수동 제외 상태를 자동 변경하는 보정이 아니며, 새 원작·검색어·다운로드·검토 구간 캐시를 전부 지우는 방식도 아니다. 운영 배포4 이후 구판3개는 재검토하고 이미 v5인 새3개는 불필요하게 다시 평가하지 않는지 별도 확인한다.

### 배포4의 재검토 helper와 실제 연결 경계

20:03:44의 새 `source-review-claim-3e73a01258f4471a.json`은 기존 v4 core3개를 그대로 보존하고 신수신 v5 context3개를 함께 기록했다. 실제 state의 현재 run.inputs에는 source_selection_mode=automatic이 있다. 읽기 전용 스냅샷에 `needs_identity_reanalysis` 순수 함수를 적용하면 구3개True/신3개False라 helper 조건 자체는 작동했다. 그러나 이 실제job에서 기존3개가 새 v5로 재평가된 결과는 없었다. source_goal의 관련부모6/5는 수량 증가 사실이며, 구판 기능 재분석 완료라는 뜻이 아니다. en/zh실제검색도0/0이라 ready는false를 유지했다.

정적 검사상 `_review_deferred_downloads`의 우선 반환 및 overlay/presentation 중심의 pending 선정 경계가 identity-only 미완료를 놓칠 수 있다. 구판 snapshot 복원 자체도 후보 경계지만 정확한 우회 경로를 이 관측만으로 확정하지 않는다. 루트에 `studio_sources.py`의 해당 호출·pending 선정과 `_review_pending_local_sources`의 연결을 전달했다. 기존 자료 보존과 새 평가 완료를 구분하고, 수동으로 v4를 v5로 바꾸지 않았다.

### 배포5의 선택적 재분석과 결과 수용 오류

루트는189테스트 후 collect/pending-local/refresh 경계에 identity-only pending을 연결하고, 새 명시 run의 구판정 소스는 확보 수에서 제외했다. 20:08:47의 실제 goal은 새v5 context3개만 관련3개로 세고 핵심0개였다. 검토는 기존3개 대상으로 진행했으며 전체 원작·검색어·신규3개 모델을 모두 다시 실행한 증거는 없다.

그러나 20:10:25.229 job252249는 `KeyError('round')`에 해당하는 오류로 실패했다. 현재 코드 `studio_sources.py:583–585`의 `_review_pending_local_sources` 반환에는 `round`가 없고, `:880`/`:889`의 `accept_source_round`는 `result['round']`를 직접 읽는다. state에는 재검토 결과가 수용되지 않았고 기존3개는 v4 그대로다. 이는 모델이 핵심 정체성을 거절했다는 뜻이 아니며 실제 판정 내용을 확인할 영수증도 이 job checkpoint에는 없다. checkpoint 키는 not_before/claim token/claim started뿐이다.

따라서 round 반환 보정뿐 아니라 로컬 재검토 시작 전에 정상 review checkpoint를 등록하여 중단·수용 오류 시 같은 입력의 모델 검토를 잃지 않는지도 확인하도록 루트에 전달했다. 감시 에이전트는 failed job을 다시 실행하거나 판정을 수동으로 복구하지 않았다. 기존v4를 확보 수에서 제외하는 안전한 부족 표시는 유지됐으며 최종 실제 소스 확보·영/중 검색 완료·편집 결과는 아직 없다.

### 배포6의 실제 수용·모델 재사용 확인

루트는 round·identity_source_review 체크포인트·항목별 실제SHA·reference/script 결속을 보완하고232테스트 후 같은 failed job을 정상 재시도했다. job252249는20:18:45.244에 done으로 수용됐다. 새 identity 영수증은 `data/studio/work-17bb4524ce3a4217/source-local-reviews/source-review-claim-415f1bf3d57f45a2.json`, 저장SHA `45c871dbbbc555b6fc061d3837b232bf12c362133c949d5a1cb633323fb603c3`다. 실제 state의 구3개 functional policy는 모두 v5가 됐다.

| 기존 source | 새 실제 판정 | 유지된 사용 제한 |
| --- | --- | --- |
| `source-6903471bd5994852` | core=true/context=true | 차량 뒤 접이식 텐트와 지면 이격 구조·사용을 지지. 후반은 접는 장면이라 펼치는 직접 동작으로 설명할 수 없음. 정확3초·4인·습기냉기 성능·정확모델 미입증. |
| `source-ae80f2fd9c594602` | core=false/context_only | 독립 다리형 구조. 캠핑 준비·지면 이격 공간의 제한적 맥락만 허용. 차량 후면 부착 운반/전개·3초·성능·4인 직접 근거 불가. |
| `source-4f55add3c5564729` | core=true, **지면 이격 특징에 한정** | 다리로 바닥을 띄운 구조만 해당 특징의 핵심 컷으로 인정. 차량 뒤 장착 운반/차량에서 펼침·3초·성능·4인·같은모델을 입증하지 않음. 사람이 안에서 쉬는 모습도 미확인. |

두 독립형의 core boolean 차이를 루트에 보고했다. 루트는 현 공통 몽타주 기준상 비교 가능한 제품 구조로 특정 홍보 기능 하나를 보여주면 그 특징에 한정한 core를 허용한다고 확인했다. 따라서 마지막 소스를 구판 복원 오류라고 판정하지 않는다. **검색 최소 정체성 전체조건**, **특정 기능의 실제 시연**, **맥락 보조컷**은 목적이 다르다. 최종 편집에서 마지막 소스를 차량 장착·차 뒤 전개의 직접 시연으로 사용하면 실제 결함이며, 높은 바닥 일반 컷으로 사용할지는 정상 scene 검토 대상이다. 수동 core 변경이나 추가 모델 검토를 요청하지 않았다.

집필 DB `data/writing/jobs.sqlite3`도 mode=ro/query_only로 읽었다. 같은 텐트 reference SHA의 기능 비교 결과3개는 다음 각각1개의 완료 Codex 호출을 가진다. 이후 retry를 위해 새로 생성된 동일 기능 비교 job은 확인되지 않았다.

- `codexd4094333de6044fc30c1e04a7737481a`: 생성20:08:23.483, 호출 완료 영수증 mtime20:08:46.753.
- `codex07c0f20d7fb97b89f8c9aca84f3e3b7e`: 생성20:09:07.069, 호출 완료20:09:26.417.
- `codexe1ebf14a82116d24e16acfe03fdf4887`: 생성20:09:43.107, 호출 완료20:10:08.227.

따라서 round 수용 오류 뒤 배포6 재시도에서 **기능 판정 모델을 다시3회 실행한 것이 아니라 기존 결과를 재사용한 사실**을 확인했다. 다만 source-reference/frame_001–004.jpg의 mtime은20:19:30으로 갱신되어 모든 프레임 파일이 일절 재작성되지 않았다고는 주장하지 않는다. 기존 원작·수신 MP4 전체를 새로 수신한 증거는 없고 최종10개 query 캐시도 4e61을 재사용했다.

### text 경로의 지속적인 구판 준비 번들 우선 선택

후속 collector e10e의20:19:17 preflight도 TikTok을 query_exhausted/no_unused_supported_scope로 표시했다. 이는 새10개 승인 쿼리의 실제 제출 실적0과 모순되는 ‘사용 scope 없음’ 판정이다. 정적 근거는 `source_preparation.py:151–157`의 탐색 순서 `[current,base,*older,...]`다. 기존 `bfe...-c460461d.json`을 먼저 반환하여 최신 acquisition 번들 `...-acq-84702c45f1.json`의v3풀보다 구형v2풀을 preflight에 제공할 수 있다. `source_access_preflight.py:117–122`는 이 구풀과 기존 history로 미사용 scope를 계산한다. 실제 find_sources가 이후 새v3풀을 사용해도 ready_routes의 text 제외가 유지된다.

해당 후속 manifest는 actualsearch_audit=[]인 채 search_receipts_only_existing_reviewed_inventory로 끝났고 새 collector가 다시 queued됐다. 단순 정상30초 pacing이나 첫 전환1회의 자동 회복만으로 설명할 수 없어 루트에 즉시 보고했다. 현재 실제 확정 상태는 관련 부모6/5·핵심2(특징 제한 포함), 영어0/5·중국어0/5, ready=false이며 새 최종 편집은 없다. CAPTCHA 현재 관찰과 이 논리적 scope 소진 판정은 서로 다른 근거다. 후속 정상 보정·접근 대기 결과를 추가 관측한다.

### 배포7의 실제 text 검색 진입

루트는 현재 acquisition bundle 우선 선택, search_history의 search_identity 보존, immutable manifest의 명시 run/context 영수증만 복원하는 ledger migration을250테스트 후 적용했다. 20:29:57에 loaded70개 현재SHA 불일치0과 verification의 task_states_equal/protected_files_equal/package_files_equal=true를 확인했다. 같은 paused collector916f와 같은 run5b8만 재개된 경계다.

최신 준비 번들 `bfe40bfcc09aa09dbd465116-c460461d-acq-84702c45f1.json` SHA256은 `6a2e54b86234666ee41081418c6917e2ad8dd14cc00ebde2b73a0150ea2f848e`, visual cache는4e61...이다. 새 manifest의 query plan에는 동일 reference SHA/product/원문SHA/run_id와 rear-mounted/folding/elevated 정체성이 있다. preflight의 TikTok 상태는 이제 query_exhausted가 아니라 현재 기존 페이지 관찰에 따른 ready다. 실제 신규검색 입력으로 진전한 사실과 과거 접근 기록은 구분한다.

20:31:16 browser `search-checkpoint-c829550650b94dabbbf6ee7b2a65c546.json`에서 아래3개가 실제 제출·결과URL일치/results를 갖는다. 각 후보 수는2개다. 같은기본구조의양언어번역은언어별검색1개씩이며,순서변경/재시도중복을새실적으로세지않았다.

| 제출 시각 | 언어 | 실제 검색어 | 확인 |
| --- | --- | --- | --- |
| 20:30:04.400 | en | `rear-mounted folding elevated tent` | submitted+URLmatched/results |
| 20:30:31.594 | zh | `车尾折叠离地帐篷` | submitted+URLmatched/results |
| 20:31:05.755 | en | `rear-mounted folding elevated tent with awning` | submitted+URLmatched/results |

다음 `带遮阳篷的车尾折叠离地帐篷`는started/locate_search_input/submitted=false여서아직집계하지않았다. state source_goal은여전히0/0이나이는 batchcallback전저장스냅샷이다. 실제브라우저영수증의 en2/zh1을 state수용완료나최소5/5완료로과장하지않는다. 현재약30초검색간격은정상pacing이며해당새검색행에는CAPTCHA관찰이없다.

### 결과2개씩 반환되는 현상의 실제 후보 비교

20:32:10에는 영어3·중국어2의 실제 제출/URL일치 결과가 있었다. `result_method=search_response`이며 서로 다른 실제 검색URL이 각 입력을 담았다. 누적 후보10개의 video URL은 모두 달랐다. 따라서 “매번 같은2개 추천 영상만 반환”이라는 가설은 현재 근거와 맞지 않는다. `browser_search.py:675`의 per_query_limit 최솟값2와도 부합하지만, 이 코드 설정만으로 실제 결과의 관련성까지 보증하지는 않는다.

| 실제 쿼리 | 반환된 TikTok video ID/계정 |
| --- | --- |
| 영어 핵심 구조 | `7678197179852262676` @campgadget / `7659413583364672771` @kd5rsmymb |
| 중국어 핵심 구조 | `7691205535281974548` @gadget_nissan / `7640370970523340045` @summer_zhong1989 |
| 영어 awning | `7635081994627534111` @itsjustchelsey / `7281086194551688491` @binlee79 |
| 중국어 awning | `7666139102798023949` @elnazhamai / `7526122191050542356` @homeevergreen8386 |
| 영어 zippered entrance | `7169189336179543342` @xhqfiddy / `7630568682791439630` @burdick5fam |

gadget_nissan 제목은 차량 후면 장착·접이식·지면 이격 설명을 포함해 핵심 주제 관련 후보로 보이지만 실제 프레임 검토를 대신하지 않는다. 일부 다른 후보 제목은 일반 cot tent·차량 탈의 텐트로 범위가 넓다. 이미 승인된 binlee/xhqfiddy URL도 다시 결과에 나타났다. 이들은 결과 중복/관련성 검토 대상으로 기록하며, 현재 검색 전용 경로에서 같은 파일을 재다운로드했다는 증거는 없다. 루트에 실제URL·후보단계와승인단계의차이를보고했다.

### 실제 최소 검색 완료와 편집 진입

20:34:54에 공유 `actual_search_coverage`로 browser10행을 읽어 영어5·중국어5 모두 고유 지문/실제 제출/URL일치/results임을 확인했다. 최종 manifest의 모든 TikTok 실제 검색행에는 명시 `run-5b8af824e2e243bc`, 현재 reference/product/text scope, search_identity가 남아 있고 state source_acquisition ledger10행에도 동일하게 보존됐다. 과거 immutable manifest의 다른 run 실적을 현재실적으로옮겨채운것이아니다.

| 언어·변형 | 실제 제출 시각 | 후보추가 수 |
| --- | --- | --- |
| en 핵심 | 20:30:04.400 | 2 |
| zh 핵심 | 20:30:31.594 | 2 |
| en awning | 20:31:05.755 | 2 |
| zh awning | 20:31:32.106 | 2 |
| en 지퍼 | 20:32:06.417 | 2 |
| zh 지퍼 | 20:32:31.809 | 2 |
| en 직사각 | 20:33:05.725 | 2 |
| zh 직사각 | 20:33:31.931 | 1 |
| en 다리 | 20:34:05.552 | 0 |
| zh 다리 | 20:34:32.024 | 0 |

마지막 두 행은 새 후보추가0이지만 status=results와 실제 제출·URL일치가 있다. 이를 미시도/제출실패로세지않고, 새독립소스추가확보로도과장하지않는다. 누적후보는15개 unique URL이다. 현재 실제 CAPTCHA 행은 없다.

실제10검색의 첫제출→마지막제출은4분27.624초, 마지막결과수용→collector완료는약8초였다. 배포7재개→수집완료는약5분이다. 전체원래새run요청19:38:35→검색완료20:34:39에는앞서기록한배포·로컬검토·반환오류·구풀소진오판의별도지연이포함되므로순수검색시간으로부르면안된다.

최종수집 manifest `data/source_jobs/DeZbgOAKTjP-1792322984855301700/manifest.json` SHA256은 `30ad107b3a032190b8faa17a69df44dbef4453af1399910b4d46e4d3d52655d1`이며, preparation_bundle_path/SHA는앞서검증한acq번들과일치한다. 새videos폴더에MP4는없다. 이미검토된관련부모6개/core2가충족되어정상TaskBatchReviewer경계를통해검색영수증만확보하고다운로드를생략했다.

새 edit payload는 승인대본 `script-a4fad68969c3449c`·승인음성 `voice-run-d0eb58f9f1404ab0`과현재관련6개source_ids를선택했다. 이중본문최소5개실제부모사용·기능별사용제한·전체자연스러움은최종계획과실제QA로별도확인한다.

20:38:07까지의확정범위는원작중심정체성의검색계획/독립검토·현재run실제en5/zh5·기존구소스3개v5재분석수용·관련원본6개준비·추가다운로드없는편집진입이다. 아직새영상완료나실제본문5parent사용/최종QA통과를선언하지않는다. source분석·검색단계의원시실패와배포보정이력도보존했으며기존완성본의해시를새결과로대체하지않았다.

## 마지막 편집·렌더 감시

### 선정 계획의 실제 부모5개와 승인 입력 결속

`job-2b4390998dbe4df4/freeze-selection-result.json`의 plan은 source_diversity_policy=minimum-five-sources-v1/minimum5, selection_frozen.sha256=`56a7c6f75a4ed9239b8d15fa9d2dcdd5ac772bc9efd3d468ba78c15baed411e9`다. 공통 `body_usage_report` 순수함수로 본문5개·부족0을 재확인했다. 원본SHA/original_sha는없어 실제파일SHA가부모키이며5개모두실제파일해시와일치했다. 표지전용사용은제외된계산이다.

| 실제 부모 SHA256 | source id | 본문 프레임 / 초(30fps) |
| --- | --- | --- |
| `67404fa92a43f7491bae78eb6b86b71906fb2179f94cb6ce463d8c2fbd3deedd` | `source-4f55add3c5564729` | 106 / 3.5333 |
| `7adee945ea590d18590f410d7708943a5b367e5ff92dea5a99cb348e5bd373b8` | `source-6903471bd5994852` | 112 / 3.7333 |
| `8b8877c8a93110b0644c06e37943f63c3131c20b69f6b66b248128507a52bf84` | `source-88eeadf240cb4914` | 113 / 3.7667 |
| `c1958d5f2b64fa24083b163ef4d2fe75e438bc01e592e60c62d9ccf90501ed28` | `source-ae80f2fd9c594602` | 46 / 1.5333 |
| `87eb42297684c27fcff481f6f19d4dd7310d24602d564e898f71b93e84c716f0` | `source-2c146a6831d540ec` | 43 / 1.4333 |

최대원본비중은26.90%다. 선택계획의 voice_source는기존voice-run-d0eb.../script-a4fad.../원본SHA76e59.../scriptSHA3668bb...를유지했다. 부모run의완성본을새run성과로대체하지않고현재job의새계획을검증한것이다.

### 맥락 컷의 실제 오인 여부는 최종 QA로 구분

모델rank는16beat에기존관찰18shot을배치했고, 현재공통정책의 montage_support를사용했다. beat5 “이건 차 뒤에 달고”와beat7 “펼치는 텐트예요”에 shot4-1(지면형차량쉘터binlee)이선택됐다. 이소스의functional v5는context_only이고원작의후면고상전개시연근거가아니라고명시했다. 따라서각대사에정확같은제품을강제하는구형규칙을복원하지않되,**완성전체에서실제다른구조를주제품의직접시연으로제시하는지**는정상QA확인대상이다. 이선정계획만으로실패를확정하거나모델/렌더를중복실행하지않았으며루트에구체beat/shot을전달했다.

### 실제 최종 QA·export·보존 검증 결과

새완성본은 `data/studio/work-17bb4524ce3a4217/job-2b4390998dbe4df4/preview.mp4`(15,250,063bytes,14.066667초)이고선택된export도동일경로다. state.status와현재run5b8.status모두completed이며run.artifacts는승인script-a4fad.../voice-run-d0eb.../새edit2b439를결속한다. QA는별도 `job-fe439f6fbd774f40/review.json`에있다.

| 검증 대상 | 직접 확인한 값 |
| --- | --- |
| 새 MP4 SHA256 | `8e3e2073dbbb74ba060cc08b502aceee54149e8cb29b18ea6be92c25e6012619` |
| 최종 timeline SHA256 | `18e9e9a7bac8bbfe8f83be72531416c5448712aaa9ea2666cc599ecdc011b193` |
| QA review SHA256 | `6f054ed5386f5b80f09d2ae6c7159bff079a293d3462d252aa6882d1ff1adc4f` |
| render request SHA256 | `2f5fe143865534b1957cd2a55bedf24ad62547913eca9560ac945ffee89654d1` |
| 품질·export | `passed=true`, issues/advisories=[], `full_decode_passed=true`, `quality_verified=true`, `export_verified=true`, export_kind=web_render |

QA의render_sha256/plan_sha256은직접계산한위파일해시와일치했고render-result._artifact_hashes도동일하다. 최종timeline에공통body_usage_report를다시적용해본문부모5개/shortfall0을확인했다. 부모목록·각사용프레임수는선정계획표와동일하다. 그5개를포함한소스6개실파일SHA모두저장값과일치하며파생5개를다른부모로세거나표지만으로개수를채운증거는없다.

QA는3그룹(18+18+12)실제출력표본48장을검토했고각파일SHA는저장값과모두일치했다. 모든그룹passed=true/issues=[]다. 오디오시간축검사는통과했고5개앵커의offset0초/상관0.99996–0.99998, duration_delta0초다. 다만receipt는 `audio_listened=false`, `editorial_review.full_motion_review_complete=false`, `auditory_naturalness_reviewed=false`를명시한다. 이결과를실제전체재생·청감검토완료로확대하지않는다.

감시 에이전트가whole-video-overview와beat5/7의실제출력표본,actual-first-frame을직접읽었다. 지면형차량쉘터는정적인차량캠핑외관으로나오며잘못된펼침/접힘동작을직접시연하는장면은표본에없다. 관련맥락컷으로사용된것으로현재독립QA통과를존중한다. 다만‘이건’이라는대사와다른구조의외관이결합하여동일제품으로읽힐모호성은남는다. 전체연속동작/청감검토를하지않은정지표본판단으로이모호성을완전해소했다고주장하지않고,단일대사마다제품을강제하는새실패조건이나수동판정치환도만들지않았다.

완료뒤기존완성본preview SHA는 `5d6806d7614e9841017f7416beea7fcf2002b50581bbe5cbe1ec05b4ab0e97a3`,원작reference SHA는 `a301284d4b72b3ea60c0410dddaf859e7b6d7bde7d1e014dff9d0ace43fd153f`,승인원본voice SHA는 `76e59f18728f587a4bdd40a8ba29c60cbdb618ed18f44f38717cde5666d9f421`로최초기준선과모두동일했다.

새run요청19:38:35.349→최종QA20:42:07.340은63분31.991초다. 실제수집완료20:34:39.836→QA완료는7분27.504초다. 앞선소스분석·구판정연결·round수용·구풀preflight보정지연과순수10검색4분27.624초를분리하여기록했다. 감시에의한운영DB/브라우저/프로세스/모델변경은없으며,수정한파일은이문서뿐이다.
