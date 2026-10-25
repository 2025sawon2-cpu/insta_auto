---
name: hotpost-new-production
description: Select and produce one new Hotpost video from the latest ranked, not-yet-made Instagram reference posts in insta_auto. Use for a new production request or the daily collection-to-top-post workflow; route a specifically paused video to the resume skill.
---

# 신규 영상 제작

신규 편집 계획에는 `docs/PRODUCTION_DELIVERY.md`의 `style-plan`으로 현재 표지/본문 기본값을 적용한다. 독립 원본 렌더를 그대로 공유하지 않고 같은 문서의 `finalize`로 광고·호환 형식·기술 검사를 거친 후보를 만든다. 최종 QA와 검토본/완료본 저장 구분은 `docs/WORKFLOW.md`, `docs/LOCAL_VIDEO_STORAGE.md`를 따른다.

1. 현재 clone의 `AGENTS.md`, `docs/COLLABORATION.md`, `docs/WORKFLOW.md`, `docs/REFERENCE_STATUS.md`와 해당 단계별 원본을 실제로 읽는다. Git 제외 중지·인계와 기존 task/run을 확인한다. 이 스킬을 읽거나 설치한 사실은 운영 재개 승인이 아니다.
2. 최신 비샘플 수집 결과를 공통 원장에 `python -m hotpost.reference_registry --registry <원장> sync --report <리포트> --run-id <수집 run>`으로 합친다. `$hotpost-reference-status` 방식으로 최신 원본 게시 날짜부터, 날짜 안에서는 검증된 우선순위부터 ID·판정·제작 상태를 확인한다. 리포트가 오래됐거나 순위 근거가 부족하면 새 1위를 만들어내지 않는다. `unknown`은 기존 DB·작업/완료본을 감사해 `not_started` 또는 실제 상태로 확인하기 전에는 신규 대상으로 삼지 않는다.
3. 다른 영상이 `in_progress`면 새 제작을 시작하지 않는다. `paused/blocked` 영상이 있으면 ID·단계·사유를 보여주고 **그 영상을 이어 만들지, 새 영상을 선택할지** 사용자의 결정을 받는다. 답이 없으면 새 작업을 시작하지 않는다. 재개 선택은 `$hotpost-resume-production` 경로로 넘긴다. 새 영상 선택은 기존 상태·자료를 보존한 채 명시 결정과 이유를 공통 원장에 기록하며 병행 제작하지 않는다.
4. `not_started`로 확인된 최상위 적격 릴스 한 편을 고정 ID·선정 근거에 결속한다. 전담 제작자와 별도 읽기 전용 감시자를 같은 task/run에 붙이고 원장 상태를 근거와 함께 갱신한다. 둘 중 하나를 붙이지 못하면 단독 제작하지 않는다. 이후 소스·대본·음성·편집·최종 QA·전달·감시 보고서 독립 검증은 `docs/WORKFLOW.md`와 작업별 원본을 따른다. 다음 후보를 자동 시작하거나 실제 Instagram 게시를 하지 않는다.
