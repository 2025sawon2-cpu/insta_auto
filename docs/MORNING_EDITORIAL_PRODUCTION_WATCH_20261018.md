# 오전 상위3 새 편집 실제 진행 감시 — 2026-10-18

검수자는 읽기 전용 SQLite(`mode=ro`)·기존 파일·프로세스 상태를 관측하고 이 문서만 작성한다. 운영 DB·설정·코드·프로세스·브라우저를 변경하거나 모델·수집·TTS·렌더를 실행하지 않는다. 정상 API를 통한 제작 재개·최종 QA·실제 GUI 재생 검증은 root가 수행한다.

## 최종 상태 (13:20:49 독립 관측)

- 같은 3task 모두 completed / daily_quality passed / issues=[]이며 전역 queued/running job은 0개다. 세 MP4/plan 실제 SHA가 최종 QA receipt와 일치한다.
- 새 render는 각 1회, 합계 3회다. 새 TTS job 0, 새 run 각 1개. 더플의 정상속도 추가 원본 구간 검토 후 같은 edit job 내 재분석은 실제 새 증거의 진전이며 재렌더 반복이 아니다.
- 텐트의 1MiB 검수 포장 실행오류와 더플의 과도한 순간 색상 불합격은 원시 기록을 보존했다. v3 실제 새 QA 2개로 텐트·더플이 통과했고, 더플은 추가 dense actual-frame confirmation도 통과했다. 손난로는 앞선 v2 계약의 실제 QA 통과를 유지한다. **3개 모두 같은 v3 instruction으로 새 모델 호출했다고 주장하지 않는다.**
- 최초 더플 색상 QA가 불필요한 수집 job 1개를 촉발했고 중지 전 실제 TikTok 4파일(15,402,045바이트)을 수신했다. 미검토 파일로 보존되며 본 제작 소스에는 편입되지 않았다. 재QA 이후 새 수집은 0이다.
- baseline 36파일 SHA/size/mtime 및 기존 15job 전필드(원래 실패3 포함)가 동일하다. 승인 대본3/음성3(request248/249/250)/기존 소스11의 실제 파일을 확인했다. 원래 paused 수집 job도 새 QA 전후 전필드가 동일하다.
- main PID31148 deployment-v2의 59모듈 loaded/expected/disk SHA가 모두 일치하고 alive다. 전체 task/jobs 불변·Chrome/VoiceBench 유지 배포 영수증을 확인했다. GUI 실제 재생·청감 검증과 공유 링크 검증은 root가 담당하며 이 보고서는 이를 대신하지 않는다.
- 아래는 원시 관측과 판단 정정 이력을 보존한다. 순간 색상만으로 결함을 단정했던 감시자 초기 해석은 철회했다.

## 기준·보존

새 전체 몽타주 기준은 `docs/editorial_montage_policy.md`와 `product-appeal-first-20261018-v2`다. 같은 특장점 반복·관련 리액션/맥락을 허용하고, 정상 속도 실제 원본 연속 구간으로 길이를 확보한다. 소스·실제 프레임·마스크 증거를 수동 승인으로 바꾸지 않는다. 서비스 대기·큐 대기·아직 시도하지 않은 상태는 콘텐츠 실패로 세지 않는다. 같은 입력/같은 확정 실패 방법의 재시도와 새 실제 승인 구간·새 증거 진전을 구분한다.

정책 검수 및 실제 원작10개의 후속 재확인 결과는 `MORNING_EDITORIAL_POLICY_REVIEW_20261018.md`, `EDITORIAL_REFERENCE_VALIDATION_20261018.md`에 있다. 원작 최종9pass/구체적인 제품 구조 오인1개와 앞으로 만들3영상의 최종 QA는 별개다.

