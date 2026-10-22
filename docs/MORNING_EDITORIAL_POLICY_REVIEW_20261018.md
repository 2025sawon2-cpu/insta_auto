# 오전 제작 기준 독립 검수 — 2026-10-18

상태: 기준 구현·실제 원작 v3 검증·동일 상위3 제작의 독립 검수 완료(2026-10-18). 아래 최종 상태가 현재 결론이며, 이후의 초기 미해결·대기·진행 중 표현은 당시의 시간순 관측 이력이다.

검수 대상: 전체 제품 매력 중심 기준과 실제 의미 후보·renderer·소스 연장·복구 연결. production 코드·운영 DB·설정·프로세스·브라우저를 변경하거나 모델·수집·TTS·렌더를 실행하지 않았다. root가 명시 위임한 테스트 2파일의 범위만 수정했고 기존 dirty 및 실패 증거를 보존했다.

## 최종 확인 상태

- 공유 기준은 `product-appeal-first-20261018-v3`, 신규 배치 정책은 `normal-speed-editorial-v1`이다. 반응/맥락·특장점 재사용·같은 제품 색상 전환을 허용하고 제품 전 컷 노출이나 반복별 새 정보를 강제하지 않는다. 실제 다른 제품 구조/부품 및 반대 동작의 직접 시연 오인은 계속 검사한다.
- 실제 원작 v3 평가는 10회 새 호출, 9pass와 실제 다른 구조 연결 결함1개다. 최초부터 공기청정기 native17장을 추가하고 원본/전사/프레임 SHA 및 동결 instruction 일치를 확인했다. 이전 v2 원시10pass와 별도 결과다.
- 같은 상위3 task는 모두 completed/QA passed, 최종 render/plan SHA 결속 및 전역 활성job0을 확인했다. 텐트·더플은 v3 새 QA, 손난로는 기존 v2 실제 QA 통과 유지이며 모두 v3로 다시 호출했다는 주장은 하지 않는다. 더플의 이전 색상 false는 삭제하지 않고 새 actual dense-frame confirmation으로 상충을 해결했다.
- baseline36파일 SHA/size/mtime와 기존15job 전필드 보존, 승인 대본3·음성3·원본소스11 실제 파일 및 새 run 각1/렌더 각1/voicejob0을 확인했다. 불필요한 더플 수집job1이 중지 전 받은4파일은 미검토 보존되며 정식 편입/최종 사용0이다.
- 현재 `daily_quality.py` 실제 코드에서 반복 advisory는 “특장점 반복은 허용하며 전체 흐름의 자연스러움”으로 정리됐고 새 정보 요구가 남지 않았다. explicit 재QA의 동일 false duplicate는 needs_attention/scene_wait/stop_method로 끝나 pending ghost를 남기지 않는다. 새 독립 반례24개가 이를 포함한다.
- `AGENTS.md` 하단 수집 v3 필수분량은 저장된 v3 이력에 한정하고 신규 v4는 권장량으로 구별했다. 반대 동작은 대사의 직접 시연 오인 금지로 한정했다. `docs/source_video_pipeline.md:105`도 신규 v4/legacy v3를 명확히 구분해 초기 문서 상충은 해소됐다.
- 남은 기능 범위는 한 beat를 여러 짧은 컷으로 자동 연결하는 일반화다. 이번3개에는 필요하지 않았으며 새 불합격 문턱으로 추가하지 않았다. 프레임 표본 QA를 연속 동작·청감 전수검증으로 확대해 주장하지 않는다. root의 실제 GUI/공유 검증 보고와 독립 파일·DB 감사를 구별한다. `ui-verification.json`의 외부 세 영상 모두 ended=true/error=null 및 duration/currentTime 일치를 읽어 총괄8절과 대조했다.

## 최종 검수 범위와 근거

명시 위임한 `tests/test_quality_progress_independent.py` cache 계약 갱신/2개 반례 추가는 파일 검사32passed, `tests/test_quality_policy_recheck_20261018.py` 새 재검토 API/duplicate 경계는24passed였다. 각 숫자는 겹치는 회귀와 합산하지 않는다. actual v3 참조·완성 QA·GUI/공유 검증은 담당 agent/root가 실행했다.

최종 raw는 `data/morning-edit-failure-audit-20261018/duffel/production-preservation-final.json`, `data/editorial-montage-20261018/completion-audit.json`, `reference-review-final/validation-summary.json`, `output-audit/`에 있다. 총괄 보고서 6~8절을 실제 수치·receipt·root GUI 검증 보고와 대조했으며 중대한 결과 차이를 발견하지 못했다. 이후 본문은 초기 발견과 수정·재평가의 이력을 보존한다.

## 사용자 기준

