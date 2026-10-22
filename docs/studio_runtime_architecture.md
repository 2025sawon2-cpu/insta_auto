# Studio 런타임 코드 지도

외부 진입점은 계속 `from hotpost.studio import Studio`다. HTTP 경로, DB 상태 형식,
작업 ID, 체크포인트, 기존 영상 경로는 변경하지 않았다. `studio.py`는 작업 디렉터리,
DB, 프로세스 잠금 및 워커 소유권을 초기화하고 아래 책임을 조립한다.

| 변경하려는 동작 | 먼저 읽을 파일 |
| --- | --- |
| 사용자 저장·재시도·재개 명령 | `hotpost/studio_runtime/commands.py` |
| 제작실 JSON·재생 주소·미디어 접근 범위 | `hotpost/studio_runtime/media.py` |
| 작업 실행 루프·결과 저장·구형 자동 제작 | `hotpost/studio_runtime/lifecycle.py` |
| 원본 준비·추가 검색·대본·VoiceBench 음성 실행 | `hotpost/studio_runtime/generation.py` |
| CapCut 별도 프로세스·편집·수정·등록 실행 | `hotpost/studio_runtime/editing.py` |
| 선택 버전 조회·파일 해시 | `hotpost/studio_runtime/common.py` |
| 현재 자동 제작 단계·피드백·완성본 이력 | `hotpost/studio_workflow.py` |
| 최소 소스 수량·병렬 수집·검색 재개 | `hotpost/studio_sources.py` |
| SQLite 트랜잭션·큐·복구 | `hotpost/studio_store.py` |
| 로컬 대본·영상 검토·음성의 GPU 작업 직렬화 | `hotpost/local_compute.py` |
| VoiceBench 시작 소유권·준비 대기 | `hotpost/studio_services.py` |
| 필수 상시 감시·AI 이상 진단·실행 결속 | `hotpost/studio_supervision.py` |
| 실제 산출물/검색/모델/음성 진전·정상 대기 관측 | `hotpost/supervision_evidence.py` |
| 타입·HTTP 응답 기반 재시도 판정 / 동일 입력 재시도 원장 | `hotpost/retry_policy.py`, `hotpost/retry_budget.py` |

## 유지해야 하는 경계

- HTTP는 `Studio.action()` / `Studio.public()` / `Studio.media()`를 사용한다.
- 단계 실행은 `self._<작업종류>()`, 완료는 `self._accept()`로 호출한다. 하위 클래스나
  테스트가 개별 실행 단계를 교체할 수 있으며, 믹스인 구현을 직접 호출하지 않는다.
- 장기 HTTP·렌더링은 상태 변경 트랜잭션 밖에서 실행한다. `check-script`와
  `prepare-caption-preview`는 명령 진입점에서 별도로 처리한다.
- 소스·미디어 제작·Codex 대본 세 워커와 렌더 잠금, 파일 기반 작업 소유권을 보존한다. 모듈 import는
  워커를 시작하거나 운영 DB를 열지 않는다.

`Studio.close()`는 stop 신호 뒤 처리 중인 worker와 watcher를 join한 다음 lease를 해제한다.
일부 thread 시작 실패도 이미 시작한 실행기를 먼저 종료한다. HTTP 서버는 모든 주소를
bind하고 최종 handler를 등록한 뒤 소비자를 시작하며, 초기화 실패와 마지막 서버 종료에서
이미 수용한 HTTP 요청·legacy 큐·Studio 작업을 순서대로 마친다. 새 owner가 이전 실행과
겹치지 않도록 종료 전에 lease를 풀지 않는다.

사진 비활성의 공통 실행 검사는 정상 worker·직접 준비·reserved 복구에서 품질 permit과
외부 호출 전에 적용한다. 모델 준비/용량·기존 음성 요청의 상태/파일 전송 대기는 같은
job/request ID로 이어가며 누적 서비스 실패 횟수를 품질 중단 상한으로 쓰지 않는다.
수동 ProductionManager는 실제 provider Retry-After가 끝나기 전에 다시 호출하지 않는다.

