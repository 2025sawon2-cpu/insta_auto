
# 제작실 편집 오류 감시 — 2026-10-18

## 역할과 기준

AGENTS.md/CODE_MAP 및 제작실 화면·정상 API·thumbnail/voice/revision 경계를 읽었다. 이번 증거 루트는 `data/studio-editing-audit-20261018/`이며 기존 후드 완료본 `work-4f3fadbcab0f4df2` / `job-a7fd60b562d7470a`와 dirty changes를 보존한다. 감시자는 이 문서 외 코드/DB/브라우저/세션/서버를 변경하지 않고 모델·렌더를 추가하지 않는다. 아래 코드상 확정 경계와 실제 UI 재현 결과는 구분한다.

## 초기 읽기 검토

1. **편집 수정 취소의 썸네일 필드 누락.** `hotpost/studio_workflow.py`의 discard-edit-feedback(285~290행)은 changes/base_edit_id/caption_only/overlay_document/remotion_only만 제거한다. thumbnail_document/thumbnail_only가 남는다. 썸네일 저장→음성 변경 저장→reproduce의 혼합 수정 Conflict 후 안내대로 구간 수정을 초기화해도 충돌 조건이 계속 남는다. base_edit_id만 없어져 다음 thumbnail reproduce의 필수 기반 edit 조회도 실패할 수 있다. 부모에게 세 썸네일 필드를 같은 편집 변경 집합으로 함께 정리하는 최소 수정을 제안했다. 아직 감시자가 실제 API를 호출한 것은 아니다.

2. **수동 썸네일의 계획 메타데이터 결속 누락.** `hotpost/studio_thumbnail.py::render_thumbnail`은 thumbnail_document/background_path를 추가하지만 기존 cover_spec.lines/source의 과거 이미지 승인·SHA와 mask_application_clock.final_render_sha256를 보존한다. 실제 문구·배경은 바뀌어도 기존 승인 표지를 가리키는 계획이 될 수 있다. 자동 품질 보완용 `cover_frame_copy.render_if_cover_only`는 새 final_render_sha256를 갱신하는 반면 이 경로는 빠져 있다. 정상 최종 QA가 실제 첫 프레임을 검토하므로 승인 우회라고 단정하지 않고, 변경 이미지/문구와 새 결과 계획의 정확한 결속을 실제 시험 대상으로 보고했다.

3. **QA 전 결과의 완성본 노출.** render_thumbnail은 export_verified=True를 반환하며 pipeline.available.export는 export_verified+파일존재만 확인한다. 따라서 품질정책 task에서 새 revision의 정상 QA가 진행 중이거나 거절돼도 pipeline.video_url/다운로드가 완성본으로 먼저 표시될 수 있다. 새 실제 output/plan의 해당 edit별 QA 영수증을 확인하고, 미검토 결과는 preview_url로 구분해야 한다. 현재 task-level QA 상태만 적용하면 과거 승인 완성본이 새 버전 QA 진행 때 사라질 수 있으므로 역사 영수증 검증이 필요하다.

## 정상 경계 확인

- 수동 썸네일 revision도 advance_workflow 첫 단계의 advance_daily_quality를 거친다. thumbnail_only 완료 분기는 그 뒤이므로 이 분기만 보고 정상 QA 우회로 오판하지 않았다.
- 저장 API는 최신 edit_id/feedback_revision/진행 중 생산 job을 검증한다. 혼합 대본·음성·소스/편집 변경은 충돌로 거절하고 기존 결과를 보존한다.
- replace_frame은 반복 썸네일 교체 때 원래 본문을 기준으로 하며 첫 프레임 외 framemd5·복사 오디오·프레임 수를 확인한다. 이 감시에서는 재렌더하지 않았다.
- 개인 목소리/Seed13 계약을 유지하고, 실제 수정 음성은 canonical script·spoken_text·voice_source와 현재 출력 시간축 결속이 필요하다. 설정 동일만으로 청감 톤 동일을 주장하지 않는다.

## 순수 메모리 반례 재현