배포 영수증 `data/editorial-montage-20261018/deployment-v1/deployment.json`을 읽었다. 메인18948/launcher42024, 적재57모듈, 전후 전체task/jobs 불변과 VoiceBench/Chrome 유지가 기록되어 있다. 종료 방식은 실제 idle에서 정확한 프로세스를 교체한 `idle exact-process replacement`이며 graceful shutdown으로 바꾸어 쓰지 않는다.

12:52:07 KST 최초 관측에서3task 모두 기존 attention/run/edit0 상태였다. 12:52:29 KST 관측에서는 동일3task에 아래 새run/newjob만 생겼고 기존 실패job은 failed/error/checkpoint를 유지했다. 새run은 기존 script/voice와 **이전 실패job의 source_ids 그대로**를 입력으로 사용한다. 손난로 task의 전체5개 소스를 자동으로 전부 넣은 것이 아니다.

|대상|동일 task|기존 실패job|새 run|새 edit job|기존 음성|
|---|---|---|---|---|---|
|텐트|work-17bb4524ce3a4217|job-b9719e6d67ad402b|run-a36d83dc38df402e|job-558f0a1bf2084148|voice-run-d0eb58f9f1404ab0|
|더플백|work-06068a52b50e41b2|job-c93716cb9c954c69|run-84e809ef14e54eca|job-388f01a4b30745c0|voice-run-0ac20463d97645a4|
|손난로|work-09928d0b8f864345|job-67cfb87c9e5c46a3|run-06a70bf217014c14|job-7164b6a7d2454940|voice-run-13e43560d23c48c5|

세 새run의 source policy는 version4, 명시 `normal-speed-editorial-v1`, source reuse허용, duration/core duration preference다. 기존 v3 source policy를 가진 과거run 이력은 별도로 남는다. 실제 편집 가능성·최종 QA는 이 재고 준비 표시와 구별한다.

## 관측 기록

|KST|실제 상태|판정|
|---|---|---|
|12:52:07|3task attention/edit0, 이전run 유지. 배포main18948 영수증 확인|재개 전 기준선|
|12:52:29|텐트 새edit running/analyze PID 기록, 더플백·손난로 새edit queued. 전역 활성job은 이3개뿐. main18948 create_time1792295502.0255318/running, 자식34300/23292/26228 관측|정상 첫 진행. queued2개는 미시도이며 콘텐츠 실패 아님|
|12:53:49|텐트 analysis→새semantic→select-shots→freeze-selection 실제결과 completed. cover-candidates 진입. 더플·손난로 queued|실제선택 진전. 과거 실패방법 반복이 아님|
|12:56:12|텐트 render결과completed/preview.mp4 생성,14.066667초. QA job3670ecae905e4be8 queued. 더플388f claim/analyze결과생성, 손난로7164 queued|실제 출력 진전. 최종QA통과 아님|
|12:57:20|더플新semantic완료. select가beat3/14의reviewed_window_required를반환. 같은job은running이며editorial-continuation 실제프레임/영수증생성과codex자식38220관측|예상한인접원본검토요청. 모델미시도/작업실패/콘텐츠실패로계수하지않음|
|13:00:29|더플延長영수증accepted/applied, 실제수용12:58:46.171. 같은388f job의 새analyze PID40280/input SHA 및semantic-history1개 확인|새 물리 승인범위에 따른재분석. 동일입력 실패반복 아님|
|13:01:51|더플의 두 번째 분석·새 의미 순위·select·freeze 완료, cover-candidates 진입|연장 범위를 실제 계획에 반영한 진전|
|13:03:38|더플 실제 출력 완료, QA job-cc4e29f6336743c8 queued. 손난로7164는13:02:59경 claim 후 analysis 완료|3개 중2개 출력 생성. QA 결과는 아직 대기|

텐트 새 select 결과는14.0337414966초, 명시normal-speed 정책, 실제 원본 시간 재사용1.2초다.16beat 중 product 증거 필수1개, 나머지는montage_support다. `search_budget_pruned=true`여도 완전한 할당을 찾아 성공했으므로 이를 예산실패로 세지 않는다. 해당 시점 기존3개 failed job의 id/kind/status/created/updated/error/checkpoint/payload 전체 선택 열 hash는12:52:29 기준선과 모두 같았다. 아직 렌더·최종 QA 성공을 뜻하지 않는다.

