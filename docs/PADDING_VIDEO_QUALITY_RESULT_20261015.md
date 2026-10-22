# 몽벨 패딩 영상 품질 개선 결과 — 2026-10-15 KST

기준 문서: `PADDING_VIDEO_QUALITY_REVIEW_20261015.md`의 단계 1~5. 대상은 `work-d82634dd9a064151` / `Dec8wlLhu9N`이다.
원본·기존 완성본·운영 task 상태·승인 대본·개인 음성을 보존하고, 새 파일은 모두 `data/padding-quality-implementation-20261015/`에 만들었다.

## 결과와 확인 범위

- 실제 개선 영상: `verified-export/preview.mp4` — 1080×1920, 30fps, 495프레임, 16.5초.
- 편집 계획: `improved-video/timeline.json`; 내보내기 계획: `verified-export/timeline.json`.
- 재생·다운로드: https://medieval-feed-prefix-toronto.trycloudflare.com (PC와 터널 프로세스 실행 중 유효).
- 새 production 검수는 기존 완성본을 **실패**, 개선본을 **통과**로 판정했다. 운영 DB의 과거 완료/검수 상태를 바꾸지 않았다.
- 관련 회귀 테스트: Hotpost 164개 + AutoCapCut 95개 = **259개 통과**. 번호·고대비 문자를 넣은 합성 픽셀 테스트, 마스크·다양성·타임라인·표지·내보내기·오디오·제품 매력 기준을 포함한다.
- 전체 디코드와 브라우저의 16.5초 전체 재생을 확인했다. 청감상 자연스러움은 실제 청취 완료로 기록하지 않았다(`audio_listened=false`).
- 실제 portable/web 내보내기는 검수본과 전체 495프레임의 decoded hash 및 AAC packet hash가 일치했다. CapCut 앱 UI에서의 native 내보내기는 실행하지 않아 그 경로의 동등성은 미확인이다.

## 단계 1 — 실패 재현, 정수 PTS 수정, 경계 검증

`qa/production-old.json`은 새 경계 표본에서 70번과 388번의 중국어 자막·bilibili 워터마크를 검출했다. 이전 내부 12/50/88% 표본으로 놓쳤던 첫 프레임 결함이 재현됐다.
`mask-only-r2/preview.mp4`는 기존 선택 구간/표지/대본/음성으로 다시 렌더해 두 프레임을 가렸다. 표지 PNG는 기존 승인본과 바이트 단위로 같다.
`boundary-before-after.jpg`는 70/71 및 388/389의 전후 실제 출력이다. 기존 파일을 덮지 않았다.

렌더러는 `best_effort_timestamp` 정수와 stream `time_base`를 보존한다. 승인 범위를 전역 프레임의 `[start,end)`로 확정한 뒤 인접 PTS의 중간값을 enable 경계로 쓴다.
생산 마스크 계약은 `integer-pts-midpoint-v3`로 버전 분리했다. 기존 승인 still 표지의 zero-clock graph는 유지했다.
사각형·강도·적용 프레임·graph SHA·최종 MP4 SHA를 `mask_application_clock`에 기록한다.
`qa/source-output-frame-map.json`은 실제 렌더의 showinfo 전후 checksum과 정수 PTS로 원본 → 선택 FPS ordinal → concat PTS → 최종 ordinal을 연결한다. 동일 픽셀 때문에 native 후보가 여러 개인 경우 후보 목록을 보존하며 임의 시각 하나를 사실로 고르지 않는다.
첫 프레임은 표지 대체임을 별도 표시했다.

`quality_boundaries.py`는 컷뿐 아니라 컷 내부 마스크의 시작/끝마다 k-1/k/k+1을 exact decode index로 추출한다.
기존 영상 49개, 개선본 34개 경계 프레임을 검사했다. 새 계약 없이 저장된 과거 통과 캐시/그룹을 새 검수로 재사용하지 않는다.
선택 구간 내부의 문자 변화는 독립 source overlay 표본과 최종 내부 표본으로 검토했다. 모든 프레임에 대한 연속 OCR 완성을 주장하지 않는다.

## 단계 2 — 실제 구간의 제품 의미와 12개 소스 판단

`source-assessment.json`에 사용 가능 12개 각각의 역할·근거 프레임·선택/탈락 이유를 남겼다. 나머지 3개 부적격 소스도 보존했다.
`42ac`의 0초 준비 구간은 새 선택에 넣지 않았다. 새 착장/퀼팅/앞섶 구간은 기존 승인 범위 밖을 포함하므로 새 근거와 독립 마스크 영수증을 받았다.
니트는 일반 코디 맥락으로, POLO는 짧은 도입 비교로 구분했다. 조끼·셸·다른 브랜드 택·세정제·뉴스를 패딩 디테일 다양성 확보로 세지 않았다.

