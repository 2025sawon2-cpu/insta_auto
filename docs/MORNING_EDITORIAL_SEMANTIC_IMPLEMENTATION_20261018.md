# 2026-10-18 전체 제품 매력 중심 의미 검토 정책 구현

구현 범위: `hotpost/product_appeal_review.py`, `hotpost/scene_analysis.py`, `tests/test_editorial_semantics_20261018.py`. 기존 변경사항을 보존했다. 이 구현 자체는 운영 DB·설정·프로세스를 바꾸거나 수집·모델·음성·렌더를 실행하지 않았다. 실제 레퍼런스의 후속 모델 검증은 별도 기록한다.

공유 정책은 `product-appeal-first-20261018-v2`다. 동일 특장점·효과적인 시연의 반복에 새 정보·새 구도·새 동작을 매번 요구하지 않는다. 일반 혜택을 설명하는 동안 제품이 보이지 않는 실제 관찰된 리액션·맥락 컷도 전체 영상의 흐름에 맞게 사용할 수 있다. 정상 속도에서 원본 구간을 늘릴 수 있으나 추가 원본 프레임·표시·가림 검토는 필요하다. 실제 잘못된 제품·기능·부품을 주제품 시연으로 제시하거나 반대 동작을 해당 동작으로 보여주는 문제는 유지한다.

순위 모델 출력의 `promoted_subject_reference`는 대사가 제품을 가리키는지만 나타낸다. 이를 모든 컷의 제품 노출 강제 조건으로 사용하던 두 군데의 필터를 제거했다. 새 `visual_requirement` 문자열은 `montage_support`가 기본이며, 명시적인 `product` 또는 `direct_action`에만 제품 증거 확인을 적용한다. 리액션에 새 별도 영수증을 요구하지 않고 기존 실제 프레임 관찰과 정상 순위 모델의 context/illustration 선택을 사용한다.

`feature_incompatible_shot_ids`는 해당 beat의 기능·설치·시연과 충돌하는 후보만 제외한다. 예를 들어 차량에 붙이지 않는 텐트는 차량 장착 시연에 사용할 수 없지만, 실제로 검토한 다리형 텐트의 지면 이격 특징을 다른 혜택 beat에서 지원하는 것까지 금지하지 않는다. 기존 `incompatible_subject_shot_ids`는 실제 다른 제품·도포 방식 등의 주제품 정체성 오인을 막는 전역 제외로 유지했다. 기존의 제품 오인·반대 동작 안전 테스트는 수정하지 않았다.

독립 검수의 프롬프트 충돌 지적도 반영했다. 동작명이 대사에 있다는 이유만으로 opposite 판정을 요구하지 않는다. 실제 반대 시연으로 제시해 오인시키는 경우에는 제외를 유지한다. `not_established` 응답의 한국어 이유에 특정 금지 문구가 있다는 이유만으로 새 명시 `montage_support`를 opposite로 승격하지 않는다. 과거 형식과 명시 `direct_action`의 순서 모순 보호는 유지한다.

순위와 최종 QA는 동일한 공유 지침을 포함한다. 최종 QA 앞부분에 남은 과거 반복·얼굴 컷 문구 정리는 root 담당 변경으로 연결했다. root는 편집 plan의 `editorial_policy`와 `visual_requirement`/`feature_incompatible_shot_ids` 복사를 담당한다. renderer는 명시 새 정책에서 원본 시간 재사용을 편집 비용으로 취급하고 일반 montage의 제품 상시 노출 조건을 제거하는 별도 변경을 담당한다. 이 main 변경만으로 renderer까지 적용됐다고 주장하지 않는다.

기존 의미 분석 캐시는 실제 OBSERVE/RANK 문구·분석 함수 코드·프레임 및 소스 SHA를 지문에 포함한다(`studio_runtime/editing.py::_semantic_binding`). 이번 문구/함수 변경은 정상적인 새 의미 검토로 연결되며, 기존 거절을 승인으로 단순 전환하지 않는다. `scene_requirements.py::render_contract_signature`도 해당 계약을 포함한다.

검증: `.venv/Scripts/python.exe -m pytest tests/test_editorial_semantics_20261018.py tests/test_scene_analysis.py tests/test_product_reference_groups.py tests/test_shot_presentation.py tests/test_product_appeal_review.py tests/test_semantic_plan_cache.py tests/test_parent_visual_review_reuse.py -q` → **87 passed** (1.63초). 실제 관찰된 리액션 허용, 명시 제품 증거 필요 구간의 보호, 차량 기능 제외의 혜택/CTA 비전파, 잘못된 제품·명시 opposite의 계속 제외, legacy 금지 판정, 최신 공유 지침의 순위/최종 QA 포함을 확인했다.

인접 구간 연장은 현재 짧은 구간 복구 API에 그대로 넣을 수 없다. 최소 0.6초와 기존 승인 범위 겹침 금지 때문에 0.45초 추가 및 원래 1초 구간과 겹치는 1.45초 제안이 거부된다. root에 동일 SHA의 인접 경계만 대상으로 새 원본 프레임을 추출하고, 승인 A∪추가 B의 실제 합집합을 정상 가림·기능·세로 검토로 확인하는 좁은 확장 경로를 권고했다. 기존 승인 A를 잃거나 새 프레임이 검토되지 않은 경우에는 수용하지 않는다.

## v3: 동일 제품의 색상 변형 몽타주

실제 가방 QA에서 navy→orange 전환의 한순간을 색상 대사와 완벽히 맞추지 않았다는 이유로 장면 부족으로 판단한 결과를 재검토했다. 순위 지침에 남아 있던 색상·모델 상세의 matching 필수 문구를 선호 사항으로 바꿨다. 최종 공유 정책은 `product-appeal-first-20261018-v3`다.

동일 제품의 검토된 여러 색상이 전체 몽타주에 등장하고 대사 beat 중간에 해당 색상으로 넘어갈 수 있다. “이 주황색”이라는 대사와 네이비 이미지의 잠깐 시차 자체는 다른 제품 오인·허위 사실·수집 또는 재편집 사유가 아니다. 명시한 독점 색상·재고·규격이 증거와 실제로 충돌하거나, 다른 구조의 기기·부품을 같은 제품의 직접 시연으로 연결하는 문제는 계속 구별한다. 색상 허용을 핑계로 구조·기능 오인을 지우지 않는다.

관련 3경우(동일 가방의 색상 전환 허용, 다른 구조 직접 시연 제외 유지, 실제로 충돌하는 전용 규격 판정 유지)를 추가했다. 같은 제한 회귀 묶음의 최신 결과는 **90 passed** (2.08초)다. v2 레퍼런스의 원시 평가·상세 반례는 보존하고, v3의 이유 있는 새 기준 검증은 `reference-review-final/`에 별도로 동결·실행한다.
