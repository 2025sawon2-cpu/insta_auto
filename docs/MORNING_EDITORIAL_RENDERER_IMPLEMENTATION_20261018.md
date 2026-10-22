# 오전 작업 재발 방지: 정상 속도 편집 renderer 구현

## 범위와 사용자 기준

사용자가 승인한 기준은 원본의 정상 속도 구간을 더 활용하고, 제품 특장점 반복과 대사에 동시 일치하지 않는 맥락·리액션 컷도 일반 편집으로 허용하는 것이다. 새 정보가 없거나 제품이 모든 컷에 보이지 않는다는 이유만으로 탈락시키지 않는다. 이번 작업은 그 기준의 renderer 경계를 구현했다. main의 prompt/후보/인접 구간 실제 검토 연결은 별도 담당과 같은 계약으로 맞췄다.

운영 DB·프로세스·생산 요청과 승인 자료를 변경하지 않았다. 모델·브라우저·네트워크·TTS·ffmpeg 실제 렌더를 실행하지 않았다. 아래의 실제 세 작업 결과는 순수 선택기 재현이며 완성 영상 검수나 운영 배포 성공을 뜻하지 않는다.

## 명시적 새 정책과 기존 자료 보존

새 제작 계획에만 아래 정책을 넣는다. 이 필드가 없는 기존 `product-story-global-v3` 계획은 기존 동작과 frozen hash 계약을 유지한다.

```json
{
  "editorial_policy": {
    "version": "normal-speed-editorial-v1",
    "allow_source_reuse": true,
    "product_reference_is_not_visual_requirement": true,
    "allow_context_reaction": true
  }
}
```

`visual_requirement`는 beat별 문자열이다. 기본 `montage_support`에는 대사의 제품 언급 여부로 `product_visible`를 강요하지 않는다. 실제 제품 증명이 필요한 `product` 또는 `direct_action`에만 기존 제품 외형 요건을 적용한다. 입력 의미 선택지와 반대 동작 배제, shot의 제외, 실제 필수 프레임은 계속 따른다. renderer가 임의로 새로운 의미 선택지를 만들거나 승인 프레임을 줄이지 않는다.

## 변경 내용

### 승인 원본 시간 재사용을 비용으로 전환

`auto_capcut/core/studio_story_selection.py`는 새 정책에서 승인 shot 안의 미사용 구간과 재사용 구간을 모두 후보로 만든다. 원본 시간 재사용은 초당 0.65의 유한 비용이며 새 정보 보상·선명도·구도 비용과 함께 비교한다. 새 정보가 없는 특장점 반복도 완전한 편집안으로 선택할 수 있다. 이 숫자는 품질 탈락 기준이 아니라 선택 순서에만 영향을 준다.

기존의 원본 시간 예약 기록은 재사용량 측정과 비용 계산에 남긴다. `selection_diagnostics`에 `source_reuse_allowed`, 총 `reused_source_seconds`, beat별 재사용 초를 보존한다. 더는 “앞에서 쓴 원본 시간이므로 뒤에서 사용할 수 없음”을 새 정책의 완료 제약으로 사용하지 않는다.

### 짧은 shot의 실제 연장은 main에 요청

어떤 의미 선택지도 한 beat의 정상 속도 길이를 채우지 못할 때만 `SelectionReviewRequired`를 반환한다. `studio_runner.py`가 다음 구조를 JSON 과정 경계 너머로 전달한다.

```json
{
  "status": "failed",
  "error_code": "reviewed_window_required",
  "diagnostics": {
    "failure_reason": "reviewed_window_required",
    "window_requests": [
      {
        "beat_id": "beat-3",
        "shot_id": "shot-2-1",
        "source_id": "source-a45e616c4a164ab2",
        "required_duration": 1.4333333333333333,
        "nominal_beat_duration": 1.4466666666666668,
        "required_output_frames": 43,
        "reviewed_source_window": [7.8, 8.8],
        "required_extra_seconds": 0.43333333333333246,
        "required_source_frames": [],
        "requires_new_visual_review": true,
        "normal_speed_only": true
      }
    ]
  }
}
```

main이 이 요청으로 실제 인접 프레임·마스크·세로 표시를 검토하고, 일치하는 shot/presentation/source 영수증을 다시 제공해야 한다. renderer는 승인 범위를 자동으로 늘리거나 source_window 숫자를 바꿔 승인을 만들어내지 않는다. 가능한 기존 대안이 하나라도 있으면 그 beat의 확장 검토를 요청하지 않는다.

현재 renderer는 **1 beat → 1 shot → 1 clip** 구조다. 짧은 여러 shot를 한 beat 안에서 이어붙이는 기능은 추가하지 않았다. 이 기능은 마스크와 실제 PTS, native draft 및 선택 결속을 함께 바꿔야 하므로 인접 실제 검토 구간 확장을 먼저 연결하는 최소안을 채택했다.

### 출력 프레임 길이를 사전에 확보하고 clone padding 제거