새 `shot-presentation-v1` 영수증은 source SHA·구간·실제 프레임 SHA·제품 등장·역할·관찰 정보·시각 군집·구도/선명도/제품 면적/가림 추정·불확실성을 전달한다.
새 자동 관찰은 프레임별 제품 등장 boolean도 요구한다. 한 표본이라도 제품이 없는 혼합 준비 구간은 `product_visible=false`가 되어 제품 근거로 승격되지 않는다.
미검토 신규 구간은 자동 제외하며 file `core`로 이를 덮지 않는다. 구도 등의 수치는 모델 추정이며 픽셀 측정 정답으로 취급하지 않는다.

## 단계 3 — 전체 편집 선택과 자막/영상 분리

승인 음성·총시간·자막 cue를 그대로 두고 시각 장면을 16개 cue와 독립적인 9개 구간으로 구성했다.
전역 후보 계획은 `product-story-global-v3`의 bounded beam search로 선택했다. 실제 의미 후보와 필요한 근거를 유지하며 새 관찰 정보, 구도/선명도, 마스크 가림, 같은 시각 군집의 연속 시간을 비교한다.
원본 개수·최대 점유율에 일괄 컷오프를 두지 않는다. 후보별 포기 이유/원 관찰과 새로 얻은 정보는 `selection_diagnostics.decisions`에 남긴다.
후보가 하나뿐인 입력은 `no_selection_freedom`으로 기록한다. 탐색 pruning과 실제 유효 후보 부재를 별도 진단하며 전역 최적해를 증명했다고 주장하지 않는다.
반복 결함의 관련 비트 묶음은 이전 컷 일괄 보존에서 풀어 재선택할 수 있다. 마스크 국소 수정에는 이 범위 확장을 적용하지 않는다.
필수 근거 앵커 검증 후 `freeze-selection`으로 계획을 고정하고 렌더 시 해시 불일치를 거부한다.

기존 3.0~8.867초의 연속 초록 패딩 동작은 착장·정면·앞섶·매장·퀼팅으로 분산됐다.
초록 원본 총 사용은 7.4초(44.8%) → 3.1초(18.8%), 최대 연속 사용은 1.6초다.
새 사용 목록은 `used-intervals.json`에 출력 프레임·원본 시간·SHA·관찰 정보를 함께 기록했다.
사용 parent 원본은 5개 → 4개이고 최대 parent 점유율은 53.7%다. 가장 많이 쓰인 보라색 원본 안에서도 전신·앞섶·퀼팅·코디의 다른 정보를 사용했다.

## 단계 4 — 구도와 블러

초록 영상은 원본 720×960에서 [124,120,472,840]의 검토된 정적 크롭을 별도 lossless H.264 파생 파일로 만들었다.
새 파일 SHA, 부모 SHA, 원본 시간, 크롭 좌표를 보존했고 해당 구간의 overlay와 의미 관찰을 다시 받았다.
천장 비중과 제품 위치를 개선하되 팔의 일부 잘림/동작 흐림은 남는다. 크롭 후 더 확대되므로 원본 디테일 복원으로 설명하지 않는다.
전후 실제 표본은 `composition-before-after.jpg`와 `green-reframed-observations.json`에 있다.

보라색 매장 소스는 46.2~46.45 / 46.45~48.8 / 48.8~50.2초로 나눠 문자 상태를 다시 검수했다.
표지의 실제 마스크 합집합 면적은 196,858 → 114,474 px로 41.8% 감소했다. 이는 canvas 마스크 면적이며 제품 가림 면적의 직접 측정은 아니다.
표지의 새 픽셀은 정상 후보 검토와 단독 독립 검토를 다시 통과했다(`cover-approval/cover-selection.json`).
본문의 필요한 블러는 유지했다. 480×852 보라색 원본의 선명도 한계와 매장 컷의 남은 큰 블러를 보존·기록했다.

## 단계 5 — 최종 검증과 보존

`qa/technical-receipt.json`은 기술/편집 통과를 분리하고 실제 파일 SHA와 연결한다.
음성 6개 시간 앵커의 offset은 0초, 파형 상관은 0.99997 이상이다. 승인 음성 SHA·대본·cue 배열은 기존과 동일하다.
`qa/production-improved.json`은 `passed=true, issues=[]`이며 경계와 내부 실제 출력 표본을 포함한다.
별도 원작 제품 매력 회귀는 저장된 6+4 기준 중 사전 holdout인 자석 도어 스토퍼로 수행하고 결과를 `qa/independent-holdout.json`에 저장했다. 기존 보정 원본 파일은 수정하지 않았다.
공유 페이지에서 실제 전체 재생 완료를 관찰했으며, HTTPS GET byte range 206·1024바이트·다운로드 헤더·실제 파일 prefix 일치를 확인했다(`public-verification.json`).

`qa/preservation.json`은 기존 task 상태와 원본 파일 SHA가 그대로임을 확인한다.
기존 미커밋 변경은 시작 시 `preexisting-changes/`에 별도로 보관했다. 이번에 수정하지 않은 기존 변경 파일은 모두 바이트가 같고, 기존 변경 파일에 더한 수정은 별도 보존본과 비교 가능하다.
운영 작업을 재개하거나 과거 완료본을 재렌더해 교체하지 않았다. native draft registry도 쓰지 않았다.