실제 studio_workflow.py의 285행 discard-edit-feedback 분기 AST를 그대로 추출해 운영/복제 DB 없이 실행했다. 입력 키 thumbnail_document/thumbnail_only/base_edit_id/speed/regenerate_voice 중 base_edit_id만 제거됐고, 남은 네 키에서 실제 reproduce 혼합 수정 조건은 true였다. 따라서 취소 안내를 따른 후에도 같은 충돌이 남는 것을 독립 재현했다. 모델/렌더/외부 요청0회이며 결과는 부모에게 즉시 전달했다.

## r1 수정 읽기 검증과 실제 저장

부모는 main28136/52모듈 SHA 배포와 관련 Python133통과를 보고했다. 목록 API `?view=list`는 brief projection을 이용해 모든 과거 timeline/frames 전체 전송을 피하고, 선택한 task만 상세 조회한다. app/studio 폴링에 in-flight guard가 있다. 초기 세 결함에 해당하는 현재 코드도 확인했다.

- 실제 discard 분기 AST를 다시 실행하니 thumbnail_document/thumbnail_only/base_edit_id가 함께 제거되고 speed/regenerate_voice가 유지됐다.
- verified_quality_export(historical=True)는 해당 edit의 가장 최근 영수증 passed와 현재 render/plan SHA를 확인한다. 실제 a7fd 파일/영수증으로 통과, task-level QA 상태/현재 edit만 메모리에서 바꿔도 과거 완료 유지, 같은 edit의 나중 거절 영수증을 추가하면 거절을 확인했다. 운영 변경 없이 독립 확인했다.
- 수동 thumbnail 계획은 기존 cover_spec을 history로 보존하고 새 실제 배경/문구/렌더 cover SHA·parent_edit_id로 대체하며, mask_application_clock.final_render_sha256도 갱신한다. 정상 actual QA 이전 표지 승인 상태를 자동 승계하지 않는다.
- 현재 운영 rev186, edit a7fd 유지/feedback에 thumbnail_document+base_edit_id+thumbnail_only가 저장되어 있으며 활성 job0이다. 부모는 첫 저장 API가01:47:31 수용됐고 script/voice/edit가 불변이라고 보고했다. 아직 감시 시점 새 렌더0이므로 실제 출력 성공으로 표시하지 않았다.

## 실제 첫 표지 반영 실패: 이전 표지 교체본의 숨김 샘플

- 새 정상 run `run-c6a45e13bbc54c18` / revision `job-a506bc18b9694b37`가 ‘첫 프레임 교체는 일정한 30fps 영상에서 지원합니다.’로 실패했다. 기존 edit a7fd는 유지되고 task는 attention이다. 새 PNG는 생성됐지만 새 완성 MP4는 수용되지 않았다.
- 감시자가 현재 thumbnail_mp4.py의 stdlib MP4 상자 파서를 메모리에서 실행해 실제 파일을 읽었다. c0f4 preview는 timescale15360, 샘플502개 모두 delta512로 통과한다. a7fd preview/body는 샘플503개 중 delta0×1+512×502이고, caption-base는 delta1×1+511×1+512×501이라 video_timing이 거절한다.
- 원인은 기존 정상 cover_frame_copy가 만든 숨김 디코더 preroll 샘플을 수동 썸네일 입력 경로가 처리하지 못하는 통합 누락이다. 최초 경고 때의 일반 PTS 추정 대신 실제 stts 결과로 원인을 정정해 부모에게 보고했다. 표지 자체의 제품/얼굴 실패가 아니다.
- 단순 delta0 허용은 압축 샘플503/실제 표시 프레임502 및 ctts/edit list 정렬을 깨뜨릴 수 있다. 현재 완료본과 원래 압축 본문 anchor의 검증된 부모 연결을 따라가되, 결과의 본문/오디오는 현재 완료본(validation_base)와 비교해야 한다. 원래 anchor SHA/부모계획/본문동일성 근거 없이 과거 영상을 임의로 대체해서는 안 된다. 부모가 수정·정상 재실행을 담당하며 감시자는 모델/렌더/DB를 변경하지 않았다.

## r2  정상 재시도 후 부모 preview 경로 누락

부모는0delta를 임의 허용하지 않고 실제 .cover-copy.json의 출력/부모 SHA·본문/음성 동일성, duration/script/voice 동일성을 검증해 CFR anchor를 찾도록 수정했다. QA가 export_kind를web_render로 바꿔도 영수증 기준으로 탐색하며 현재 승인 a7fd를 validation_base로 유지한다. 관련30Python/13Node 통과(skip0),main41556/52SHA/재시작 중 모든 task 불변을 보고했다.