`studio_editorial_policy.py`는 실제 renderer의 30fps 정수 경계와 마지막 `ceil`을 공유한다. 새 선택기는 명목 beat 초 대신 **실제로 출력할 프레임 수 / 30초**를 승인 구간 안에서 확보한다. 반올림에 따라 명목 대사 구간보다 약간 길거나 짧을 수 있으며, 소스의 재생 속도는 바꾸지 않는다. 특히 마지막 올림으로 1프레임이 더 필요하면 그것도 미리 확장 요청에 포함한다.

`studio_render.py`의 새 정책 본문 경로는 `tpad=stop_mode=clone`과 owned-loop 보충을 사용하지 않는다. 새 캐시 키를 사용해 과거 padding 캐시와 섞이지 않게 한다. 선택 범위가 출력 프레임 길이보다 짧으면 인코딩 전에 막고, 출력 clip의 실제 프레임 수를 ffprobe로 읽어 모자라면 정지 프레임 보충 없이 실패시킨다. 기존 표지 1프레임 삽입 계약은 유지한다.

### 증거와 frozen 선택 결속

기존 실제 프레임 SHA, shot 범위, 필수 증거 프레임, 원본 시간·마스크 범위 검사는 보존했다. 새 정책의 frozen hash에는 `editorial_policy`, 전체 길이·fps 및 `visual_requirement`와 제외 ID 목록도 결속한다. 정책이나 명시 제품 요건을 바꿔 과거 frozen 선택을 자동 승계하지 않는다. 새 정책 freeze는 실제 출력 프레임 길이와 현재 명시 시각 요건도 검증한다.

## 실제 오전 세 입력 재현

원본 `select-shots-request.json` 바이트를 scratch에 보존하고, 같은 입력을 기존 정책과 새 명시 정책으로 비교했다. 실제 source 파일과 증거는 읽기만 했으며 선택된 모든 범위를 기존 `require_reviewed_shot`으로 추가 확인했다.

| 원래 작업 | 기존 정책 | 새 정책 결과 |
|---|---|---|
| 텐트 `work-17bb4524ce3a4217` / `job-b9719e6d67ad402b` | 선택 실패 | 전체 정상 속도 구간 선택·freeze·승인 범위 검사 통과 |
| 더플백 `work-06068a52b50e41b2` / `job-c93716cb9c954c69` | 선택 실패 | 실제로 짧은 beat 3/14만 구조화 추가 검토 요청 |
| 사과 손난로 `work-09928d0b8f864345` / `job-67cfb87c9e5c46a3` | budget 오류 | 특장점 재사용으로 전체 선택·freeze·승인 범위 검사 통과 |

더플백은 동일한 `shot-2-1`의 승인 범위 [7.8, 8.8]에 대해 beat 3이 43프레임(추가 약 0.433333초), beat 14가 38프레임(추가 약 0.266667초)을 요구한다. 이 보고서는 추가 구간을 승인하지 않았다. main의 실제 확장 검토 후 재분석이 필요하다. 명목 1.45초 단일 마지막 beat의 일반 회귀에서는 44프레임이 필요하므로 추가 요청 길이도 0.45초에 고정하지 않고 실제 출력 시계를 따른다.

사과 손난로의 이전 “12초에 12.03687초를 중복 없이 넣을 수 없음” 진단은 그 당시 정책 아래 맞는 원인이다. 새 명시 정책은 원본 반복을 허용하므로 같은 승인 shot로 배정할 수 있다. 과거 실패 기록을 수정하거나 그때 성공했다고 바꾸지 않는다.

## 검증과 파일

renderer 저장소 변경 파일:

- `auto_capcut/core/studio_story_selection.py`
- 신규 `auto_capcut/core/studio_editorial_policy.py`
- `auto_capcut/core/studio_render.py`의 새 정책 한정 분기
- `auto_capcut/studio_runner.py`의 구조화 오류 직렬화
- 신규 `tests/test_editorial_selection.py`, `tests/test_editorial_render.py`, `tests/test_studio_runner_review_error.py`

검증은 새 반복/맥락/짧은 구간/증거·정책 변조 회귀와 기존 selection/diversity/mask/integer clock/timeline 계약을 포함했다. renderer mock 검사는 실제 ffmpeg 실행 없이 생성 명령의 padding 제거, 인코딩 전 짧은 구간 중지, 출력 프레임 부족 시 fallback 없는 실패를 확인한다.

- renderer 관련 70개 검사 통과.
- 실제 세 요청 scratch 회귀 4개 통과.
- 실제 완성 렌더·모델 before/after 품질 검증과 운영 반영은 root 담당의 별도 단계이며 이 문서에서 완료로 주장하지 않는다.

실제 입력과 전후 선택 증거는 `data/morning-edit-failure-audit-20261018/editorial-renderer/`에 있다. `replay_actual_three.py`, 원본 세 JSON, 기존/새 정책별 plan, `actual-three-replay.json`, `test_actual_three.py`를 보존했다. JSON의 `production_request_unchanged`는 세 작업 모두 true다.