Codex 집필은 `scripts`(rewrite/proposal) 워커, 원본 준비·음성·편집·등록·출력은
`media` 워커가 담당한다. 로컬 미디어/모델 작업과 렌더는 여전히 한 제작 워커에서
실행한다. 긴 음성/렌더링이 다른 게시물의 집필까지 막지 않는다. `claim('production')`은
기존 호출자를 위한 전체 제작 단계 조회를 유지한다. DB 트랜잭션은 같은 게시물의
상태를 바꾸는 제작 작업 하나만 실행하도록 제한하며, 별도 소스 수집과 적용 전
대본 수정안은 병행할 수 있다. 내부 Codex CLI 집필 큐의 단일 OS 워커는 유지한다.
- `digest`, `selected`는 기존 호출자를 위해 `hotpost.studio`에서 재노출한다.
- 구형 자동 제작과 수동 승인 경로는 실제 저장 데이터·호출자·회귀 테스트가 있으므로
  죽은 코드로 간주해 제거하지 않는다. 새 기능은 가능하면 현재 workflow 경로에 추가한다.

## 검증 범위

`tests/test_studio_runtime.py`는 명령 검사 중 워커 진행, UI용 상태의 복사,
재생 주소의 작업 범위, 단계/완료 오버라이드를 확인한다. 기존 `test_studio*`,
`test_parallel_sources.py`, `test_source_expansion.py`는 승인·재개·재시도·복제 음성·
자막·미디어·완성 이력 및 별도 서비스 경계를 함께 검증한다.

리팩토링은 동작 변경과 분리한다. 소스 기준이나 대본 정책을 바꿀 때에는 위 대응
파일과 계약 테스트만 읽으면 되며, 전체 제작 코드를 매번 읽을 필요는 없다.

## 2026-10-19 필수 상시 감시와 재시도

Studio의 OS 실행 소유자가 감시 스레드와 SQLite 상태를 먼저 준비한 뒤 세 제작 워커를 시작한다.
감시에는 종료 시한이 없으며 서버 재시작 때 같은 관측 원장과 진전 상한을 읽는다.
정상 종료는 제작 워커를 먼저 drain하고 마지막에 감시를 종료한다.
`/api/studio-supervision`은 작은 상태 조회이며 전체 제작/프레임 목록을 조회하지 않는다.
목록 projection에도 작업별 감시 상태가 포함된다.

5초 간격으로 작업·claim에 결속된 수신 바이트, 소비한 검색 범위, 완료 결과, 고유 모델 내용,
VoiceBench 완료 구간을 관측한다. 로그·heartbeat·DB revision은 진전이 아니다.
완료 모델 호출 이력을 보존해 짧은 호출이 조회 사이에 끝나도 놓치지 않는다.
모델/음성 큐, 현재 로컬 계산 잠금, 음성 서비스 busy, 실제 pacing/Retry-After는 대기로 분리한다.
유효 진전이 있으면 총 실행 시간이 길어도 계속한다. 관측 부재는 제작 불가능 확정이 아니다.

진전 없는 활성 관측 300초부터 비동기 Codex 진단을 요청한다. 진단 실패 또는 180초 응답 대기 시
실행을 안전 보류하며, 모델의 근거 없는 계속 지시로 시간을 초기화하지 않는다.
감시 건강이 45초 이상 오래되거나 관측 저장에 실패하면 새 claim을 막는다.
진행 작업은 기존 모델/수집/편집 취소 확인 경계에서 정리한다. 동기 외부 요청의 즉시 강제 취소는 보장하지 않는다.
소유권·입력 SHA가 다른 늦은 진단을 적용하지 않고, 새 claim/다른 소비자의 모델 실행은 취소하지 않는다.
외부 VoiceBench 프로세스는 종료하지 않으며 저장 request ID로 재연결한다.

알려진 보류는 재시작으로 해제되지 않는다. 명시 재개는 별도 이력으로 남기고,
그 재개로 허용된 취소 모델 요청만 새 명시 재개 identity로 다시 실행할 수 있다.
검증 실패·불명확한 timeout·무진전·인증 오류를 문자열로 일시 오류에 넣지 않는다.
타입이 확인된 연결/HTTP 일시 오류만 동일 의미 입력·오류당 자동 재시도 최대 2회를 예약하며,
작업 ID·claim·파일명·서버 재시작으로 횟수가 초기화되지 않는다. 서비스 용량 대기는 별도 gate를 유지한다.
배포된 DB는 감시 소유자가 없는 Store의 claim을 거부한다. 독립 reserved recovery 실행기는
상태를 만지기 전에 종료하며 정상 서버의 재개/재시도 API를 사용하도록 안내한다.