- 대사의 문장·순간마다 장면이 기계적으로 일치할 필요가 없다.
- 같은 특장점·시연·제품 화면이 반복될 수 있다. 매번 새 정보·새 각도를 보여야 하는 것은 아니다.
- 관련 리액션·생활 맥락 화면은 제품이 잠시 보이지 않아도 전체 흐름에서 사용할 수 있다.
- 부족한 길이는 실제 원본의 연속 구간을 정상 속도로 늘리는 방법을 먼저 검토한다. 감속·정지 프레임으로 채우는 방식과 구분한다.
- 다른 제품·부품·반대 동작을 해당 제품의 직접 시연이라고 오인시키는 것은 계속 구체적인 결함으로 검토한다. 실제 가림·출처·음성·파일/시간 증거 계약을 무효화하지 않는다.
- 과거 불합격을 새 기준의 pass로 수동 치환하지 않는다. 실제 원본/출력과 새 기준으로 독립 재평가해야 한다.

## 최초 직접 읽기에서 확인한 상충 경계

1. 기존 `scene_analysis.py`는 `promoted_subject_reference=true`인 모든 fragment에서 `supports_product`를 강제했다. 추천·혜택·마무리까지 true로 만들도록 지시하므로 제품 없는 리액션/맥락이 사실상 불가능했다. `shot_presentation.interval_receipt`의 `all(frame_product_visibility)`는 “제품이 전체에 보이는 직접 증거” 분류로 남을 수 있지만, 모든 montage support의 입장권이 되어서는 안 된다.
2. 기존 renderer `studio_story_selection.py`도 같은 flag로 제품 전 표본 노출을 강제하고 이미 사용한 원본 시간은 전부 빼고 할당했다. 프롬프트만 완화해도 실제 계획 생성은 여전히 막혔다. 새 정책이 제품 맥락/직접 시연을 구분하고 정상 속도 범위·필수 증거를 보존하며 반복을 평가 의견으로 다루는지 별도 확인해야 한다.
3. 기존 공통 정책과 최종 `daily_quality.REVIEW_INSTRUCTION`에 “새 구도/동작 없는 반복” 표현이 있었다. 새 정보가 없는 반복 자체를 결함으로 돌려보내지 않게 실제 QA 지침도 동기화해야 한다. `visual_metric_advisories`는 현재 수치만으로 실패시키지 않으므로 그 성질을 유지한다.
4. `source_coverage.coverage_goal`의1.25배/핵심4초는 재고 준비 규칙이지 대본별 편집 가능성 또는 최종 매력의 증명이 아니다. 더 많은 비제품 맥락을 무조건 수집해야 한다는 품질 기준으로 바꾸거나 원작 자체를20% 부족으로 부적합 판정하지 않는다. 원작5개 감사에서도 전장 단독 원본은1.25배에 미달하지만 intrinsic appeal은 별도로 통과했다.
5. `scene_requirements.required_scenes`는 저장된 모든 scene_gap/repetition/watermark를 계속 활성화한다. 새 기준으로 과거 literal/repetition 결함이 유효한지 실제 재평가 없이 같은 근거를 계속 복구하면 새 기준이 다시 옛 문턱에 걸린다. 반대로 저장된 불합격을 수동 삭제/pass 치환해서도 안 된다.
6. `scene_requirements._requires_native_proof`는 scene_gap 전부와 명시 proof match를 구속한다. `product_support`는 실제 관련 제품 프레임1개, direct_transition은 필요한 전후 상태를 유지하는 현재 계약이다. 이를 제품과 관계없이 모든 혜택/리액션에 새 프레임 의무로 확대하지 않아야 한다. 실제 직접 증거의 필수 native 노출은 유지한다.
7. 기존 functional/presentation 검토는 파일 전체 분류를 개별 장면의 제품 증거로 승격하지 않는다. context_only 자체의 활동이 읽히고 중앙 크롭이 보존되면 사용할 수 있는 경로가 있다. 새로운 “리액션 승인 영수증” 같은 별도 필수 모델 호출을 도입할 필요는 없다.

## 초기 v2 구현 확인 이력

`product_appeal_review.py`를 다시 직접 읽어 `product-appeal-first-20261018-v2`를 확인했다. 새 정책은 반복마다 새 정보 의무를 제거하고, 일반 혜택 중 제품 없는 reaction/context를 허용하며, 실제 검토된 원본 연속 구간의 정상 속도 연장을 설명한다. 차량 설치 없는 텐트의 공통 raised-floor 뷰를 전체 금지하지 않고 해당 기능만 제한하도록 명시했다. 이 공통 문구 자체는 사용자 기준과 맞는다.

후속 직접 읽기로 다음 보완을 확인했다. 실제 완료 영상의 품질 승인은 별도다.

