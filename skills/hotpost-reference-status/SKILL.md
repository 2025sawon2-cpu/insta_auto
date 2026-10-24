---
name: hotpost-reference-status
description: Show ranked viral Instagram reference posts and each post's verified Hotpost production state for insta_auto. Use when the user asks which reference is current, what is paused or completed, or which video ID to choose; this skill does not start production.
---

# 레퍼런스 현황

1. 현재 `insta_auto` clone의 `AGENTS.md`, `docs/COLLABORATION.md`, `docs/WORKFLOW.md`, `docs/REFERENCE_STATUS.md`를 읽는다. 현재 clone의 Git 제외 상태 원장과 최신 비샘플 수집 리포트가 있는지 확인한다. 다른 PC의 로컬 상태를 추정하지 않는다.
2. `python -m hotpost.reference_registry --registry <원장> list --report <최신 리포트>`로 원본 게시 날짜(한국 시간) 내림차순, 날짜별 우선순위 목록을 읽는다. 각 후보의 고정 `video_id`(Instagram shortcode), 원본 링크, 게시일·핫 감지일, 점수·잠정 판정, 제작 상태·단계·중단 사유·근거를 필요에 따라 `show`로 확인한다. 순위 번호는 ID가 아니다.
3. `unknown`은 미제작이 아니다. 기존 DB·작업 폴더·인계·완료본과 모순이 있으면 미확인으로 표시한다. 사용자가 재개할 ID를 고를 수 있게 실제 상태를 간결하게 제시한다.

이 스킬은 수집·제작·상태 변경을 실행하지 않는다. 상태 변경이 필요하면 `docs/REFERENCE_STATUS.md`의 근거·기대 상태 검사를 따른다.