이 감시는 자동 코드 수정기나 품질 승인자가 아니다. 이상 원인·필요한 새 근거를 저장하고
동일 작업의 무의미한 계속 실행을 차단한다. 이미 승인된 대본·음성·소스와 과거 실패는 보존한다.

## 로컬 모델 자원 조정

`_rewrite`, `_voice`, `StudioAdapter.editorial`은 재진입 가능한 프로세스 내 잠금을
공유한다. 대본 작업 안에서 editorial을 호출해도 중복 잠금으로 멈추지 않는다.
대본/시각 검토 시작 전과 성공한 음성 저장 직후에는 인증된 VoiceBench HTTP
`POST /v1/resources/release-idle`로 유휴 모델 해제를 요청한다. 음성 작업이 있으면
서버가 해제를 거절하면 대본은 콘텐츠 실패 대신 attempted=False 서비스 대기로 저장된다.
로컬 잠금·서비스 대기는 실제 모델 호출/품질 보완 사용량과 구분한다.
성공한 음성 뒤의 선택적 정리 실패는 저장된 음성을 실패로 바꾸지 않는다.

VoiceBench의 엔진·참조·목소리 선택은 기존 서버 정책을 유지한다. Hotpost는 다른
프로젝트를 import하거나 프로세스를 강제 종료하지 않는다. 구버전 API 404/405/501,
서비스 미연결은 호환성을 위해 건너뛰며 원격 서비스 자원은 조정하지 않는다.
독립된 외부 클라이언트나 다른 Hotpost 프로세스까지 잠그는 분산 GPU 예약은 아니다.


## 2026-10-18 편집·검수 경계

`MediaMixin.brief`는 목록용 projection이며 전체 과거 timeline/검토 프레임을 읽지 않는다. 기존 public 상세와 다운로드 계약은 유지한다. 다운로드는 현재 또는 역사적 edit의 실제 마지막 통과 리뷰와 파일/계획 SHA에 결속한다. 새 QA 진행/실패 중에도 이전 통과본은 유지한다.

수동 표지는 실제 렌더 문서·폰트/배경/PNG·MP4 SHA와 본문 보존 영수증으로 검사한다. 연속 교체는 export_kind 대신 실제 copy 영수증을 따라 CFR 조상을 찾는다. 음성 수정 후 표지는 새 본문 검토 뒤 별도 revision과 정상 QA로 유지한다. 승인 장면 재사용은 원고/구간/소스 맥락 불변 및 새 길이 범위에 한정하며 그 외에는 정상 선택으로 돌아간다.

quality 재시도는 현재 edit/승인 voice를 검사하며 사용자 중지를 해제하지 않는다. refresh 전체는 pause_scope를 사용하고 `_generate`가 다음 실제 모델 호출 직전에 task의 중지를 확인한다. 현재 호출 결과·실패/보류 이력은 보존한다. 표지 전용 prepared_plan은 새로운 본문 보완 계획으로 사용하지 않는다. 구현·실증·미해결 범위는 `STUDIO_EDITING_AUDIT_20261018.md`를 참고한다.


## 2026-10-19 영상 담당 에이전트

예약/수동 생성은 공통 owner 등록을 사용한다. `video_agents.py`는 영속 판단/관찰, `video_agent_context.py`는 입력·증거·완료 확인, `video_agent_actions.py`는 원자 제작 도구, `video_agent_repairs.py`와 `video_agent_runtime.py`는 격리 수정/독립 검토/적용/재시작을 담당한다. 기존 `studio_supervision.py`는 claim 단위 감시를 계속 담당한다. 상세 계약과 확인 범위는 [구현 보고서](VIDEO_AGENT_IMPLEMENTATION_20261019.md)를 따른다.
