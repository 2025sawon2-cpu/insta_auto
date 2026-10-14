# 전체 영상 제작 흐름 독립 감사 — 2026-10-14

main이 흐름·책임 경계·공통 계약·변경 검토·통합 검증·운영 반영을 맡고, 두 구현 담당과
구현에 참여하지 않은 독립 검증자 A/B, 읽기 전용 운영 감시자를 단계별로 배치했다.
동시 한도는 main 포함 4였다. 초기 판단을 먼저 기록하고 알려진 여섯 사례를 뒤에 대조했다.
기존 dirty worktree를 이번 변경으로 오인하지 않도록 변경 전 코드/해시/patch를 보존했다.

증거 루트는 `data/workflow-audit-20261014/`다. `initial-analysis.md`, 영역별 initial,
`acquisition-report.md`, `production/report.md`, `verify-a/report.md`, `verify-b/report.md`,
`monitor/`를 함께 읽는다. 운영 데이터와 docs/HANDOFF.md는 로컬 전용으로 커밋하지 않는다.

## 실행 경로와 경계

| 단계 | 실제 호출과 완료 근거 | 독립 점검의 핵심 |
|---|---|---|
| 수집·핫 선정 | cli/collectors → storage/analyze/report → studio_automation 선정 동결 | 24시간/예약/선정 보존, collect.lock, OS 총시간 종료 |
| 원본·전사 | source_finder._download_reference → transcript/별도 speech_worker | SHA별 전체 디코드, 원자 수신, 부분 전사 보존·유효 segment 진전 |
| 대본 3안·선택 | studio_adapter → writing/jobs/pipeline/variants → studio_top_pick | 사실/복사 결함과 단순 지적 수 분리, terminal 상태·CLI 진전·취소 |
| 소스 검색·검토 | collect_sources/refresh_sources → source_finder/discovery/triage → source reviews | 미소비 범위 허용, 검사 URL 이력, 접근 대기·시각 검토 재개 |
| 개인 음성 | generation._voice → VoiceBench HTTP | 전체 1회 제출, request ID 재사용, 승인 설정 보존, 저장 전 소유권 |
| 장면·표지·자막·편집 | editing._process/scene/cover → 별도 auto_capcut.studio_runner | 전체 요청 서명, 실제 산출물, 본문/표지 분리, 실제 자막/노출 |
| 완성본 검수·보완 | daily_quality → quality_progress → workflow/정상 큐 | 실제 결함·관련 새 방법·동등 실패/순환 차단, 검수 파일 결속 |
| 완료·내보내기·전달 | workflow/export → comparison_share/HTTP | 실제 파일/검수 SHA, 공유 스냅샷, 바이트 범위·다운로드 계약 |
| 수동·복구·재시작 | production.py, JobQueue, Commands, recovery tools, Store.recover | 같은 제한/수용 계약, 늦은 결과·중복 완료·사용자 중지 보호 |

## 수정한 문제와 정책 판단

