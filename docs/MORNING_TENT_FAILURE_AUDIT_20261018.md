# 2026-10-18 오전 텐트 편집 실패 감사

대상: `work-17bb4524ce3a4217` / `DeZbgOAKTjP` / 자동 선정 1위. 범위는 보존된 DB·요청·응답·프레임과 현재 코드의 읽기 전용 조사다. SQLite는 `file:data/studio/studio.sqlite3?mode=ro` 및 `file:data/writing/jobs.sqlite3?mode=ro`로 열었다. 운영 상태·설정·브라우저·프로세스·제작 자료를 변경하지 않았다. 모델·수집·TTS·렌더를 실행하지 않았다. 기존 선택기를 메모리 복사본에만 실행해 분기별 상태 수를 관찰했다.

## 판정

**직접 원인은 의미 검토 후 허용된 구간의 부족이다. 실제 저장된 후보 그래프는 수학적으로 배정 불가능하다.** 전체 검토 소스 27.5초가 준비되었다는 판정과, 현재 대본의 모든 beat에 중복 없이 배정 가능한지를 혼동했다. 편집기는 이를 정상적인 추가 검토·장면 확보 문제로 전달하지 못하고 일반 실행 오류로 종료했다.

이 사례는 빔 폭 부족이나 필수 증거 프레임 제약 때문에 생긴 오탐이 아니다. 필수 프레임·사전 선택 고정이 없으며, 실제 선택기가 한 번도 빔 가지치기를 하기 전에 beat-9에서 후보가 0이 된다. 다만 수집의 기능별 승인과 순위 모델의 제품 전체 제외 범위가 일치하지 않으므로, 물리적으로 받은 모든 영상 자체가 부족하다고까지 결론 내릴 수 없다.

## 실제 실행·오류 근거

시각은 KST다. DB의 jobs 및 events에 다음 기록이 있다.

| 단계 | 작업 ID | 시각/결과 |
|---|---|---|
| 작업 생성 | work-17bb4524ce3a4217 | 07:24:01.431 |
| 원본 준비 | job-b3d832e74c1d41ef | 07:24:02.124 claim → 07:24:56.554 완료 |
| 소스 확보 | job-9371e70d730a4f25 | 07:24:57.138 claim → 07:58:34.029 완료 |
| 대본 | job-93f7c30fbde64cb4 | 07:31:20.206 완료 |
| 음성 | job-3b3b9e8609d74e25 | 07:32:32.962 완료, request 248 |
| 편집 | job-b9719e6d67ad402b | 07:58:34.405 claim → 08:01:05.831 실패 |

실패 파일: `data/studio/work-17bb4524ce3a4217/job-b9719e6d67ad402b/select-shots-result.json:2` (`status=failed`), `:3` (`No reviewed complete global plan; insufficient candidates or required evidence`). `select-shots.log`는 빈 파일이다. 별도 Python traceback은 이 결과 파일에 저장되지 않았다. DB checkpoint의 select process는 PID 24480, created=1792278065.2816043이며, analyze는 PID 15108이다. 실패 result의 request SHA는 `fa3c1be3dc36abeab08c6f6256c282bdf57a941220a662cfb4c241f6b0f8e7ff`이다.

호출 위치는 `../auto_capcut/auto_capcut/core/studio_story_selection.py:98–102`; runner의 일반 예외 처리(`../auto_capcut/auto_capcut/studio_runner.py:102–103`)가 문자열 오류만 반환한다. Hotpost `hotpost/studio_runtime/editing.py:250`이 이를 RuntimeError로 바꾼다.

실패 후 DB에는 `status=attention`, `automation.active=false`, `daily_quality.pending=failed`, `daily_quality.failed_job_id=job-b9719e6d67ad402b`, `edits=[]`가 남았다. 다음 수집·수정 작업은 생성되지 않았다. 생성된 완성 편집본도 없다.

## 실제 beat별 후보