실제 동일 실패 revision a506의 정상retry는 ‘썸네일 원본 완성본이 준비되지 않았습니다.’로 끝났다(rev192). 읽기 검토에서 c0f4는 당시 표지만 QA 거절되어 export_path 없이 preview_path만 있다는 것을 확인했다. parent_video 검증에는 export_path or preview_path를 쓰지만 다음 anchor_video/최종 source_video에는 export_path만 쓰는 경로 누락이다. 그 실제 영수증에 결속한 preview_path를 anchor 조회 전체에 일관되게 사용하도록 부모에게 즉시 보고했다. 거절 preview를 완성본으로 승격하는 것이 아니라, 현재 승인 base와 완전히 같은 본문/오디오를 만들기 위한 압축 샘플 원본으로만 쓰며 마지막 validation_base 검사는 유지해야 한다.

## r3 첫 표지 출력과 정상 QA 형식 통합 실패

- 부모는 preview-only ancestor 두 경로를 수정하고 실제 구조12회귀 통과/main16464 r3배포 뒤 같은 revision a506을 정상retry했다. 렌더는 done, 새502프레임/16.733333초 thumbnail-final.mp4가 생겼다. copy 영수증은 c0f4 압축 anchor와 현재 a7fd validation_base를 함께 결속하고 body_frames_identical/audio_identical=true다.
- 실제 계획을 독립 읽기 검증했다. 새 문구는 ‘청바지는 그대로 / 재킷이 만든 차이’, 선택 배경240프레임, copy_origin=manual_thumbnail_document다. 배경/렌더PNG SHA와 현재 MP4의 mask_application_clock.final_render_sha256가 모두 맞고 이전 cover_spec history1개가 남는다.
- 후속 정상 QA `job-6084c423ba7c489d`는 ‘도현 두 줄 썸네일 설정이 확인되지 않았습니다.’로 기술 실패했다(rev197). 현재 QA는 자동 표지의 cover_spec.font.font_family와 정확한2줄/CapCut cover-line 트랙2개를 무조건 요구한다. 수동thumbnail 결과는 portable_draft_path도 없으므로 font만 붙이면 다음 단계에서 다시 실패한다. 기존 수동thumbnail_document의1~20요소 계약에 맞는 실제 Remotion 문서/폰트/PNG/MP4 및 본문복사 영수증 검증 분기가 필요하다고 즉시 보고했다. 과거2줄 승인 메타데이터를 새 표지에 복사하는 우회는 권하지 않았다.
- 미승인 표시 경계는 정상이다. 실제 새 a506은 export_verified=true여도 quality_verified가 없어 verified_quality_export(historical=True)=false다. 현재 새 QA 실패 상태에서도 기존 a7fd는 같은 함수로 true다. 미승인 변형을 완성본으로 표시하지 않고 과거 승인본을 유지하는 수정 경계를 실제 상태에서 확인했다.

## r4 표지 실제 QA 통과와 완료 상태 전이 누락

- 부모는 수동 표지 QA helper를 도입했다. 실제 request.document, 묶음 DoHyeon.ttf와 로컬폰트SHA, 새 배경/PNG·MP4 SHA, 승인 부모의 실제 render/plan 영수증, 같은 duration/script/voice, copyreceipt의 부모/표지/결과 및 본문·음성 동일성을 검증한다. 자동 CapCut 형식 검사만 수동 경로에 맞게 대체하고 실제 모델/오디오/디코드 검사는 유지한다. 관련51통과/main8432 r4배포 후 동일 QA6084를 정상retry했다고 보고했다.
- 감시자는 실제 child plan의 BODY_FIELDS18개를 승인 a7fd plan과 직접 비교해 모두 동일함을 확인했다. helper에도 이를 일반 검증으로 추가하면 stale child timeline이 실제 복사 본문과 어긋나는 반례를 막을 수 있다고 제안했으나, 현재 산출물에서 그 불일치가 발생했다는 뜻은 아니다.
- QA6084의 정상 결과는 passed=true/issues0/advisories0/full_decode_passed=true다. 실제 새 MP4 SHA8e911e71040fa93aea51209c95b112b937e812f62e85b8c609a7185b5f4af5b9 / plan913527fe06edba8b0e276c4772fb1e21ab1212b22efbda147c80bff1abfecf6b에 결속된다.
- 그러나 rev199의 task.status=attention, 현재run.status=running, latest_completed_run_id=이전run이다. automation.active=false/paused_by_user=false/stage=quality_review라 QA 수용 후 정상 완료 전이가 멈춘 것을 발견해 즉시 부모에게 보고했다. 이는 새 표지 내용 실패가 아니라 정상retry/완료 상태 전이 오류다. task/run을 직접수정해 완료로 만들지 않고 일반 경로를 고쳐야 한다.