| 발생 조건/원인 | 수정 후 동작과 판단 근거 |
|---|---|
| 살아 있는 legacy 큐를 다른 생성자가 interrupted 처리; queued read/update 분리 | 독점 lease 후 복구, 원자 claim/토큰 수용, producer와 consumer 연결, 마지막 서버 종료 후 drain |
| Store가 done 또는 옛 claim의 완료·실패·중간 저장 수용 | 현재 소유 세대만 수용. SQLite 외 파일/음성/하위 실행까지 검사하며 회계·이벤트 멱등 |
| 새 요청 checkpoint가 옛 runner 응답과 결합 | action·출력 폴더를 포함한 전체 요청 hash와 산출물 hash 확인; 원본 영수증 보존 |
| 제작실 접수를 영상 2편 제작 완료라고 표시 | 접수 완료와 실제 제작 task 연결로 표시; 영상 완료와 구분 |
| 새 검색 범위가 남아도 무성과 3회 중단 | 진단 횟수 보존, 실제 소비 범위·검사 탈락 이력 기반 중단. 새 임의 상한 추가 없음 |
| 메타데이터 탈락 local 후보가 URL 이력에서 빠져 shortlist 독점 | 검사 이력과 네트워크 시도 회계를 분리; 다음에는 실제 미사용 외부 범위 탐색 |
| CAPTCHA/로그인/429/서비스 대기가 실패·영구 scene_wait으로 변환 | 접근 대기/Retry-After/not_before로 보존·재개; 완료한 수신/검토는 재실행하지 않음 |
| 기존 파일·반복 URL/로그를 유효 진전으로 간주 | 실행 전 media baseline, 유한 handoff, 실제 증가 바이트/segment/FFmpeg/runner 결과 감시 |
| 연결 오류가 reference.mp4를 덮거나 probe 가능한 손상 캐시 승계 | 임시 수신·검증 후 원자 저장; SHA별 전체 영상/음성 디코드. 손상/실패 증거·기존 파일 보존 |
| ASR/VoiceBench/FFmpeg/native 내보내기의 총시간 중단 | 정상 대기와 단계 진전을 구분하고 기존 설정을 무진전 감시에 사용; 연결/창 확보 감시는 유지 |
| 4초보다 짧으면 실제 유효 장면도 검토 전에 탈락 | 양수·유한/실제 영상만 기술 gate. 실제 승인 초수/장면으로 준비 판단; 중복 초수 합산 금지 |
| 같은 원본 subframe 이동이 새 실패 방법; 자막 시간축 누락 | 실제 노출 및 자막 입력을 동등성에 포함; 진짜 다른 근거를 허용하고 metadata 이동을 차단 |
| 대본 개선 채택을 지적 개수나 바뀐 인용 문구만으로 결정 | 비교 판단+구체적 중요 결함 의미/사실 회귀 검사. 사소한 의견 개수 증가만으로 개선을 버리지 않음 |
| 수동 cached 완료가 소실 초안·다른 range/style/voice를 재사용 | 실제 draft_content 및 전체 handoff 결속; 불충분 과거 영수증은 보존·보류, 자동 재제작 금지 |
| passed 결과 뒤 파일/계획이 바뀌어도 completed | 검수 시작/끝/수용/최종 완료/공유의 실제 SHA 검사. 현재 코드·task ID만으로 승격 금지 |
| 복구 도구가 정상 permit·과거 중단·사용자 중지를 우회 | 정상 worker와 품질 permit 공유; 새 근거 명시 재개 평가와 stop_history 보존 |
| 완료 뒤 남은 자동 수집 큐 실행 | 기존 queued 자동 수집을 paused 보존; 수동 refresh와 실행 중 결과 보존은 별도 |
| 수MB media payload를 취소/poll마다 다시 역직렬화 | 경량 상태/cancel 조회. 기존 3.06GiB 집필 DB와 이력은 삭제하지 않음 |
| 뒤 포트 bind/큐 활성화/일부 thread 시작 실패가 실행 소유권을 남김 | 모든 socket 선확보, 최종 handler 뒤 소비 시작. 실패와 마지막 서버 종료에서 HTTP·큐·Studio 작업 drain 후 lease 해제 |
| VoiceBench cold start의 중복 launch·60초 준비 미확인 영구 실패 | OS 시작 lease 및 PID/create_time/command/cwd 영수증. 살아 있는 준비 프로세스는 미시도 대기, 확정 시작 종료는 설정 조치 필요로 구분 |
| 과거 service_retries 3회가 현재 미시도 대기까지 failed 처리 | 누적 횟수는 진단으로 보존. 실제 용량 gate·Retry-After·동일 요청 ID를 따르며 서비스 대기 때문에 콘텐츠 중단하지 않음 |
| 사진 비활성 설정을 과거 durable 제작 큐가 우회 | 실제 worker 실행 전에 현재 설정 확인, 사진 준비의 중간 저장도 현재 claim 검사. 기존 사진 자료와 품질 이력 보존 |
| VoiceBench 상태·음성 파일 전송 대기가 즉시 제작 실패; 수동 응답 불명 제출의 키 누락 | 기존 요청 ID로 GET 재개·Retry-After 준수, 수동 작업/대본 결속 generation_key. 인증·설정·확정 합성 실패·손상 WAV는 구분 |

정상 제품 몽타주·이야기 지원 장면과 직접 기능/동작 증거를 구분하는 정책은 유지했다.
문장별 사건·인물·재료 일치를 통과 조건으로 추가하지 않았다. 후보 수·동일 SKU·점수·
지적 개수는 전체 영상의 제품 매력과 자연스러움, 사실/반대 동작/별도 도구 오인을 대신하지 않는다.
핵심 장면·사용 가능 분량은 제작 준비 근거이며 최종 품질 통과를 대신하지 않는다.
짧은 소스 허용은 장면 검수 완화가 아니라 불필요한 사전 탈락 제거다.

## 알려진 사례와 최근 수정 대조

상위 0.17초 전달은 실제 다운로드 호출의 deadline 분리와 진전 반례로 확인했다.
고정 품질 3회는 이력/방법 정책으로 유지하되 별도 수집 3회 중단과 연결 누락도 수정했다.
검색어 변경의 동일 영상 재사용, 무관한 새 파일/코드/task의 가짜 근거, 본문 ready를
표지 ready로 승격, 동일 검수 입력을 통과까지 재질문하는 문제는 기존 독립 반례와 현재
caller를 대조했다. 새로운 subframe·shortlist·복구·늦은 파일 수용 결함도 별도로 찾았다.

## 검증 종류와 운영 보존