12:54:49 텐트cover-candidates 결과 JSON 생성(94,370바이트), 아직 render요청은 없었다.12:54:57 main18948/create_time 동일, 실제codex 자식23708(create_time1792295696.319549/CPU누적0.75초) 관측으로 모델 검토가 진행 중임을 확인했다. 파일 쓰기가 잠시 없다는 이유만으로 무진전/실패라고 판정하지 않는다.

텐트 `job-558f0a1bf2084148/render-result.json`은status completed와 request SHA `1556f76787db18619e72464b707acfaf9a8eaaf585bbc1c60b0dc774111e9aac`를 담는다. 결과duration14.066667초와 선택 계획14.0337414966초 차이는 실제30fps 최종ceil 경계와 구분한다. 해당 job에editorial-continuation 영수증은0개다. 기존 승인 범위 및 새 반복 허용으로 출력까지 진행한 것이며 새 원본 구간 승인/새 TTS가 있었다는 증거로 쓰지 않는다.

더플 새 semantic은16beat중 “이 더플백은”1개만product 증거를 요구하고 나머지는montage_support다. 주황색을 말하는beat3/14는 새 독립 순위에서도1초shot2-1만 제시했다. 실제renderer 요청은각43/38출력프레임(정상속도1.433333/1.266667초)이므로, 같은 원본 실제 연속 구간 검토로 이어진다. `select-shots-result.json.status=failed`는 이 구조화된 검토 요청의 전송 형식이며, Studio job이failed로 끝났다는 뜻이 아니다. pending/repair_round는각null/0을유지했다.

12:58:06 더플의A∪B 독립mask 영수증은7.8–9.2666667초를 포함한5개 범위 전체에coverage_confirmed/subject_visible=true, rejected_intervals=[]를 기록했다. 각5개 실제native표본(전체25개)과 gray preview 검토가 명시되어 있다. 기능·세로검토 수용 전 extension 상태는started였으므로 이 단계만으로 최종소스 승인을 선언하지 않는다. 후속codex자식5708/create_time1792295914.1631012를 관측했다.

12:59:17 기존스냅샷과 읽기 전용 보존 점검:3task의 모든기존script 레코드 포함, voice ID/path/기록SHA 동일 및 실제음성SHA일치, 기존소스11파일의 실제SHA일치, 기존reference path 동일, 과거run ID 전체보존을 확인했다. reference **경로** 확인과 reference MP4의새 전체SHA검증은 구별한다. 소스범위 영수증이 새로 생겨도 원본파일을 덮은 것은 아니다.

더플 extension 최종 영수증 `job-388f01a4b30745c0/editorial-continuation/extension-59aae574fd1c47dd70417f0b482b04fb7832741d65dacff2f5e7f81e6e70f52d.json`은accepted, 기능same_core_function=true, 세로usable=true, editing_eligible=true다. 실제7.8–9.2666667초 추가범위와기존4범위를모두수용했다. checkpoint의editorial_continuations는accepted/applied=true를기록했다. source SHA는e549037c81f9979cbbe00a54bcbe806f95aa8f5050baa9734dec4f1930b3d954로기존과같고, 새analysis input은7079185d32e53f8a5081eeab26f0f9e1b4cb2b277e5018626db1762a34955a36이다. 기존실패입력의단순재시도와구분한다.

더플 연장 후 실제 freeze 계획은15.08초/정상속도/원본 시간 재사용4.4초다. beat3는7.8–9.233333초, beat14는7.8–9.066667초를 사용하여 새 승인7.8–9.266667초 안에 들어간다. 이 범위는 원본을 느리게 만들거나 마지막 프레임을 늘린 것이 아니라, 정상 속도로 사용할 실제 인접 원본을 추가 검토한 결과다.13:03:38 관측까지 기존3개 실패job의 전체 선택 열 hash는 계속 기준선과 같았다.