## r5 완료 전이 보정과 속도 수정 신규 제작

- 현재 코드의 정상 quality_review/quality_reedit retry는 protocol2이고 사용자 중지가 아닐 때만 automation.active를 복구하고 해당 생산 상태/quality.pending을 설정한다. 사용자 중지 권한은 유지한다. 실제 썸네일 run-c6a45e13는 completed/latest_completed로 정리됐다.
- 통과 표지 QA의 저장 beat48+경계49=97프레임 SHA 불일치0을 독립 확인했다. 실제오디오6anchor offset0/상관0.99998~0.99999/길이차0이며 원래 a7fd SHA도 불변이다. helper의 본문 계획 동일성 일반 검사도 현재 코드에 추가됐다.
- 부모는 이어 UI에서 속도1.05로 신규 run `run-5335948911624c97`을 시작했다. voice `job-42e11a7130af4cee` 완료, edit `job-8393e3535a0f4a6b` 실행 중인 상태를 읽었다. script ID/SHA60c3ea90…와 본문·댓글은 그대로다.
- 새 voice `voice-run-5335948911624c97`의 실제 approved-listening.wav SHA098590f8…/17.4296초, 개인clone/speed1.05다. original.json과 tts.json은 기존 VoiceBench request247 재사용=true/원음18.285714초/selected Seed13을 기록한다. 기존/신규 original.wav 실제 SHA도 동일했다. 따라서 이 시험은 새 seed 재합성이 아니라 승인 원음을 재사용해 사용자가 바꾼1.05배속을 적용하는 경로다. 현재 새 최종영상/오디오 QA는 아직 완료 전이며 동일 톤 청감 통과로 단정하지 않는다.

## 속도 변경 뒤 실제 표지 리셋·제품 소개 재발 감시

속도1.05 edit8393이 렌더 완료되고 정상 QA `job-8c2f260f5e2b400a`가 진행됐다. 실제 timeline의 표지 문구가 원래 자동 문구 ‘같은 청바지인데 / 재킷에서 갈려요’로 돌아갔다. 직전 수동 변경 ‘청바지는 그대로 / 재킷이 만든 차이’가 속도만 수정한 새 버전에 계승되지 않은 것을 확인했다. activate_reproduction이 이전 thumbnail_document를 제거하고 새 _edit가 원고 후보 문구를 적용하는 경로다. 부모에게 새속도 외 수동표지 유지 기대와 실제 결과 차이를 보고했다.

또한 beat4 ‘이 레더 후드 집업을’은 source796b10.4833335~11.3633335초를 선택했다. 실제 새 QA `beat-4-1.jpg`를 직접 열어 보니 무광 스웨트형 검정 후드를 정면으로 보여준다. 기존에 통과시킨 fe908 광택 외형과 다르며, 최초 교정의 직접 제품유형 소개 오인과 같은 유형의 재발이다. 소재 성분/정확SKU를 새로 추정하는 지적이 아니다. 당시 정상 QA는 아직 진행 중이라 최종 QA 판정과 독립 감시 관찰을 구분해 부모에게 즉시 보고했다.

## 속도 수정 QA 확정과 보유 구간 대안

정상 QA8c2f는 beat4와 beat10 scene_gap을 확정했다. b4는 직접 ‘레더’ 소개에 무광 스웨트형 제품, b10은 ‘밑단이 잡혀 아래로 길게 늘어지지 않는다’는 설명에 엉덩이를 덮는 긴 후드 뒷면을 보여주는 구체적인 반대 실루엣이다. 부모는 진단을 위해 정상 pause-auto로 후속 자동 수집을 보류했다고 보고했다. 이는 사용자의 작업 취소 지시가 아니며 기존 실패/중지 근거와 구분한다.

