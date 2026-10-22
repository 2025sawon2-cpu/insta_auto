# 수납선반 사용자 지정 소스 확인 · 2026-10-22

## 최신 정정: 주요 소스16번 / SnapAny로32번 확보 성공

사용자가 소스7번이 아니라16번이라고 정정했다. 과거7번 지정을 철회 기록하고16번을 사용자 지정 주요 영상으로 task.user_source_designations에 결속했다. 자동검토 원문은 보존했다. 소스16번은 변기 물탱크 위 선반 배치와 욕실용품 수납이 일치한다는 기존 검토를 확인했고, 전체1fps 시트도 재확인했다. 과거 소스7번 불일치 설명은 철회된 번호에 관한 이력이다.

사용자 지정 SnapAny `https://snapany.com/ko/bilibili`의 실제 Chrome UI에 BV19Y4y1e7GD를 입력하고 분석 결과의 동영상 다운로드 링크로 파일을 받았다. 파일은 `data/new-hot-video-20261022/source-followup/snapany-bilibili32/BV19Y4y1e7GD.mp4`,39.171837초/1080×1440/H264+AAC/13,907,337바이트/SHA763b4165e2539da5e7cd6690b1ab37f44ced550f98680bb3a4d774156da6ccca이다. ffmpeg 전체디코드를 통과했다. 기존32번3회 실패는 과거 이력이며 현재는 다운로드 성공이다. 자동제작 재개나 기존 품질승인 변경은 하지 않았다. 일반 자동 실행기의 SnapAny 통합은 이번에 구현하지 않았다.

중간에는 재생 중인 원본 Chrome 페이지의 DASH 자산을 확인했지만 자산 bundle은other형식을 지원하지 않았고, 외부파일요청은403으로 중지했으며 Chrome blob download도미지원이었다. 해당 HTTP 경로에 추가 재시도·우회는 하지 않았다. 이후 사용자가 명시 지정한 SnapAny의 보이는 UI 경로에서 성공했다. 증거는 `{snapany-bilibili32.json,user-source16-correction.json,recovered-bilibili-share.json,bilibili32-full-1fps.jpg,source16-full-1fps.jpg}`에 보존했다.


사용자 요청: 소스7을 주요 소스로 지정하고, 파일 미확보29·32의 실패 원인을 확인해 같은 URL로 각각 최대3회 다운로드한다. 이 두 URL의 수동 재시도만 승인됐으며 제작·다른 수집·자동 복구는 중지 유지다.

- 소스7: `source-bd19959ad9f74141`. 검색어 `免打孔马桶置物架`(무타공 변기 선반)에서 찾았다. 욕실 수납 관련성으로 후보에 들어갔고 기존 시각 검토는 세면대 수전 회피형 얕은 선반이라는 구조/설치 위치 차이로 context_only에 분류했다. 사용자 지정 주요 소스는 task.user_source_designations와 이벤트에 출처·SHA와 함께 보존했다. 기존 자동 검토/품질 영수증은 덮어쓰지 않았다. 이 metadata 추가를 편집 적용/핵심 제품 자동 승인 완료라고 간주하지 않는다.
- 현재 레퍼런스17.8초를2fps로 끝까지 확인했고 변기 물탱크 위 바스켓이 보인다. 소스7 전체1fps에서는 세면대 수전 주변 선반이 보인다. 현재 연결된 파일에서 동일 장면이라는 근거는 찾지 못했다. 사용자 주요 소스 지정과 시각상 동일성 판단은 구분한다. 새 제작 재개 전 이 차이를 현재 대본/사용 장면에 맞게 해소해야 한다.
- 미확보29: Bilibili가 아니라 TikTok. 과거5,250,507바이트 영상 중957,645바이트에서 수신이 멈췄고, tikvideo 대체 페이지도 차단돼 파일 미완료였다. 이번 같은 URL 첫 재시도에서5,250,507바이트/53.96초/480×854 전체를 확보했다. ffmpeg 전체 디코드 통과, SHA581518c0b227ab3a57a9a62ed62c88f34c891dd0b3e7b7740e07d26a50a3c63a. 성공 후 더 시도하지 않았다. 변기 물탱크 위 바스켓 장면으로 기존 레퍼런스의 제품/사용 맥락과 관련됨을 확인했지만 정상 개별 소스 검토/프로덕션 등록은 아직 실행하지 않았다.
- 미확보32: Bilibili BV19Y4y1e7GD. 이번 같은 URL3회(각 명시 실행의 내부 yt-dlp retry0) 모두 `Unable to extract initial state`로 실패. 영상 수신 전 페이지 정보 추출 단계다. Chrome은 게시물 제목/본문 페이지를 열지만 CLI 파서 실패를 그대로 기록한다. 원본 삭제/접근불가 전체로 확대 해석하지 않는다. 추가4회 시도는 하지 않는다.
- 기존 source_finder.download_candidate는 timeout/연결/5xx 전송 오류에만 재시도하고 initial-state/format 추출 오류는 즉시 종료한다. 따라서 과거32번은 그 실행에서 같은 URL을 최대3회 다시 시도하지 않았다. 이번에는 사용자 명시 요청 범위의 별도 운영 절차로3회 확인했다. production code의 일반 재시도 정책은 변경하지 않았다.

Cloudflare 검증 링크: https://deputy-rear-modeling-wilderness.trycloudflare.com

기존 전체 갤러리의 번호를 유지하고29번에 재시도 성공 링크를 추가했다. 전체 파일은33→34개, 미확보 후보47→46개다. 소스7은 사용자 지정 주요 소스/기존 자동 검토 보조를 함께 표시한다. 공유 페이지와 실제 영상3개의 Range206·29번 다운로드 전체 SHA·API404를 확인했다. 임시 서버/터널 실행 의존성은 followup-share.json에 기록했다.

근거: data/new-hot-video-20261022/source-followup/{review-and-retry-audit.json,missing29-retries.json,missing32-retries.json,followup-share.json,reference-full-2fps.jpg,source7-full-1fps.jpg,recovered29-full-1fps.jpg}. retry_selected.py는 이미 두 대상을 실행했으며 count를 초기화해 재실행하지 않는다.