- `scene_analysis`는 `visual_requirement=montage_support`를 기본으로 하고 `product`/`direct_action`에만 전 표본 제품 증거를 요구한다. `promoted_subject_reference`는 대사의 참조만 기록한다. 기존 관찰+순위 경로에서 리액션을 허용하며 새 리액션 전용 영수증을 요구하지 않는다.
- 특정 기능의 부적합 `feature_incompatible_shot_ids`는 해당 beat에만 적용한다. 실제 wrong-product `incompatible_subject_shot_ids`는 오인을 만드는 제품 참조에 계속 적용한다. 차량 설치 차이만으로 공통 raised-floor 장면 전체를 금지하지 않는다.
- RANK의 opposite 지침은 단순 동작 단어 등장과 실제 오인 시연을 구분하도록 바뀌었다. 새 명시 montage_support는 한국어 reason의 “순서여서…쓸 수 없음”만으로 not_established를 opposite로 자동 승격하지 않는다. 명시적으로 확정된 opposite를 context로 재명명해 되살리는 것은 계속 막는다.
- `daily_quality.REVIEW_INSTRUCTION`의 반복 새 정보 요구와 제품 없는 사람 컷 일반 금지가 제거되었다. 검수자가 지적한 “missing illustration(scene_gap)”와 “folding must not show unfolding”도 각각 literal 불일치는 advisory, 직접 시연으로 제시된 반대 동작만 구체 결함으로 다루도록 수정되었다.
- renderer는 명시 `normal-speed-editorial-v1` 아래 `allow_source_reuse=true`일 때 원본 시간 재사용을 soft cost로 취급한다. `promoted_subject_reference`만으로 제품을 강제하지 않고 `visual_requirement`를 확인한다. 기존 정책이 없는 과거 계획은 그대로 보존한다.
- renderer 선택 영수증 hash는 새 editorial_policy/visual_requirement를 포함한다. 새 정책의 실제30fps 출력 프레임 수에 맞춰 원본 구간을 할당하고, body `tpad`를 제거하며 실제 출력 clip 프레임 수를 확인한다. 짧은 구간은 일반 실패 문자열 대신 `reviewed_window_required`와 구간 요청을 반환한다.

단위시험 통과 보고는 담당 구현자의 실행 결과이며, 본 검수자는 시험·모델·렌더를 실행하지 않았다. 테스트 파일의 반례는 직접 읽었다. 의미 분석 시험은 제품 없는 혜택 리액션, 누락된 새 필드의 기본 montage, 기능 제외의 비전파, 실제 wrong-product/opposite 유지 등을 포함한다.

`daily_quality._quality_review`는 현재 instruction SHA가 다르면 과거 review를 이력으로 보존하고 다시 실제 검토하도록 되어 있다. 이 경계는 정책 변경 후 과거 pass/failed를 그대로 최신 결과로 재사용하는 것을 막는 데 유효하다. 실제 새 모델 평가가 완료됐다는 뜻은 아니다.

## 연속 구간 연결 검수와 당시 미해결 사항 이력

`hotpost/editorial_continuation.py` 및 `EditingMixin._render_editorial_feedback`를 직접 읽었다. 실제 file duration까지 같은 원본의 정상 속도 범위를 제안하고, 기존 A 승인 범위를 잃지 않는 A∪B 독립 가림·기능·세로 검토 후 같은 job에서 재분석한다. 같은 확장 방법의 실패/확정 결과를 영수증으로 보존하고 무의미하게 다시 승인받지 않는 방향이다.

최초 구현의 무조건 추가1프레임 요구는 실제 필요한2초가 원본2초에 들어가도2.033초가 없다는 이유로 거절할 수 있었다. 검수자가 지적했고 현재는 `required`와 선호 여유 `needed`를 분리하여 실제 필요 길이가 원본에 들어가면 여유가 없어도 제안하도록 보정되었다. 여유 프레임은 새 통과 문턱이 아니다.

아래는 후속 확인이 필요한 경계다.

1. 현재 solver는1beat=1shot을 유지한다. 모든 관련 파일의 실제 끝 때문에 한 beat를 복수의 정상 속도 컷으로 연결해야 하는 경우, 연장 제안이 없고 accepted0이면 hold로 끝날 수 있다. 다른 적합한 긴 컷이 있으면 기존 대안에서 선택 가능하지만, 복수 짧은 컷 연결 자체는 현재 구현에서 확인하지 못했다. 실제3task가 이 한계를 만나는지 관측해야 한다.
2. `_semantic_binding`에 현재 editorial_policy dict가 빠진 최초 구현을 지적했다. 후속 직접 읽기에서 geometry 입력에 실제 editorial_policy가 포함된 것을 확인했다. policy flag만 바뀌어도 과거 semantic cache를 그대로 최신 계약으로 재사용하지 않는다.
3. continuation 수용 저장은 최초에 source SHA만 확인했다. 검수 지적 후 현재는 실제 source 레코드 전체 hash가 검토 시작 시점과 같은지 확인하고, candidate에 최신 withdrawal을 적용했을 때 달라지면 Conflict로 거절한다. 검토 중 수동 사용/제외 변경을 덮지 않는 경계를 직접 읽어 확인했다. 사용자 pause와 claimed ownership 검사도 존재한다.
4. legacy scene_gap의 실제 재평가와 최종 QA 통과 여부는 실행 전이다. 새 기준 문구만으로 과거 불합격을 통과로 바꾸지 않는다.

## 관련 회귀 발견

root가 관련 회귀92개 중 `test_initial_pre_render_scene_gap_resumes_deferred_sources_and_updates_frozen_run_inputs` 1건의 실패를 전달했다. 검수자는 실행하지 않고 현 test와 흐름을 읽어 원인을 확인했다.