부모 요청으로 기존7소스의 실제 저장 프레임만 읽어 대안을 제안했다. source-fe908…의10.4~11.74초(새b10의1.28초라면10.4~11.68초)는 현재 승인7.7833335~11.7833335 안이며 이전 fe908 b4/b12 선택시간과 원본 재사용을 피할 수 있다. native10.766667초 프레임63ddb56e… 실제SHA177c1698c08a1c9d742e6c4cadc7f3e99c9ec113ac9b47d9c61344a9a88a8f2e를 확인했다. 실제 원프레임·coverage이미지에서 광택후드/흰삼선/여유소매 및 가림 아래 청바지 윗부분에서 모이는 짧은 밑단이 보인다. 중앙 큰가림은 한계로 남기고 전체핏을 완벽히 입증했다고 주장하지 않는다. 새 정상 장면 assess/필수프레임 결속은 부모가 담당하며 이 독립 관찰 자체가 자동 승인은 아니다. a919는 원래 기능검토부터 길고 덜 모이는 밑단이 명시돼 있어 b10 대안으로 권하지 않았다.

## 로컬 실제 장면 승인과 과거 표지 준비 상태 분리

부모의 정상 local_scene_assessment_only job-b1bf8185e0aa436c가 실제 모델로 fe908를 새 독립 검토했다. alternative-coverage/decision의 ready/current/unused/resume이 true다. b4는7.8~8.8초 product_support/실제7.8초 단일외형프레임, b10은8.8~10.766667초 structural_detail/실제10.766667초 밑단프레임으로 승인됐다. 모델은 동작 전후를 요구하지 않고 해당 외형·구조를 최소 핵심으로 검토했다. source_end가 표본시각인 것은 실제 native frame exposure의 끝10.8초까지만 _match_render_end가 증명된 승인범위 안에서 연장하는 기존 경계로 처리하며 임의 프레임 길이를 더하지 않는다.

r6 quality_reedit90f121은 렌더 시작/출력폴더 없이 과거 cover_repair_evidence의 prepared_plan 입력 불일치 guard에 걸려 done/scene_wait가 됐다. ‘검토된 표지·선택 계획의 파일 또는 입력이 변경됨’이 실제 원인이며 새b4/b10 자료 품질 실패가 아니다. 현재 코드에 feedback가 모두cover일 때만 과거prepared표지를 사용하는 가드가 추가돼 scene_gap 회차에서 이전 준비계획을 이력으로만 보존하는 방향임을 확인했다.

새 approved_voice_scenes 경로도 읽기 검토했다. 부모 통과 실제render/planSHA, 같은 원고·전체 sourceSHA·같은 phrase, 현재 사용 제한·승인interval·mask/세로 맥락을 비교하고 새beat가 옛 usedwindow보다 길면 정상 fresh selection으로 fallback한다. 감시 제안 후 맥락/길이 가드가 추가됐다. 실제 이번1.05의 새beat3는1.0067초로 옛 사용창0.82초보다 길어 재사용 guard를 통과하지 못하므로 이번을 해당 최적화의 성공 실측으로 과장하지 않도록 부모에게 보고했다. 새voice/cueclock을 유지하며 과거 실패/미승인 파일을 자동 승인하지 않는다.

## r7 본문 보완과 표지 보존 경로의 실제 동작

새 실제 window assess1622는 b4 product_support와b10 structural_detail을 새 구간/필수프레임으로 승인했고 unused/resume이 true였다. 정상 quality_reedit `job-c79c597f536f4a35`에서 b4 fe9087.953333~8.833333초(8.8native 노출 유지), b10 fe9089.766667~11.046667초(10.766667native 노출 유지)를 실제 계획·출력 이미지로 확인했다. b4 광택/삼선과 b10의 가림 아래 짧고 모이는 밑단이 보여 이전 두 구체 결함의 보완을 독립 관찰했다. 정상 QA `job-43d83f2e3d19481e`는 통과했다.