요청은 `select-shots-request.json`의 plan이다. 길이는 무음 제거 후 14.033741497초, 16 beat, 10 shot, 3 source다. 의미 분석 전 음성 길이 16.300408초와 구분한다. 전역 정책은 같은 파일 `:27712`에 저장된 `product-story-global-v3`다.

아래 A/B/C는 source 1의 shot-1-1/1-2/1-3, D는 shot-2-3, E는 shot-3-1이다. 모든 후보는 source 원본 시간 재사용 없이 beat 전체 길이를 채워야 한다.

| beat | 대사 | 길이(초) | 실제 허용 후보 |
|---|---|---:|---|
| 1 | 같이 도착했는데 | 1.040000 | E, B, D |
| 2 | 저쪽은 벌써 | 0.540000 | C, B |
| 3 | 텐트 안에서 | 0.600000 | C, B, E |
| 4 | 쉬면 부럽잖아요 | 0.986667 | C, B |
| 5 | 이건 차 뒤에 달고 | 1.066667 | C, A, B |
| 6 | 와서 삼 초 만에 | 0.800000 | C, A, B |
| 7 | 펼치는 텐트예요 | 0.900000 | C, A, B |
| 8 | 짐 풀기도 전에 쉴 | 1.400000 | C, B |
| 9 | 자리가 생기는 거예요! | 1.200000 | C, A, B |
| 10 | 바닥이 땅에 | 0.653333 | C, A, B |
| 11 | 닿지 않아 습기랑 | 0.800000 | C, A, B |
| 12 | 냉기가 덜하고 | 0.880000 | C, A, B |
| 13 | 네 식구가 함께 | 0.853333 | C, A, B |
| 14 | 들어갈 만큼 넉넉해요 | 1.100000 | C, A, B |
| 15 | 댓글에 | 0.353333 | C, A, B |
| 16 | ‘나도’ 남겨주세요 | 0.860408 | C, A, B |

A=`[4.1,5.1]` 1초, B=`[6.85,10.85]` 4초, C=`[10.9,11.9]` 1초. 원본 SHA는 모두 `7adee945ea590d18590f410d7708943a5b367e5ff92dea5a99cb348e5bd373b8`이다. 요청의 shot 정의는 `:944`, `:1019`, `:1094`다. 나머지 4초짜리 shot-1-4(`[13.7,17.7]`, `:1168`)는 어떤 beat의 option에도 없다. 이 구간은 휴식 장면에서 다른 외형 제품의 접기처럼 보이는 장면으로 전환되며, beat-6/7에는 opposite로 명시되어 있다.

source 2는 5.5초(0.8+0.7+4.0), source 3은 12초(4+4+4)다. source 2/3 총 17.5초는 준비 판정에는 포함되나 beat 5–16의 모든 option에서 제외된다. 0.8/0.7초 짧은 shot도 일부 beat보다 길이가 짧고, shot-2-1은 product_visible=false다.

**불가능성 증명:** beat 2, 4, 5–16의 후보 합집합은 A/B/C뿐이며 수요가 12.393741497초다. 공급 합집합은 겹치지 않는 6초다. 최소 6.393741497초가 부족하다. beat 5–16만 보아도 10.867074830초 대 6초다. 따라서 어떤 탐색 알고리즘도 현재 승인 그래프로 완성 배정을 만들 수 없다.

메모리 복사본에 기존 `select()`를 적용하고 `sys.settrace`로 `studio_story_selection.py:98`에서 관찰한 `(incoming, next)`는 beat 1부터 `(1,3),(3,6),(6,15),(15,21),(21,20),(20,41),(41,52),(52,8),(8,0)`이다. 모든 시점 `pruned=False`; beat-9에서 원래 오류가 재현된다. 모든 shot의 `required_source_frames=[]`, selected_shot_id 고정 없음, selection_exclusion 없음도 확인했다. 여기서 재현한 것은 선택 산술뿐이며 렌더나 모델 호출이 아니다.

## 완화된 레퍼런스 기준의 적용과 기능 범위 불일치

