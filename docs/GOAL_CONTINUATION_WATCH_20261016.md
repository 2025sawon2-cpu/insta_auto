# 목표 이어서 작업 감시 기록 (2026-10-16)

기존 영상·대본·음성·운영 DB를 보존하며 점검했다. 발견 즉시 main에 보고했고 main이 로직을 수정했다. `독립 검증`은 외부 요청 없는 격리 fixture·실제 OS lease·실제 함수/JS식 실행이다. 브라우저 UI stub 검증을 실제 사이트 성공으로 취급하지 않는다.

| ID | 발견한 오류 | 반영한 수정 | 확인 범위 |
|---|---|---|---|
| W1 | 무관한 mirror 명사·허위 subject quote로 중심 제품 검색어 검증 우회 | 중심 명사 보정·quote 선검증·정책 v3 | 독립 반례 통과 |
| W2 | 계정 대소문자/@ 차이로 1회 시도·예약 중복 | 저장 경계 계정 정규화 | 독립 동시예약 차단 |
| W3 | SQLite 연결 미종료로 Windows 잠금 잔존 | 명시적 close context | 격리 DB 정리 통과 |
| W4 | 중단된 effect running/dispatching 잔존·예약 경계 누락 | 실제 OS lease·예약 원자 저장·죽은 소유자만 복구 | 실제 child 종료·live 보존·중복 복구 검증 |
| W5 | 원작자와 기존 DM 대화가 없으면 댓글 전 실패 | 빈 baseline·신규 수신 대기·필수탭 사전 확인 | 코드 보완 / 실제 UI 미검증 |
| W6 | 송수신 혼동·옛 팔로우 확인 버튼 선택 | sender 표시·신규 수신 row로 범위 한정 | 코드 보완 / 실제 UI 미검증 |
| W7 | 요청 package를 실제 리틀리 저장값으로 오인 | 저장 입력·답글 수·활성/예약 상태 확인 | 코드 보완 / 실제 UI 미검증 |
| W8 | 타인의 같은 댓글 키워드 때문에 성공 확인 실패 | 현재 계정 댓글 전후 증가·동일 답글 locator | 코드 보완 / 실제 UI 미검증 |
| W9 | lifecycle local import가 current_run을 가려 수용 실패 | 중복 local import 제거 | main 재현·회귀 / import 구조 확인 |
| W10 | 개별 endpoint 충돌이 thread 예외로 끝나 ready 잔존 | 자기 record의 오류를 공통 guard에서 저장 | 독립 경쟁 검증·기존 owner 보존 |
| W11 | 실행 충돌 전에 slot을 선점해 orphan 예약 | slot·effect·record 원자 예약 | 충돌 후 slot/effect 0 검증 |
| W12 | effect 오류와 record 종료 사이 중단 경계 | 양쪽 종료 transaction 통합 | SQL abort 시 함께 rollback 검증 |
| W13 | 같은 DM ID의 상대시각 변경을 새 수신으로 오인 | stable ID 우선·변동표시 signature 제외 | 실제 helper 반례 통과 |
| W14 | 늦게 로딩된 과거 ID를 신규 DM으로 승인 | ID와 무관하게 실제 수신시각 확인 | 2020년 과거 DM 거부 검증 |
| W15 | 이미 예약된 계정에서 새 상품 댓글·API 발급 낭비 | 첫 외부동작 전 account workflow 원자 확보 | 첫 댓글만 실행·두 번째 미시도 대기 검증 |
| W16 | 상품확인 중단·API 오류 뒤 workflow가 영구 잔존 | 생성 전 workflow만 오류/복구 때 해제 | workflow 해제·reserved 유지 검증 |
| W17 | thread accepted 후 effect 전 중단으로 완료 outbox 유실 | dispatched 재관찰·실제 task lease·안전한 미시도 재수용 | 재시작·live 보존·awaiting_post done 검증 |
| W18 | 로그인/필수탭 preflight 실패를 영구 오류로 분류 | 외부효과 전 준비 실패는 waiting_connections | 두 tick에도 대기·effect 0 검증 |
| W19 | waiting_slot을 UI에서 준비로 오표시 | 슬롯·연결·게시물·발송 상태 분리 | 실제 JS식 표시 검증 |
| W20 | 성공 0건/실패 row를 전달 성공으로 오판 | 상태 column의 정확한 개별 성공값만 인정 | 실제 method+UI stub 반례 통과 |
| W21 | 타인 댓글의 caption 복사를 우리 본문으로 오판 | 게시물 author header·caption heading으로 한정 | 실제 method+UI stub 반례 통과 |
| W22 | 저장 상세에 옵션 문구가 보이기만 해도 선택된 정책으로 오인할 여지 | 실제 checked/selected/pressed 상태 요구 | main 로컬 DOM에서 미선택 거부·선택 허용 확인 / 실제 사이트 미검증 |
| W23 | 관측 direct 상품의 redirect에서 옵션 ID가 바뀌어도 승인 | 관측 상품/옵션과 최종 identity 비교 | 실제 method fixture에서 모델 전 거부 |
| W24 | 동일 상품 라벨의 다른 옵션을 모델 index로 임의 선택 | 동일 라벨·다른 canonical identity 결정적 거부 | 탐색 1회·모델 0회 종료 검증 |
| W25 | HTTP Instagram wrapper를 HTTPS 상품 링크로 승인 | wrapper 자체 HTTPS·userinfo·port 선검증 | helper 반례 거부·정상 wrapper 유지 |
| W26 | 오류 근거 누락·이전 캡처 덮어쓰기·Playwright TimeoutError 근거 유실 | session 실제 접근 page 추적·UUID 불변 영수증·동일 session 근거 chain·일반 예외 check 기록 | 독립 fixture 14경계 확인 / 실제 계정 미검증 |

