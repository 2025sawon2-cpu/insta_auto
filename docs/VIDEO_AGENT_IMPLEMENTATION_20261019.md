# 영상별 책임 에이전트 — 2026-10-19

사용자 승인: 예약 제작과 직접 실행이 같은 경로를 사용하고 영상 하나당 담당 에이전트 하나가 제작·진단·복구·검수까지 책임진다.

## 실행 구조

- 신규 StudioStore.create 트랜잭션에서 영상별 영속 owner를 등록한다. 예약 enqueue_top, 수동 Studio.create, 직접 촬영 생성이 같은 등록 경로를 사용한다. 수동 초안은 inactive 상태를 유지한다. 기존 작업 조회·중복 생성·서버 재시작은 과거 작업을 자동 등록/재개하지 않는다.
- 신규 Instagram 작업은 예약/수동 여부와 무관하게 설정된 동일 일일 품질 정책을 초기화한다. 과거 run/완성본 정책은 이전하지 않는다.
- Studio의 OS worker lease 소유자만 VideoAgentManager를 실행한다. 정상 제작 단계는 기존 검증된 worker가 진행하고 담당 에이전트는 결과를 관찰한다. idle/실패/기술 보류 때 LLM이 다음 도구를 선택하고 실행 결과가 다음 판단 자료로 저장된다.
- `video_agents`는 task당 owner/epoch/pending decision을, `video_agent_steps`는 실제 도구 관찰을, `video_agent_action_receipts`는 원자 실행 영수증을 저장한다. 프로세스가 바뀌어도 같은 영상의 기억과 책임을 이어받는다.
- 모델은 `video_agent` 작업으로 JSON 도구 호출을 결정한다. shell/web 도구를 연 CLI에 모든 권한을 주는 구조가 아니다. 호스트가 검증한 제작/유지보수 도구가 실제 실행한다. `repair_review`는 별도 독립 검토 호출이다. 기존 대본 작성 역할 프롬프트와 분리하고 action 스키마를 검증한다.

## 실제 실행 도구

- 영상에 연결된 텍스트 증거 읽기와 미디어 SHA 확인, 소스 코드의 제한된 literal 검색/읽기.
- 정상 진행, 소스 확보, 기존 장면 보완, 실제 영상 품질 검토, 유형별 제한 재시도.
- 수정안 격리 복사 → 고정 회귀/신규 테스트 → 독립 코드 검토 → 검토 서명 검증 → 유휴 상태 적용 → 소유 서버 정상 종료/재시작 → 로드 검증 → 원 작업 재개.
- 같은 기술 대기가 반복되면 실행 중뿐 아니라 queued 상태도 관찰한다. claim token/not_before 갱신은 실질 진전으로 세지 않는다. 300초는 기술 조사 시작 기준이며 제작 전체 완료 시한이 아니다. 정상 pacing/서비스 대기는 별도로 보존한다.
- 반복 대기 작업은 테스트와 독립 검토까지 통과한 정확한 수정안에 결속된 경우에만 `park_for_repair`로 보관할 수 있다. running 작업은 이 도구로 중단하지 않는다.

## 권한과 완료 조건

- 사용자 명령 시작 전에 epoch를 바꾸고 명령 처리 중 자동 실행을 차단한다. 사용자 중지/대본 변경 이후의 이전 결정은 실행하지 않는다. 입력 지문과 큐 증거도 재검증한다.
- 같은 입력의 실패 행동, 같은 코드에 영수증 ID만 바꾼 재시도, 파일명만 바꾼 미디어를 새 방법으로 인정하지 않는다. 읽기 도구는 반복 가능하며 모든 과거 관찰을 recall로 조회한다. 형식 오류·조회 실패는 사건으로 기록하고 pending을 해제해 복구 결정을 이어간다. 실패·무진전 상태를 사용자 명령 대기로 고정하지 않는다.
- 무진전 8회에는 복구 역할을 추가하고, 16회에는 복구 가능한 실제 작업과 코드 증거가 있을 때 수정 실행 전용 스키마로 전환한다. 현재 코드·해시를 직접 제공하며 수정 제안→테스트→독립 검토→적용의 결과를 확인한다. 대상 없는 정상 시작, 인증·서비스 대기, 증거가 없는 경우에는 불가능한 수정 도구만 강요하지 않는다. 사용자 명령으로 epoch가 바뀌면 진단 카운터를 초기화하고 과거 사건은 보존한다.
- 구형 준비 경로의 재개는 오류 문자열만으로 허용하지 않는다. 운영 진단으로 발급한 정확한 task/job/실패 시각/원본 SHA와 테스트한 준비 모듈의 실제 로드 SHA를 확인한다. 자료 수신은 미검토 파일을 보존하되 최종 편집 허가와 분리한다.
- 공통 수정은 실제 현재 dirty tree를 복사한다. 원본 SHA/의존 파일/테스트 로그/독립 검토를 결속하고 사용자 수정과 충돌하면 적용하지 않는다. 제어 계층·인증·품질 기준 등 보호 파일은 자동 변경 대상에서 제외한다.
- 격리 테스트의 Python audit guard는 stage 밖 쓰기, 외부 네트워크/프로세스/네이티브 로더를 차단한다. 이는 악성 native 코드를 막는 OS sandbox라고 주장하지 않는다. 실제 렌더러 실행 전체를 이 테스트로 검증했다고 보고하지 않는다.
- 적용 완료 후 marker 기록 사이의 프로세스 중단은 서명된 applied receipt로 복구한다. 이미 적용된 요청은 멱등 처리한다. 코드 SHA와 프로세스 시작 시각을 확인해 이전 모듈 캐시를 로드 완료로 오인하지 않는다.
- 완료는 모델의 선언으로 정하지 않는다. 승인 대본·음성·편집본 연결과 실제 export/plan SHA에 결속된 품질 검수를 확인한다.
- 로그인/CAPTCHA는 사용자 접근 복구 대상으로 구분한다. 서비스 용량·요청 제한은 자동 대기로 유지하며, 내부 실패·자료 부족은 원인과 시도한 방법을 기록하고 복구·다른 근거 탐색을 계속한다. 성공을 선언하려고 보호된 품질 기준이나 실제 결과 검수를 생략하지 않는다. 테스트 통과와 실제 영상 완성을 구분하며 모든 외부 상황의 성공을 보장한다고 주장하지 않는다.

## 확인한 결과

- 관련 회귀 묶음 384개 통과. 이후 literal 코드 검색/런타임 자료 제외 테스트를 포함한 integration 20개 통과. 합계 고유 관련 테스트 386개.
- 실제 저장소 복사본의 격리 테스트: 메인 112개, 렌더러 선택/품질 보호 21개 통과(해당 실행 당시 테스트 구성). 전체 렌더러 import는 native loader 제한으로 별도 검증 대상이다.
- 실제 Codex 호출로 `inspect_artifact → advance`를 선택하고 실제 영속 작업 enqueue 영수증을 생성했다. 이는 격리 도구 연동 시험이며 제작 영상 완료 시험은 아니다.
- 최초 실모델 시험에서 대본 전용 역할 프롬프트/모호한 fixture 지시가 blocked 응답을 낳았다. 에이전트/독립 검토 역할과 action 스키마를 분리하고 fixture 도구 계약을 명확히 한 뒤 실제 시험이 통과했다. 실패 기록도 보존했다.
- 운영 적용은 exact PID/생성시각/명령줄, 큐 유휴 상태를 확인하고 진행했다. 모든 task/job 행은 재시작 전후 동일했다. 브라우저와 VoiceBench는 재시작하지 않았다.
- 원래 상위3만 명시 등록했다. 오리·화구는 새 owner가 실제 완료를 검증했다. 미역국은 기존 소스2개와 대본/승인 음성을 보존한 채 담당 owner로 재개했다. 이 문서 작성 시 미역국 최종 영상 완료는 미검증이다.

운영 API: `GET /api/video-agents`, 작업 상세/목록의 `video_agent`. 담당 에이전트의 상태와 실제 완료 영수증을 노출한다.

증거: `data/top3-recovery-20261019/deployment-agents-3/receipt.json`, `agent-preservation.json`, `agent-handoff.json`, `agent-selfcheck-1792386341/result.json`.