이 fixture는 초기 render가 아직 없고 feedback도 없지만, cover 사전 준비 실패와 실제 deferred source가 있어 `resume_assessment`가 정상 `pending=recollect`로 복구한다. 그러나 기존 dirty의 `advance_daily_quality` 최적화는 `coverage_current(state)`만 참이면 바로 reedit로 전환한다. 여기서는 `required_scenes=[]`라 coverage가 진공 참이며, reedit의 `queue_method/hypothesis`에는 해결할 실제 feedback/fact가 없어서 grounded=false로 hold한다. 따라서 refresh_sources가 enqueue되지 않는다.

이는 새 프롬프트 문구 때문에 생긴 모델 결과가 아니다. 최초 정적 읽기에도 존재하던 “이미 로컬 근거가 준비되면 외부수집 대신 편집” 분기의 빈 요구 경계 문제다. 실제 초기 deferred-source 재개에 영향을 주는 관련 회귀로 분류했다. root에 “실제 required_scenes가 존재할 때만 준비 coverage로 reedit 우회; cover/preparation-only의 빈 요구는 필요한 수신파일 검토를 계속”하는 좁은 수정과 현 test/기존 body-coverage 반례 유지 검증을 권고했다. 검수자가 파일을 수정하지 않았다.

root는 좁은 required_scenes 조건 보완 후 해당 시험이 통과했다고 보고했다. 이후222개 혼합 회귀 중221통과/1실패를 전달했다. 남은 `test_quality_review_reuses_same_actual_evidence_after_review_code_change`도 정적으로 확인했다. 이 시험은 과거 `older-review-contract` 및 boundary_evidence 없는 false판정을, 현재 REVIEW_INSTRUCTION까지 변경한 뒤에도 무조건 재사용하도록 요구한다. 현재 runtime은 policy SHA 일치와 `output-boundaries-v1` 영수증이 있을 때만 cache를 재사용하므로 fresh 검토로 넘어간다. 시험의 preview가 실제 MP4가 아닌 `b'old result'`라 다음 FFmpeg 단계에서 실패한다.

이는 정상 영상의 decode 실패 실측이 아니라 기존 fixture와 최신 검토 계약의 불일치다. 사용자 기준에 맞춰 runtime의 실제 새 기준 재평가 경계를 제거해서는 안 된다. 동일 policy/정상 경계 영수증일 때 재사용과 policy 변경/경계 영수증 누락일 때 fresh 검토 선택을 나누어 검증하도록 root에 권고했다. 현재3task는 edit0개여서 이 cache 경계를 직접 지나지 않는다. 이 시험이 아직 정리되지 않은 상태에서 회귀 전부 통과라고 기록하지 않는다.

이후 root가 **이 test 부분만 명시적으로 수정 위임**했다. 검수자는 `tests/test_quality_progress_independent.py`의 해당 부분만 갱신하고 production 모듈을 수정하지 않았다. 공통 fixture는 같은 영상/계획의 이전 false검토를 현재 instruction SHA와 경계 영수증으로 구성하며, 이 조건에서는 decode/모델을 다시 실행하지 않고 이전 판정을 보존하는 것을 확인한다. 두 반례는 policy 변경과 boundary receipt 누락이다. 실제 MP4가 아닌 unit fixture에서 decode 성공을 꾸미지 않고, 첫 FFmpeg 무결성 검사 호출 인수까지 확인한 뒤 `FreshMediaReviewStarted` sentinel로 중단하여 fresh 경로가 선택되었음을 검증한다. 이전 불합격 review 불변도 확인한다. 검수자 실행: `.venv/Scripts/python.exe -m pytest tests/test_quality_progress_independent.py -q` → **32 passed in 1.61s**. 이32개는 root의 혼합 시험과 겹칠 수 있으므로 합산하지 않는다. 실제 MP4 decode/모델 QA 완료를 뜻하지 않는다.

## 수집 준비 기준의 추가 상충

root가 명시 신규run의 v4 `editorial_montage`를 제안하여 직접 현재 source policy/coverage/batch 분기를 확인했다. 현재 v3는 총음성1.25배와 core4초를 hard ready로 요구한다. 실제 동일 특장점 반복을 허용하는 편집기와 달리 unique 원본 초를 필수로 유지하면 편집 가능한 풀에서도 수집이 이어질 수 있다. 새 명시v4에서 정상 검토된 핵심 제품 구간이 실제 존재하고 usable>0인 경우 inventory-ready로 보고,1.25배/4초는 선호 진단으로 유지하는 방향은 사용자 기준과 맞는다. core1초 같은 새로운 임의 문턱을 추가할 필요는 없다. inventory-ready는 현재 모든 결함 해결 또는 최종 QA pass와 별개다.

