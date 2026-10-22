# 패딩 지정 소스 제외 재제작 독립 검수

상태: **실제 재제작·최종 QA·실파일 독립 감사 통과**. production 코드·DB·프로세스·모델·브라우저를 변경하지 않았다. DB는 `mode=ro`, 미디어는 ffprobe와 null decode로만 검사했다. 공개·GUI 재생·청감은 root 담당이다.

대상 task `work-d82634dd9a064151`, 새 run `run-f29a7280768f44d3`, 새 edit `job-957951e909cc45be`, QA `job-3b56b9228aea4da6`.

사용자가 지정한 첫 등장 소스 `source-365377abf5784c84`(YouTube `RlP056m1ACc`, SHA `f7ef89c5feb7c6b5c26661220ce7c0d693a635a87dd44383049c6cb297b966c7`) 자체와 파생본을 제외했다. 인종·민족 분류는 수행하지 않았다. 정상 make-video API에서 해당 원본을 뺀11개를 선택했다.

## 최종 실파일 결과

- 지정 소스와 동일 SHA/부모 alias: **새 plan 입력·본문 선택·실제 rendered_clips·표지 source·표지 pixel binding 모두0사용**. 실제 전체 영상 overview 표본에서도 지정 소스 대신 다른 장면을 확인했다.
- 본문 실제6원본, 표지 첫1프레임을 제외한494본문프레임. 표지는 허용 source-2155c644604b4df4 / SHA e506d09f… / shot-4-3의8.733334초다.
- MP4:1080×1920·30fps·495프레임·16.5초. 전체 video/audio decode와16개 실제 clip의 정상 원본 span·프레임 수·shot/SHA/window 결속이 통과했다.
- 기존 승인 script-112f53277b5c466e / voice-run-f40858ef18e84c0d와 실제 대본·원본 음성 SHA·처리 음성 원본 결속을 유지했다. 새 TTS0, 새 edit1, QA1이다.
- 최종 QA3groups passed/issues[],48검수 프레임 SHA 정상. QA render/plan SHA가 최종 파일과 일치하며 quality_verified=true, active jobs0이다.
- 기존28파일 실제 SHA와 과거 scripts/voices/edits/runs **전필드 동일**. 이전 완료본과 제외된 원본 파일은 보존됐고 새 완성본에서만 사용을 제외했다.
- 새 run 실제 검색 en5/zh5가 수용됐고, 검토된 기존 재고를 활용해 추가 다운로드·probe0이었다.

독립 출력 감사 **90검사 통과/실패0**. 원시 증거는 `data/padding-source-exclusion-20261018/independent-watch/latest.json`, `job-957951e909cc45be-output-audit.json`이다.

최종 MP4 SHA: `d9b374cd5d0aa4ee7a5dcf1ae5d4f63c7badfba2ed5ed198da8d6a89c33b1b94`\
plan SHA: `67c0b994a5876e024bfbff03a2f35760a678bc3742a4cbc925d26161aad5303b`

## 시간과 관찰 재사용

모든 작업 시간은 created→updated **큐 포함 wall**이다. 수집5분1.850초, 편집5분55.632초, QA46.478초. 요청→QA 완료는11분44.278초, root 별도 파일 검증까지는12분35.854초다. 순수 모델 처리시간으로 표현하지 않는다.

현재29shot의 OBSERVE payload를 순수 오프라인으로 재구성하고 writing DB/실제 모델 영수증을 대조했다. Jobs.create나 모델을 호출하지 않았다.3batch18shot은 이전 completed job 재사용,2batch11shot은 새 관찰이다. 새2호출 영수증 seconds는40.53+37.94=78.47초다. 소스 제외 뒤 번호가 바뀐 후반11개가 같은 실제 근거를 다시 관찰했다.

올바른 현재 context를 적용한 `_parent_observations`는29/29 재사용 가능했다. 현재 `_edit`가 새 run의 state.edit_id=None 때문에 parent run의 이전 semantic plan을 찾지 않는 것이 이 추가 관찰의 원인이다. 진행 중 코드는 수정하지 않았고 후속 최적화 사항으로 남겼다. `independent-watch/observation-reuse.json`에5개job ID·생성시각·shot ID·새 호출 영수증 시간을 보존했다.

QA의 audio_listened=false이므로 해시·파형 일치만으로 청감 검토를 주장하지 않는다. 표본 overview 확인과 전체 브라우저 재생도 구분한다.