CLI 연결 참고: [공식 비대화형 실행 문서](https://developers.openai.com/codex/noninteractive). 실제 실행 모델은 기존 CLI 기본 선택을 유지한다.

운영 후 확인: 미역국 owner가 같은 queued 증거의 300초 정체를 감지해 실제 LLM 진단을 시작했다. 첫 inspect_code의 잘못된 path 인자를 호스트가 거부한 결과를 다음 판단에 전달했고, owner는 다른 도구인 inspect_artifact로 실제 deferred-source-review.json을 읽어 SHA 영수증을 얻었다. 이후 판단도 자동 시작됐다. 운영 증거는 `data/top3-recovery-20261019/agent-live-verification.json`. 이는 실제 진단·도구 루프 확인이며 미역국 최종 완성/운영 코드 자동 복구 성공을 의미하지 않는다.


## 재개발 검증 중 — 2026-10-19

- 최초 싱크대 실패는 작업 생성과 자동화 전환 사이의 경합으로 준비 worker가 구형 수동 선택 경로를 실행한 사건이다. 원본 영상/전사 SHA, 작업/실패 시각 및 실제 로드한 수정 코드에 결속된 복구 후 준비가 완료됐다. `data/sink-agent-root-cause-20261019/audit.json`, `live-self-recovery.json`에 실제 증거를 보존했다.
- 실제 같은 싱크대 작업에서 대본 3안, 선택 대본, 17.728초 개인 목소리와 소스 수집을 실행했다. 실검색 영어5/중국어5 및 후보15개 기록이 있으나 이후 제품/정책 맥락 전환으로 현재 집계에는 그대로 승계하지 않는다. 현재 최종 영상은 미완성이다.
- 미역국 담당 owner는 제안 캐시와 작업별 SHA 원장 불일치를 진단하고 통합 테스트 및 독립 검토가 있는 수정안을 실제 제출했다. 공통 실행기 변경 때문에 snapshot이 달라진 수정안은 재시험하도록 거부했다. 승인·미디어 품질 검토를 원장과 함께 이전하지 않는다.
- 내부 자료 결속 오류는 외부 접근 대기와 구분해 traceback과 유형을 기록한다. worker cooldown은 보존하면서 책임 에이전트의 수리 대상으로 삼는다. 반복 내부 오류 관찰 유예는30초, 일반 큐의 관찰 유예는300초다. 정상 조회 결과에 누적 실패 대기 시간을 붙이지 않는다.
- 이전 문맥 축약이 마지막 코드 읽기 본문까지5000자로 잘라 next_offset과 실제 전달 범위를 다르게 만든 결함을 수정했다. 다음 판단은 마지막 도구의 전체 본문을 받고, 이전 자료는 영속 recall로 조회한다.
- 테스트/검토 시작과 커밋 시 현재 owner epoch와 사용자 중지를 트랜잭션으로 확인한다. 테스트 로그는 실행별 경로를 사용해 오래된 검토 증거를 덮지 않는다.
- 유휴 공통 적용은 진행 중 작업을 막고 대기 중인 다른 작업을 보존한다. 디스크 maintenance 장벽이 다른 프로세스의 claim까지 막으며 실제 새 코드 로드 전에는 해제하지 않는다.
- Python SourceLoader가 실제 실행한 소스 바이트 SHA를 메모리에 기록한다. 이후 디스크 pyc 유무나 파일 SHA만으로 이전에 로드한 코드를 인증하지 않는다. 파일 교체는 원본을 고유 보존 파일로 넘기고 no-clobber 설치한다. 교체 도중 종료는 영속 handoff journal로 다음 import 전에 누락 원본을 복원한다. 경쟁 저장된 파일은 덮어쓰지 않는다.
- 최신 관련 전체 묶음545개 통과. 최신 전체 수치는 `data/sink-agent-root-cause-20261019/regression.xml`을 기준으로 갱신한다. 이것은 영상 완수 증거가 아니다.
- 운영 rebuild4는 정확한 서버 신원을 확인하고 큐 유휴 상태에서 배포했으며 task/job 행이 일치했다. 기존 브라우저/VoiceBench를 재시작하지 않았다. rebuild3의 행 불일치는 시작 직후 queued worker가 정상 실행하며 갱신한 것으로 별도 `post-start-audit.json`에 기록했다.
- 실제 완수 시험은 동일 싱크대/미역국 작업을 계속 사용하며, `completed_video_ready`와 owner completion 및 실제 출력 SHA에 결속된 QA가 모두 확인되기 전에는 완료로 보고하지 않는다.


## 실제 자동 복구 연쇄 검증

- 미역국 owner가 `repair-683ad6489658402c8ae7499ca2cd2eb3`를 작성·시험·독립 검토·적용했고, 새 프로세스 로드 후 `retry_repaired`로 원래 `job-5a88ad1ba82548ff`를 재개했다. SHA 대기에서 벗어나 실제 새 소스 수신·글자/기능 검토가 진행됐다.
- 싱크대 owner가 내부 대기 분류 수정 `repair-36c37e79025649e49f9fd0277b269204`를 적용했다. 이 수정만으로 원래 결속 오류는 해결되지 않았음을 유지한다. 실제 작업 상태의 읽기 전용 복제 시험에서 이미 소비된 후보만 남은 중단 영수증을 검사하는 순서가 원인임을 확인했고, 운영자 진단으로 명시 기록하여 owner에게 제공했다. 후속 `repair-96be4bd54899453882260e76379e3e0b`는 회귀/독립 검토를 통과하고 유휴 적용 대기 중이다.
- 공통 변경 때문에 과거 수정안의 dependency snapshot이 바뀌면 `propose_patch`의 `prior_repair_id`로 정확한 코드와 통합 테스트를 재사용할 수 있다. 새 snapshot에서 테스트·독립 검토를 다시 받아야 하며, 다른 소유자/입력 또는 바뀐 대상 소스에는 적용하지 않는다.
- 이전 승인 수리로 보관된 작업을 새로운 검증 수리로 재개할 때, 최초 보관의 실제 action receipt와 task/job/input/epoch가 같아야 한다. 새 코드의 검토·실제 로드 검증은 별도로 유지한다. 사용자 중지와 cooldown은 해제하지 않는다.
- `loaded_code_receipts`는 동시에 적용된 서로 다른 영상의 여전히 정확한 파일 SHA를 가진 수리별 로드 영수증을 유지한다. 최신 한 건이 다른 영상의 영수증을 가리지 않는다. owner snapshot의 `loaded_repair`로 실제 로드 증거를 직접 전달한다.
- 확장 전체 회귀605개 통과, 수리별 로드 보존을 포함한 마지막 관련 묶음190개 통과. 세부 실행 XML과 운영자 복제 시험은 `data/sink-agent-root-cause-20261019`에 보존한다. 최종 영상 완료는 계속 별도 검증 대상이다.

## 실제 자료로 발견한 후속 결함과 운영 반영

- 싱크대 후속 수리 `repair-96be4bd54899453882260e76379e3e0b`는 적용·새 코드 로드까지 완료했다. 이미 검증된 수리 뒤 owner가 설명 조회만 반복하던 지연을 제거하기 위해, 새 프로세스가 같은 `retry_repaired` 도구로 원래 보관 작업을 이어간다. task/job/input/epoch, 사용자 중지, cooldown, 서명·실제 코드 SHA 검증을 그대로 거친다. 임의 재시도나 새 제작 작업 생성이 아니다.
- 실제 재개에서 `watermark_masks: null`이 재시도 입력 계산을 실패시키는 결함을 재현했다. null/빈 배열/생략을 같은 의미로 처리하고, 실제 마스크 변경은 계속 별도 입력으로 구별한다. 재개 예외는 해당 owner의 traceback과 복구 상태에 기록하며 다른 영상의 서비스 시작까지 실패시키지 않는다.
- 미역국의 실제 검수는 6개 원본의 `featured_product_identity=true`를 확인했지만, 특정 불림 첨가 단계가 없다는 `same_core_function=false` 때문에 핵심 제품 수가0으로 계산됐다. v6 제품 동일성 집계와 직접 기능 시연 역할을 분리했다. 동일성·실파일 SHA·관련 사용 승인이 있는 원본만 핵심 제품으로 집계하며, 해당 영상의 `source_role=context_only`, 비법 직접 시연 금지 등 원래 검수 제한은 유지한다. 과거 v5 계약은 바꾸지 않는다.
- 읽기 전용 실제 자료 검사에서 미역국은 관련 원본7·핵심 동일성6·사용 가능75.43초·영어/중국어 각5회 실검색으로 수집 준비가 확인됐다. 자료와 검수 원문은 변경하지 않았다. `real-reference-identity-audit.json`에 기록했다.
- 관련 확장 회귀707개 통과(`regression.xml`). 독립 검토17은 위 재개·빈 입력·동일성/시연 분리 변경에 findings 없이 승인했다. 실제 영상 완료를 검토가 보증한 것은 아니다.
- rebuild9 운영 전환에서 task/job 행은 동일했다. 두 작업의 참조 영상, run, 대본, 음성, 원본 목록을 보존하고 즉시 재개했다. 브라우저·VoiceBench는 재시작하지 않았다. `identity-maintenance-resume.json`과 `deployment-agent-rebuild-9/receipt.json`에 증거를 남겼다.
- 운영 반영 직후 미역국이 실제 장면·자막 편집 단계로 진행했다. 싱크대는 현재 맥락의 실검색·추가 수집을 계속한다. 이 시점에는 두 신규 최종 영상의 완료 검증을 아직 하지 않았다.

## 실제 편집 시험에서 드러난 추가 원인

- 미역국 첫 편집 `job-9a4b0e2cf7d94425`는 실제 장면 추출·관찰·순위를 만들었지만 `Core product placement feasibility was not checked`로 실패했다. 파일별 제품 동일성은6개인데 샷 관찰에 중심 대상 정보가 빠져, 실제 미역국이 보이는 모든 샷까지 `general_context`로 분류된 것이 원인이었다.
- `featured_subject`와 검증된 파일별 `product_source_kind`를 샷 관찰에 전달한다. 파일 분류는 해당 샷의 실제 가시성을 대신하지 않으며, 샷마다 전체 표본 확인과 직접 시연 제한을 유지한다. 의미 캐시와 부모 관찰 재사용은 동일한 코드·프롬프트 계약 SHA, 두 정체성 필드, 실제 프레임 SHA를 모두 확인한다. 독립 검토18에서 발견한 부모 캐시 우회는 수정 후 검토19에서 승인됐다.
- 실제 참조/후보 프레임을 다시 시험했다. 달걀만 보이는 준비 샷은 product_visible=false, 미역국이 실제 보이는 두 샷은 promoted_product로 판정됐다. `real-shot-identity-observation.json`에 실제 모델·프레임 근거를 저장했다. 이 세 관찰만 교체한 읽기 전용 선택 재현은 `real-selection-replay.json`에 통과로 기록했으며, 최종 영상이나 전체5개 핵심 사용 검증을 의미하지 않는다.
- 첫 편집 오류 처리의 `fail_daily_quality`가 `automation.active=False`를 써 owner를 dormant로 만든 결함도 확인했다. protocol2 내부 품질 실행 오류와 대본 문맥 보류는 현재 active 권한을 유지한다. 사용자 중지/이미 비활성인 권한을 true로 바꾸지 않는다. 실패 작업과 품질/문맥 보류는 계속 보존하고 증거 있는 복구만 허용한다.
- rebuild10 전환 시 모든 task/job 행이 동일했고 브라우저·VoiceBench를 재시작하지 않았다. 명시 재개된 기존 미역국 run의 두 번째 편집 `job-3b58673f097440e8`가 새 관찰을 실행한다. 실패 편집과 기존 대본·음성·소스는 보존한다.
- 최신 확장 회귀818개 통과. `regression.xml`이 실행 증거다. 이 시점의 최종 영상은 아직 검수 완료 전이다.

## 실제 영상 완수 확인과 중단 검토 재개

- 미역국 `work-bfa7dbe990b747be`의 `job-3b58673f097440e8`는 실제 MP4 출력과 최종 QA를 통과했다. `completed_video_ready=true`, owner의 `completion_verified=true`, 현재 승인 대본/음성 및 실제 출력·계획 SHA의 검수 결속을 별도로 확인했다. 증거는 `soup-verified-completion.json`이다.
- 출력은1080×1920·30fps·14.9초, H.264/AAC48kHz이며 전체 디코드 오류가 없었다. 최종 본문은 서로 다른 원본6개와 핵심 원본5개를 사용하며, 핵심 제품 노출 비중은 약93.5%다. 최종 검수의 결함·권고 목록은 비어 있었다. 출력 SHA256은 `bcbcf33ec762f518c5617b1e25d89eb8433e75f6f8b6f42997354e9925c84efd`다.
- 중단 신호 `StudioPaused`를 영구 검수 실패로 저장해 같은 파일의 재검토를 막던 경우를 분리했다. 신규 중단은 `interrupted/operation_paused`로 기록한다. 과거 기록은 현재 source SHA·stage와 호스트의 정확한 중단 문구가 모두 일치하는 경우만 재검토 대상으로 복구한다. 기존 부적합/응답 형식 오류는 그대로 차단하고 사용자 중지와 미디어 승인을 해제하지 않는다.
- 관련 중단/오버레이/재개 묶음62개가 통과했다. 실제 싱크대 `source-941ca0816a8e4f40`의 읽기 전용 재현은 재검토 필요=true, 편집 승인=false, 원본 기록 변경 없음으로 확인됐다. `actual-interrupted-review-reproduction.json`에 보존했다.
- rebuild11을 유휴 적용하고 싱크대만 재개했다. 완료된 미역국의 상태·QA·출력 바이트가 그대로임을 확인했다. 이 시점 싱크대는 핵심4·관련9개로 검토를 계속하며 아직 최종 완료로 표시하지 않았다.


## 전송 전 중단 검색의 근거 있는 복구

- 싱크대는 핵심5·관련10개를 확보했지만 중국어 실검색이4/5에 머물렀다. 정확한 작업자 종료 영수증의 한 검색이 `started/locate_search_input`이고 실제 전송=false였는데도 미확정 검색 범위로 영구 차단됐다.
- 새 복구는 호스트가 종료 확인 후 수용한 중단 영수증과 원본 manifest·등록된 모든 child의 SHA를 재검증한다. 실제 child row와 일치하고 입력 전이며 requests·입력값·submit intent가 없는 경우만 `confirmed_not_submitted`로 정리한다. native worker는 입력 전에 search_input 요청 표지를 동기 체크포인트로 기록하므로 Enter 후 강제 종료된 경우는 이 복구 대상이 아니다. 제출/입력 의도·화면 판독 실패·이미지·누락·변조 기록은 해제하지 않는다.
- 원본 영수증/worker 파일과 검색 횟수는 보존하고 이전 row와 해제 근거를 별도 기록한다. 실제 작업 복사본에서 미사용 검색1건만 열리며 현재 run의 영어5/중국어4 집계가 그대로임을 검증했다. 실제 결과 수신 전 완료 횟수를 올리지 않는다. 증거: `actual-interrupted-search-reproduction.json`.
- 관련 중단/전송/접근 회귀105개, 검색/수집 다양성 회귀163개 통과. 독립 검토20은 findings=[]로 승인했다. rebuild12 유휴 배포에서 모든 task/job 행 일치를 확인했고 브라우저·VoiceBench를 재시작하지 않았다.


## 재개발 실제 완수 검증 완료

- 싱크대의 남은 중국어 검색은 실제 `results` 영수증을 받아 현재 run 영어5/중국어5를 충족했다. 이어 동일 task/run에서 `job-685afb0c9c454e20` 편집과 `job-2bbf9a3c4e6b43bb` 최종 검수를 자동 실행했다.
- 싱크대 최종 MP4는1080×1920·30fps·14.0667초·H.264/AAC48kHz이며 전체 디코드 오류가 없다. 서로 다른 핵심 원본5개가 본문에 사용됐다. QA passed=true, issues/advisories=[], API completed_video_ready=true, 담당 owner completion_verified=true와 현재 승인 대본·음성·출력 SHA 결속을 모두 별도로 확인했다.
- 출력 SHA256: `892fa831d92583e8301009393655266f45d4600bfff3975a84c5c762b7a3ece9`. 근거: `sink-verified-completion.json`, `sink-render-technical-audit.json`. 표지를 실제로 열어 제품과 한글 문구를 확인했다.
- 미역국·싱크대가 모두 완성됐다. 기존 오리·화구까지4개 작업의 API 완료, owner 검증, 실제 결과 파일 SHA 일치를 재확인했다. `all-reference-completions.json`에 저장했다. 기존 완료본과 자료는 보존했다.
- 이번 검증에서 담당 owner가 코드 수정을 제안·시험·독립 검토·적용하고 원래 작업을 재개한 사례를 확인했다. 공통 실행 계층의 결함은 운영자도 직접 진단·수정했다. 모든 수정이 담당 owner 단독으로 이뤄졌다고 주장하지 않는다. 회귀 시험과 실제 영상 성공은 검증한 사례의 증거이며, 모든 가능한 외부 장애에서 성공한다는 수학적 보장은 아니다.

## 2026-10-20 신규 3개 작업의 무진전·수리 적용 보강 (완수 검증 진행 중)

- 대상은 스파크 `work-ff0ee01205f2467e`, 에어텐트 `work-33fa1ca3d69641b9`, 향수 `work-56d49cbfc5a64c1c`의 기존 run이다. 기존 완료 영상과 구분한다. 01:02 기준 세 작업 모두 소스 단계이며 최종 영상 완수는 아직 검증되지 않았다.
- 작업 ID·회차·시간·큐 갱신만으로 진전으로 세지 않고 같은 실제 입력/방법의 정체를 지속 추적한다. 복구 대상인 정확한 대기 작업만 예약하여 일반 worker와 경쟁하지 않는다. 실제 운영·수리 전제조건 변경은 같은 거절의 무의미한 재시도와 구분한다.
- 수리 검토에는 호스트가 캡처한 현재 task/job/checkpoint와 등록된 원본 증거, 변경되지 않은 관련 검증 코드를 함께 전달한다. 미래 신규 작업의 예방만으로 기존 실패 복구를 승인하지 않는다. 과거 이력의 모델 입력 초과는 원본을 유지하면서 요약·SHA로 투영한다.
- 격리 테스트는 `HOTPOST_REPAIR_INCIDENT` 환경변수의 호스트 생성 JSON에서 전체 `task`, 전체 `job`, 허용된 원문 `artifacts`를 읽는다. 운영 파일 대신 테스트 임시 경로에 복제하여 실제 진입점의 복구를 검증할 수 있다. 증거 파일 쓰기/삭제/이동과 상대 경로 변경은 감사 훅으로 차단하고 테스트 전후·검토·적용에서 SHA를 확인한다. fixture 정보는 서명된 검토 자료에 포함하며 기존 서명된 harness의 바이트는 보존한다.
- 독립 검토에서 fixture job의 `task_id` 누락과 디렉터리 FD 상대 쓰기 허점을 발견해 보완했다. 관련 회귀 240개 통과, Windows symlink 권한에 따른 3개 건너뜀. 검토33 승인, deployment11은 모든 task/job 행을 보존한 유휴 적용이다. 브라우저/VoiceBench를 재시작하지 않았다.
- 실행·검토·배포·관찰 근거는 `data/agent-progress-repair-20261019/`에 보존한다. 운영자가 영상을 대신 제작하거나 검수를 승인한 것은 없으며, 실제 완료는 API·담당 owner·현재 출력/계획/대본/음성 QA의 결속이 모두 확인될 때만 기록한다.
- 실제 fixture 사용 후 Windows 경로 길이로 테스트 준비가 실패한 사례를 확인했다. v2 harness는 임시 경로에 확장 경로를 사용하고 감사 비교는 일반/확장 경로를 같은 기준으로 정규화한다. 원래 stage가 확장 경로인 경우도 fixture 쓰기·삭제·이동을 거절한다. 기존 서명된 v1 harness는 그대로 유지한다. 회귀 242개 통과·3개 건너뜀, 독립 검토35 승인, deployment12 행 보존 적용.
- 이전 읽기 결과가 다음 판단에서 5천 자로 줄어 뒷부분을 재조회하는 현상을 보완했다. `working_evidence`가 최근 완전한 읽기 구간을 최대 144,000자·10개까지 보존하고 최신 관찰 SHA와 다른 구버전은 제외한다. 짧은 재조회가 기존 긴 구간의 뒷부분을 지우지 않으며, 새 버전의 빈 읽기도 구버전 제외에 반영한다. 역사적 자료임을 표시하고 실시간 결속 검증 권한을 부여하지 않는다. 회귀 160개 및 독립 검토38 통과, deployment13 적용.


## 현재 세 영상의 자율 복구 검증 — 2026-10-20 02:15 기준

- 대상은 스파크 `work-ff0ee01205f2467e`, 에어텐트 `work-33fa1ca3d69641b9`, 향수 `work-56d49cbfc5a64c1c`다. 이 셋의 최종 영상은 아직 완성 검증되지 않았다. 앞 절의 미역국/싱크대 완료와 구분한다.
- 스파크 담당 에이전트는 `repair-3362e15584b9490fa85c9dfd42d85929`를 직접 제안·시험·독립 검토·적용하고 기존 `job-d3839e3f0f974c92`를 재개했다. 빈 product descriptor와 영수증 결속 오류는 해결됐지만, 다음 실제 검수에서 `Accepted function frame is outside its bound interval`가 발생했다. 담당 에이전트가 해당 후보의 잘못된 증거를 보존·격리하는 후속 수리를 검증 중이다.
- 격리 재현에 필요한 전체 task/job/checkpoint와 등록된 보정·검수 JSON을 해시 검증된 읽기 전용 fixture로 제공한다. 모델 입력에는 별도 용량 제한 투영을 사용한다. 제안된 새 테스트도 `inspect_repair`로 정확한 staged 파일을 읽을 수 있다. 원래 실패 조건과 관련된 최소 재현은 허용하되 소유권 변경의 정확한 결속·거부 시험, 실제 진입 경로와 저장 동작의 검증은 유지한다.
- 에어텐트의 120초 테스트 시간 초과를 분석하니 상태 복사 한 번이 `builtins.id` 감사 이벤트417,205개를 발생시켰다. v2 테스트 감시기는 각각에 불필요한 경로 확인을 수행했다. v3는 기존 파일·네트워크·프로세스 차단 대상에만 검사하며, 실제 같은 상태 복사는0.141초였다. 과거 서명된 v1/v2 harness는 유지하고 재제안 시 v3를 사용한다. 독립 검토47 승인·관련82개 시험 통과; 운영 반영 결과는 deployment-19/receipt.json에서 별도로 확인한다.
- 공통 에이전트 회귀는 앞선 변경 기준308개 통과·3개 건너뜀, 이후 v3 변경 관련82개 통과다. 중복 실행 수를 합산하지 않는다. 테스트나 코드 적용은 최종 영상 완료 증거가 아니다. 운영자 수동 제작·검수 승인·새 제작 작업 생성은 하지 않았다.

- 기존 수리와 새/보완 테스트를 한 번에 제출하면 거절되던 도구 인터페이스를 수정했다. 같은 task/job/epoch의 원래 staged 파일과 SHA를 검증하고, 명시한 파일만 대체·추가하며 나머지는 보존한다. staged 파일의 exact replacement는 그 초안에 적용하되 실제 live base SHA를 계속 검증한다. 새 수리 ID에는 과거 승인·시험 결과를 승계하지 않는다. 변조·기존 회귀 수정·중복 경로·live source 변경 거부와 실제 재시험을 포함한145개 시험 통과, 독립 검토48 승인. 운영 배포 증거는 deployment-20/receipt.json이다.

- deployment21은 실제 공통 재시도·서명·현재 프로세스 로드 검증 코드와 실행된 고정 테스트 본문을 검토 자료에 결속한다. 개별 오류의 실제 생산 함수 회귀와 공통 재개 계약을 조합해서 평가하되, 보존된 checkpoint/receipt/access 분기에서 해당 함수로 이어지는 관련 연결을 확인한다. failed 작업의 명시 retry_repaired와 parked 작업의 자동 재개를 구분한다. 자료 누락을 명시하며 테스트와 독립 검토·소유권·품질 가드는 유지한다. 독립 진단49 및 보완 검토51, 관련92개 시험과 누락 표기 시험2개가 근거다. 운영 전환에서 task/job 행을 보존했다.
- 02:35 에어텐트 수리 `repair-4a83eb98443a451a98946fcddfeb632c`가116개 시험과 독립 검토를 통과했다. 아직 운영 적용·실제 영상 완성과는 구분한다. 02:34 완료 검증은 세 작업 모두 false였으며 운영자 수동 제작은 하지 않았다.

- 02:51 에어텐트의 원래 수집 작업이 완료됐고, 관련18·핵심7개 및 영어/중국어 각각5회 실제 검색을 충족해 `job-cf67f8d8088f41a1` 편집으로 자동 진행했다. 새 수집 후보를 포함한 저장 sources는23개다. 최종 QA는 아직 미완료다.
- 스파크 담당 에이전트가 `repair-71397025db7443d394898008d704f8ba`를 직접 제안·시험·독립 검토·적용했다. 실제 캐시 복원 테스트에서 발견한 deferred_download_origin 소실까지 고쳤다. 원래 `job-d3839e3f0f974c92`를 재개하여 검수 결과6개를 보존하고 다음 `job-7f13982a4424436c` 추가 검수/수집으로 진행했다. 운영자가 후보를 선택하거나 영상을 대신 제작하지 않았다.
- 향수는 자기 manifest가 SHA로 참조하는 source-preparations 번들을 읽는 도구 권한이 누락됐다. 등록된 자기 manifest와 정확한 shortcode 준비 디렉터리·실제 SHA·4MiB 제한을 모두 확인한 번들만 읽고 fixture에 추가한다. 임의 재귀 링크는 허용하지 않는다. 잘못된 JSON을 건너뛰고 과거 manifest 탐색을64개로 제한하며, 캡처는 권한 검사 후 한 번 읽은 동일 바이트를 재사용한다. 일반 도구24,000자 제한은 유지한다. 실제50,321바이트 향수 번들의 SHA 유지·완전 캡처와111개 통과·3개 건너뜀, 독립 검토53이 근거다. 전체 캡처 예산 초과는 기존처럼 truncated로 표시하며 모든 이력의 완전 수집을 보장하지 않는다. deployment22는 활성 제작을 보존하며 안전한 적용을 기다리는 중이다.

- deployment22가 실제 작업·브라우저·VoiceBench를 보존한 유휴 전환으로 적용됐다. 향수의 원래 준비 번들 접근 제한이 해소됐고, 담당 에이전트의 통합 회귀·독립 검토가 통과했다(`repair-96260eaddfd445e3aaa71b8ade96f855`, 이후 최신 의존성 재검토 `repair-6aba99fb987c43f7bb30611b5a0f6cab`). 아직 실제 재개/완성 확인과 구분한다.
- 스파크 후속 무진전에서 `review_outcome.checked_at`과 동일 `review_error_history.resolved_at` 누적만 달라져 감시300초가 초기화되는 결함을 실제 round9→10 상태 비교로 재현했다. deployment23은 큐 감시 투영에서만 시각·동일 실패 중복을 제외한다. 실제 SHA/범위/판정/새 결함/접근 상태 변화와 정확한 작업·수리 입력 결속은 유지한다. 원문 이력은 변경하지 않는다. 171개 시험 통과·3개 건너뜀, 독립 검토55 승인. 운영 적용 후 반복 회차에도 같은 감시 시작 시각이 유지되는 것을 확인했다.
- 에어텐트는 편집 계획1개를 생성했으나 QA에서 표지의 인물 얼굴 노출이 발견되어 보완 필요 상태다. 담당 에이전트가 스스로 보완 경로를 분석 중이며, 아직 완료로 보고하지 않는다.

## 완료된 검수 작업의 미해결 결과 복구 — 2026-10-20 03:31

- 스파크는 동일 검토 시각 누적에도 감시 시작을 유지했고 실제 반복 작업 `job-ab4c02837a2d4eca`를 복구 대상으로 예약했다. 담당 owner가 `repair-20f0515babbe4162839bd81e76323bd4`를 제출하고 실패한 통합 시험을 보완 중이다. 향수는 `repair-6aba99fb987c43f7bb30611b5a0f6cab` 적용 후 원래 작업을 직접 재개했으며, 후속 검색 계획 문제를 진단 중이다. 아직 최종 영상 완수는 아니다.
- 에어텐트의 `job-94bace5b057040a7`는 실행 상태 done이지만 선택 편집본의 검수가 불합격이고 `scene_wait`다. 공통 수리 계층이 failed/paused/queued만 받아 실제 수정 제안을 거부했다. 새 경로는 현재 선택 대본·음성·편집 및 마지막 불합격 검수/피드백이 일치한 done QA만 수리 문맥으로 인정한다. 과거 작업을 실패로 바꾸지 않는다.
- `continue_repaired`는 해당 task/job/input/owner의 서명된 독립 검토·실제 코드 적용·현재 프로세스 로드를 확인한 뒤 정상 자동 진행 함수를 호출한다. 새 작업이 없거나 기존 job 결과·현재 QA 실패 이력·피드백이 변경되거나 완료/합격으로 바뀌면 트랜잭션을 되돌린다. 사용자 중지·접근·콘텐츠·내레이션·supervision 보류는 유지한다. 완료 QA를 재큐잉하지 않는다.
- 보호된 `daily_quality.py` 안의 예약 함수만 `daily_quality_routing.py`로 동일 AST를 유지해 분리했다. 이를 통해 담당 owner가 예약 순서를 격리 시험·독립 검토·유휴 적용 경로로 수정할 수 있다. 품질 판정/승인 검증기는 보호 모듈에 남는다. 분리 자체는 표지 준비 순서의 결함을 수정하지 않으며 해당 도메인 수리는 담당 owner가 수행한다.
- 확장 시험에서 기존 표지 범위 `scene_gap` 준비 증거를 `_quality_reedit`가 무시하는 불일치가 드러났다. 기존 `is_cover_scene_gap` 판정을 공유하여 준비 계획의 경로·SHA·입력 변경 검증을 유지했다. 명시 cover-only 최적화와 본문/음성 변경 경로는 유지한다. 기존 회귀를 완화하지 않고 품질 관련130개 시험을 통과했다.
- 공통 시험301개 통과, 별도 품질130개 통과(중복 합산하지 않음). 독립 검토56의 QA 이력 보존 지적을 반영하고57에서 승인됐다. `actual-done-quality-context.json`은 실제 에어텐트 문맥 인식의 읽기 전용 증거다. 배포는 `deployment-24/receipt.json` 존재와 로드 SHA로 별도 확인한다. 운영자가 후보 선택·렌더·검수 승인을 실행한 것은 없다.
- deployment24 실제 적용에서 task/job 행을 보존했고 브라우저·VoiceBench를 재시작하지 않았다. 향수도 마지막 수집 회차 done 이후 `strategy_exhausted` 내부 보류 때문에 수리 대상이 없었다. 마지막 보존 회차의 job/run/round/manifest와 현재 manifest가 일치하고 접근·영수증 대기가 없는 경우에만 같은 수리 문맥을 허용했다. `continue_repaired`는 source hold를 그대로 유지한 채 후속 근거 확보 작업을 예약해야 하며 즉시 hold 삭제·변경 시 롤백한다. 실제 worker가 새 계획/검색 근거를 확보하여 기존 검증 경로로 내부 보류를 해결해야 한다. 이 변경만으로 검색·완성 성공을 주장하지 않는다.
- 공통314개 시험 및 source planner 연결1개 시험 통과, 독립 검토58 승인. deployment25에서 행 보존·새 코드 로드를 확인했다. 세 작업 모두 아직 실제 완수 검증 중이다.
- 로컬 수정안 문법/독립 검토 거절도 누적 진단 횟수 때문에300초 제작 재시도 대기로 처리됐다. propose/test/review의 `RepairRejected` 피드백은2초 후 수정 판단을 허용하되, 실패 횟수·조회 예산·동일 제출 거부는 유지한다. 실제 문법 거절 후 같은 초안을 재제출하면 기존 중복 차단과300초 지연이 유지되는 manager 시험을 포함해147개 통과, 독립 검토59 승인. 서비스 대기·실제 생산·접근 제한 타이밍은 바꾸지 않았다. deployment26 행 보존 적용을 확인했다.
- 에어텐트 owner가 과거 SQLite claim 장애 수리 `repair-add1c41f77f44159ba85f483eff6265c`를 현재 표지 수리로 혼동해 검토한 사례를 확인했다. 시험/검토/적용 도구의 사전·사후 권한 검증에 현재 task 의미 입력과 정확한 job 입력을 추가했다. 과거 수리는 읽기 가능하지만 다른 사고의 검토·시험 근거로 소비하지 않는다. 기억 색인에 수리별 action repair_id·당시 job/input·가설·역사적 자료 표시를 보존하여 검토 거절이 다른 수리로 덮이지 않게 했다. 관련275개 및 기억2개 시험 통과·독립 검토60 승인, deployment27 행 보존 적용.
- 현재 에어텐트 표지 수리 `repair-2bf003362a06416ea5d56ad4fcbc70f1`는 격리 시험을 통과했지만 실제 DB에서 기존 큐 키와 충돌하지 않고 후속 작업을 등록하는 회귀가 부족해 독립 검토에서 보완 요청됐다. 향수와 스파크도 현재 보존 사고의 정상 생산 진입점 연결을 보완 중이다. 아직 세 영상 완수 확인은 false다.
- 에어텐트의 보완 수리 `repair-18f04bba8c6d4fbc8f9d2816b3b2d679`가 실제 SQLite와 원래 QA 작업을 보존한 회귀를 추가하여 시험·독립 검토를 통과했다. 적용과 실제 후속 작업은 별도 확인 중이다.
- 과거 적용된 수리를 재검토하면 기존 적용 status가 덮일 수 있었다. 테스트·검토의 시작과 최종 저장 시 applied_at/status를 확인하며, 적용과 최종 저장은 같은 receipt-root 잠금 및 운영 Studio 트랜잭션으로 직렬화한다. 다른 pipeline 인스턴스가 외부 시험/검토 중 적용하는 순서를 재현해 적용 영수증 바이트를 보존했다. 실제 과거 `repair-add1...`는 원래 서명·적용 시각과 후속 거절 기록을 그대로 남겨 두며 임의로 다시 승인하지 않았다. 감사 목록은 applied_at의 역사적 사실과 최신 status를 구분한다.
- 스파크의 실제 인과 필드는 전체 격리 fixture에 있었지만 모델용 투영에 빠져 반복 조회가 발생했다. `inspect_repair(incident_path=[...])`가 자기 작업의 SHA 검증된 불변 fixture에서 JSON 하위 항목을 최대24,000자씩 읽는다. 다른 작업·변조·잘못된 키·음수/불리언 인덱스를 거부하며 파일 쓰기는 없다. 과거 캡처임을 표시하고 현재 실행 권한으로 쓰지 않는다. 실제 실패 소스의 정책·SHA·검토 구간을 읽은 증거는 `actual-incident-navigation.json`이다.
- 최종 관련281개 및 교차 인스턴스 적용 순서2개 시험 통과, 독립 검토62 승인. deployment28 행 보존 적용·새 코드 로드를 확인했다. 운영자 수동 제작은 계속0건이며 세 영상 완수는 아직 검증되지 않았다.


### 2026-10-20 응답 계약 불일치 복구

에어텐트 담당자가 검토·적용된 repair-870ba6b1e3b44fba9034fcda309b8d2a 뒤 정상 continue_repaired를 선택했지만, 일반 writer의 enum에 명령이 빠져 JSON 형식 보정 실패로 반복됐다. 실제 저장 응답은 올바른 JSON이었다. hotpost/writing/jobs.py의 허용 목록에 이미 구현된 명령을 추가했다. 호스트의 서명·현재 로드·소유권·기존 QA/hold 보존 검증은 변경하지 않았다. 실제 Jobs.execute와 decode를 연결한 회귀는 수정 전 해당 경로만 1실패/26통과, 수정 후 관련150테스트 통과. independent-review-63 승인. 이는 실행 연결 수정이며 영상 완료 증거가 아니다.


### 2026-10-20 실패 테스트 진전 오판·복구 작업 메모

향수 담당자의 tests_failed 응답이 단순 실행 성공으로 분류되어 idle_decisions와 증거 조회 예산을 초기화하는 운영 사례를 확인했다. tests_failed를 실패·무진전으로 분류하고 로컬 교정은 2초 뒤 가능하게 하며, 동일 방법 판정에 tests_failed/tests_passed 영수증을 포함해 같은 시험 반복의 진전 초기화를 막았다. test-outcome-progress.xml 139통과와 independent-review-64 승인.

스파크·향수 담당자가 10개 작업 증거 범위 밖의 코드·테스트 계약을 반복 조회하는 것을 확인했다. 별도 top-level working_notes(문자열, 최대12000자)를 owner record에 판단 ID·입력 fingerprint·historical_evidence와 함께 보존해 다음 판단의 자료로 전달한다. 확인한 계약·증거 위치·남은 수정·다음 행동을 기록하며 승인·현재 코드·도구 결과를 대신하지 않는다. 메모는 실행 분기, 소유권, 완료, 무진전 및 동일 방법 키에 사용하지 않는다. 새 사용자 epoch에서 초기화, 잘못된 타입·길이·빈 메모는 기존 내용을 보존한다. 재시작 후 계승 및 메모 변경으로 동일 행동 제한을 우회할 수 없는 회귀를 포함한 관련157테스트 통과, independent-review-65 승인. 배포30은 실행 중인 실제 검토 작업을 종료시키지 않고 유휴 시점을 기다린다. 최종 영상 완료 증거와 구분한다.


### 정확한 3개 중 에어텐트 실제 완료 확인 (2026-10-20 04:28 KST)

work-33fa1ca3d69641b9 / run-94431a419d194f5e 담당자가 repair-870ba6b1e3b44fba9034fcda309b8d2a를 시험·독립 검토·적용 후 스스로 continue_repaired를 실행했다. refresh_sources job-76dbd83516b143cc에서 후보3개를 실제 검토하고 표지 준비를 저장했으며, quality_reedit job-efcdcf2542854bd4를 정상 제작 경로로 수행했다. 최종 편집은 1080x1920 H.264/AAC,15.033333초. API completed_video_ready, owner completion_verified, 새 completion(state)의 선택·검수·영상 SHA 결속이 일치한다. 렌더 SHA 212b053fa5339ac618ee5aac2af2a6a55e8199abc4ba26d1f05d3a9c58bc5547. ffmpeg 전체 비디오·오디오 디코드 종료0 및 검증 전후 동일 SHA. 증거 data/agent-progress-repair-20261019/air-final-media-verification.json. 수동 제작·승인·렌더 실행 없음. 스파크와 향수는 아직 미완료이며 전체3개 성공으로 보고하지 않는다.

배포30은 1792438074.227219 유휴 상태에서 완료됐으며 state_rows_preserved=true, browser_voice_restarted=false. 무진전 테스트 분류 및 owner 작업 메모 보강을 새 프로세스에서 로드했다.


### 복구 기억의 읽은 위치·최신 사용 순서 보존

긴 파일의 최근 line/offset을 기억 목록이 보존하지 않아 repair_packet이 앞48000자만 반복 제공했다. source SHA가 현재와 같을 때만 마지막 읽은 위치를 복원하며, 기존 실패 trace 위치를 우선한다. 관련146통과/기존fixture3skip, independent-review-66 승인, 배포31 완료. 실제 장기 owner 기록 재생에서 추가 원인을 발견했다. unique[key]=item은 딕셔너리의 처음 삽입 위치를 유지하므로 마지막160개 제한에서 방금 다시 읽은 오래된 참조가 사라졌다. key를 pop한 후 저장하여 마지막 사용 순으로 제한하도록 수정했다. 170개 참조 뒤 첫 참조를 재사용하는 영속 회귀 및 관련147통과/기존fixture3skip, independent-review-67 승인. 실제 읽기 전용 재생 actual-memory-recency-replay.json에서 스파크 studio_sources offset39595, 향수 finder51428·studio_sources71620 구간이 다시 제공된다. 앞선 actual-read-location-replay.json에서는 해당 중요 파일이 누락되거나 offset0이었다. 배포32를 유휴 시점에 적용한다. 파일 조회 메모는 승인·미디어 진전 증거가 아니다.

배포32는 1792439167.2980556 완료됐으며 state_rows_preserved=true, browser_voice_restarted=false. 읽은 위치 및 최신 사용 순 기억 복구를 새 프로세스에서 확인했다.


### 스파크 반복 로컬 검토 탈출 (2026-10-20 04:51 KST)

담당자가 repair-764e0d59418343358b461b0b6e1e47ad의 실제 사고 준비 파일 복원·_collect_source_attempt 회귀를 시험·독립 검토 후 적용했다. 정확한 queued job-ab4c02837a2d4eca를 주차하고 fresh load 확인 뒤 retry_repaired로 원래 작업을 재개했다. 기존 overlay 실패·편집 불가 판정은 보존하며 동일 정책/SHA의 확정 실패를 오래된 mask receipt로 해제하지 않는다. 운영상 source_attempts·visual_query_input이 새로 기록되고 실제 제품 구조 검색어 생성/독립 검토 단계에 도달했다. 현재 TikTok/Yandex ready 관측, 예전 YouTube 로그인 기록은 유지. 아직 신규 소스 확보나 최종 영상 완료로 보고하지 않는다.


### 2026-10-20 검색 내부 오류와 해제된 인증 기록 분리

불꽃 owner가 overlay 수정 764e0d를 직접 적용·재시도해 실제 TikTok 영어4/중국어3 검색에 도달했다. 이후 manifest `Deogf81Se6b-1792439485402600600`의 `locate_search_input` 오류는 실제 검색창 부재가 아니라 검색 checkpoint atomic replace의 WinError5였다. readiness는 page_unresolved로 저장됐고 downloader는 `_cooling_down`의 실제 사유 대신 requires_verification=false인 과거 captcha reason을 사용하여 후보를 CAPTCHA 대기로 오분류했다. Yandex 수집 회차만 계속 증가했다.

공통 수정은 실제 cooling 결정의 typed receipt 보존, readiness와 현재 manual gate 분리, 무진전 회차에서 동일 claimed job을 보존한 parser_repair_context 및 owner 진단 예약이다. 타임스탬프만 바뀌는 preflight는 새 진전으로 세지 않는다. 적용/재시도는 기존 정확한 작업·run·owner·서명된 검토·fresh-load 계약을 거치며 플랫폼 readiness와 로그인/CAPTCHA 기록을 수동 변경하지 않는다. 다음 정상 worker preflight가 다시 접근을 판단한다.

격리 로컬 회귀112개 통과(parser-owner-recovery.xml), 독립 검토68 approve. 실제 owner/claim 테스트에서 작업1개 유지, 진단 예약, 중복 claim 차단, 이전 대기 기록 및 미완성 상태 보존을 확인했다. 이 검증은 남은 두 영상의 완성을 뜻하지 않는다. Air tent만 실제 완성 파일·검수·SHA·전체 디코드가 확인됐다.


### 검색 오류의 원인 영수증 우선 전달

실제 Spark source_acquisition JSON이566KB를 넘어 snapshot의 첫16KB 요약 뒤에 PermissionError가 가려졌다. 현재 parser_repair_context의 provider/query/parser revision 및 현재 run에 일치하는 원래 page_unresolved 검색 영수증을 최대8개 별도로 투영한다. 진단 자료만 보강하며 원본 이력·접근/검토 권한은 변경하지 않는다. actual-parser-causal-replay.json에서 정확한 WinError5 원인1개를 확인했다. 관련113개 테스트 통과, 독립 검토69 승인.


### 작업 메모의 줄바꿈 때문에 정상 도구 응답이 버려지는 문제

향수 owner의 codexc957a9b2b5db54575ed08e2ce1105487는 outer JSON은 정상이지만 inner working_notes에 실제 LF가 있어 decode가 실패했다. 1회 형식 보정도 같은 값을 반환했다. structured_json은 이 정확한 JSONDecodeError에 한해 문자열 내부의 원시 LF/CR/TAB을 의미가 같은 escape로 바꾸고 다시 엄격 파싱·기존 schema 검증한다. 모호한 backslash+제어문자, NUL, 기타 문법 오류는 여전히 거부한다. 실제 실패 응답2개 읽기 전용 재해석에서 action/메모 값의 동일성을 확인했으며 과거 응답을 실행하지 않았다. 실제 Jobs.execute 경로와 잘못된 action 거부 등38개 테스트 통과, 독립 검토70 approve.


### 동일 수정본 재제출의 진전 오판 및 초안 기억 누락

향수 repair-63d7c3a84a4c4e94826ffd695f047c91→3ecb80d2f0204e29a9659517f2141b9b는7개 파일 내용 SHA가 모두 동일했다. 기존 성공 propose 판정이 idle·추가 조회 예산을 초기화하여 진단 반복이 이어졌다. 이제 task/job/owner epoch가 같은 과거 성공 제안의 repo/path/content SHA를 호스트가 비교한다. prior_repair_id를 생략한 전체 재제출과 A→B→A도 내용이 같으면 진전으로 세지 않는다. 최신 의존성으로 재스테이징하는 작업 자체는 허용하지만 코드 진전과 구분한다.

강제 복구 자료는 현재 task/job/epoch의 최신 실제 스테이지 소스·테스트를 우선 제공하며, 적용된 코드나 승인으로 표시하지 않는다. 실제 staged integrity 검증을 유지하고 최대8파일·총180K문자 한도에서 각 파일 최대96K를 검증된 두 구간으로 결합한다. 이전 잘못된 읽기 위치 때문에 짧은 파일 앞부분이 사라지지 않는다. 남은 공간에는 최근 실제 읽은 운영 의존성을 제공한다. 실제 재생에서7개 초안 파일 전체+finder를169693문자로 전달했다.

광범위 관련340개 통과, 대형 초안 전달1개 통과. 독립 검토71이 prior 생략 재제출 경로를 지적하여 수정했다. 실제 manager+pipeline의 A,A,B,A 회귀 및 관련103개 통과 후 독립 검토72 approve. tests의 기존 stub3개는 새 읽기 전용 metadata 계약을 제공하도록 갱신했으며 검증 조건을 제거하지 않았다.


### Windows 줄바꿈으로 정확한 수정 제안이 거절되는 결함

불꽃 owner가 제출한 browser_search.py replacement는 검사한 원본 SHA가 현재 파일과 같았지만 LF 문맥은 byte-exact0건, CRLF/LF 동등 문맥은 정확히1건이었다. 원본은880개 CRLF 줄바꿈을 포함했다. _replace_exact_source는 기존 byte-exact 유일 매치를 우선하고0건일 때만 이 줄바꿈 동등성을 허용한다. 다른 공백·들여쓰기·내용은 완전 일치해야 하고 중복 위치는 거부한다. 변경 span 외의 바이트와 파일 줄바꿈은 보존한다. 원본 SHA·AST guard·독립 검토·유휴 적용은 유지한다.

과거 파서 오류로 거절된 같은 제안도 변경된 호스트 검사 계약에서1회 평가되도록 source_replacement_contract를 호스트 실행 전제에 포함한다. 이 값은 모델이 고를 수 없으며 같은 계약에서 동일 행동을 다시 반복하는 것은 계속 차단된다. 실제 pipeline 테스트140개 및 manager 재평가/진전 회귀61개 통과. 실제 거절 제안은 메모리 안에서만 재생해 근거를 저장했으며 대신 적용하지 않았다. 독립 검토73 approve.


### 일반 복구 판단에도 현재 초안 지속 전달

최신 스테이지 소스는 기존16회 무진전 강제 복구에서만 제공되어, 실제 부분 패치 이후에도 같은 worker·finder·preparation 본문을 다시 조회하는 흐름이 이어졌다. 현재 복구 대상에 성공 제안이 있고 외부 미확정 대기가 아닌 경우 일반 계획 단계에도 같은 bounded verified repair_packet을 전달한다. 진단 한도·허용 동작은 바뀌지 않는다. 적용 완료/적용 중인 과거 수정은 초안에서 제외한다.

독립 검토74에서 최신 비대상 완료 job의 초안이 선택될 가능성을 지적해, normal/forced 모두 정확한 repair target ID 집합을 전달하도록 수정했다. material.binding의 실제 job ID와 owner epoch를 검증하고 비대상 trace도 제외한다. 실제 manager+pipeline에서 현재 실패A와 더 최근 완료B 초안을 함께 두고 A만 전달되는지 검증했다. 관련117개 및 applied draft 제외1개 통과. 독립 검토75 approve.


### 추가 운영 관찰: 정책 지역 변수의 적용 전 검사 거절

향수 worker 연결 제안은 새 `policy` 지역 대입이 파일 전체의 보호 AST 비교를 변경해 거절됐다. 기존 검증 함수나 정책값을 실제로 변경한 것은 아니었다. 담당 에이전트가 검사 코드를 읽고 기존 정책을 읽는 지역 변수명을 `acquisition_config`로 수정하여 `repair-c526c8a14e374c2eb4b30b3d1e3fbc89`로 스스로 재등록했다. 호스트는 보호 검사 완화나 도메인 수정안 대리 적용을 하지 않았다. 등록 성공은 완성이나 적용 성공이 아니며 worker 회귀와 독립 검토·실제 제작은 계속 검증 중이다. 근거: `data/agent-progress-repair-20261019/perfume-guard-rejection-diagnosis.json`.


### 추가 보완 39: 큰 수정안의 실제 변경 구간 전달

8개 파일·180,000자 제한을 유지하면서 전체를 담지 못하는 staged 파일은 같은 SHA의 최근 읽기 위치 또는 첫 diff 변경 구간을 중심으로 전달한다. 전체가 들어가는 파일은 그대로 제공한다. 실제 향수 `repair-c526c8a14e374c2eb4b30b3d1e3fbc89`의 `source_finder.py`는 이전 0~31,185자에 수정 함수가 모두 빠졌으나, 읽기 전용 재생에서 47,264부터 같은 길이로 두 복구 함수를 모두 전달했다. 작업·job·epoch·상태 결속과 staged 내용 SHA 검증은 유지한다. 새 회귀는 8개 파일 예산, 최신/오래된 SHA 위치, live 파일 불변을 확인했다. 관련 242개 테스트 통과(`draft-change-window.xml`), 독립 검토76 승인, 유휴 배포39 및 loaded hash 확인 완료. production 상태 행과 Chrome·VoiceBench는 유지됐다. 이 보완 자체는 영상 완성 증거가 아니다.


### 추가 보완 40: 부분 수정·테스트 순환과 복구 단계 진전 구분

실제 이력의 기존 idle 카운터는 불꽃8·향수9였으나 같은 job/input/epoch에서 tests_passed 이후 상위 복구 단계로 못 넘어간 결정은42·179회였다. 부분 제안과 통과한 테스트가 매번 기존 카운터를 초기화하는 허점이었다. durable 이력에서 제안→테스트 통과→독립 승인→적용/로드→정상 재개 단계를 복원하고, 새 repair ID나 추가 테스트만으로 단계 정체가 초기화되지 않도록 했다. 현재 대상/input/epoch만 사용하며16회 이상이면 기존6개 누락 근거 조회 한도의 수정 실행 모드가 유지된다. 여러 대상 중 실제 실행한 대상의 단계로 예산 갱신을 판단한다. 호스트가 확인한 의존성 대기는 누적하지 않고, 잘못된 저장 repair ID는 조회와 재시작을 막지 못한다. 콘텐츠 기준·소유권·독립 승인·실제 제작 도구 권한은 그대로다.

검증: 관련263개 테스트 통과, 최종 ID 경로 보완 후11개 집중 회귀 통과. 독립 검토77·78 지적(잘못된 ID, 여러 대상 예산 초기화, 의존성 대기 누적)을 수정하고79 승인. 유휴 배포40 및 loaded hash 확인, task/job 행과 Chrome·VoiceBench 보존. `actual-repair-stage-replay.json`, `repair-stage-watch.xml`, `repair-stage-watch-review-fixes.xml` 참조. 영상 완성은 여전히 별도 실파일·QA 검증 대상이며3개 완료를 주장하지 않는다.


### 추가 보완 41: 담당 에이전트의 대화 연속성과 즉시 실패 피드백

기존 writer는 매 결정마다 `exec --ephemeral`과 새 임시 cwd를 사용했다. 요약·읽기 범위가 잘리면 기존 사고 계약을 재탐색하는 현상이 있었다. 영상 담당 호출에만 task/run/owner epoch 결속을 전달하고, 별도 해시 경로의 OS 잠금 레지스트리에서 검증된 CLI thread ID를 이어 사용하도록 변경했다. 다른 영상·회차·명령 세대는 분리된다. read-only, shell/web 비활성, 사용자 설정 무시, 기존 CLI 로그인·기본 모델·호스트 도구 실행/승인 검증은 유지한다. 독립 검토와 JSON 형식 보정은 기존 ephemeral 세션이다. 새 세션은 과거 model 문맥을 승인이나 최신 상태로 취급하지 않고 현재 호스트 증거를 우선한다.

설치된 CLI와 실제 bridge 두 번 호출 시험에서 두 번째 요청에 재전달하지 않은 임의 표식을 같은 thread가 기억했으며 외부 도구·제작 행동은 없었다. 공식 동작 근거: https://learn.chatgpt.com/docs/non-interactive-mode#resume-a-non-interactive-session . 정확히 확인한 no-rollout 오류/종료1/이벤트없음만 이전 레지스트리를 보존하고 같은 owner의 새 세션으로1회 복구한다. 로그인·용량·다른 종료 코드에서는 대체하지 않는다. 손상·다른 binding의 로컬 레지스트리는 원문 보존 후 현재 호스트 binding으로 새 문맥을 시작하며 다른 thread를 재개하지 않는다. 기존 writer OS 독점/고아 프로세스 확인 및 추가 세션 OS잠금을 유지한다.

독립 검토80이 지적한 ‘복구 성공 result.json 저장 후 DB완료 전 종료’는 실패 receipt→정확한 성공 대체 call ID·같은 job payload binding·결과 digest·저장된 inference calls 일치로만 복구한다. 다른 실패를 일반 무시하지 않는다. 실제 Jobs 재시작 통합 회귀와 변조 거절을 검증했다.81 지적에 따라 종료 코드1 조건도 실시간·재시작 복구에서 일치시켰다.

별도 실제 막힘: 조회 예산 소진 후 test_patch가 실패해도 오류 본문 없이 로그 경로만 반환되어, 에이전트가 추가 inspect_repair를 못 쓰고 원인을 추측했다. 이제 test/review 결과 자체에 SHA 확인된 로그 발췌·독립 검토 지적·의존성 변경 진단을 포함한다. 새 조회 예산은 늘리지 않는다. 전달 전 현재 owner guard를 다시 확인한다. 실패 로그와 거절 근거를 먼저 사용하고, 미완성임을 아는 초안을 반복 검토하는 대신 빠진 사고 복구 연결을 완성하라는 지시를 추가했다.

검증: owner-session/feedback 통합338개 통과, 마지막 종료조건 보완 후 owner-session15개 통과. 독립 검토82 승인. 유휴 배포41, 신규 owner_session 포함 실제 loaded hash 확인, task/job 행·Chrome·VoiceBench 유지. `owner-bridge-smoke/proof.json`, `actual-feedback-gap.json`, `owner-session-and-feedback.xml`, `owner-session-exit-contract.xml` 참조. 아직 실제3개 완성을 주장하지 않는다.


### 2026-10-20: unread source contracts after a spent diagnosis budget

The Spark owner explicitly recorded that the readiness contract was missing while all six missing-reference reads were spent. It continued negative-only patch/test cycles despite knowing the positive recovery connection was absent. This was a host admission deadlock, not production progress.

The repair-only mode now retains the six general-reference limit but permits an exact allowlisted `inspect_code(repo,path)` for essential unread source. A durable same-owner-epoch ledger checks canonical file paths, exact source SHA, and the union of already delivered character ranges. Each bounded page must add at least 1024 unread characters or the file's short final tail. Rewording, path aliases, repeated/mostly overlapping ranges, searches, and artifact/recall requests do not gain this exception. New information does not reset the repair-stage watchdog or grant mutation/review/production approval. Existing source path, symlink, size, and sensitive-file restrictions remain in force.

The actual manager/pipeline regression exhausts six reads, obtains the missing contract, restarts the manager, rejects aliases/overlaps, reads a new range/final tail and a genuinely changed SHA, rejects query/traversal, and confirms production jobs are unchanged. Independent review 83 approved. Deployment and live recovery evidence are recorded separately; this fix alone is not completion of the remaining videos.


Live follow-up: the required readiness source had been read in three old ephemeral calls, before the persistent owner conversation existed. Root42 correctly detected historical range reuse but incorrectly assumed the current model had received those old bodies. Root43 scopes delivered-code ranges to the host-attested CLI conversation: exact task/run/epoch, successful call, canonical thread UUID, and decoded-result digest are checked from host inference receipts. Model-supplied thread claims cannot reset this scope. Old/lost-context code can be restored once into the current conversation, while another read in the same conversation remains blocked across manager restarts. Missing/invalid attestation falls back to the stricter historical ledger. Nine focused tests and 189 integration tests passed (overlapping executions), review84 approved; deployment43 preserved Studio task/job rows and did not restart browser or VoiceBench. These remain infrastructure results, not final-video completion.


### Verified planning child was stopped before the worker (deployment44)

The Perfume owner autonomously applied repair12e0bd567c5540e2bb315aa6d8cf6e12, verified the fresh process load, and used continue_repaired to create job7acdf5827d1d4127. StudioStore.pause_queued then paused this never-started child solely because the original strategy_exhausted hold was intentionally preserved. The corrected normal worker could never obtain fresh planning evidence.

The shared queue now admits only the exact planning child linked by the durable host continuation receipt to its reviewed/loaded repair, original done parent, current owner epoch, task semantic fingerprint, parent job fingerprint, current run/round/policy and deduplication key. Current user/access/quality holds retain their existing checks. Legacy restoration is limited to this verified child with no checkpoint, no error, and identical creation/update timestamps; claimed, explicitly paused or previously failed jobs are not resumed. The original hold and receipt remain unchanged. Normal atomic claim, supervision, maintenance, due-time and stale-claim checks still run.

23 focused tests passed including the full captured actual incident, which fails to claim with the old gate and claims the same child with the correction. The broader suite had 289 passes and one unchanged source_pause_history expectation failure, independently reproduced in the pre-change repair stage; evidence is recorded separately. Independent review85 approved. Deployment44 restarted only Studio, and the normal worker immediately claimed the same child and started source-topic analysis. Therefore its before/after snapshot differs due to normal autonomous production (not data replacement); no task/job IDs were deleted/recreated. Final video completion is still unverified for Perfume and Spark.


### A new failure inside the retained planning hold (deployment45)

The same Perfume child started normally after deployment44, then encountered a real Windows nested-cache path FileNotFoundError. The old source hold still correctly remained, but _gate consequently rejected even retry_repaired for this new failed child. The captured failure is planning-child-failure-incident.json.

Only structurally exact planning-recovery children now pass the source-hold eligibility check for park_for_repair/retry_repaired; ordinary retry remains held. Actual application/retry still requires the existing signed, tested, applied/loaded repair verifier for this child and current owner/input. Claim admission requires the original host continuation provenance and, after a failed child or changed input, a fresh durable verified-retry receipt matching the child checkpoint and action receipt. The normal retry executor records a scoped admission marker; Store.fail consumes it on another failure, while service deferral preserves it. The marker is operational, excluded from job-method input hashing. Both failure_classification and unclassified failure_trace require fresh admission (review86 caught the latter gap; review87 approved the correction).

397 integration tests passed, followed by 32 focused tests of the final condition, including captured actual failure -> real retry executor -> same-child claim, missing verification rejection, service wait, second failure and implicit requeue rejection. The signed/load verifier is isolated in this connection test and separately covered by the real repair pipeline suite. Deployment45 completed with task/job rows preserved and browser/VoiceBench untouched. Because new morning work was running, deployment temporarily deferred new owner/queued-job starts, allowed active calls to finish, and restored all leased scheduling fields in finally. This remains infrastructure recovery, not video completion.


### Owned visual query diagnostics and available recovery action (deployment46)

The Perfume owner was denied its own nested identity-correction diagnostic despite a DB checkpoint binding task/job/run and visual-input SHA. Only five fixed JSON filenames under that exact input cache and at most two full-hash recovery directories are now available to normal inspection and isolated incident capture. Path traversal and link aliases are rejected before resolution; existing explicit artifact authority is unchanged. The helper does not follow embedded paths or approve any production work. Capabilities now advertises retry_repaired for the eligible failed planning child, consistent with the already-verified executor; ordinary retry remains held.

430 integration tests passed (4 existing link skips), followed by 71 final focused passes (6 link skips due to Windows permissions); executions overlap. Independent review89 approved after the raw alias check was fixed. Actual diagnostic SHA15ab392091ee0574269ab8c082d62720bfc255d3e0548f0eb504b49146d8ba73 was read and captured, read-only. Deployment46 preserved all task/job rows and restored temporary scheduling leases; browser and VoiceBench were untouched. Air tent remains verified, other two videos are unfinished.


### Readiness successor omitted the causal receipt from its test fixture

Spark's current queued successor has no source_attempts: its readiness error originated in an earlier same-run job. The original execution receipt, manifest and worker checkpoint were already readable by the owner, but incident_artifacts only captured the successor's own paths. Consequently four strict captured-incident tests stopped before reaching production recovery. The common capture now resolves prior same-task/run receipts by the current stored provider/query/parser revision/request time. All three original files must be registered own artifacts and match recorded SHA values; task/job/run/shortcode and payload run are checked. These originals are prioritized within the existing bounded test/review budgets. No history, readiness state or production authorization is changed.

Read-only live proof captured receipt a41f23..., worker cc9f6d... and manifest3fb786... in full. 411 integration tests passed with8skips before final overflow handling, and56 focused tests passed with6 Windows link-permission skips after final handling. Review90 found huge JSON timestamp integers could raise OverflowError; finite-time checks and mixed malformed/valid history regressions fixed this, and review91 approved. Deployment47 completed at1792450814 with task/job rows preserved and scheduling leases restored; browser and VoiceBench were untouched. Completion of the two remaining videos is not established by these tests.


### Independent owners were serialized behind all model calls (deployment48)

Five live owners shared one synchronous writer loop, so a long call for one video delayed every other video's next repair decision. The writer keeps its single exclusive OS dispatcher and durable claim/orphan recovery, while admitting at most three model jobs. Calls for the same video task remain serial across epochs/runs; ordinary production calls retain a single serial lane. Existing conversation locks, capacity circuit breaker and access/quality/production guards are unchanged. A bounded64-row cursor scans past blocked lanes, and a small lane cache avoids repeatedly loading queued media payloads.

Independent review92 identified the initial64-row head starvation and ThreadPoolExecutor shutdown regression. Keyset cursor traversal and daemon calls preserve the prior process-exit behavior; normal dispatch drains admitted calls before releasing ownership. Separate subprocess tests verify blocked daemon exit and retained running-row recovery. The final review93 passed. The broad related suite had67passes before the final thread-start cleanup; the7focused dispatcher cases then passed including thread-start failure preserving a durable claim for existing orphan recovery. No real video production is performed by these tests. Deployment48 completed at1792451565 with all task/job rows preserved, leased schedules restored and no browser/VoiceBench restart. Live concurrency and exact3 completion remain to be verified.


### Planning recovery contract missing from independent review (deployment49)

Perfume's independent reviewer accepted the storage correction and incident regression but could not verify the current failed planning child could pass _gate: the new video_agent_planning_claim module and its actual host retry/claim tests were omitted from recovery_context. Owners cannot choose the constructor's host-pinned test list. For a captured collect_sources incident with planning_recovery_from, the host now pins the existing planning claim test file and supplies the exact staged gate source and executed test body to independent review. Missing trusted tests reject the proposal; failed tests still block review. The guard module is also protected against owner writes. Default review budgets remain160K; planning-child cases receive180K, fitting the actual seven files166774characters without omissions. No runtime authorization or production state is loosened.

Broad verification had173passes2skips and a new test's Windows CRLF equality error; that assertion was corrected to compare original bytes, and all3focused tests passed. The tests demonstrate the added host regression actually runs and can reject review, not merely appear in metadata. Independent review94 approved. Deployment49 at1792452146 preserved task/job rows, restored temporary schedules and left browser/VoiceBench untouched. Root read-only context-budget proof is hypothetical fresh capture, never an amended old review or approval. Separate live proof confirmed3 distinct CLI model processes after deployment48; no source production or media approval was performed manually. Both remaining owners still need their domain repairs applied and final videos verified.

### Live autonomous recovery after deployment49

Perfume's owner submitted repair-d302a58b112847ba845e7c0c0d741f18, passed138tests with2optional local-incident skips, obtained independent approval and applied it at1792452642.5026157. A fresh Studio process loaded source_visual_queries.py SHA c5a167bce19b26dd729586cee30004eef7e123f5b00873d5c4be3ffeacd0869d. Its normal retry_repaired action was accepted, and the worker claimed the same job-7acdf5827d1d4127 at1792452688.342884. It passed the original Windows path failure and reached a new PreparationEvidenceWaiting at1792452718.7949371: the nested cached query pool was still insufficient. This is a new observed failure after actual recovery, not final completion or evidence that the old retry was blocked. The owner is now repairing insufficient nested-cache feedback and the current paused-child connection. The original receipt, hold and job remain preserved. Evidence: data/agent-progress-repair-20261019/perfume-same-job-path-recovery.json.

Spark's exact causal receipt now reaches its SQLite persistence and current access-gate regression, but the positive preparation-plan integration is still failing. Its draft has not been applied. Air tent alone has verified final media; both remaining final videos are unfinished. Root has performed no manual source production, rendering, media approval or receipt clearing.


### Original preparation evidence and authenticated superseded startup (deployment51)

Spark's existing immutable preparation already passes the actual query contract (English5/Chinese5); relocating its isolated test media invalidated nested evidence hashes. The host now supplies bounded, registered-SHA-bound original preparation diagnostics to the owner and incident fixture. Actual media hashes, identity, query receipts and current reference binding remain required. Diagnostic validators skip duplicate file reads only after the host performs bounded descriptor/path/hash verification; production defaults still verify files. Review95/96 findings about unbounded rereads and discovery/read races were fixed; review97 approved, with92 final passes and7 Windows link skips.

Deployment50 failed before worker startup because an authenticated historical applied repair's source hash had been superseded by the reviewed common addition. The four common files were restored from verified prechange copies and the prior server resumed; no production records were changed. The runtime now distinguishes authenticated source supersession from invalid signatures. Superseded receipts remain historical and cannot authorize retries; current loaded proof maps are cleared, or another independently authenticated current proof is selected. Invalid latest signatures and pending-apply barriers remain fail-closed. Review98 found an absent-marker stale-projection case, which was fixed; review99 approved and146 final tests passed after302 broader passes/1skip. Deployment51 succeeded at1792455633.7126038 with task/job rows preserved, temporary schedules restored and no browser/VoiceBench restart.

### Paused internal planning wait accepts a fresh reviewed repair (deployment52)

The Perfume child passed its Windows storage failure but entered PreparationEvidenceWaiting. Its automatic hold paused the internally deferred job, while repair parking previously accepted only queued work. A read-only proof now recognizes only the exact current internal defer: task/run/parent/policy, claim token/start, due time, latest timing event and unchanged job timestamp must match; user/access/quality gates remain intact. Fresh independently reviewed repair parking can append the normal signed parking receipt while leaving status paused. Normal application, fresh-process loaded proof, verified retry and atomic same-job claim are still required. Explicit pauses, changed records, future waits, service waits and missing provenance do not qualify. Store.defer now uses the timing event's exact timestamp for its job update.

The captured actual child fixture passed99 tests with2 optional historical-incident skips; related suites passed449 with3 skips. These are overlapping executions. Independent review100 approved. Planning-only review context increased to200K to retain all mandatory host tests (actual bodies exceeded180K); default remains160K. Deployment52 succeeded at1792456145.3398209, preserved task/job rows and restored leased schedules. Browser and VoiceBench were untouched. Owners must rebase and obtain fresh review on current dependencies. Air tent remains complete; Spark and Perfume still require autonomous production and final media verification. No manual source collection, render, media approval, receipt clearing or duplicate production job was performed.


### Spark owner independently applied and resumed the original queued job

The Spark owner completed repair-e9ce6eb513324db4aade818515caa66c:114 tests passed, independent reviewer codexf35f16d673c3e75c28ab2ab70621cb39 approved binding5ead3ca9c0bb49c9f518ec58d9f29f3de7ecb8723e3deaffd2b5d6dfbab3554a, and the owner's normal park/apply path applied at1792456439.5505. Fresh process45252 loaded the exact reviewed source and test hashes at1792456450.131519. Normal retry admitted the same job-ad8c5c4b516b448c; worker claim-adeabf21584f4014 began at1792456457.51976. Read-only observation at1792456534 showed real TikTok collection running and ordinary request pacing. This establishes autonomous code recovery and same-job resumption, not finished sources or a final video. Full bounded proof is spark-same-job-autonomous-recovery.json. Perfume remains in its own domain repair; no root production actions were taken.


### Both owners passed autonomous application and original-job resumption

Spark's resumed source job finished at approximately1792461204 with related8/core2 approved originals and actual English5/Chinese5 matching search receipts. The normal acquisition controller scheduled job-c8a55a9eb82b4508 to continue the existing v6 core-priority policy. This is measurable inventory/search progress, not final video completion. The source round took about79minutes, including bounded local-interval attempts. Distinct rejected scopes were recorded and not counted as useful inventory. Some irrelevant plant-sprayer candidates consumed multiple different-scope reviews; this efficiency limitation is not a successful-media claim. Exact live diagnostic receipts and partial-batch proofs are preserved in the audit directory.

As soon as the running source job drained, Perfume's already-approved repair-cfd15d91c83c485aa7185c25773736b1 applied autonomously at1792461204.7516205. It had160passing tests/3skips and independent approval binding43b81f7edabe56e76db7119b4db351f350aa1d7f388b12afe0918f2cdbb56614. Fresh process44960 loaded source_visual_queries.py SHAb8259644dd5d98171a314bf791613cc5385fc2317a555b2f421ec3877dc5b528 at1792461213.2673626. The normal loaded-repair continuation admitted the same paused child job-7acdf5827d1d4127, claimed at1792461259.220828 with claim-8901a467db0e484d. Proof: perfume-paused-child-autonomous-recovery.json. The wait retained the same approved repair and decision rather than generating new drafts; no root intervention resumed or rendered this job. The two remaining final videos are still unverified.


### Twelve-hour outcome audit and diagnostic deployment53

Fresh compact API and file/QA proof still verify only Air tent. Spark has9related/3core originals with actual English5/Chinese5 searches; Perfume has0sources. Both owners applied reviewed repairs and resumed original jobs, but neither remaining video is complete. Root repaired shared infrastructure repeatedly, so full autonomous completion without root intervention is not established. Action-count evidence is in data/agent-progress-repair-20261019/twelve-hour-outcome-audit.json; actions and passing tests are not production throughput.

Flat query-pool diagnostics passed432tests with8Windows/optional skips and independent review103 after fixes requested by reviews101/102. Deployment53 loaded at1792462473.587456, leases restored, browser/VoiceBench untouched. Its state_rows_preserved flag is false; follow-up found no missing/new task/job IDs, but task revisions advanced. Do not report exact row equality. Perfume owner actually inspected the newly exposed receipt. Spark still repeats exhausted-scope preflight; timestamps reset the watch and deferred_wait prevents diagnosis. tests/test_video_agent_scope_wait.py is an UNRUN draft regression, not an implemented or deployed fix.
