---
name: hotpost-resume-production
description: Resume one explicitly identified paused or blocked insta_auto Hotpost video from its preserved task and run. Use when the user supplies the stable Instagram video ID after reviewing reference status; do not select a fresh ranked post.
---

# 중단 영상 재개

1. 사용자가 지정한 Instagram shortcode `video_id`를 받는다. 순위 번호만 받았다면 `$hotpost-reference-status`로 고정 ID를 확인한 뒤 대상이 확정될 때까지 실행하지 않는다.
2. 현재 clone의 `AGENTS.md`, `docs/COLLABORATION.md`, `docs/WORKFLOW.md`, `docs/REFERENCE_STATUS.md`와 단계별 원본을 다시 읽고, 공통 원장 `show <video_id>`를 실행 직전에 확인한다. 원래 task/run·담당자·인계·대본·음성·소스·최종 파일과 실제 중지 사유를 대조한다. 원장과 원본이 충돌하면 먼저 근거를 확인한다.
3. `paused/blocked`인 그 영상에 대한 새 명시 재개 지시인지 확인한다. 무진전 보류는 새 근거 없이 풀지 않는다. `completed`·`unknown`·`not_started`를 재개 작업으로 바꾸지 않고, 다른 영상이 진행 중이면 병행하지 않는다.
4. 기존 전담 제작자를 재사용하고 별도 읽기 전용 감시자를 같은 task/run에 붙인다. 누락된 식별자는 원본 자료에 근거해 기록하고 임의로 꾸미지 않는다. 둘을 결속한 뒤 기대 상태를 확인하며 `in_progress`로 갱신하고, 저장된 단계부터 같은 한 편을 진행한다. 감시자를 붙이지 못하면 단독 재개하지 않는다.
5. 최종 QA·전달과 감시 Markdown·문제 주장별 독립 검증은 `docs/WORKFLOW.md`를 따른다. 다른 후보와 실제 Instagram 게시는 시작하지 않는다.