이어 보존표지 revision `job-e102dcad99824ea7`가 자동으로 생성됐다. 원래 사용자 수동 표지a506의 문구 ‘청바지는 그대로 / 재킷이 만든 차이’, 배경PNG SHA7f403413…와 렌더PNG SHAea8fbbe9…가 새e102에서도 완전히 동일하다. 새본문은c79와 beats/shots/sources/voice/cues/pause/audio/alignment/rendered_clips가 같고 copyreceipt474프레임/15.8초/body+audio동일이다. 음성 변경 후 사용자 표지를 보존하는 기능은 실제 동작했다.

그러나 후속 정상 QA `job-fda3f3803c7a436b`가 cover와beat5를 거절했다. 첫째는 같은 표지의 긴 등판이 짧은 삼선 레더 착장/청바지 문구를 충분히 지지하지 않는다는 판단, 둘째는 제품 소개 문장에 긴 직선 밑단 아우터 뒷면을 직접 제시한다는 관찰이다. b5 실제중앙/후반 프레임을 독립 열어 긴 등판과 낮은 직선 밑단이 보임을 확인했다.

이것은 복사 기능이 새 픽셀 결함을 만든 회귀가 아니다. cover는 과거승인a506의 동일픽셀·문구에 대한 후속판정 변화이고 b5는 직전통과c79의 변경 없는 본문에서 추가 발견됐다. 동일성·모든 QA이력을 보존하고 실제 구체 결함은 별도로 다뤄야 한다고 보고했다. QA 재현성/불변근거 재사용 경계는 개선항목이지만, 이전판정과 달랐다는 이유만으로 실제 새 관찰을 삭제하거나 우회 통과시키지는 않는다.

## 실제 외부 검색 횟수 정정

후속 refresh126121의 `data/source_jobs/DeiD1rYzW9--1792258206634756400/manifest.json` search_audit와 interrupted-execution-receipt를 읽었다. Yandex 기존페이지에서 서로 다른 이미지SHA e9562f6a…/7620b149…의 검색2건이 실제 실행됐다. page/upload의 고유 요청4개는1792258219.9007/8229.8991/8239.9047/8249.9023에 기록되며, 두 결과는no_results/candidates0·다운로드0이다. receipt의 strategy표시 유무 중복행을 새 요청으로 더 세지 않는다.

따라서 앞선 시점의 ‘외부 수집0 유지’는 이 후속회차 이후에는 다운로드0으로만 맞고 외부검색0은 아니다. 즉시 부모에게 실측 정정을 전달했다. 앞선 두manifest에도 같은 이미지SHA가 검색근거로 존재하지만 실제 search_audit 실행행은 없었으므로 이 두 검색을 과거 실행의 무의미한 재시도로 단정하지 않았다. TikTok 미사용 지원범위 없음/다른플랫폼tab_missing/저장YouTube게이트는 미시도이고 CAPTCHA로 오판한 기록은 없다.

## 최종 감시 상태

`final-audit.json`(02:37:17KST)을 읽고 현재 SQLite rev242/source_wait·활성job0을 별도로 확인했다. 속도1.05 최종시험 e102에는 cover와beat5의 내용 문제가 남아 quality_passed=false다. 미승인 시험버전의 완성 다운로드는404이고 이전 정상 v1/v2/v3 다운로드는200·실제SHA일치다. v3 수동 표지 변경 자체는 정상 QA 통과했지만 후속 속도 시험 전체를 품질 통과로 확대하지 않는다.

부모 전체 감사에는 대상 외54task, 기존MP4 3531개(중간파일 포함),원본/소스611개,설정SHA와 기존script/voice/edit/source레코드가 보존됐다고 기록된다. 이 감시자가 독립 확인한 원래 a7fd 파일SHA도 동일했다. 신규 시험파일/실패/QA이력은 별도 버전으로 남는다. 기본목소리·Seed13·수집Chrome/VoiceBench설정 변경은 없다. 외부 Yandex이미지검색은 고유2건, 다운로드0이며 서비스 대기/미시도/내용 거절/기술 오류를 분리했다.

현재 남은 것은 API/편집 기능 실패가 아닌 후속 시험영상의 구체 내용2건이다. 자동으로 같은 실패방법을 반복하지 않고 보류한 상태다. 청감 자연스러움/전체동작 검토를 수행했다고 주장하지 않으며, 저장 QA의 실제 오디오시간축·파일/계획·프레임 결속 결과만 보고했다.