모의 외부 결과를 이용한 실제 SQLite·worker·HTTP·파일 계약 반례와 실제 로컬 child/FFmpeg
시험을 구분했다. main은 두 기존 MP4 전체 디코드·실제 PCM 시간축을 검사하고,
승인된 기존 입력을 별도 auto_capcut 프로세스로 격리 렌더했다. 결과는 기존 통과 MP4와
바이트가 동일했다. 기존 실패 초안은 격리된 정상 모델 검수 경로로 확인했으며 별도 도구
후처리의 제품 단독 효과 오인 및 같은 구간 재등장 결함을 유지했다. 새 제작본의 품질
통과나 새로운 외부 소스 확보로 표현하지 않았다.

최종 테스트 명령/결과는 감사 루트의 회귀 로그와 main 결과 기록을 따른다. 독립/구현
테스트 집합이 겹치므로 숫자를 합산하지 않는다. 새 플랫폼 수집·로그인·CAPTCHA 처리,
실제 새 개인 음성 합성/청감, native CapCut UI 조작·새 공개 터널은 실행하지 않았다.

운영 감시는 42 작업, 대본 68·음성 66·편집본 119·소스 436과 전체 큐/회계/실패 이력을
기준으로 삼았다. 기존 완료/초안/과거 중단은 재개하지 않았다. 실제 서비스 반영 증거와
예약 시각·활성·기본 목소리·사진 false·세션 및 자료 보존 비교는 `monitor/`와 최종
운영 영수증을 따른다. 서비스/예약 변경은 main만 수행한다.

## 최종 회귀와 운영 반영 (2026-10-14 02:36 KST)

최종 동결 전체 Python 회귀는 **1,879 passed / 1 skipped**(353.07초), 별도 auto_capcut
전체 회귀는 **215 passed**, JS는 **47 passed / 9 skipped**다. Python의 건너뜀은 기존
visible Chrome 옵트인 fixture이며 실제 새 플랫폼 수집 시험을 통과했다고 세지 않는다.
컴파일·JS 구문·diff 검사는 통과했다. 처음 전체 회귀의 실패와 수정 전 반례 로그도 보존했다.

main이 세 운영 큐의 실행·대기 0을 DB 쓰기 잠금으로 다시 확인하고, 기존 서비스
PID/create_time/command/cwd와 환경을 확인·보존해 해당 Hotpost만 재시작했다.
새 8775 owner는 PID15620(parent28784), HTTP200이다. 기존 통과 작업의 상태·선택 IDs를
실제 HTTP로 확인했고 MP4 Range206의 4,096바이트와 정적 파일이 저장 바이트와 일치했다.
Windows 기존 수집 예약은 총시간 종료 PT2H만 PT0S로 변경했다. XML 의미 비교에서도
이 한 필드만 바뀌었고 07:00·활성·명령·principal은 유지했다.

독립 운영 감시는 42 작업·대본68·음성66·편집119·소스436, 기존 작업/회계/실패/선택,
세션·중지·접근 상태가 동일하고 핵심 파일 SHA 변경·자료 삭제가 없음을 확인했다.
DB의 승인된 변경은 schema_version 테이블 5→6 및 기존 21 jobs에 빈 claim_token 추가다.
PRAGMA user_version은 0을 유지한다. 새 legacy-queue.lock은 소비자 소유권 파일이다.
VoiceBench의 비가동 상태도 유지했으며 기존 중지/실패/완료 작업을 재개하지 않았다.
증거는 감사 루트의 `main-report.md`, `full-regression-deployable.log`, `deployment/`,
`monitor/post-restart/` 및 `monitor/final-monitor-report.md`에 있다.

## 남은 한계

- 임의 자연어의 모든 의미 동등성·모든 영상의 매력을 자동으로 증명하지 않는다.
  고정 근거 계획·실제 파일/장면·독립 검수의 경계를 사용한다.
- ASR 첫 segment 전 큰 모델 초기 로드는 실제 현장에서 검증하지 않았다. 이 구간의
  180초 무응답 감시와 cold start의 구분은 추가 관찰이 필요하다.
- 과거 부모 수용 해시 없는 편집 영수증과 외부 변조된 개별 render-cache clip의 소급
  무결성은 보장하지 않는다. 전체 cache 삭제/일괄 렌더는 하지 않는다.
- 현재 기본 native95의 byte 진전 경계는 수정했지만 다른 버전의 pycapcut fallback UI
  구현과 실제 native 창/진행률은 현장 검증이 필요하다.
- VoiceBench는 baseline에서 8765 비가동이었다. 기존 음성의 영수증/파일 검증을 현재
  서비스 가동이나 실제 새 합성 성공으로 보고하지 않는다.
- 집필 media payload 보관 DB는 약 3.06GiB다. 경량 조회만 개선하고 기존 이력은 보존했다.