`source_batches.py`의 repair에서 신규 usable source를 초기2개/기존 edit3개 요구하는 조건도 새 기준과 상충한다. 한 새 구간으로 결함을 해결해도 수집을 멈추지 못하기 때문이다. v4에서는 개수 문턱을 제거하고 실제 장면 요구 preflight/최종 검토를 유지하되, 과거v3의 저장 계약은 보존하도록 권고했다. `source_finder.py`의 batch_enabled/정지조건/quota_ready도 completion_mode 분기를 함께 바꿔야 구 quota 경로로 되돌아가지 않는다. `goal_message`는 선호1.25배를 필수 미달처럼 표시하지 않아야 한다. `adopt_policy`가 미완료 savedrun을 덮는 현재 동작을 고려해 명시 새run 수용 경계와 과거 paused 읽기/재시작 불변 시험이 필요하다. 이 절의 v4는 아직 구현/검증 완료 판정이 아니다.

후속 직접 읽기에서 root는 `completion_mode=scene_duration`을 유지하고 version4/명시 editorial flags로 coverage를 분기했다. 따라서 수집기의 mode 분기가 구 quota 경로로 빠지는 위험을 피한다. 실제 core>0/usable>0인 준비, 기존1.25배·4초 `*_target_met` 선호 지표, “권장” 표시, repair 신규2·3개 개수 문턱 우회를 확인했다. `test_editorial_inventory_policy.py`에는 짧은 검토 core, context-only/다른 SHA의 비승격, pausedv3 읽기 불변 반례가 있다. 다만 `ensure_source_collection`은 기존부터 active 미완료 작업에서 adopt_policy를 호출하므로 적용 범위는 문자 그대로 새run에만 한정되는 것은 아니다. 읽기/paused 상태는 보존되지만 active v3 진행은 adopt 시 새 계약을 받을 수 있음을 root에 알렸다. 이번 대상3개는 명시 새run 재개라 그 차이를 기록하여 처리할 수 있다.

## 실제 저장 입력의 순수 배치 대조

renderer 담당자의 `data/morning-edit-failure-audit-20261018/editorial-renderer/replay_actual_three.py` 및 `actual-three-replay.json`을 직접 읽었다. 이 대조는 운영 select 요청을 복사하고 명시 editorial_policy만 새 사본에 적용한 산술 배치다. 기존 semantic 관찰·후보를 새 모델 평가처럼 바꾸지 않았고 실제 MP4/QA를 생성하지 않았다. 세 원래 요청 파일 불변 확인도 있다.

- 텐트 `work-17bb4524ce3a4217`: 기존 no feasible → 새 명시 반복 허용으로 완전 할당. 승인 mask 구간 검증 통과. 실제 새 의미 검토/최종 QA 통과를 뜻하지 않는다.
- 더플백 `work-06068a52b50e41b2`: 일반 실패 대신 beat3/14의 실제 정상 속도 인접 구간 검토 요청으로 분리. 이 파일은 새 실제 승인 전 완료가 아니다.
- 손난로 `work-09928d0b8f864345`: 기존 예산 초과 → 새 명시 반복 허용으로 완전 할당. 승인 mask 구간 검증 통과. 영상 자체의 자연스러움은 실제 출력 후 판단한다.

반복 장면의 `new_product_information=[]`가 있어도 즉시 거절하지 않고 배치한 사례가 있어 새 정보가 hard gate가 아니라는 코드 경계를 확인할 수 있다. 이 결과만으로 기존 failed를 production pass로 수동 치환하지 않는다.

## 실제 레퍼런스 재평가 계획

기존 결과를 덮거나 이미 완료된 출력의 skip을 새 평가로 부르지 않아야 한다.

### 원작6개 + holdout4개

기존 준비자료는 `data/reference-calibration-20261013-v2-native/selection.json`과 각 `<shortcode>/evidence.json`, `frames/`, `sequence-*.jpg`, `source-first-frame.jpg`다. 정확한 first_frame 파일명은 evidence 안의 path를 사용한다.6개 development와4개 holdout 선정은 이미 동결되어 있다.

|역할|코드|대상|
|---|---|---|
|calibration|DeWWWOeDhGk|주방 매트|
|calibration|DeRFXHpEwck|미니 파일 홀더|
|calibration|DeXut7fTAxb|폴로 니트|
|calibration|DeYveh9yeCq|모듈형 충전기|
|calibration|DeXupxVztwJ|틈새 청소 도구|
|calibration|DeVUQRZqKRM|캠핑 테이블 박스|
|holdout|DeXs0K5S52W|접이식 벽 행거|
|holdout|DeYZSuUyzzX|자석 도어 스토퍼|
|holdout|DeY776gqIQw|반려동물 공기청정기|
|holdout|DeWPBQyzpfR|자동 타코야끼 기계|

`tools/calibrate_reference_quality.py::review`는 원본/video·transcript와 first-frame/sheets 실제 SHA를 재확인하고 모델을 호출한다. 운영 task를 쓰는 경로가 아니다. 그러나 root가 과거 폴더로 고정되어 있고 target이 있으면 `already_completed`로 즉시 반환한다. 그대로 CLI를 다시 실행하면 현재 기준 실제 재평가가 아니다.