## 운영 세대와 디스크 변경 구분

root는 진행 중3job을 중단하지 않고 `source_interval_recovery.py`의 “제품 없는 상반신 화면 일반 금지/새로운 정보가 있는 뷰만 요구” 잔여 문구를 디스크에서 보정했다. 관련reaction/맥락/특장점 반복 허용으로 정렬하는 변경이다. 이 마지막 변경은 deployment-v1 main18948 메모리에 아직 없다. 실제57개 loaded SHA와 디스크를 직접 대조한 차이는 해당모듈1개뿐이었다: loaded `6f7b9009f9febc6b7bbe8477fdf9b702d123c2f11f5ebfd355da7f1f9c4f5cab`, disk `b2edf349a75668d7eed95924a1f7db9e1378daa2ebee9d70ce428f449a819073`. 지금까지3작업은 초기 재고가 준비되어 이 proposal 경로를 사용하지 않았다. root는 모든job 종료 후 idle에서 deployment-v2로 반영할 예정이며, 현재 디스크 수정만으로 운영에 이미 반영됐다고 기록하지 않는다.

v4 adoption 보존 경계를 직접 읽었다. 기존 run/source policy가 있으면 일반 adopt는그 정책을 반환하고, 명시new_run=True만 state의 새계약을 만든다. reproduce의new_run=True는 oldruns를 덮지 않는다. 별도 발견한 향후 신규task 생성경계(StudioStore.create가current_policy=v3를 먼저 넣어 신규run이v4를 받지 못할 가능성)는root에 알렸으며 현재3개의 명시v4재개에는 영향이 없다.

root는후속으로 `source_policy.montage_policy()`를분리하고StudioStore.create의신규task를v4로생성하도록보정했다. 기존current_policy는v3 standalone/legacy factory, 기존run adopt는불변으로유지한다. 신규task 재조회불변반례를직접읽었다. 이source_policy/studio_store 변경과앞선source_interval_recovery 문구보정은현재진행중인main18948에는아직없고최종idle deployment-v2대상이다. 현재3run은이미v4입력으로실행되어있어이신규접수경계변경과독립적이다.

아직 새 완성 영상·최종 QA 통과를 확인하지 않았다. 후속 실제 상태 변화와 오류/무진전 확인을 이 문서에 이어 기록한다.


## 13:05 텐트 QA 실행 오류: 콘텐츠 판정 전 이미지 포장 제한

13:05:17 읽기에서 텐트 `job-3670ecae905e4be8`가 `Codex 실행 실패: 분석 프레임이 너무 큽니다.`로 failed/attention. `daily_quality.pending=failed`, repair_round=0. 더플 QA `job-cc4e29f6336743c8` running, 손난로 렌더 완료 후 QA `job-26633bf96fee4e4a` queued. 모든 실제 영상 렌더는 완료되었으나 QA 통과를 뜻하지 않는다.

직접 원인은 `hotpost/quality_boundaries.py:40–45`의 12프레임 JPEG sheet(quality=92)와 `hotpost/writing/jobs.py:227`의 개별 inlineData 1MiB 제한 불일치다. 텐트 실제 `job-3670ecae905e4be8/boundaries/boundary-sheet-1.jpg`는 1,244,452바이트, `boundary-sheet-3.jpg`는 1,096,485바이트. 둘 다 1440×2010=2,894,400픽셀이므로 해상도 4MP 제한 문제가 아니라 바이트 제한이다. overview/cover/개별 beat JPG는 제한 이내. worker는 `codex_writer.chat`(:239) 이전에 거절하므로 이는 모델의 콘텐츠 불합격/근거 부족 판단이 아니다. 원본 경계프레임과 SHA를 보존하면서 sheet grouping/encoding을 1MiB 안으로 조정해야 한다. 같은 입력을 같은 포장으로 재시도하면 동일 실행 실패 가능성이 있다. 13:06 root에 즉시 통보했으며 본 감시자는 코드/운영 변경을 하지 않았다.