적용 여부는 현재 코드만으로 추정하지 않았다. 실제 순위 모델 작업 `codex208c7481b37390c8ebf7ec67da21571b`의 `data/writing/.../payload.json:2`에 PRODUCT_APPEAL_INSTRUCTION 전체와 “Exact sentence-by-sentence ... a preference, not a pass/fail requirement”가 있다. 응답은 `result.json`이다. 원문 이야기의 도착·부러움·정확한 3초·4인 수용을 직접 입증하지 않는 source 1을 context로 허용한 점에서도 이 기준은 실제 사용되었다.

반면 모든 beat 5–16은 `promoted_subject_reference=true`이며 source 2/3의 6개 shot이 모두 incompatible로 기록되었다. 실제 raw result도 동일하다(`result.json:105` beat-5, `:278` beat-10, `:453` beat-15). 따라서 이 건의 후보 소실을 Python 후처리 단독으로 설명할 수 없다.

`hotpost/scene_analysis.py:247–252`는 전체 beat의 incompatible 집합을 합치며 `:262–267`에서 모든 promoted beat에 적용한다. 이 구조는 기능 한 가지의 불일치를 제품 전체·후속 문장에 전파할 위험이 있지만, **이번 raw 응답은 이미 같은 제외를 모든 beat에 반복했으므로 union 제거만으로 텐트 작업은 고쳐지지 않는다.**

수집의 실제 functional review는 source 2/3을 same_core_function=true로 승인했다. 승인 특징은 “다리와 프레임으로 텐트 바닥을 지면 위에 띄우는 구조”, “지면에서 떨어진 잠자리 공간”, “출입구를 열어 내부 공간 접근”이다. 동시에 차량 연결·운반/전개·4인 수용은 확인되지 않는다는 제한을 유지한다. 근거는 `data/source_jobs/DeZbgOAKTjP-1792275897166605000/source-review-claim-b026a603b4ba47fe.json`의 현재 sources 영수증과 `hotpost/source_functional.py:153–164`의 기능별 core 허용 지침이다.

보존 프레임을 직접 확인했다. reference `source-reference/frame_001.jpg`와 `frame_003.jpg`는 차량 뒤 주황색 상자형 텐트다. source 1의 `analysis-frames/5347022744b3421193e3a65eb9e9a0ee/shot-1-2-1.jpg`는 같은 계열의 주황색 텐트에서 사람이 쉬는 모습이다. `shot-2-3-1.jpg` 및 `shot-3-1-2.jpg`는 실제 바닥을 다리로 띄운 녹색 침상형 텐트다. 단순 색상·정확한 SKU 차이만 있는 것은 아니며 차량 장착 구조의 차이는 실재한다. 이들을 차량 부착·차량에서 펼침의 직접 시연으로 배치하면 부정확하다.

다만 수집 단계는 기능별 core로 분량을 세고, 순위 단계는 차량형 제품 전체와 다르다는 이유로 지면 이격 혜택·마무리까지 배제한다. 이는 **증거로 확인된 단계 사이 의미 범위 불일치**다. 녹색 텐트를 전체 영상의 주제품으로 오인시키지 않으면서 지면 이격 기능의 관련 예시로 사용할 수 있는지는 별도 실제 컷 검토가 필요하다. 이 감사는 그 컷을 자동 승인하지 않았다. 동일 SKU를 강제했다거나 모든 incompatible 판단이 틀렸다고 단정할 수 없다.

또한 beat 10 이후만 완화해도 충분하지 않다. beat 2/4/5–9만 6.893333333초를 A/B/C의 6초에서 요구한다. 실제 관련 휴식 장면의 범위를 재검토하거나 기존 혼합 구간을 정확하게 나누거나 새 matching source를 확보하는 조치도 필요하다.

## 공급은 정말 고갈되었는가