권장 실행 설계: 별도 감사 scratch runner에서 module.root를 새 출력 폴더로 바꾸고 기존 selection을 복사하되 절대 evidence_path는 보존한다. 새 `calibrated-policy.json`에 현재 `reference_instruction(daily_quality.REVIEW_INSTRUCTION)` 원문과 SHA를 먼저 동결한다. 이후 기존 review 함수를10건에 호출한다. holdout을 보기 전에 정책을 동결한다. `prepare`는 이미 준비된 프레임을 다시 만들고 Studio(workers=False)를 생성하므로 이번에는 불필요하다. 실제 실행은 root 담당이며 본 검수자는 실행하지 않는다.

기존 결과는 `summary.json`에10개 중 intrinsic9pass/holdout3pass,412표본으로 남는다. 이는 새 기준 결과가 아니다. 공기청정기의 다른 원통형 기기 연결처럼 구체적인 오인이 남으면 계속 불합격일 수 있으며, 새 기준을 검증한다고10/10을 강제하지 않는다.

### 원작5개 별도 감사

준비자료는 `data/source-strictness-audit-20261017/selection.json` 및 각 code의 `evidence.json`, `sequence-*.jpg`, `frames/`다. 대상은 `DeiBMuLzPxV` 스웻팬츠, `DeiCA-gyWhM` 틈새 선반, `DeiD1rYzW9-` 후드 집업, `Dege8mKBaUR` 지퍼 슬라이더, `DegiqugP5pn` 토트백이다.

`tools/audit_source_strictness_20261017.py`도 OUT가 과거 폴더로 고정되어 있고 종류별 target이 존재하면 skip한다. `run_one(...,'montage')`는 현재 PRODUCT_APPEAL_INSTRUCTION을 사용하며 실제 순서표본 SHA를 검사한다. 새로운 OUT/선정 영수증과 새 instruction SHA를 가진 scratch 경로로 재평가해야 한다. 기존 function/portrait/overlay 결과를 새 montage 결과로 바꾸지 않는다. 새 정책이 외관·맥락 평가에 미친 영향을 검증하려면 montage fresh review가 직접적이고, 가림 영수증 전체를 다시 돌리는 것은 별도 필요성 판단 대상이다.

### 결과 판정

- 실제 source/frame SHA·policy SHA·원문/시간·새 요청 시작/종료·원시 모델 JSON·passed/issues를 보존한다.
- 원작의 제작자 워터마크·얼굴 표지·개인 목소리 등 신규 제작 계약 차이는 intrinsic montage 결함과 분리한다.
- 새 pass는 실제 새 검토 결과일 때만 인정한다. 미완료·용량 대기·전송 실패·cache skip을 pass로 세지 않는다.
- 허용된 불일치/반복/맥락과 실제 오인 결함을 사례별로 구분한다. 정책 변경 때문에 점수가 올라야 한다는 전제를 넣지 않는다.
- 표본 프레임은 전체 청감·실시간 동작·시청자 반응을 검증하지 않는다. 프레임 사이 동작을 추정하거나 음성을 들었다고 쓰지 않는다.

### 새 실제 결과와 독립 재확인 요청

담당자가 `data/editorial-montage-20261018/reference-review/validation-summary.json`과10개 새 원시 평가를 생성했다. 검수자는 동결 instruction `51b4824ae703330f39edcbe4575e80d32784205e34d9092b54df1e10efd7542c`, 새 경로, actual call10개/각1회/동시1개, 새 원시10pass/issues0, 영상·전사·412프레임/39시트 SHA검증 결과를 읽었다. 기존 실패를 수동으로 pass 치환한 작업은 확인되지 않는다. 모든 allowed_mismatches가 비어 있어 특정 문장별 불일치가 실제 발견되어 승인되었다는 근거로 확대하지 않는다.

**다만 공기청정기1건의 구체적 기존 관찰과 새 판정 상충은 아직 해소되지 않았다.** 기존 `DeY776gqIQw/calibrated-review.json`의 불합격은 literal 이야기 불일치가 아니라, “이 공기청정기 앞 서랍을 열면”이라는 ref-3 대사에 사각 HEAPETS 앞문(7.0–8.0초) 뒤 다른 원통형 본체·필터(8.5–10.0초)를 같은 결과로 연결한다는 관찰이었다. 새 원시 pass는 제품 전반의 용도와 털 포집을 설명하지만 이 구조 차이가 왜 허용되는지 다루지 않았다.

검수자는 기존 `data/reference-calibration-20261013-v2-native/DeY776gqIQw/sequence-01.jpg`를 직접 열어 사각 앞문과 원통형 기기/필터가 다른 장면임을 확인했다. 표본 사이 동작이나 정체가 미확인인 부품 관계를 새로 추정하지 않았다. 새 사용자 기준도 다른 제품을 해당 제품의 직접 시연으로 오인시키는 문제는 유지하므로, raw10pass를 곧바로 “검수 상충0”으로 확정하지 않도록 root에 알렸다. 기준은 동결한 채 이 구간과 정확한 대사를 실제 픽셀로 targeted 독립 재확인하고 새 원시 pass/기존 fail을 모두 보존할 것을 권고했다. 검수자가 새 결과를 수동 fail로 바꾸거나 모델을 실행하지 않았다. 원작 평가의 상충과 앞으로 제작할3task의 정상 QA는 구분한다.