이 시점 이전 실패 3job 행의 hash는 baseline과 동일했다.


## 13:06–13:09 실제 QA 판정과 로컬수선 우선순위

더플 QA `job-cc4e29f6336743c8`는 실행 자체는 done이며 실제 콘텐츠 issue 1개: beat-3 “이 주황색에 눈이 가요”의 시작/중간에는 네이비 가방, 끝에는 주황 가방이 보인다는 명시색 지시 불일치. 감시자는 저장된 `beat-3-0.jpg`, `beat-3-2.jpg`를 직접 열어 네이비→주황 연결을 확인했다. 따라서 전반 몽타주의 반응/맥락 허용과 구별되는 구체적 내용 결함 근거가 있다. 같은 원본 4.4초 재등장은 advisory이며 blocking repetition issue가 아니다. 단 advisory 문자열의 “새 장점·구도·마무리 제공하는지” 표현은 새 정보 필수처럼 오해할 여지가 남아 root에 정리 권고했다.

자동화는 바로 `refresh_sources` `job-fbdb188208334660`을 시작했다. `daily_quality.py:615–624`는 required_scenes가 있고 현재 coverage가 맞을 때만 reedit으로 보내며, 없는 경우 수집을 enqueue한다. 기존 source의 다른 주황 컷/인접 원본 정상속도 구간으로 beat-3를 수선할 수 있는지 먼저 판단하지 않은 채 수집으로 넘어간 점은 비효율 가능성이 있어 root에 즉시 보고했다. 이는 “추가 수집이 필수”라는 결론을 확인한 기록이 아니다. 수집 checkpoint에는 TikTok no_unused_supported_scope, 여러 provider not_attempted/tab_missing, YouTube saved manual gate가 기록되어 있으며 이러한 접근 미시도를 콘텐츠 소스 실패로 세지 않는다.

13:09 손난로 `job-7164b6a7d2454940`의 QA `job-26633bf96fee4e4a` done, task completed, quality passed/issues=[], repair_round=0 확인. technical agent의 세 MP4 및 47개 source clip normal-speed/frame/voice/mask/clock 감사 PASS는 별도 산출물 `data/editorial-montage-20261018/output-audit/job-*-technical.json`에 있다. 이 기술통과가 텐트 QA 실행오류 또는 더플 실제색지시 issue를 덮지 않는다.

## 최신 디스크 정책과 운영 세대 구분 재확인

`source_policy.current_policy()`는 legacy v3, `montage_policy()`는 명시 v4로 분리됨. `adopt_policy(existing)`는 saved policy를 반환하고 `new_run=True`만 새 v4를 state에 채택하며 이전 run은 보존한다. `StudioStore.create` 신규 task는 montage_policy를 동결하고 기존 task 재오픈은 그대로 보존한다. 현재 디스크에 이에 대한 테스트가 있다. 이 최신 source_policy/studio_store 및 source_interval_recovery prompt 변경은 main PID 18948의 deployment-v1 이후 변경으로 최종 idle deployment-v2 대상이다. 현재 세 run의 v4 및 주요 semantic/renderer 정책 적재와 혼동하지 않는다.


## 중요 정정: 순간 색상 불일치를 실제 결함으로 단정하지 않음

root가 사용자 최신 기준을 다시 지적한 뒤, 감시자는 앞 절의 “구체적 내용 결함 근거”라는 즉시 분류를 철회한다. 저장된 `whole-video-overview.jpg`와 beat-3 시작/끝을 함께 보면 전체 몽타주에 Montbell 더플의 주황·네이비·초록·노랑 변형과 착용/수납이 반복되며, 같은 대사 beat 안에서도 네이비에서 주황으로 넘어간다. 다른 제품 구조/부품을 해당 제품의 실제 시연처럼 보여주는 사례와는 다르다. navy 순간과 orange 자막의 차이 자체로 전체 제품 이해·매력의 손상이 입증되지는 않는다. 관련 반응 컷도 허용하는 사용자 기준에서 동일 제품 변형의 지원 컷에 더 엄격한 동시 색상 일치를 부과할 이유는 확인하지 못했다. 이 관찰만으로 외부 수집이 필수라는 결론은 부적절하다.