## 목표 영상과 보존

- 손난로 `Dec5bcqyffk` / `work-2d881e5afb2043ce`는 10/15 03:48:34 신규 생성, 05:04:32 완료(revision 188). 기준 42개 작업에 해당 shortcode가 없고 생성 전/후 보존 영수증도 확인했다. 중복 제작하지 않았다.
- 원본 reference가 존재하며 최종 MP4(10,686,246 bytes)·timeline의 실제 SHA가 최종 review 승인 SHA와 일치한다. 검수 passed/issues 없음, 전체 decode 및 export/quality 검증 통과. 청감 검수는 미실시다.
- 기존 손난로 D1~D7의 원문 결함·수정 이력은 [이전 감시 문서](GOAL_LIVE_WATCH_20261015.md)에 보존했다. D2 잔여 반례는 이번 W1에서 보완했다. 과거 사용자 중지 작업은 임의 재개하지 않았다.

## 검증 한계

- 순차 service.run, 같은 계정·레퍼런스 중복 차단, DM 실패 후 재댓글 방지, 기존 영상 fixture state/SHA 보존을 검증했다.
- 읽기전용 확인 fixture에서 잘못된 게시물은 슬롯을 유지하고, 올바른 연결은 awaiting_delivery로 전환·슬롯 해제, 잘못된 발송 영수증은 미완료 유지, 결속된 성공 영수증만 completed로 전환했다. 호출은 inspect_post/inspect_delivery뿐이며 외부 effect 0개였다.
- **실제 연결된 Instagram·본인 쿠팡파트너스 발급·리틀리 등록/발송은 미검증이다.** 코드·fixture 통과나 손난로 SHA에 결속한 준비 상태를 실계정 종단 성공으로 확대하지 않는다. 서로 겹치는 테스트 집계는 합산하지 않는다.
- 상세 SHA·근거·반례·판정: `data/goal-continuation-20261016/production-audit.json`. 단계별 기록 원문도 같은 폴더의 `watch-history-before-summary.md`, `watch-history-before-final-summary.md`에 보존했다.


- 링크페이지 추가 독립 fixture: 정상 2회 이동·옵션 유지, redirect 순환 2회 후 종료, 403/429 각 1회 후 종료를 확인했다. 실패 후 service 재시작에도 상품확인 adapter 1회·effect 1개로 보존되며 재시도를 차단했다. 외부 요청 0회이며 실제 링크페이지 사이트·계정 검증은 미완료다.


- **W26 최종 독립 검증:** 원예외 객체 유지, disconnect 전 현재 actor의 실제 마지막 page만 캡처, 미선택/attach 실패의 옛 포인터 미사용, screenshot 실패의 새 영수증과 원예외 보존, 동시 actor 분리, record/effect의 같은 근거·keyword·attempt=1 및 재시작 재댓글 차단을 확인했다.
- 같은 folder·같은 step의 다음 session에서도 새 UUID 파일을 생성해 과거 previous_evidence_path의 바이트·URL이 변하지 않고 이전 session chain을 재사용하지 않는다. 실제 Playwright TimeoutError를 session 안에서 발생시켜 post는 awaiting_post와 슬롯을 유지하고 delivery는 awaiting_delivery를 유지하며, 반복 읽기 확인도 기존 littly_create effect 1개를 보존했다. 공통 guard도 예외에 결속한 근거를 유지했다.
- W26 상세 증거: `data/goal-continuation-20261016/w26-independent-fixture-09c027f0/verification.json` 및 같은 폴더의 UUID 영수증. 모두 외부 요청 없는 fixture이며 실제 캡처 화면이 아니다. main은 관련 149개 회귀 통과를 보고했으며 이전 중복 범위와 합산하지 않는다.

**운영 반영 한계:** main에 따르면 자동 정책 검토가 서버 재시작 명령을 거부해 기존 helper 프로세스를 보존했고 우회하지 않았다. 이번 검증은 현재 소스·격리 실행 기준이며 실행 중 helper에 코드가 반영됐다는 증거가 아니다. 승인 Chrome·본인 API도 미연결로 세 차례 재확인돼 실제 계정 종단 검증은 연결 의존 대기다.