후속 담당자의 실제 `DeY776gqIQw/targeted-continuity/review.json`을 직접 읽었다. 동일 instruction SHA 아래 실제 추가 native17프레임을 사용한 독립 재평가는 **passed=false/ref-3 scene_gap1개**였다. 6.766667–8.366667초 사각 전면패널과8.633333–10.233333초 원통 본체/망 필터의 연결이 확인되지 않는데 한 문장의 직접 시연으로 이어 사각 제품에서 필터를 꺼낸 듯 오인시킨다는 구체 관찰이다. 원시 첫10pass를 보존하고 최종 기준 검증은 **9pass+실제 결함1개**로 정리해야 한다.

같은 후속 응답은 ref-4의 “눈에 보이니 속이 시원하고 소음도 거의 없거든요”에 쉬는 반려동물을 보여주는 컷을 `allowed_mismatches`로 명시적으로 허용했다. 이는 제품 사용 맥락/편안한 일상을 지원하지만 실제 소음 측정 증거라는 뜻은 아니라고 구분했다. 이 실제 반례는 새 기준이 모든 문장에 제품을 요구하지 않으면서 실제 구조 오인은 계속 차단한다는 근거다. 검수자의 지적→새 실제 프레임→동일 기준 독립 재확인 경로였으며, 과거 fail을 모델 없이 강제 복원하거나 새 pass를 수동으로 바꾸지 않았다. 전체 청감·모든 컷 경계 검증은 여전히 별도다.

## 실제3task 검증 대기

12:41:30 KST 읽기 전용 SQLite 관측에서 전역 queued/running0, 아래3task의 state는 앞선 `data/morning-edit-failure-audit-20261018/<task>-snapshot.json`과 모두 같았다. 셋 모두 attention, edit_id=null, script1개/voice1개/edit0개다.

|task|run|소스 수|현재 task raw SHA256|
|---|---|---:|---|
|work-17bb4524ce3a4217|run-d0eb58f9f1404ab0|3|c0e635ca98d91573304ccfa6c3d69b60451b1605233c8cfb61fb49105d3274a5|
|work-06068a52b50e41b2|run-0ac20463d97645a4|3|8b45d48ff3cc77ac8edfca0c4573a72d5e35e105c67d0d2d1a8ce56b0ef9df04|
|work-09928d0b8f864345|run-13e43560d23c48c5|5|6e8c8473779681398b5b4a63ae08240161e97b8306b6433796815edb18cbc206|

새 코드 적용·정상 재평가·편집/QA 진행의 관측 요청 전이다. 현재 문서는 실제3개 완성/통과를 확인하지 않았다. 후속 감시에서는 이전 원본·실패job·script/voice/source/run ID 보존, 정상 속도 원본 길이/가림 범위, 새 semantic 선택 정책, 실제 최종 QA의 policy SHA, 반복 실패 방법 차단과 서비스 대기 구분을 확인한다.


## 13시 실제 더플 QA로 발견한 기준 상충과 감시 판정 정정

`scene_analysis.RANK_INSTRUCTION`의 “A color/model-specific detail needs matching footage only for that detail”은 여전히 색상/모델 detail마다 matching을 요구한다. 10/18 전체 몽타주·리액션 허용 기준에서는 이것도 선호여야 하며 실제 제품 구조 오인과 구별해야 한다. 실제 더플 QA는 “이 주황색에 눈이 가요” 중 navy→orange 연결을 blocking scene_gap으로 보았으나, 전체 영상에 동일 제품 변형과 주황 실물이 반복되고 같은 beat 안에 주황으로 전환되는 상황이다. 감시자가 처음 이를 실제 내용 결함으로 단정한 것은 과도했음을 정정한다. 순간 색상 동시 일치 부재만으로 전체 매력 손상이나 수집 필요를 입증하지 못했다. 원시 QA 실패는 보존하고 기준을 명확히 한 실제 독립 재평가로만 새 판정을 받아야 한다. 레퍼런스 HEAPETS 사각 패널→원통 필터의 실제 다른 구조 연결 결함과 같은 범주로 확대하지 않는다.


### v3 문구 재검토

공유 기준 `product-appeal-first-20261018-v3`와 RANK 선두 색상 문구를 직접 읽었다. 동시 색상/모델 일치는 선호이고 같은 제품 변형 및 같은 대사 안 전환을 허용하며, 독점 규격/판매 사실 허위와 실제 다른 구조를 해당 제품의 직접 시연으로 연결하는 결함은 따로 유지한다. 기존 detail별 mandatory matching 충돌은 해소되었다. 새 3case 단위 검사는 주어진 model response를 대상으로 색상 대안 유지와 실제 identity/feature 제외를 검사하므로 실제 모델이 같은 기준으로 판단한다는 증거로 과장하지 않는다. 그 부분은 새 frozen actual 더플 QA 및 v3 reference 재평가가 담당한다. 이 문구 diff에서 별도의 새 production hard gate는 발견하지 못했다. `daily_quality.py:207` 반복 advisory의 “새 장점·구도·마무리” 문구는 여전히 남아 root에 최종 정리를 권고했다.