기존 QA false/원시 응답은 보존하고, 동결 대본과 실제 전체 프레임을 새 명확 기준으로 재평가해야 한다. 본 감시자의 판단은 모델 영수증이나 실제 청감·영상 재생 검증을 대체하지 않으며 pass를 수동 변경하지 않는다. root는 정상 pause-auto로 더플 수집을 중지하여 불필요한 외부 비용 진입을 막고 재평가를 준비한다고 알렸다.

남은 직접 상충: `scene_analysis.py:50` “A color/model-specific detail needs matching footage only for that detail”은 detail별 matching을 필수로 요구하므로 전체 몽타주 기준과 충돌할 수 있다. matching은 선호이고 관련 색상/모델 변형도 지원 컷으로 허용하며, 실제로 다른 구조를 그 제품의 직접 시연으로 제시하거나 전체에 없는 상품 사실을 단정하는 문제와 구별해야 한다. `daily_quality.py:207`의 반복 advisory도 새 정보·새 구도 필수처럼 읽히지 않게 정리 권고했다.


시각 정정: 앞의 “13:09” 손난로 결과 메모는 수기 시각 오기이며 실제 마지막 스냅샷 시각은 13:08:57.401이다. 이 스냅샷에서 텐트 attention/QA failed, 더플 paused/수집job paused, 손난로 completed/QA passed이다. 더플 정상 pause-auto가 13:07:58.336에 job에 반영되었다. 기존 실패 3행 hash는 baseline과 동일하다.

정적 보완 검토: scene_analysis에 색상 전용 Python hard filter는 발견하지 못했다. 모델의 feature_incompatible_shot_ids/opposite 결과를 결속하는 일반 필터는 존재한다. 따라서 RANK의 색상 detail별 matching 문구를 완화할 때 단순 색상 차이를 feature_incompatible/opposite로 자동 분류하지 않는다는 의미도 일관되게 명확히 할 필요가 있다. 실제 wrong-product 구조/기능 시연 보호는 유지한다.


## 최종 독립 감사 근거

실행 산출물: `data/morning-edit-failure-audit-20261018/duffel/production-preservation-final.json` (SQLite mode=ro, 13:20:49.294+09:00).

|대상|최종 actual QA job|결과|계약 SHA / 추가 실제 확인|
|---|---|---|---|
|텐트|job-fdebcc884aa84bcd|passed / issues=[]|079d83876025… (v3), 새 실제 프레임 검수|
|더플|job-96d66a9a26db4790|passed / issues=[]|079d83876025… (v3), evidence_recheck=true, 실제 dense frame confirmation|
|손난로|job-26633bf96fee4e4a|passed / issues=[]|a3750c9fa335… (앞선 v2), 기존 통과 유지|

원래 세 failed edit만이 아니라 `three-before.json`에 저장한 기존 15job의 **모든 DB 필드**를 현재 행과 비교해 일치했다. 오전 실패 디렉터리의 baseline-evidence 36파일은 SHA·바이트·mtime 전부 일치했다. scripts/voices 전체 기존 record가 보존되고 대본 파일은 기존 저장 text+개행과 일치한다. 음성3/원본소스11은 실제 파일 SHA가 기존 저장 SHA와 일치한다. source ID/path도 보존된다. 더플 source review의 추가 실제 interval/mask receipt 갱신과 원본 파일 불변은 구별한다. 기존 run ID와 source_policy는 모두 남고 각 task에 새 run 1개가 추가되었다.