그렇게 입증되지 않았다. 수신은 TikTok 6편, 최종 사용은 3편이다. 수집 완료 영수증은 `quota_met`, available_sources=6, reviewed_sources=3, deferred_sources=3을 남긴다. 추가 미검토 수신본 SHA는 `44717bad475916147d2041fb1c36533909c4e93e0b99c4400adc3c5ccb42ce44`, `8955aaa10dc8285af9cee3789de3b05ed7422006a54ae252db69612bc64dcbc1`, `25794104da2c1c33e40395ca76a45fb44575b0fa5b93034f525c1800a8e29faa`다. collect checkpoint의 이전 batch 영수증에는 8955…가 포함된 4편/31.6초가 보이나, 현재 최종 sources 및 goal은 3편/27.5초다. 이전 checkpoint를 현재 가용 소스로 더해 계산하면 안 된다.

TikTok 검색 5회, 수신 6편 외 후보의 not_probed도 보존돼 있다. 실제 접근 제한이 별도로 기록된 다른 플랫폼을 자동 사용 가능한 공급으로 가정하지 않는다. 현재 소스 재고로 해결할 수 있을 가능성은 있으나 미검토 파일을 승인분으로 셀 수 없다. 기존 짧은 구간 복구도 collect checkpoint의 `interval_recovery` 영수증에 실제 수행 흔적이 있으므로 “로컬 복구를 전혀 시도하지 않았다”는 결론은 틀리다.

현재 source_goal은 ready=true, usable_seconds=27.5, required_seconds=20.38, output_seconds=16.3, core_seconds=27.5다. 준비 판정은 모든 beat에 대한 의미·부모 시간 비중복 배정까지 검사하지 않았다. 코드상 수집 조기 완료는 `hotpost/studio_sources.py:781–791`, batch의 준비 완료는 `hotpost/source_batches.py:151–155`다.

## 정상 재검토·재수집으로 이어지지 않은 이유와 수정 제안

`hotpost/studio_runtime/editing.py:410–416`은 options가 아예 없는 beat만 QualitySceneGap으로 바꾼다. 이번에는 모든 beat에 2~3개 옵션이 있어 통과하지만 전체 배정은 불가능하다. 전역 선택 실패의 구조화된 diagnostics는 runner 일반 예외 처리에서 사라진다. `hotpost/studio_runtime/lifecycle.py:180–181`의 정상 scene-gap 경로에 들어가지 못하고 `:204–214`의 일반 실패 경로를 탄다. `hotpost/daily_quality.py:300–317`의 실패 처리로 active=false가 된다. 단순한 자동 서비스 재시도도 이 수학적 부족을 해결하지 못한다.

권장 순서:

1. 전역 선택 실패를 구조화해 보존한다. 실패 beat, 후보별 길이·제외 사유·부모 SHA, 부족한 후보 집합, search_budget_pruned를 반환하고, 정확한 부족은 QualitySceneGap/사전 준비 부족으로 연결한다. 빔 예산 부족은 자료 부족과 구별한다.
2. 수집 ready를 확정하기 전에 현재 음성 beat와 의미 승인 후보로 전체 비중복 배정을 확인한다. raw usable/core 총합을 보조 지표로 유지하되 그 값만으로 완성 가능하다고 선언하지 않는다.
3. source의 matched_reference_features/usage_limits와 beat의 실제 기능 범위를 같은 계약으로 전달한다. 차량 부착 불일치를 지면 이격의 관련 예시까지 자동 확대하지 않도록 하고, 제품 전체 오인과 기능 한 가지의 지원을 구분한다. 실제로 다른 기능을 주제품 직접 시연으로 쓰는 제한은 유지한다.
4. 전역 배정 부족이 입증되면 이미 받은 deferred 파일·혼합 구간의 기존 증거를 먼저 재검토하고, 미충족 기능에 맞는 새로운 scope만 수집한다. 새 대본·새 TTS·같은 조건의 무의미한 재편집을 먼저 반복하지 않는다.
5. 불가능성이 입증된 이 건에서 beam_width 확대나 원본 시간 재사용 허용을 해결책으로 삼지 않는다. 필요한 승인 공급을 늘리거나 잘못 확장된 의미 제외 범위를 실제 증거에 맞게 고쳐야 한다.

본 감사에서는 수정·재개·추가 검토를 실행하지 않았다. 운영 자료를 보존한 채 원인과 필요한 수정을 특정한 결과다.