## 명시 현재 기준 QA 재평가 API 독립 검수

root가 구현한 `CommandsMixin._command_recheck_quality`와 QA worker를 읽고, 별도 명시 위임받은 `tests/test_quality_policy_recheck_20261018.py`만 추가했다. 임시 Studio store/workers=False로 요청 원자성·이력 보존·중복 차단·실제 fresh 경로 선택을 검사하며 운영 DB·모델·미디어 실행은 하지 않는다.

첫 실행은 18 pass/5 fail로 다음 실제 결속 구멍을 재현했다: 큐 payload에 render/plan SHA 누락, worker가 큐 등록 당시 render/plan/contract와 실제 실행을 비교하지 않음(3반례), explicit 요청이 현재 계약의 이전 false를 cache reuse함. root가 production 코드만 수정했고, 독립 재실행에서 기존 23검사 전부 통과했다. 실행 전 3가지 SHA를 검증하며 explicit에서 이전/group 검수 재사용을 막는다. 같은 job의 이미 완성한 실제 receipt 재시작 재사용과 별개다.

추가로 같은 edit의 fresh explicit 재검토가 동일 false findings를 돌려줄 때 `accept_daily_quality` duplicate 분기가 `reviewed_edit_id`가 같다는 이유로 pending 상태를 정리하지 않고 return하는 문제를 지적했다. root는 duplicate 처리 조건에 explicit 요청을 포함하도록 최소 수정했다. 새 행동 반례는 정상 command→claim→finish(_accept) 후 needs_attention/scene_wait/stop_method, 새 QA job done, 활성 큐 없음, 이전 false review·feedback·repair_round=0·중지한 수집job 불변을 확인한다.

최종 독립 실행: `.venv/Scripts/python.exe -m pytest tests/test_quality_policy_recheck_20261018.py -q` **24 passed (1.53s)**. reason/edit/actual render/plan/revision guard, disabled quality 계약, queued/running 작업, 사용자 중지 토큰 누락/다른 시각/문자열 토큰 거절, 정확한 토큰에서 신규 QA만 허용, done/failed/paused/superseded/cancelled 중복 이력 재등록 금지, 실제 정책 변경에 새 QA 등록, worker의 render/plan/contract stale 실행 거절, valid old false receipt가 있어도 fresh 실제 decode 경계 선택, duplicate false settle를 포함한다. fresh 경계 검사는 invalid fixture 파일을 성공 decode로 위장하지 않고 첫 FFmpeg 호출에서 명시 sentinel 예외로 멈춘다. acceptance 검사는 controlled 결과를 사용하므로 실제 콘텐츠 통과 증거가 아니다.

수집 repair v4 동작 검사 `test_source_batch_recovery.py:146`도 직접 읽었다. 같은 parent 원본의 새 검토 interval에서 existing_edit 유무×v3/v4의 4가지 반례를 검사한다. `test_source_batch_recovery.py`+`test_visual_media.py` 별도 독립 실행 **15 passed (0.95s)**이며 다른 실행 숫자와 고유 검사 수로 합산하지 않는다.

v3 실제 reference 검증 summary를 직접 읽어 `reference-review-final/validation-summary.json`의 policy v3, frozen instruction `42c78579f070ad3591256663f49c712df82c9d350c17ce6798ab9d4433067bd2`, 10 actual calls/1 parallel/서비스 실패0, 원본 SHA 전부 일치, 9pass+1actualdefect를 확인했다. 공기청정기는 최초 평가부터 native17장을 추가했고 외관 차이 자체가 아니라 실제 사각 서랍과 다른 원통 필터의 관계를 잘못 전달한 direct-demo 문제를 유지한다. 이는 보고서/산출물 읽기이며 본 검수자의 모델 실행은 아니다.


## 최종 문서 대조 추가 확인

총괄6~8절은 실제 전송 재인코딩 바이트467,624/475,488, completion-audit 보존·시간·HTTP14관측, 독립 보존 raw, 공개 스냅샷 완성본3 SHA와 일치했다. root의 `ui-verification.json`은 세 외부 완성본 모두 currentTime=duration/ended=true/error=null, 실제1080×1920 및 원본왼쪽/완성본오른쪽을 기록한다. 총괄의 재생 확인은 이 root 실제 관측에 근거하며 본 독립 검수자의 브라우저 재실행이나 청감 판정은 아니다.

공유 정책 문서는 v3 같은 제품 색상 전환 허용과 직접 시연 구조 오인 구별을 반영했고, 새 평가에는 현재 계약을 사용하되 이미 통과한 다른 완성본을 정책 변경만으로 일괄 재개하지 않는다고 명시했다. 손난로 기존v2통과 보존과 텐트/더플v3새실제검토의 구분에 부합한다. 과거 미해결 기록은 초기 이력으로 유지하고 첫머리의 최종 상태와 혼동하지 않도록 정리했다. 이번 문서 검토로 새 production/test 변경은 하지 않았다. 남은 중대한 문서·runtime 기준 상충을 발견하지 못했다.