최초 재제작 이후 job 합계는 edit3, quality_review5, refresh_sources1(paused), voice0이다. 세 edit 디렉터리에 각각 render-request.json 1개와 completed render-result.json 1개가 있다. 추가 검수만으로 원본 MP4/plan을 다시 렌더하지 않았다. 더플의 구멍은 정상속도 source extension 승인 후 같은 job에서 다시 분석하여 해결했고, 그 뒤 각 영상은 렌더 1회로 완성됐다. 불필요했던 수집1개는 정상 pause-auto로 중지되었고 새 QA 전 `final-quality-recheck/before.json`의 paused row와 최종 row가 전필드 일치한다.

수집 정확성: paused manifest의 search_attempts=0, deferred-candidates 결과9개와 실제 network_received=4/download_attempts=4를 구별한다. videos 폴더의 MP4 4개와 transfer receipt의 attempted/complete를 직접 확인했다. 생성/수정 시각은 13:06:18–13:07:50, 최종 수집job paused는 13:07:58.336이다. 미시도5개와 다른 provider의 tab_missing/manual login gate는 콘텐츠 실패로 세지 않는다. 새 수신 파일은 소스 state에 편입되지 않았고 기존 source 수는 3/3/5 그대로다. 따라서 “외부 수집 없이 제작 성공”이나 “추가 수신0”은 사실과 다르다. 정확한 설명은 **불필요한 추가 수신4개를 중지·보존한 뒤 기존 소스만으로 성공**이다.

### 큐와 실제 claim 이후 시간

아래 active 값은 worker claim에서 마지막 DB update까지이며 순수 모델 추론 시간이나 CPU 시간은 아니다. paused 수집은 중간 작업과 정상 중지 대기까지 포함한다.

|작업|큐 대기 초|claim→마지막 update 초|created→updated 초|
|---|---:|---:|---:|
|텐트 edit|0.776|182.416|183.192|
|텐트 첫 QA 전송실패|581.446|7.720|589.166|
|더플 edit(추가 실제 구간 검토 포함)|182.727|454.061|636.788|
|더플 첫 QA|135.241|43.316|178.557|
|더플 불필요 수집→paused|0.313|120.562|120.875|
|손난로 edit|636.358|126.915|763.274|
|손난로 QA|51.489|38.447|89.936|
|텐트 새 QA|0.678|45.259|45.937|
|더플 새 QA|45.829|44.226|90.055|

텐트 첫 QA 589초는 대기 581초를 포함하므로 이미지 포장 오류 처리에 589초가 걸렸다고 쓰지 않는다. 첫 새 edit 생성부터 최종 완료까지의 큐 포함 전체 wall time은 텐트25:03, 더플25:47, 손난로14:13이며 병렬·직렬 단계가 겹치므로 단순 합산하지 않는다.

### 최종 배포와 검증 한계

deployment-v2는 main31148/launcher22244, idle exact-process replacement, loaded59. 실제 loaded receipt와 expected59 및 현 디스크59 SHA 일치, process alive를 독립 확인했다. v1 때 pending이던 source policy/store/proposal 정렬, v3 색상 기준, image transport budget, 새 explicit recheck API가 v2에 반영됐다. 정상 API 재QA는 queue render/plan/contract SHA를 worker까지 결속하고 기존 failed/paused job을 되살리지 않는다. 독립 회귀 24passed 결과는 정책 검수 문서에 기록했다.

새 QA가 통과한 사실은 저장된 실제 프레임·경계·오디오 시계 감사 결과다. receipt의 audio_listened=false/full_motion_review_complete=false 한계는 유지하며 감시자가 실제 GUI 재생·청감을 했다고 주장하지 않는다. 기술 output-audit와 root의 실제 재생/공유 검증 결과를 함께 봐야 한다. 최종 v3 원작 재평가는 9pass+실제 다른 구조 direct-demo 1fail로 원시 이전 결과와 별도 보존돼 있다.
